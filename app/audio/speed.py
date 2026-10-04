"""
Speed and pitch-preserving time-stretch engine for KAGEVIETSUB TTS.
Preserves voice pitch perfectly using FFmpeg's high-fidelity atempo audio filter graph.

Core Rules:
1. If speed == 1.00x: BYPASS FFmpeg completely. Keep original audio file, saving massive CPU/IO.
2. If speed != 1.00x: Run FFmpeg with chained atempo filters, outputting 16-bit PCM WAV at 44.1kHz.
3. Concurrency is managed internally (CPU Audio Worker Pool: 1-4 workers dynamically calculated)
   and strictly independent of TTS worker count (1-30).
4. Strict thread limit: Every FFmpeg process runs with -threads 1 to prevent CPU saturation.
"""

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import shutil
import subprocess
from typing import List, Optional
from app.core.srt_parser import SRTItem
from app.utils.logger import log_audio, log_error, log_info


def get_cpu_audio_worker_count() -> int:
    """
    Dynamically computes safe concurrency for CPU-heavy audio tasks (FFmpeg, time-stretch, conversion).
    Independent of TTS worker count.
    Formula balances CPU throughput without causing CPU spikes or UI stutter:
    - <= 2 cores: 1 worker
    - 3-6 cores: 2 workers
    - 7-12 cores: 3 workers
    - > 12 cores: 4 workers
    """
    cores = os.cpu_count() or 4
    if cores <= 2:
        return 1
    elif cores <= 6:
        return 2
    elif cores <= 12:
        return 3
    else:
        return 4


MAX_SPEED_WORKERS = get_cpu_audio_worker_count()


def build_atempo_filter(speed: float) -> str:
    """
    Builds an FFmpeg atempo filter string.
    Since atempo only accepts [0.5, 2.0], chaining is required for outer values:
    e.g. speed=2.5 -> atempo=2.0,atempo=1.25
    e.g. speed=0.4 -> atempo=0.5,atempo=0.8
    """
    if speed <= 0:
        return "atempo=1.0"

    filters: List[str] = []
    curr = float(speed)

    while curr > 2.0:
        filters.append("atempo=2.0")
        curr /= 2.0

    while curr < 0.5:
        filters.append("atempo=0.5")
        curr /= 0.5

    filters.append(f"atempo={curr:.4f}")
    return ",".join(filters)


def process_audio_speed(
    input_file: Path,
    output_wav: Path,
    speed: float = 1.0,
    target_sample_rate: int = 44100,
) -> Path:
    """
    Adjusts audio playback speed while PRESERVING PITCH.
    - If speed == 1.0x: Skips FFmpeg completely. Returns input_file directly.
    - If speed != 1.0x: Runs FFmpeg time-stretch, outputs 16-bit mono PCM WAV at 44.1kHz.
    Strictly forces '-threads 1' to avoid multi-threaded CPU spikes.
    """
    if not input_file.exists() or input_file.stat().st_size == 0:
        log_error(f"File âm thanh đầu vào không tồn tại hoặc rỗng: {input_file}")
        return input_file

    # Rule 1: Bỏ qua FFmpeg nếu speed = 1.0x
    if abs(speed - 1.0) < 0.01:
        return input_file

    output_wav.parent.mkdir(parents=True, exist_ok=True)
    temp_wav = output_wav.with_suffix(".tmp.wav")

    atempo_str = build_atempo_filter(speed)
    # Strictly enforce -threads 1 for both input demuxing and output filtering
    cmd = [
        "ffmpeg",
        "-threads",
        "1",
        "-y",
        "-i",
        str(input_file),
        "-filter:a",
        atempo_str,
        "-threads",
        "1",
        "-ar",
        str(target_sample_rate),
        "-ac",
        "1",
        "-c:a",
        "pcm_s16le",
        "-vn",
        str(temp_wav),
    ]

    try:
        subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            timeout=30,
        )
        if temp_wav.exists() and temp_wav.stat().st_size > 0:
            temp_wav.replace(output_wav)
            return output_wav
        else:
            return input_file
    except Exception as e:
        log_error(f"Lỗi khi time-stretch ({speed}x) file {input_file.name}: {e}")
        if temp_wav.exists():
            temp_wav.unlink(missing_ok=True)
        return input_file


def batch_process_speeds(
    items: List[SRTItem],
    speed: float = 1.0,
    max_workers: Optional[int] = None,
) -> None:
    """
    Processes speed for a batch of items.
    Bypasses entirely if speed == 1.0x.
    Uses limited internal workers (1-4 dynamically calculated) to avoid CPU bottleneck.
    """
    if abs(speed - 1.0) < 0.01:
        log_info("Tốc độ = 1.00x: Giữ nguyên audio gốc, bỏ qua toàn bộ FFmpeg time-stretch.")
        return

    workers = max_workers or get_cpu_audio_worker_count()
    log_info(f"Bắt đầu xử lý tốc độ ({speed:.2f}x) cho {len(items)} audio con với {workers} workers nội bộ...")

    def _task(item: SRTItem) -> None:
        if not item.audio_path:
            return
        orig_p = Path(item.audio_path)
        if not orig_p.exists():
            return

        out_wav = orig_p.parent / f"speed_{orig_p.stem}.wav"
        result_p = process_audio_speed(orig_p, out_wav, speed=speed)
        item.audio_path = str(result_p)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        list(executor.map(_task, items))

    log_info(f"Đã hoàn thành chuẩn hóa tốc độ {speed:.2f}x cho các file audio.")
