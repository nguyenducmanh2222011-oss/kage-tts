"""
Audio validation and health verification for KAGEVIETSUB TTS.
"""

from pathlib import Path
import wave
from typing import Optional, Tuple
from app.utils.logger import log_error, log_info


def validate_wav_file(file_path: Path) -> Tuple[bool, str]:
    """
    Validates that a WAV file exists, has content > 0, and has a readable WAV header.
    Returns (is_valid, message).
    """
    if not file_path.exists():
        return False, f"File không tồn tại: {file_path}"

    size = file_path.stat().st_size
    if size < 44:
        return False, f"File quá nhỏ hoặc rỗng ({size} bytes)"

    try:
        with wave.open(str(file_path), "rb") as wf:
            channels = wf.getnchannels()
            rate = wf.getframerate()
            frames = wf.getnframes()
            duration_s = frames / rate if rate > 0 else 0
            return True, f"WAV hợp lệ: {duration_s:.2f}s, {channels}ch, {rate}Hz"
    except Exception as e:
        return False, f"File WAV không đúng định dạng: {e}"


def validate_final_output(
    file_path: Path, expected_min_duration_ms: int = 1000
) -> Tuple[bool, str]:
    """
    Validates final synthesized master audio.
    """
    is_valid, msg = validate_wav_file(file_path)
    if not is_valid:
        log_error(f"Kiểm tra file cuối thất bại: {msg}")
        return False, msg

    log_info(f"✅ Kiểm tra file cuối thành công: {msg}")
    return True, msg
