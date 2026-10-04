"""
Timeline Engine for KAGEVIETSUB TTS.
Arranges individual audio segments onto the master timeline:
- Exact SRT timestamp synchronization.
- Preserves actual start times without delaying overlapping tracks.
- Natural silence between gaps.
- Overlap intervals are marked for simultaneous multi-track mixing.
"""

from dataclasses import dataclass
from pathlib import Path
import subprocess
from typing import List, Optional
from app.core.srt_parser import SRTItem
from app.utils.logger import log_audio, log_info


@dataclass
class TimelineEvent:
    item_id: int
    file_path: Path
    start_ms: int
    end_ms: int
    duration_ms: int

    @property
    def start_sec(self) -> float:
        return self.start_ms / 1000.0

    @property
    def end_sec(self) -> float:
        return self.end_ms / 1000.0


_DURATION_CACHE: dict = {}


def get_audio_duration_ms(file_path: Path) -> int:
    """
    Measures audio duration in milliseconds.
    Uses cached values if already measured.
    Uses standard wave module for instant WAV inspection, falls back to ffprobe with -threads 1.
    """
    if not file_path.exists() or file_path.stat().st_size == 0:
        return 0

    path_key = str(file_path.resolve())
    if path_key in _DURATION_CACHE:
        return _DURATION_CACHE[path_key]

    duration = 0
    if file_path.suffix.lower() == ".wav":
        try:
            import wave
            with wave.open(str(file_path), "rb") as wf:
                frames = wf.getnframes()
                rate = wf.getframerate()
                if rate > 0:
                    duration = int((frames / rate) * 1000)
                    _DURATION_CACHE[path_key] = duration
                    return duration
        except Exception:
            pass

    try:
        cmd = [
            "ffprobe",
            "-threads",
            "1",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(file_path),
        ]
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, timeout=5)
        sec = float(out.decode("utf-8").strip())
        duration = int(sec * 1000)
        _DURATION_CACHE[path_key] = duration
        return duration
    except Exception:
        return 0


class TimelineEngine:
    def __init__(self, srt_items: List[SRTItem]):
        self.items = srt_items
        self.events: List[TimelineEvent] = []
        self.total_duration_ms = 0
        self._build_timeline()

    def _build_timeline(self) -> None:
        """
        Builds the timeline event list based on SRT timestamps and generated audio files.
        Each audio segment is placed at its exact SRT start_ms.
        """
        self.events = []
        max_end_ms = 0

        for item in self.items:
            if not item.audio_path:
                continue
            audio_p = Path(item.audio_path)
            if not audio_p.exists() or audio_p.stat().st_size == 0:
                continue

            actual_duration = get_audio_duration_ms(audio_p)
            if actual_duration <= 0:
                actual_duration = item.duration_ms

            start_ms = max(0, item.start_ms)
            end_ms = start_ms + actual_duration

            self.events.append(
                TimelineEvent(
                    item_id=item.id,
                    file_path=audio_p,
                    start_ms=start_ms,
                    end_ms=end_ms,
                    duration_ms=actual_duration,
                )
            )

            if end_ms > max_end_ms:
                max_end_ms = end_ms

        self.total_duration_ms = max_end_ms
        self.events.sort(key=lambda ev: ev.start_ms)
        log_info(
            f"Đã lập sơ đồ timeline: {len(self.events)} audio segments, "
            f"tổng thời lượng: {self.total_duration_ms / 1000.0:.2f}s"
        )
