"""
Pipelined Worker Manager for KAGEVIETSUB TTS.
Decouples I/O-bound TTS concurrency from CPU-heavy audio processing concurrency:

1. TTS Worker Pool:
   - Exactly N workers as selected by the user (1 to 30 workers).
   - Never downscales user's choice.
   - Performs strictly I/O and network operations (calling CapCut API, saving raw audio to disk).
   - Zero FFmpeg calls inside TTS workers.

2. CPU Audio Worker Pool:
   - Independent concurrency dynamically calculated based on host CPU cores (1 to 4 workers).
   - Dedicated solely to CPU-intensive operations (speed time-stretch, WAV conversions).
   - FFmpeg processes strictly restricted to single-threaded mode (-threads 1).
   - Completely bypassed when speed == 1.00x.

3. UI Queue Decoupling:
   - Workers put lightweight event dicts into a thread-safe Queue.
   - Zero direct Qt signals per item emitted from worker threads.
   - Processed by UI timer in batches at 250-500ms intervals.

4. Resilient Error Queue & Targeted Retry:
   - Failed lines enroll into error queue with exponential backoff (up to 5 retries).
   - No busy loops: workers sleep/block on queue events.
"""

import os
from pathlib import Path
import queue
import threading
import time
from typing import Callable, Dict, List, Optional
from app.audio.speed import process_audio_speed, get_cpu_audio_worker_count
from app.core.srt_parser import SRTItem
from app.core.state_manager import StateManager
from app.core.retry_manager import RetryManager, MAX_RETRIES
from app.core.tts_manager import TTSManager
from app.utils.logger import log_error, log_info, log_retry


class WorkerManager:
    def __init__(
        self,
        tts_manager: TTSManager,
        state_manager: StateManager,
        retry_manager: RetryManager,
        num_workers: int = 10,
        speed: float = 1.0,
        ui_queue: Optional[queue.Queue] = None,
        status_callback: Optional[Callable[[SRTItem], None]] = None,
        progress_callback: Optional[Callable[[int, int, Dict[str, int]], None]] = None,
    ):
        self.tts_mgr = tts_manager
        self.state_mgr = state_manager
        self.retry_mgr = retry_manager

        # TTS workers strictly respects user choice (1 to 30)
        self.num_tts_workers = max(1, min(num_workers, 30))
        self.speed = speed

        # CPU audio workers strictly decoupled from TTS workers
        self.num_cpu_workers = get_cpu_audio_worker_count()

        self.ui_queue = ui_queue
        self.status_cb = status_callback
        self.progress_cb = progress_callback

        self._is_cancelled = False
        self._lock = threading.Lock()
        self._all_done_event = threading.Event()

    def cancel(self) -> None:
        """Safely cancel the pipeline."""
        self._is_cancelled = True
        self._all_done_event.set()
        log_info("Yêu cầu hủy quá trình xử lý pipeline.")

    @property
    def is_cancelled(self) -> bool:
        return self._is_cancelled

    def _emit_status(self, item: SRTItem) -> None:
        """Emits status update to UI queue without blocking workers."""
        if self.ui_queue is not None:
            evt = {
                "id": item.id,
                "status": item.status,
                "retry_count": item.retry_count,
                "error": item.error,
                "audio_path": item.audio_path,
            }
            try:
                self.ui_queue.put_nowait(evt)
            except Exception:
                pass
        elif self.status_cb is not None:
            try:
                self.status_cb(item)
            except Exception:
                pass

    def process_items(
        self,
        items: List[SRTItem],
        global_voice: str,
    ) -> bool:
        """
        Executes pipelined TTS and Speed processing:
        - 30 TTS workers pull from tts_queue
        - When an item finishes TTS:
          - If speed == 1.0x: marks done immediately (no FFmpeg)
          - If speed != 1.0x: pushes to audio_queue for CPU audio workers
        - UI queue receives batch events
        """
        self._is_cancelled = False
        self._all_done_event.clear()
        total = len(items)
        need_speed = abs(self.speed - 1.0) >= 0.01

        log_info(
            f"Bắt đầu pipeline: {total} dòng | TTS workers={self.num_tts_workers} (người dùng chọn) | "
            f"Speed={self.speed:.2f}x ({'FFmpeg CPU pool=' + str(self.num_cpu_workers) + ' workers (threads=1)' if need_speed else 'Bỏ qua FFmpeg (1.00x)'})"
        )

        tts_queue: queue.Queue = queue.Queue()
        # Bounded audio_queue enforces backpressure when CPU workers are busy
        max_audio_q_size = max(8, self.num_cpu_workers * 4)
        audio_queue: queue.Queue = queue.Queue(maxsize=max_audio_q_size)

        # Track remaining uncompleted items
        remaining_lock = threading.Lock()
        remaining_count = [total]

        for item in items:
            if item.status == "Hoàn thành":
                with remaining_lock:
                    remaining_count[0] -= 1
            else:
                tts_queue.put(item)

        if remaining_count[0] <= 0:
            return True

        def _decrement_remaining() -> None:
            with remaining_lock:
                remaining_count[0] -= 1
                if remaining_count[0] <= 0:
                    self._all_done_event.set()

        # -------------------------------------------------------------
        # 1. CPU AUDIO WORKER ROUTINE (Only launched when speed != 1.0x)
        # -------------------------------------------------------------
        def _cpu_audio_worker() -> None:
            while not self._is_cancelled:
                try:
                    item: Optional[SRTItem] = audio_queue.get(timeout=0.3)
                except queue.Empty:
                    if self._all_done_event.is_set():
                        break
                    continue

                if item is None or self._is_cancelled:
                    break

                try:
                    raw_audio = Path(item.audio_path)
                    speed_wav = self.state_mgr.get_speed_audio_path(item.id)
                    result_p = process_audio_speed(raw_audio, speed_wav, speed=self.speed)
                    item.audio_path = str(result_p)
                    self.retry_mgr.record_success(item)
                    item.status = "Hoàn thành"
                    self._emit_status(item)
                except Exception as e:
                    err_msg = str(e)
                    self.retry_mgr.record_failure(item, err_msg)
                    self._emit_status(item)
                finally:
                    _decrement_remaining()

        # -------------------------------------------------------------
        # 2. TTS WORKER ROUTINE (Exact user choice, up to 30 workers)
        # -------------------------------------------------------------
        def _tts_worker() -> None:
            while not self._is_cancelled:
                try:
                    item: Optional[SRTItem] = tts_queue.get(timeout=0.3)
                except queue.Empty:
                    if self._all_done_event.is_set():
                        break
                    continue

                if item is None or self._is_cancelled:
                    break

                item.status = "Đang tạo"
                self._emit_status(item)

                voice_to_use = item.voice or global_voice
                audio_file = self.state_mgr.get_audio_path(item.id, "mp3")

                try:
                    self.tts_mgr.synthesize_line(item.text, voice_to_use, audio_file)
                    item.audio_path = str(audio_file)

                    if need_speed:
                        # Pipeline streaming: hand over to CPU audio worker pool (with backpressure support)
                        item.status = "Đổi tốc độ"
                        self._emit_status(item)
                        while not self._is_cancelled:
                            try:
                                audio_queue.put(item, timeout=0.2)
                                break
                            except queue.Full:
                                continue
                    else:
                        # 1.00x: Instant completion without FFmpeg
                        self.retry_mgr.record_success(item)
                        item.status = "Hoàn thành"
                        self._emit_status(item)
                        _decrement_remaining()

                except Exception as e:
                    err_msg = str(e)
                    self.retry_mgr.record_failure(item, err_msg)

                    if item.retry_count < MAX_RETRIES and not self._is_cancelled:
                        item.status = f"Retry {item.retry_count}/{MAX_RETRIES}"
                        self._emit_status(item)
                        # Backoff delay before re-queuing
                        delay = self.retry_mgr.get_backoff_delay(item.retry_count)
                        time.sleep(delay)
                        tts_queue.put(item)
                    else:
                        item.status = f"Thất bại {MAX_RETRIES}/{MAX_RETRIES}"
                        self._emit_status(item)
                        _decrement_remaining()

        # Start CPU audio workers (if speed != 1.0x)
        cpu_threads: List[threading.Thread] = []
        if need_speed:
            for i in range(self.num_cpu_workers):
                t = threading.Thread(target=_cpu_audio_worker, name=f"CPUAudioWorker-{i}", daemon=True)
                t.start()
                cpu_threads.append(t)

        # Start TTS workers (exact user count, e.g. 30)
        tts_threads: List[threading.Thread] = []
        for i in range(self.num_tts_workers):
            t = threading.Thread(target=_tts_worker, name=f"TTSWorker-{i}", daemon=True)
            t.start()
            tts_threads.append(t)

        # Wait for all items to complete or cancellation (no busy loop!)
        while not self._all_done_event.is_set() and not self._is_cancelled:
            self._all_done_event.wait(timeout=0.3)
            # Periodic throttled progress update if callback provided (CLI mode)
            if self.progress_cb:
                completed = sum(1 for it in items if it.status == "Hoàn thành")
                generating = sum(1 for it in items if it.status in ("Đang tạo", "Đổi tốc độ"))
                failed = sum(1 for it in items if "Lỗi" in it.status or "Thất bại" in it.status)
                pending = total - (completed + generating + failed)
                self.progress_cb(completed, total, {
                    "completed": completed,
                    "generating": generating,
                    "failed": failed,
                    "pending": pending,
                })

        # Signal all worker threads to terminate
        for _ in tts_threads:
            tts_queue.put(None)
        for t in tts_threads:
            t.join(timeout=1.0)

        if need_speed:
            for _ in cpu_threads:
                audio_queue.put(None)
            for t in cpu_threads:
                t.join(timeout=2.0)

        # Final progress callback
        if self.progress_cb:
            completed = sum(1 for it in items if it.status == "Hoàn thành")
            generating = sum(1 for it in items if it.status in ("Đang tạo", "Đổi tốc độ"))
            failed = sum(1 for it in items if "Lỗi" in it.status or "Thất bại" in it.status)
            pending = total - (completed + generating + failed)
            self.progress_cb(completed, total, {
                "completed": completed,
                "generating": generating,
                "failed": failed,
                "pending": pending,
            })

        success_count = sum(1 for it in items if it.status == "Hoàn thành")
        log_info(f"Hoàn tất pipeline TTS & Speed: {success_count}/{total} câu thành công.")
        return success_count > 0
