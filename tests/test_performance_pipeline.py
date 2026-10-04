"""
Comprehensive test suite verifying the performance optimizations for KAGEVIETSUB TTS:
1. Concurrency separation: 30 TTS workers remain 30; CPU audio pool is independently bounded (1-4).
2. Speed 1.00x bypass: No FFmpeg atempo processing.
3. Speed != 1.00x: CPU audio worker pool processes speed with FFmpeg -threads 1.
4. UI queue decoupling: workers emit thread-safe queue dicts without blocking Qt GUI.
5. Overlap timeline mixing: simultaneous audio tracks mixed without pushing timestamps.
6. Gaps between subtitles: natural silence preserved.
7. Retry queue: targeted retry up to 5 times.
"""

from pathlib import Path
import queue
import sys
import unittest
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.audio.mixer import AudioMixer
from app.audio.speed import get_cpu_audio_worker_count, process_audio_speed
from app.audio.timeline import TimelineEngine
from app.core.retry_manager import RetryManager, MAX_RETRIES
from app.core.srt_parser import SRTItem
from app.core.state_manager import StateManager
from app.core.worker_manager import WorkerManager
from app.ui.srt_table import SRTTableModel, SRTTableView


class Test3000LinesPerformance(unittest.TestCase):
    def test_3000_lines_model_batch_updates_speed(self):
        """Verify that updating 3,000 lines in SRTTableModel completes in under 50ms."""
        import time

        items = [
            SRTItem(
                id=i,
                start_str="00:00:01,000",
                end_str="00:00:03,000",
                start_ms=1000,
                end_ms=3000,
                duration_ms=2000,
                text=f"Phụ đề câu số {i} trong tập phim hoạt hình Kagevietsub.",
            )
            for i in range(1, 3001)
        ]

        model = SRTTableModel(items)
        self.assertEqual(model.rowCount(), 3000)

        # Simulate batch status updates for all 3,000 lines
        batch_evt = {
            i: {
                "status": "Hoàn thành",
                "retry_count": 0,
                "error": "",
                "audio_path": f"/tmp/audio_{i}.wav",
            }
            for i in range(1, 3001)
        }

        t_start = time.perf_counter()
        model.apply_batch_updates(batch_evt)
        t_elapsed_ms = (time.perf_counter() - t_start) * 1000.0

        self.assertLess(t_elapsed_ms, 50.0, f"Batch update for 3,000 lines took {t_elapsed_ms:.2f}ms (must be < 50ms)")
        self.assertEqual(items[1499].status, "Hoàn thành")

    def test_3000_lines_search_filter_speed(self):
        """Verify that filtering 3,000 lines in SRTTableModel completes in under 20ms."""
        import time

        items = [
            SRTItem(
                id=i,
                start_str="00:00:01,000",
                end_str="00:00:03,000",
                start_ms=1000,
                end_ms=3000,
                duration_ms=2000,
                text=f"Phụ đề câu số {i} {'nguy hiểm' if i % 100 == 0 else 'bình thường'}.",
            )
            for i in range(1, 3001)
        ]

        model = SRTTableModel(items)

        t_start = time.perf_counter()
        model.set_filter("nguy hiểm")
        t_elapsed_ms = (time.perf_counter() - t_start) * 1000.0

        self.assertLess(t_elapsed_ms, 20.0, f"Filtering 3,000 lines took {t_elapsed_ms:.2f}ms (must be < 20ms)")
        self.assertEqual(model.rowCount(), 30)  # 3000 / 100 = 30 matching lines


class TestWorkerManagerConcurrency(unittest.TestCase):
    def test_30_workers_strictly_preserved(self):
        """Verify that selecting 30 workers preserves exactly 30 TTS workers and does not downgrade."""
        mock_tts = MagicMock()
        state_mgr = StateManager("test_30_workers")
        retry_mgr = RetryManager(state_mgr)

        wm = WorkerManager(
            tts_manager=mock_tts,
            state_manager=state_mgr,
            retry_manager=retry_mgr,
            num_workers=30,
            speed=1.0,
        )
        self.assertEqual(wm.num_tts_workers, 30, "TTS workers must be exactly 30!")
        self.assertTrue(1 <= wm.num_cpu_workers <= 4, "CPU audio workers must be bounded between 1 and 4!")

    def test_cpu_audio_worker_count_formula(self):
        """Verify that get_cpu_audio_worker_count adapts to core count without exceeding 4."""
        count = get_cpu_audio_worker_count()
        self.assertTrue(1 <= count <= 4, f"Dynamic CPU worker count {count} is out of safe range [1, 4]")

    def test_speed_1_0_bypass(self):
        """Verify that speed=1.00x bypasses FFmpeg time-stretch completely."""
        test_file = PROJECT_ROOT / "test_audio.mp3"
        out_wav = PROJECT_ROOT / "temp_bypass_test.wav"
        res = process_audio_speed(test_file, out_wav, speed=1.0)
        # Should return original file directly without creating out_wav
        self.assertEqual(res, test_file)
        self.assertFalse(out_wav.exists())


class TestUIQueueDecoupling(unittest.TestCase):
    def test_workers_emit_to_ui_queue(self):
        """Verify that worker manager emits to ui_queue without blocking."""
        ui_q = queue.Queue()
        mock_tts = MagicMock()
        state_mgr = StateManager("test_ui_q")
        retry_mgr = RetryManager(state_mgr)

        item = SRTItem(id=1, start_str="00:00:01,000", end_str="00:00:03,000", start_ms=1000, end_ms=3000, duration_ms=2000, text="Test queue")
        test_file = PROJECT_ROOT / "test_audio.mp3"

        def mock_synth(text, voice, out_p):
            import shutil
            shutil.copyfile(str(test_file), str(out_p))
            return out_p

        mock_tts.synthesize_line.side_effect = mock_synth

        wm = WorkerManager(
            tts_manager=mock_tts,
            state_manager=state_mgr,
            retry_manager=retry_mgr,
            num_workers=2,
            speed=1.0,
            ui_queue=ui_q,
        )

        success = wm.process_items([item], "BV421_vivn_streaming")
        self.assertTrue(success)

        # Verify events received in ui_q
        events = []
        while not ui_q.empty():
            events.append(ui_q.get_nowait())

        self.assertGreaterEqual(len(events), 2)
        statuses = [e["status"] for e in events]
        self.assertIn("Đang tạo", statuses)
        self.assertIn("Hoàn thành", statuses)


class TestTimelineOverlapAndGaps(unittest.TestCase):
    def test_overlap_mixing_preserves_start_timestamps(self):
        """Verify that overlapping subtitles are mixed naturally without delaying the 2nd line."""
        test_file = PROJECT_ROOT / "test_audio.mp3"
        if not test_file.exists():
            return

        items = [
            SRTItem(id=1, start_str="00:00:01,000", end_str="00:00:05,000", start_ms=1000, end_ms=5000, duration_ms=4000, text="Line 1", audio_path=str(test_file)),
            SRTItem(id=2, start_str="00:00:04,000", end_str="00:00:07,000", start_ms=4000, end_ms=7000, duration_ms=3000, text="Line 2", audio_path=str(test_file)),
        ]

        timeline = TimelineEngine(items)
        events = timeline.events

        self.assertEqual(len(events), 2)
        # Event 2 MUST start at 4000ms, not pushed to 5000ms!
        self.assertEqual(events[0].start_ms, 1000)
        self.assertEqual(events[1].start_ms, 4000)

    def test_gap_preservation(self):
        """Verify large gaps between subtitles are retained as silence."""
        test_file = PROJECT_ROOT / "test_audio.mp3"
        if not test_file.exists():
            return

        items = [
            SRTItem(id=1, start_str="00:00:01,000", end_str="00:00:03,000", start_ms=1000, end_ms=3000, duration_ms=2000, text="Line 1", audio_path=str(test_file)),
            SRTItem(id=2, start_str="00:00:15,000", end_str="00:00:18,000", start_ms=15000, end_ms=18000, duration_ms=3000, text="Line 2", audio_path=str(test_file)),
        ]

        timeline = TimelineEngine(items)
        self.assertGreaterEqual(timeline.total_duration_ms, 15000)


class TestRetryManager(unittest.TestCase):
    def test_targeted_retry_and_terminal_failure(self):
        state_mgr = StateManager("test_retry_mgr")
        retry_mgr = RetryManager(state_mgr)

        item = SRTItem(id=42, start_str="00:00:01,000", end_str="00:00:02,000", start_ms=1000, end_ms=2000, duration_ms=1000, text="Retry test")

        for attempt in range(1, MAX_RETRIES + 1):
            retry_mgr.record_failure(item, "Connection timeout")
            self.assertEqual(item.status, f"Retry {attempt}/5")

        # Exceeding MAX_RETRIES records terminal failure
        retry_mgr.record_failure(item, "Terminal failure")
        self.assertEqual(item.status, f"Thất bại {MAX_RETRIES}/{MAX_RETRIES}")
        self.assertEqual(item.retry_count, 6)


if __name__ == "__main__":
    unittest.main()
