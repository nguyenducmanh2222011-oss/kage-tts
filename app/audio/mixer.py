"""
Master Audio Mixer and Merger for KAGEVIETSUB TTS.
High-Performance Block-Based Streaming Timeline Synthesizer:
- Memory-bounded block processing (e.g. 5-minute chunks, ~26MB RAM for any length 1h-10h).
- Exact sample-accurate SRT timeline placement without delays.
- True multi-track overlap mixing with saturation/clipping protection via audioop.
- Natural silence in timeline gaps without slow seeking or giant pre-allocated disk files.
- Exports final master WAV to Downloads/TTS/ and auto-cleans temporary files.
"""

import audioop
import os
from pathlib import Path
import subprocess
import wave
from typing import Callable, Dict, List, Optional
from app.audio.timeline import TimelineEngine, TimelineEvent
from app.utils.logger import log_merge, log_error, log_info
from app.utils.paths import get_default_download_dir, sanitize_filename, cleanup_job_temp_dir

SAMPLE_RATE = 44100
CHANNELS = 1
BYTES_PER_SAMPLE = 2  # 16-bit PCM (s16le)
BLOCK_DURATION_SEC = 300  # 5 minutes per block


def _read_pcm_s16le(file_path: Path) -> bytes:
    """
    Decodes audio file into 44.1kHz 16-bit mono PCM bytes.
    If already a conforming WAV file, reads frames directly in zero-overhead Python.
    Otherwise uses FFmpeg to stream decoded s16le PCM to memory.
    """
    if not file_path.exists() or file_path.stat().st_size == 0:
        return b""

    if file_path.suffix.lower() == ".wav":
        try:
            with wave.open(str(file_path), "rb") as wf:
                if (
                    wf.getnchannels() == CHANNELS
                    and wf.getframerate() == SAMPLE_RATE
                    and wf.getsampwidth() == BYTES_PER_SAMPLE
                ):
                    return wf.readframes(wf.getnframes())
        except Exception:
            pass

    # Decode directly to raw PCM s16le mono 44.1kHz via FFmpeg pipe (single-threaded)
    cmd = [
        "ffmpeg",
        "-threads",
        "1",
        "-v",
        "error",
        "-i",
        str(file_path),
        "-threads",
        "1",
        "-ar",
        str(SAMPLE_RATE),
        "-ac",
        str(CHANNELS),
        "-f",
        "s16le",
        "-c:a",
        "pcm_s16le",
        "pipe:1",
    ]
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, timeout=30)
        return proc.stdout
    except Exception as e:
        log_error(f"Lỗi giải mã audio cho {file_path.name}: {e}")
        return b""


class AudioMixer:
    def __init__(self, timeline: TimelineEngine):
        self.timeline = timeline

    def merge(
        self,
        output_filename: str,
        custom_output_dir: Optional[Path] = None,
        job_name: Optional[str] = None,
        progress_cb: Optional[Callable[[float], None]] = None,
    ) -> Path:
        """
        Synthesizes timeline events into the master output file using block-based streaming.
        Saves output in Downloads/TTS/ and purges temporary files upon completion.
        """
        output_dir = custom_output_dir or get_default_download_dir()
        output_dir.mkdir(parents=True, exist_ok=True)

        safe_name = sanitize_filename(output_filename)
        if not safe_name.lower().endswith(".wav"):
            safe_name += ".wav"

        final_path = output_dir / safe_name
        temp_dest = final_path.with_suffix(".merge.tmp.wav")

        total_ms = self.timeline.total_duration_ms
        if total_ms <= 0:
            total_ms = 1000  # Default 1 second minimum

        total_sec = total_ms / 1000.0
        total_samples = int(total_sec * SAMPLE_RATE)

        log_merge(
            f"Bắt đầu tổng hợp master audio theo block ({total_sec:.2f}s, "
            f"khoảng {(total_samples * 2) / (1024 * 1024):.1f} MB) tại {final_path}..."
        )

        # Pre-cache PCM bytes for small-to-medium files or stream as needed
        # Timeline events sorted by start_ms
        events = self.timeline.events
        total_blocks = max(1, int(total_sec // BLOCK_DURATION_SEC) + (1 if total_sec % BLOCK_DURATION_SEC != 0 else 0))

        with wave.open(str(temp_dest), "wb") as master_wf:
            master_wf.setnchannels(CHANNELS)
            master_wf.setsampwidth(BYTES_PER_SAMPLE)
            master_wf.setframerate(SAMPLE_RATE)

            block_idx = 0
            while True:
                block_start_sec = block_idx * BLOCK_DURATION_SEC
                if block_start_sec >= total_sec:
                    break

                block_end_sec = min((block_idx + 1) * BLOCK_DURATION_SEC, total_sec)
                block_duration = block_end_sec - block_start_sec
                block_samples = int(block_duration * SAMPLE_RATE)
                if block_samples <= 0:
                    break

                # Allocate zero-filled silence buffer for this block (~26MB for 5 min)
                block_buf = bytearray(block_samples * BYTES_PER_SAMPLE)

                # Find all events intersecting this block:
                # event.start_sec < block_end_sec and event.end_sec > block_start_sec
                overlapping_events = [
                    ev for ev in events
                    if ev.start_sec < block_end_sec and ev.end_sec > block_start_sec
                ]

                for ev in overlapping_events:
                    pcm_data = _read_pcm_s16le(ev.file_path)
                    if not pcm_data:
                        continue

                    ev_total_samples = len(pcm_data) // BYTES_PER_SAMPLE
                    if ev_total_samples == 0:
                        continue

                    # Calculate start position within this block
                    if ev.start_sec >= block_start_sec:
                        block_sample_offset = int((ev.start_sec - block_start_sec) * SAMPLE_RATE)
                        ev_sample_offset = 0
                    else:
                        block_sample_offset = 0
                        ev_sample_offset = int((block_start_sec - ev.start_sec) * SAMPLE_RATE)

                    if block_sample_offset >= block_samples or ev_sample_offset >= ev_total_samples:
                        continue

                    # Number of samples to mix in this block
                    samples_to_mix = min(
                        block_samples - block_sample_offset,
                        ev_total_samples - ev_sample_offset,
                    )
                    if samples_to_mix <= 0:
                        continue

                    ev_byte_start = ev_sample_offset * BYTES_PER_SAMPLE
                    ev_byte_end = ev_byte_start + (samples_to_mix * BYTES_PER_SAMPLE)
                    ev_slice = pcm_data[ev_byte_start:ev_byte_end]

                    block_byte_start = block_sample_offset * BYTES_PER_SAMPLE
                    block_byte_end = block_byte_start + (samples_to_mix * BYTES_PER_SAMPLE)
                    current_block_slice = block_buf[block_byte_start:block_byte_end]

                    # Mix with saturation (audioop.add)
                    mixed_slice = audioop.add(current_block_slice, ev_slice, BYTES_PER_SAMPLE)
                    block_buf[block_byte_start:block_byte_end] = mixed_slice

                # Write block directly to WAV file
                master_wf.writeframes(block_buf)
                del block_buf

                block_idx += 1
                if progress_cb:
                    progress_cb(min(1.0, block_idx / total_blocks))

        if temp_dest.exists() and temp_dest.stat().st_size > 44:
            temp_dest.replace(final_path)
            log_merge(f"✅ Hoàn tất ghép audio thành công! File lưu tại: {final_path}")
        else:
            raise RuntimeError("Tổng hợp master audio thất bại (file rỗng hoặc lỗi).")

        # Cleanup temporary audio files if job_name specified
        if job_name:
            cleanup_job_temp_dir(job_name)
            log_info(f"Đã dọn dẹp sạch thư mục temp cho job '{job_name}'.")

        return final_path
