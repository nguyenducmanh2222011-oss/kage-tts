"""
KAGEVIETSUB TTS - Application Entry Point.
Launches the PySide6 modern desktop GUI.
Also supports optional headless CLI execution for automation.
"""

import argparse
from pathlib import Path
import sys

# Ensure project root and capcut-tts-api are in sys.path
CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

CAPCUT_DIR = CURRENT_DIR / "capcut-tts-api"
if str(CAPCUT_DIR) not in sys.path:
    sys.path.insert(0, str(CAPCUT_DIR))


def run_gui():
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    from app.ui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("KAGEVIETSUB TTS")
    app.setOrganizationName("KAGEVIETSUB")

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


def run_cli(args):
    """Headless CLI mode for batch automation or testing."""
    from app.core.srt_parser import parse_srt
    from app.core.tts_manager import TTSManager
    from app.core.state_manager import StateManager
    from app.core.retry_manager import RetryManager
    from app.core.worker_manager import WorkerManager
    from app.audio.speed import batch_process_speeds
    from app.audio.timeline import TimelineEngine
    from app.audio.mixer import AudioMixer
    from app.audio.validator import validate_final_output
    from app.utils.paths import sanitize_filename, get_default_download_dir

    srt_path = Path(args.srt)
    if not srt_path.exists():
        print(f"Error: File SRT không tồn tại: {srt_path}", file=sys.stderr)
        sys.exit(1)

    print(f"[KAGEVIETSUB TTS CLI] Nạp file: {srt_path}")
    items = parse_srt(srt_path)
    print(f"Đã đọc {len(items)} dòng phụ đề.")

    job_name = sanitize_filename(srt_path.stem)
    state_mgr = StateManager(job_name)
    retry_mgr = RetryManager(state_mgr)
    tts_mgr = TTSManager()

    voice = args.voice or tts_mgr.get_default_voice()
    workers = args.threads or 10
    speed = args.speed or 1.0

    state_mgr.init_job(items, voice, speed)
    print(f"Bắt đầu xử lý TTS: Voice='{voice}', Threads={workers}, Speed={speed}x")

    def on_progress(comp, tot, st):
        pct = (comp / tot * 100) if tot > 0 else 0
        print(f"\rTiến độ: {comp}/{tot} ({pct:.1f}%) | Hoàn thành: {st['completed']} | Lỗi: {st['failed']}", end="", flush=True)

    worker_mgr = WorkerManager(
        tts_manager=tts_mgr,
        state_manager=state_mgr,
        retry_manager=retry_mgr,
        num_workers=workers,
        speed=speed,
        progress_callback=on_progress,
    )

    worker_mgr.process_items(items, voice)
    print("\nHoàn tất tạo TTS từng dòng.")

    print("Đang tổng hợp timeline và silence/overlap (block streaming)...")
    timeline = TimelineEngine(items)
    mixer = AudioMixer(timeline)
    out_file = f"{job_name}_TTS.wav"
    out_path = mixer.merge(out_file, job_name=job_name)

    val_ok, val_msg = validate_final_output(out_path)
    print(f"\n[KẾT QUẢ] {val_msg}")
    print(f"File master audio đã xuất tại: {out_path.resolve()}")


def main():
    parser = argparse.ArgumentParser(description="KAGEVIETSUB TTS Desktop & CLI Application")
    parser.add_argument("--cli", action="store_true", help="Chạy chế độ dòng lệnh không mở GUI")
    parser.add_argument("--srt", type=str, help="Đường dẫn tới file phụ đề .srt")
    parser.add_argument("--voice", type=str, help="Mã voice_type (ví dụ: BV421_vivn_streaming)")
    parser.add_argument("--threads", type=int, default=10, help="Số luồng TTS (1 đến 30)")
    parser.add_argument("--speed", type=float, default=1.0, help="Tốc độ âm thanh (0.5 đến 2.0)")

    args = parser.parse_args()

    if args.cli or args.srt:
        if not args.srt:
            parser.error("--srt là bắt buộc khi chạy chế độ CLI")
        run_cli(args)
    else:
        run_gui()


if __name__ == "__main__":
    main()
