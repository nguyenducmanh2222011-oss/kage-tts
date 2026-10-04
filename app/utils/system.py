"""
System resource detection, theme detection, and environment checks for KAGEVIETSUB TTS.
"""

import os
import shutil
import subprocess
import sys
from typing import Tuple


def get_cpu_count() -> int:
    """Returns number of logical CPU cores, at least 1."""
    return os.cpu_count() or 4


def get_ram_info() -> Tuple[float, float]:
    """
    Returns (total_gb, available_gb) using platform-specific APIs.
    Fallback safely if psutil is not installed.
    """
    total_gb = 8.0
    avail_gb = 4.0

    try:
        import psutil  # type: ignore
        mem = psutil.virtual_memory()
        return (round(mem.total / (1024**3), 1), round(mem.available / (1024**3), 1))
    except Exception:
        pass

    if sys.platform == "linux":
        try:
            with open("/proc/meminfo", "r") as f:
                lines = f.readlines()
            mem_dict = {}
            for line in lines:
                parts = line.split(":")
                if len(parts) == 2:
                    key = parts[0].strip()
                    val = parts[1].strip().split()[0]
                    mem_dict[key] = int(val)
            if "MemTotal" in mem_dict:
                total_gb = round(mem_dict["MemTotal"] / (1024**2), 1)
            if "MemAvailable" in mem_dict:
                avail_gb = round(mem_dict["MemAvailable"] / (1024**2), 1)
            elif "MemFree" in mem_dict:
                avail_gb = round(mem_dict["MemFree"] / (1024**2), 1)
        except Exception:
            pass

    return (total_gb, avail_gb)


def get_recommended_tts_workers() -> Tuple[int, str]:
    """
    Calculates recommended TTS worker count based on system CPU and RAM.
    Returns (recommended_default, tip_message).
    IMPORTANT: This is only a recommendation. The user can pick 1 to 30 freely.
    """
    cpu = get_cpu_count()
    total_ram, avail_ram = get_ram_info()

    if cpu <= 2 or avail_ram < 2.0:
        rec_range = "2–4"
        default_val = 4
    elif cpu <= 4:
        rec_range = "4–6"
        default_val = 6
    elif cpu <= 8:
        rec_range = "6–10"
        default_val = 10
    else:
        rec_range = "8–16"
        default_val = 12

    tip = f"💡 Đề xuất: {rec_range} luồng (CPU: {cpu} cores, RAM khả dụng: {avail_ram}GB)"
    return default_val, tip


def get_recommended_merge_workers() -> int:
    """
    Calculates recommended workers for audio speed/time-stretch & mixing.
    Auto-managed internally without exposing technical sliders to the user.
    """
    cpu = get_cpu_count()
    return max(2, min(cpu - 1, 8))


def is_dark_mode_active() -> bool:
    """
    Detects if system OS is currently set to Dark Mode.
    Supports Windows 10/11, macOS, and Linux (GNOME/KDE).
    """
    if sys.platform == "win32":
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            )
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            winreg.CloseKey(key)
            return value == 0
        except Exception:
            return False

    elif sys.platform == "darwin":
        try:
            out = subprocess.check_output(
                ["defaults", "read", "-g", "AppleInterfaceStyle"],
                stderr=subprocess.DEVNULL,
                timeout=1,
            )
            return "Dark" in out.decode("utf-8")
        except Exception:
            return False

    elif sys.platform == "linux":
        try:
            # Check GNOME color-scheme
            out = subprocess.check_output(
                ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
                stderr=subprocess.DEVNULL,
                timeout=1,
            )
            return "dark" in out.decode("utf-8").lower()
        except Exception:
            pass

    return False


def is_ffmpeg_available() -> bool:
    """Check if ffmpeg executable is found in system PATH."""
    return shutil.which("ffmpeg") is not None
