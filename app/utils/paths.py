"""
Path utilities for KAGEVIETSUB TTS.
Handles platform-independent path resolution, download directories,
temporary job workspaces, and voice catalog locations.

Specifications:
- Output directory: Downloads/TTS/
- Temporary audio directory: app_data/temp/{job_name}/
- Temporary files auto-cleaned after successful merge
- 7-day automatic expiration cleanup on app launch
"""

from pathlib import Path
import os
import re
import shutil
import sys
import time

APP_NAME = "TTS"


def get_default_download_dir() -> Path:
    """
    Returns the standard Downloads directory for the current operating system:
    Downloads/TTS/
    """
    home = Path.home()
    download_dir = home / "Downloads" / APP_NAME
    download_dir.mkdir(parents=True, exist_ok=True)
    return download_dir


def get_app_data_dir() -> Path:
    """
    Returns the base application data directory:
    - Windows: %APPDATA%\\KagevietsubTTS
    - macOS: ~/Library/Application Support/KagevietsubTTS
    - Linux: ~/.local/share/kagevietsub_tts
    """
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))

    app_dir = base / "kagevietsub_tts"
    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir


def sanitize_filename(name: str) -> str:
    """
    Sanitize string to be safe for filenames across Windows, macOS, and Linux.
    """
    name = re.sub(r'[\\/*?:"<>|]', "_", name)
    name = name.strip(" ._")
    return name or "output"


def get_job_dir(job_id_or_name: str) -> Path:
    """
    Returns temporary workspace folder for a specific job under temp/.
    """
    return get_temp_job_dir(job_id_or_name)


def get_temp_job_dir(job_id_or_name: str) -> Path:
    """
    Returns a dedicated temporary workspace folder for a specific SRT job.
    Structure:
    temp/{job_id}/
    ├── created_at.txt
    └── audio/
    """
    safe_name = sanitize_filename(job_id_or_name)
    temp_dir = get_app_data_dir() / "temp" / safe_name
    temp_dir.mkdir(parents=True, exist_ok=True)
    (temp_dir / "audio").mkdir(parents=True, exist_ok=True)

    # Record created_at timestamp for 7-day expiration check
    created_at_file = temp_dir / "created_at.txt"
    if not created_at_file.exists():
        try:
            with open(created_at_file, "w", encoding="utf-8") as f:
                f.write(str(time.time()))
        except Exception:
            pass

    return temp_dir


def cleanup_job_temp_dir(job_id_or_name: str) -> None:
    """
    Removes the temporary directory for a specific job after successful merge.
    """
    try:
        safe_name = sanitize_filename(job_id_or_name)
        temp_dir = get_app_data_dir() / "temp" / safe_name
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
    except Exception:
        pass


def cleanup_expired_temp_dirs(max_age_days: int = 7) -> int:
    """
    Scans the temporary directory and deletes any job workspace older than max_age_days.
    Returns the count of deleted directories.
    """
    base_temp = get_app_data_dir() / "temp"
    if not base_temp.exists():
        return 0

    now = time.time()
    max_age_sec = max_age_days * 86400
    deleted_count = 0

    try:
        for job_folder in base_temp.iterdir():
            if not job_folder.is_dir():
                continue

            created_at_file = job_folder / "created_at.txt"
            folder_time = 0.0

            if created_at_file.exists():
                try:
                    folder_time = float(created_at_file.read_text(encoding="utf-8").strip())
                except Exception:
                    folder_time = job_folder.stat().st_mtime
            else:
                folder_time = job_folder.stat().st_mtime

            if (now - folder_time) >= max_age_sec:
                shutil.rmtree(job_folder, ignore_errors=True)
                deleted_count += 1
    except Exception:
        pass

    return deleted_count


def get_project_root() -> Path:
    """
    Returns the repository / project root path.
    """
    current = Path(__file__).resolve().parent
    while current != current.parent:
        if (current / "capcut-tts-api").exists() or (current / "Voice.json").exists():
            return current
        current = current.parent
    return Path.cwd()


def get_voice_json_path() -> Path:
    """
    Locates the authentic Voice.json from the capcut-tts-api repo.
    """
    root = get_project_root()
    candidates = [
        root / "capcut-tts-api" / "Voice.json",
        root / "Voice.json",
        Path.cwd() / "capcut-tts-api" / "Voice.json",
        Path.cwd() / "Voice.json",
    ]
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate.resolve()

    found = list(root.glob("**/Voice.json"))
    if found:
        return found[0].resolve()

    raise FileNotFoundError("Không tìm thấy Voice.json từ repo capcut-tts-api!")
