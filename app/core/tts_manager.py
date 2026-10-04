"""
TTS Manager for KAGEVIETSUB TTS.
Directly interfaces with CapCutClient and Voice.json catalog from capcut-tts-api.
Enforces:
- Original CapCutClient usage without mock/alternative engines.
- Authentic Voice.json loading with Vietnam (vi-VN) prioritized at the top.
- API rate fixed at 1.0x (subsequent speed adjustments handled by audio engine).
- Audio streaming directly to disk cache.
"""

import json
from pathlib import Path
import sys
import time
from typing import Dict, List, Optional, Tuple, Any

# Ensure capcut-tts-api is in Python import path
from app.utils.paths import get_project_root, get_voice_json_path
from app.utils.logger import log_tts, log_error, log_info

root_path = get_project_root()
capcut_sdk_path = root_path / "capcut-tts-api"
if str(capcut_sdk_path) not in sys.path:
    sys.path.insert(0, str(capcut_sdk_path))

try:
    from capcut_tts_api import CapCutClient
    from capcut_tts_api.models import VoiceInfo
except ImportError:
    # Fallback to local import if installed as package
    try:
        from capcut_tts_api.client import CapCutClient  # type: ignore
        from capcut_tts_api.models import VoiceInfo  # type: ignore
    except ImportError as e:
        log_error(f"Không thể import CapCutClient: {e}")
        CapCutClient = None  # type: ignore
        VoiceInfo = None  # type: ignore

try:
    import requests
except ImportError:
    requests = None


class TTSManager:
    def __init__(self):
        if CapCutClient is None:
            raise RuntimeError("capcut-tts-api chưa sẵn sàng trong môi trường Python.")
        self.client = CapCutClient()
        self.voices: List[VoiceInfo] = []
        self._load_voices()

    def _load_voices(self) -> None:
        """
        Loads authentic Voice.json from capcut-tts-api using VoiceInfo.load_catalog.
        Sorts catalog so Vietnamese voices (vi-VN) are STRICTLY AT THE TOP.
        """
        voice_path = get_voice_json_path()
        all_voices: List[VoiceInfo] = VoiceInfo.load_catalog(voice_path)

        # Sort: Vietnam (vi-VN) first, then language name, then display name
        vietnamese_voices = [v for v in all_voices if (v.lang or "").lower() == "vi-vn" or (v.lan or "").lower() == "vi-vn"]
        other_voices = [v for v in all_voices if v not in vietnamese_voices]

        # Keep original ordering within Vietnam, sort others alphabetically by lang
        other_voices.sort(key=lambda v: (v.lang or "", v.display_name or ""))

        self.voices = vietnamese_voices + other_voices
        log_info(f"Đã nạp {len(self.voices)} voices từ Voice.json ({len(vietnamese_voices)} giọng Việt Nam ở đầu)")

    def get_all_voices(self) -> List[VoiceInfo]:
        return self.voices

    def get_vietnamese_voices(self) -> List[VoiceInfo]:
        return [v for v in self.voices if (v.lang or "").lower() == "vi-vn"]

    def search_voices(self, query: str, country_filter: Optional[str] = None) -> List[VoiceInfo]:
        """Search by name, voice_type, or filter by country/lang code."""
        query_lower = query.strip().lower()
        results: List[VoiceInfo] = []

        for v in self.voices:
            if country_filter and country_filter != "Tất cả":
                if country_filter == "Việt Nam":
                    if (v.lang or "").lower() != "vi-vn":
                        continue
                else:
                    if country_filter.lower() not in (v.lang or "").lower():
                        continue

            if not query_lower:
                results.append(v)
            else:
                name_match = (v.display_name or "").lower()
                type_match = (v.voice_type or "").lower()
                lang_match = (v.lang or "").lower()
                if query_lower in name_match or query_lower in type_match or query_lower in lang_match:
                    results.append(v)

        return results

    def get_default_voice(self) -> str:
        """Returns standard default Vietnamese voice_type."""
        vn_voices = self.get_vietnamese_voices()
        if vn_voices:
            return vn_voices[0].voice_type
        return self.voices[0].voice_type if self.voices else "BV421_vivn_streaming"

    def synthesize_line(
        self,
        text: str,
        voice_type: str,
        output_file: Path,
        timeout: int = 40,
    ) -> Path:
        """
        Synthesizes a single text segment using CapCutClient.
        Enforces API speed 1.0x.
        Downloads audio directly to disk.
        """
        if not text.strip():
            text = "..."

        output_file.parent.mkdir(parents=True, exist_ok=True)

        # 1. Create TTS task via CapCutClient
        create_res = self.client.create_tts_task(
            texts=text,
            voice=voice_type,
            rate="1.0",
        )

        tasks = (create_res.get("data") or {}).get("tasks") or []
        if not tasks:
            raise RuntimeError(f"CapCut API không trả về task: {create_res}")

        task_id = tasks[0]["id"]
        token = tasks[0]["token"]

        # 2. Poll until task finishes
        start_time = time.time()
        audio_url: Optional[str] = None

        while time.time() - start_time < timeout:
            query_res = self.client.query_tts_task(task_id, token)
            q_tasks = (query_res.get("data") or {}).get("tasks") or []
            if q_tasks:
                status = q_tasks[0].get("status")
                if status in ("success", "succeed"):
                    # Extract speech URL
                    audio_url = self.client.extract_tts_audio_url(query_res)
                    break
                elif status == "failed":
                    raise RuntimeError(f"CapCut TTS Task failed: {query_res}")
            time.sleep(0.4)

        if not audio_url:
            raise TimeoutError(f"TTS Task quá thời gian chờ ({timeout}s)")

        # 3. Stream audio to disk without keeping in memory
        r = requests.get(audio_url, stream=True, timeout=30)
        r.raise_for_status()

        temp_file = output_file.with_suffix(output_file.suffix + ".tmp")
        with open(temp_file, "wb") as f:
            for chunk in r.iter_content(chunk_size=16384):
                if chunk:
                    f.write(chunk)

        temp_file.replace(output_file)
        return output_file
