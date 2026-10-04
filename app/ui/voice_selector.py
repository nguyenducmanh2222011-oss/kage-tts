"""
Voice selector widget for KAGEVIETSUB TTS.
Modern, minimalist desktop application style.
Features:
- Region dropdown (Việt Nam default on top) + Search input.
- Voice selection dropdown.
- Active Voice Card:
  ┌──────────────────────────────────────────────┐ [🔊]
  │ Nhỏ Ngọt Ngào                             │
  │ Tiếng Việt • Nữ • Giọng kể truyện nhẹ nhàng   │
  └──────────────────────────────────────────────┘
"""

from typing import List, Optional
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from app.core.tts_manager import TTSManager
from capcut_tts_api.models import VoiceInfo


def get_voice_description(voice: Optional[VoiceInfo]) -> str:
    if not voice:
        return "Vui lòng chọn giọng đọc"
    name = voice.display_name or ""
    v_type = voice.voice_type.lower()
    lang = (voice.lang or voice.lan or "").lower()

    if "vi" in lang:
        if "female" in v_type or "nữ" in name.lower() or "ngọt" in name.lower() or "cô" in name.lower():
            return "Tiếng Việt • Nữ • Giọng kể truyện nhẹ nhàng"
        elif "male" in v_type or "nam" in name.lower() or "chàng" in name.lower() or "niên" in name.lower():
            return "Tiếng Việt • Nam • Giọng đọc truyền cảm"
        return "Tiếng Việt • Chuẩn phổ thông"
    elif "en" in lang:
        return "English • Studio Quality"
    elif "ja" in lang:
        return "Japanese (日本語) • Natural"
    elif "ko" in lang:
        return "Korean (한국어) • Natural"
    return f"{voice.lang or voice.lan or 'Quốc tế'} • {voice.voice_type}"


class VoiceSelectorWidget(QFrame):
    voice_changed = Signal(str)  # Emits selected voice_type

    def __init__(self, tts_manager: TTSManager, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setProperty("panel", "true")
        self.tts_mgr = tts_manager
        self.all_voices = self.tts_mgr.get_all_voices()
        self.current_filtered_voices: List[VoiceInfo] = []

        self._init_ui()
        self._populate_countries()
        self._apply_filter()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        # Section title
        title_label = QLabel("GIỌNG ĐỌC")
        title_label.setStyleSheet("font-weight: 700; font-size: 11px; color: #08A8E8; letter-spacing: 0.5px;")
        layout.addWidget(title_label)

        # Row 1: Khu vực + Tìm kiếm
        row1 = QHBoxLayout()
        row1.setSpacing(8)

        self.country_combo = QComboBox()
        self.country_combo.setFixedHeight(28)
        self.country_combo.currentIndexChanged.connect(self._apply_filter)
        row1.addWidget(self.country_combo, stretch=4)

        self.search_input = QLineEdit()
        self.search_input.setFixedHeight(28)
        self.search_input.setPlaceholderText("🔍 Tìm giọng...")
        self.search_input.textChanged.connect(self._apply_filter)
        row1.addWidget(self.search_input, stretch=6)

        layout.addLayout(row1)

        # Row 2: Voice selection dropdown
        self.voice_combo = QComboBox()
        self.voice_combo.setFixedHeight(28)
        self.voice_combo.currentIndexChanged.connect(self._on_voice_selected)
        layout.addWidget(self.voice_combo)

        # Row 3: Active Voice Card + Speaker button [🔊]
        active_card = QFrame()
        active_card.setStyleSheet("""
            QFrame {
                background-color: #101319;
                border: 1px solid #272D36;
                border-radius: 4px;
                padding: 4px 6px;
            }
        """)
        active_layout = QHBoxLayout(active_card)
        active_layout.setContentsMargins(8, 6, 8, 6)
        active_layout.setSpacing(8)

        text_box = QVBoxLayout()
        text_box.setSpacing(2)
        self.voice_title_lbl = QLabel("Đang tải...")
        self.voice_title_lbl.setStyleSheet("font-size: 12px; font-weight: 700; color: #E8EDF3;")
        self.voice_desc_lbl = QLabel("")
        self.voice_desc_lbl.setStyleSheet("font-size: 11px; color: #8993A3;")
        text_box.addWidget(self.voice_title_lbl)
        text_box.addWidget(self.voice_desc_lbl)
        active_layout.addLayout(text_box, stretch=1)

        self.preview_btn = QPushButton("🔊")
        self.preview_btn.setFixedSize(32, 32)
        self.preview_btn.setToolTip("Nghe thử câu mẫu giọng này")
        self.preview_btn.clicked.connect(self._on_preview_voice)
        active_layout.addWidget(self.preview_btn)

        layout.addWidget(active_card)

    def _populate_countries(self) -> None:
        self.country_combo.blockSignals(True)
        self.country_combo.clear()

        self.country_combo.addItem("🇻🇳 Việt Nam", "vi-VN")
        self.country_combo.addItem("🌐 Tất cả", "ALL")

        seen_langs = {"vi-vn"}
        for v in self.all_voices:
            l = (v.lang or v.lan or "").strip()
            if l and l.lower() not in seen_langs:
                seen_langs.add(l.lower())
                flag = "🌐"
                lc = l.lower()
                if "en" in lc:
                    flag = "🇺🇸"
                elif "ja" in lc:
                    flag = "🇯🇵"
                elif "ko" in lc:
                    flag = "🇰🇷"
                elif "id" in lc:
                    flag = "🇮🇩"
                elif "fr" in lc:
                    flag = "🇫🇷"
                elif "es" in lc:
                    flag = "🇪🇸"
                self.country_combo.addItem(f"{flag} {l}", l)

        self.country_combo.blockSignals(False)

    def _apply_filter(self) -> None:
        country_code = self.country_combo.currentData() or "vi-VN"
        query = self.search_input.text().strip().lower()

        filtered: List[VoiceInfo] = []
        for v in self.all_voices:
            v_lang = (v.lang or v.lan or "").lower()

            if country_code != "ALL":
                if country_code == "vi-VN" and v_lang != "vi-vn":
                    continue
                elif country_code != "vi-VN" and country_code.lower() not in v_lang:
                    continue

            if query:
                name = (v.display_name or "").lower()
                vtype = v.voice_type.lower()
                if query not in name and query not in vtype and query not in v_lang:
                    continue

            filtered.append(v)

        self.current_filtered_voices = filtered

        self.voice_combo.blockSignals(True)
        self.voice_combo.clear()
        for v in filtered:
            display = f"{v.display_name} ({v.voice_type})"
            self.voice_combo.addItem(display, v.voice_type)

        self.voice_combo.blockSignals(False)

        if filtered:
            self.voice_combo.setCurrentIndex(0)
            self._update_card(filtered[0])
            self.voice_changed.emit(filtered[0].voice_type)
        else:
            self.voice_title_lbl.setText("Không tìm thấy")
            self.voice_desc_lbl.setText("Không có giọng đọc phù hợp")

    def _on_voice_selected(self, idx: int) -> None:
        if 0 <= idx < len(self.current_filtered_voices):
            voice = self.current_filtered_voices[idx]
            self._update_card(voice)
            self.voice_changed.emit(voice.voice_type)

    def _update_card(self, voice: VoiceInfo) -> None:
        self.voice_title_lbl.setText(voice.display_name or voice.voice_type)
        self.voice_desc_lbl.setText(get_voice_description(voice))

    def get_selected_voice(self) -> str:
        idx = self.voice_combo.currentIndex()
        if 0 <= idx < len(self.current_filtered_voices):
            return self.current_filtered_voices[idx].voice_type
        return "BV421_vivn_streaming"

    def get_selected_voice_type(self) -> str:
        return self.get_selected_voice()

    def _on_preview_voice(self) -> None:
        from pathlib import Path
        import tempfile
        voice_type = self.get_selected_voice()
        v_obj = next((v for v in self.all_voices if v.voice_type == voice_type), None)
        text = "Xin chào, đây là giọng đọc thử nghiệm từ KAGEVIETSUB TTS."
        if v_obj and "en" in (v_obj.lang or "").lower():
            text = "Hello, this is a test audio from KAGEVIETSUB TTS."

        try:
            self.preview_btn.setEnabled(False)
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                tmp_p = Path(f.name)
            success = self.tts_mgr.synthesize_line(text, voice_type, tmp_p)
            if success:
                import subprocess
                subprocess.Popen(["ffplay", "-nodisp", "-autoexit", str(tmp_p)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
        finally:
            self.preview_btn.setEnabled(True)
