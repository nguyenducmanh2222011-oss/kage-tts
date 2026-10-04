"""
Retry manager and error queue for KAGEVIETSUB TTS.
Enforces the mandatory error queue pattern:
- Immediate enrollment into error queue upon failure.
- Maximum 5 retries per failed line (Retry 1/5 ... Retry 5/5).
- Exponential backoff with jitter.
- Targeted retry stage processing ONLY error queue items.
"""

import random
import threading
import time
from typing import List, Set
from app.core.srt_parser import SRTItem
from app.core.state_manager import StateManager
from app.utils.logger import log_retry, log_error, log_info

MAX_RETRIES = 5


class RetryManager:
    def __init__(self, state_manager: StateManager):
        self.state_mgr = state_manager
        self._error_ids: Set[int] = set()
        self._lock = threading.Lock()

    def record_failure(self, item: SRTItem, error_msg: str) -> None:
        """
        Record a failure for a line.
        Enrolls item into error queue and increments retry counter.
        """
        item.retry_count += 1
        item.error = error_msg

        if item.retry_count > MAX_RETRIES:
            item.status = f"Thất bại {MAX_RETRIES}/{MAX_RETRIES}"
            log_error(f"Dòng {item.id} thất bại sau {MAX_RETRIES} lần thử: {error_msg}")
        else:
            item.status = f"Retry {item.retry_count}/{MAX_RETRIES}"
            log_retry(f"Dòng {item.id} lỗi ({error_msg}). Đã ghi nhận vào hàng đợi lỗi ({item.status})")

        with self._lock:
            self._error_ids.add(item.id)
        self.state_mgr.update_line(item)

    def record_success(self, item: SRTItem) -> None:
        """
        Record success for a line.
        Clears error and removes from error queue.
        """
        item.status = "Hoàn thành"
        item.error = ""
        with self._lock:
            self._error_ids.discard(item.id)
        self.state_mgr.update_line(item)
        log_info(f"Dòng {item.id} đã hoàn thành thành công!")

    def get_backoff_delay(self, retry_count: int) -> float:
        """Calculates exponential backoff with jitter in seconds."""
        base = 0.5 * (2 ** max(0, retry_count - 1))
        jitter = random.uniform(0.1, 0.4)
        return min(base + jitter, 10.0)

    def get_pending_retry_ids(self) -> List[int]:
        """Returns error queue IDs eligible for retry (< MAX_RETRIES)."""
        with self._lock:
            return list(self._error_ids)
