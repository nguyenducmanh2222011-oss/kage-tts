"""
Custom structured logger for KAGEVIETSUB TTS.
Provides categorized logging: [INFO], [WARNING], [ERROR], [RETRY], [TTS], [AUDIO], [MERGE]
with thread-safe execution, file persistence, and listener callbacks.
"""

from datetime import datetime
from pathlib import Path
import threading
import sys
from typing import Callable, Optional
from app.utils.paths import get_app_data_dir


class AppLogger:
    _instance: Optional["AppLogger"] = None
    _lock = threading.Lock()

    def __init__(self, log_to_file: bool = True):
        self.log_to_file = log_to_file
        self.log_file_path: Optional[Path] = None
        self._listeners: list[Callable[[str, str, str], None]] = []

        if log_to_file:
            log_dir = get_app_data_dir() / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            today_str = datetime.now().strftime("%Y-%m-%d")
            self.log_file_path = log_dir / f"kagevietsub_tts_{today_str}.log"

    @classmethod
    def get_instance(cls) -> "AppLogger":
        with cls._lock:
            if cls._instance is None:
                cls._instance = AppLogger()
            return cls._instance

    def add_listener(self, callback: Callable[[str, str, str], None]) -> None:
        """Register a callback for UI updates: callback(category, message, timestamp)"""
        with self._lock:
            if callback not in self._listeners:
                self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[str, str, str], None]) -> None:
        with self._lock:
            if callback in self._listeners:
                self._listeners.remove(callback)

    def _log(self, category: str, message: str) -> None:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        formatted = f"[{now_str}] [{category.upper()}] {message}"

        # Write to stderr or stdout
        if category in ("ERROR", "WARNING"):
            print(formatted, file=sys.stderr, flush=True)
        else:
            print(formatted, file=sys.stdout, flush=True)

        # Write to log file
        if self.log_file_path:
            try:
                with open(self.log_file_path, "a", encoding="utf-8") as f:
                    f.write(formatted + "\n")
            except Exception:
                pass

        # Notify listeners
        for listener in list(self._listeners):
            try:
                listener(category, message, now_str)
            except Exception:
                pass

    def info(self, msg: str) -> None:
        self._log("INFO", msg)

    def warning(self, msg: str) -> None:
        self._log("WARNING", msg)

    def error(self, msg: str) -> None:
        self._log("ERROR", msg)

    def retry(self, msg: str) -> None:
        self._log("RETRY", msg)

    def tts(self, msg: str) -> None:
        self._log("TTS", msg)

    def audio(self, msg: str) -> None:
        self._log("AUDIO", msg)

    def merge(self, msg: str) -> None:
        self._log("MERGE", msg)


# Convenience module-level functions
_logger = AppLogger.get_instance()


def log_info(msg: str) -> None:
    _logger.info(msg)


def log_warning(msg: str) -> None:
    _logger.warning(msg)


def log_error(msg: str) -> None:
    _logger.error(msg)


def log_retry(msg: str) -> None:
    _logger.retry(msg)


def log_tts(msg: str) -> None:
    _logger.tts(msg)


def log_audio(msg: str) -> None:
    _logger.audio(msg)


def log_merge(msg: str) -> None:
    _logger.merge(msg)
