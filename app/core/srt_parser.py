"""
SRT subtitle parser for KAGEVIETSUB TTS.
Parses standard and loose SRT subtitle files into strongly-typed SRTItem records.
Preserves original IDs, exact timestamps, and text content.
"""

from dataclasses import dataclass, asdict
from pathlib import Path
import re
from typing import List, Optional, Union


@dataclass(slots=True)
class SRTItem:
    id: int
    start_str: str
    end_str: str
    start_ms: int
    end_ms: int
    duration_ms: int
    text: str
    voice: str = ""
    status: str = "Chờ"  # "Chờ", "Đang tạo", "Hoàn thành", "Lỗi", "Retry X/5", "Thất bại 5/5"
    retry_count: int = 0
    error: str = ""
    audio_path: str = ""
    speed: float = 1.0

    @property
    def duration_str(self) -> str:
        sec = self.duration_ms / 1000.0
        return f"{sec:.2f}s"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "SRTItem":
        return cls(
            id=int(data["id"]),
            start_str=data["start_str"],
            end_str=data["end_str"],
            start_ms=int(data["start_ms"]),
            end_ms=int(data["end_ms"]),
            duration_ms=int(data["duration_ms"]),
            text=data["text"],
            voice=data.get("voice", ""),
            status=data.get("status", "Chờ"),
            retry_count=int(data.get("retry_count", 0)),
            error=data.get("error", ""),
            audio_path=data.get("audio_path", ""),
            speed=float(data.get("speed", 1.0)),
        )


def timestamp_to_ms(ts: str) -> int:
    """
    Converts '00:01:23,456' or '00:01:23.456' to milliseconds.
    """
    ts = ts.strip().replace(",", ".")
    parts = ts.split(":")
    if len(parts) == 3:
        h, m = int(parts[0]), int(parts[1])
        s_parts = parts[2].split(".")
        s = int(s_parts[0])
        ms = int(s_parts[1].ljust(3, "0")[:3]) if len(s_parts) > 1 else 0
        return (h * 3600 + m * 60 + s) * 1000 + ms
    elif len(parts) == 2:
        m = int(parts[0])
        s_parts = parts[1].split(".")
        s = int(s_parts[0])
        ms = int(s_parts[1].ljust(3, "0")[:3]) if len(s_parts) > 1 else 0
        return (m * 60 + s) * 1000 + ms
    return 0


def ms_to_timestamp(ms: int) -> str:
    """
    Converts milliseconds to standard SRT timestamp 'HH:MM:SS,mmm'.
    """
    total_seconds = ms // 1000
    milliseconds = ms % 1000
    seconds = total_seconds % 60
    total_minutes = total_seconds // 60
    minutes = total_minutes % 60
    hours = total_minutes // 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"


def clean_subtitle_text(text: str) -> str:
    """
    Strips formatting tags (HTML/ASS style like <i>, <b>, {\an8}) while preserving text.
    """
    # Remove HTML tags
    clean = re.sub(r"<[^>]+>", "", text)
    # Remove ASS/SSA tags {\...}
    clean = re.sub(r"\{[^\}]+\}", "", clean)
    # Normalize whitespaces
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean


def parse_srt(file_path_or_content: Union[str, Path]) -> List[SRTItem]:
    """
    Parses an SRT file or raw string content into a list of SRTItem.
    Auto-detects UTF-8, UTF-8-sig (BOM), UTF-16, latin-1 encodings.
    """
    content = ""
    if isinstance(file_path_or_content, Path) or (
        isinstance(file_path_or_content, str) and "\n" not in file_path_or_content and Path(file_path_or_content).exists()
    ):
        file_path = Path(file_path_or_content)
        for enc in ("utf-8-sig", "utf-8", "utf-16", "cp1258", "latin-1"):
            try:
                with open(file_path, "r", encoding=enc) as f:
                    content = f.read()
                break
            except UnicodeDecodeError:
                continue
    else:
        content = str(file_path_or_content)

    if not content.strip():
        return []

    # Standardize newlines
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    # Split blocks separated by blank lines
    blocks = re.split(r"\n\s*\n", normalized.strip())

    items: List[SRTItem] = []
    fallback_id = 1

    time_pattern = re.compile(
        r"(\d{1,2}:\d{2}:\d{2}[,\.]\d{1,3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,\.]\d{1,3})"
    )

    for block in blocks:
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        if not lines:
            continue

        item_id = fallback_id
        time_line_idx = -1

        # Check if first line is numeric ID
        if lines[0].isdigit():
            item_id = int(lines[0])
            # Second line should be timestamp
            if len(lines) > 1 and time_pattern.search(lines[1]):
                time_line_idx = 1
        elif time_pattern.search(lines[0]):
            time_line_idx = 0

        if time_line_idx == -1:
            # Search any line matching timestamp pattern
            for idx, line in enumerate(lines):
                if time_pattern.search(line):
                    time_line_idx = idx
                    break

        if time_line_idx == -1:
            # Not a valid SRT block
            continue

        match = time_pattern.search(lines[time_line_idx])
        if not match:
            continue

        start_str = match.group(1).replace(".", ",")
        end_str = match.group(2).replace(".", ",")
        start_ms = timestamp_to_ms(start_str)
        end_ms = timestamp_to_ms(end_str)

        duration_ms = max(0, end_ms - start_ms)

        # Remaining lines are subtitle text
        text_lines = lines[time_line_idx + 1 :]
        raw_text = " ".join(text_lines)
        clean_txt = clean_subtitle_text(raw_text)

        if not clean_txt:
            clean_txt = "..."

        items.append(
            SRTItem(
                id=item_id,
                start_str=start_str,
                end_str=end_str,
                start_ms=start_ms,
                end_ms=end_ms,
                duration_ms=duration_ms,
                text=clean_txt,
            )
        )
        fallback_id += 1

    return items
