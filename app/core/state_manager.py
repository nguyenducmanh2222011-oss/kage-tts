"""
Temporary State and Audio Path Manager for KAGEVIETSUB TTS.
Manages transient files during pipeline execution in temp/{job_id}/:
temp/{job_id}/
├── created_at.txt
└── audio/
    ├── 1.mp3
    ├── speed_1.wav
    └── ...

No persistent project recovery state is saved to disk:
If cancelled, crashed, or reopened, the user simply runs the SRT afresh.
"""

from pathlib import Path
import threading
from typing import Dict, List, Optional
from app.core.srt_parser import SRTItem
from app.utils.logger import log_info
from app.utils.paths import get_temp_job_dir, cleanup_job_temp_dir


class StateManager:
    def __init__(self, job_name: str, base_dir: Optional[Path] = None):
        self.job_name = job_name
        self.job_dir = base_dir or get_temp_job_dir(job_name)
        self.audio_dir = self.job_dir / "audio"
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._items_map: Dict[int, SRTItem] = {}

    def init_job(self, srt_items: List[SRTItem], global_voice: str, speed: float) -> None:
        """Initialize transient job session in memory and prepare temp audio folder."""
        with self._lock:
            self._items_map = {item.id: item for item in srt_items}
        log_info(f"Đã khởi tạo phiên tạm cho job '{self.job_name}' tại {self.job_dir} ({len(srt_items)} dòng)")

    def update_line(self, item: SRTItem) -> None:
        """Update in-memory state of a line."""
        with self._lock:
            self._items_map[item.id] = item

    def get_line(self, item_id: int) -> Optional[SRTItem]:
        with self._lock:
            return self._items_map.get(item_id)

    def get_audio_path(self, item_id: int, ext: str = "mp3") -> Path:
        """Returns standard transient audio path for a line item."""
        ext_clean = ext.lstrip(".")
        return self.audio_dir / f"{item_id:04d}.{ext_clean}"

    def get_speed_audio_path(self, item_id: int) -> Path:
        """Returns transient time-stretched WAV path for a line item."""
        return self.audio_dir / f"speed_{item_id:04d}.wav"

    def cleanup(self) -> None:
        """Removes the temp folder once job is finalized."""
        cleanup_job_temp_dir(self.job_name)
