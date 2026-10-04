"""
Main Application Window for KAGEVIETSUB TTS.
Polished Desktop Utility Tool:
- Main content container centered with max-width (~1440px), responsive on smaller screens.
- Clean header (18-20px title, subtle subtitle, no right buttons).
- File SRT: Compact row, metadata together, clean small button.
- Voice: Balanced 35/65 ratio, compact dropdown, small preview button.
- Settings: Centered titles, centered controls (90-120px width), centered hints. No sliders.
- Start CTA: Centered horizontally (340-380px width, 45px height), prominent and clean.
- Progress: 8px bar, left counter, right status counts.
- Table: Header 'PHỤ ĐỀ' left and '154 dòng' right, balanced column widths.
"""

from pathlib import Path
import queue
import subprocess
import sys
from typing import List, Optional

from PySide6.QtCore import (
    QObject,
    QThread,
    QTimer,
    Qt,
    Signal,
)
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.audio.mixer import AudioMixer
from app.audio.speed import batch_process_speeds
from app.audio.timeline import TimelineEngine
from app.audio.validator import validate_final_output
from app.core.retry_manager import RetryManager
from app.core.srt_parser import SRTItem, parse_srt
from app.core.state_manager import StateManager
from app.core.tts_manager import TTSManager
from app.core.worker_manager import WorkerManager
from app.ui.srt_table import SRTTableModel, SRTTableView
from app.ui.styles import get_theme_stylesheet
from app.ui.voice_selector import VoiceSelectorWidget
from app.utils.logger import log_error, log_info
from app.utils.paths import get_default_download_dir, sanitize_filename, cleanup_expired_temp_dirs
from app.utils.system import (
    is_dark_mode_active,
    is_ffmpeg_available,
)

SPEED_OPTIONS = [
    "0.50x",
    "0.75x",
    "0.80x",
    "0.90x",
    "1.00x",
    "1.10x",
    "1.20x",
    "1.25x",
    "1.50x",
    "2.00x",
]


def format_total_duration(ms: float) -> str:
    """Format milliseconds into HH:MM:SS or MM:SS."""
    total_sec = int(ms / 1000)
    hours = total_sec // 3600
    minutes = (total_sec % 3600) // 60
    seconds = total_sec % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


class TTSPipelineWorker(QObject):
    """
    Background worker thread running the complete TTS pipeline:
    SRT -> TTS Workers (1-30) -> CPU Audio Pool (1-4) -> Timeline Engine -> Mixer -> Final WAV
    """
    status_step = Signal(str, str)  # step_id, status_message
    pipeline_finished = Signal(bool, str, str)  # success, message, final_path

    def __init__(
        self,
        items: List[SRTItem],
        global_voice: str,
        num_workers: int,
        speed: float,
        srt_file_path: Path,
        ui_queue: Optional[queue.Queue] = None,
    ):
        super().__init__()
        self.items = items
        self.global_voice = global_voice
        self.num_workers = num_workers
        self.speed = speed
        self.srt_path = srt_file_path
        self.ui_queue = ui_queue

        self.job_name = sanitize_filename(self.srt_path.stem)
        self.state_mgr = StateManager(self.job_name)
        self.retry_mgr = RetryManager(self.state_mgr)
        self.tts_mgr = TTSManager()
        self.worker_mgr: Optional[WorkerManager] = None
        self._is_cancelled = False

    def cancel(self) -> None:
        self._is_cancelled = True
        if self.worker_mgr:
            self.worker_mgr.cancel()

    def run(self) -> None:
        try:
            self.status_step.emit("tts", f"Đang tạo giọng đọc ({self.num_workers} luồng)...")
            self.state_mgr.init_job(self.items, self.global_voice, self.speed)

            self.worker_mgr = WorkerManager(
                tts_manager=self.tts_mgr,
                state_manager=self.state_mgr,
                retry_manager=self.retry_mgr,
                num_workers=self.num_workers,
                speed=self.speed,
                ui_queue=self.ui_queue,
            )

            success = self.worker_mgr.process_items(self.items, self.global_voice)
            if self._is_cancelled or not success:
                self.pipeline_finished.emit(False, "Quá trình đã dừng.", "")
                return

            completed_count = sum(1 for it in self.items if it.status == "Hoàn thành")
            if completed_count == 0:
                self.pipeline_finished.emit(False, "Không có dòng phụ đề nào được tạo thành công.", "")
                return

            # Timeline arrangement
            self.status_step.emit("timeline", "Đang ghép timeline và khoảng lặng (overlap tự nhiên)...")
            timeline = TimelineEngine(self.items)

            # Master audio mixing with block streaming
            self.status_step.emit("merge", "Đang xuất master audio theo block...")
            mixer = AudioMixer(timeline)
            out_filename = f"{self.job_name}_TTS.wav"
            final_wav_path = mixer.merge(
                out_filename,
                job_name=self.job_name,
                progress_cb=lambda pct: self.status_step.emit("merge", f"Đang xuất master audio: {int(pct * 100)}%"),
            )

            is_valid, val_msg = validate_final_output(final_wav_path)
            if not is_valid:
                self.pipeline_finished.emit(False, f"Lỗi file: {val_msg}", str(final_wav_path))
                return

            self.status_step.emit("done", "Hoàn tất!")
            self.pipeline_finished.emit(True, "Xuất audio thành công!", str(final_wav_path))

        except Exception as e:
            log_error(f"Lỗi pipeline: {e}")
            self.pipeline_finished.emit(False, f"Lỗi: {e}", "")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("KAGEVIETSUB TTS")
        self.setMinimumSize(960, 680)
        self.resize(1160, 780)
        self.setAcceptDrops(True)

        # 7-day automatic cleanup of expired temporary workspaces
        cleaned = cleanup_expired_temp_dirs(max_age_days=7)
        if cleaned > 0:
            log_info(f"Đã tự động dọn {cleaned} thư mục temp hết hạn (> 7 ngày).")

        self.current_srt_path: Optional[Path] = None
        self.srt_items: List[SRTItem] = []
        self.tts_thread: Optional[QThread] = None
        self.pipeline_worker: Optional[TTSPipelineWorker] = None
        self.last_output_path: Optional[Path] = None

        self.ui_queue: queue.Queue = queue.Queue()
        self.ui_timer = QTimer(self)
        self.ui_timer.setInterval(300)
        self.ui_timer.timeout.connect(self._on_ui_timer_tick)

        # Debounced search timer (250ms) for high-performance filtering
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(250)
        self.search_timer.timeout.connect(self._on_search_timer_timeout)

        self.tts_manager = TTSManager()

        self._init_ui()
        self._apply_auto_theme()

        if not is_ffmpeg_available():
            QMessageBox.warning(
                self,
                "Thiếu FFmpeg",
                "FFmpeg chưa được cài đặt trong hệ thống PATH. Tốc độ âm thanh có thể bị hạn chế.",
            )

    def _init_ui(self) -> None:
        central = QWidget(self)
        central.setObjectName("centralWidget")
        self.setCentralWidget(central)

        # Outer root layout for centering
        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # Main content container (max-width ~1440px, centered horizontally)
        container = QWidget()
        container.setObjectName("mainContainer")
        container.setMaximumWidth(1440)

        main_layout = QVBoxLayout(container)
        main_layout.setContentsMargins(16, 12, 16, 12)
        main_layout.setSpacing(10)

        root_layout.addStretch(1)
        root_layout.addWidget(container, stretch=10)
        root_layout.addStretch(1)

        # -------------------------------------------------------------
        # 1. HEADER (App Title Left, Subtle Subtitle, Settings Gear Right)
        # -------------------------------------------------------------
        header_bar = QHBoxLayout()
        header_bar.setContentsMargins(0, 0, 0, 2)

        header_box = QVBoxLayout()
        header_box.setSpacing(1)
        title_lbl = QLabel("KAGEVIETSUB TTS")
        title_lbl.setStyleSheet("font-weight: 800; font-size: 19px; color: #08A8E8; letter-spacing: 0.5px;")
        sub_lbl = QLabel("SRT → Âm thanh")
        sub_lbl.setStyleSheet("font-size: 11px; color: #8993A3;")
        header_box.addWidget(title_lbl)
        header_box.addWidget(sub_lbl)
        header_bar.addLayout(header_box)

        header_bar.addStretch(1)

        self.settings_btn = QPushButton("⚙")
        self.settings_btn.setFixedSize(30, 30)
        self.settings_btn.setStyleSheet("font-size: 14px; padding: 0px;")
        self.settings_btn.setToolTip("Cài đặt & Thông tin")
        self.settings_btn.clicked.connect(self._on_show_settings)
        header_bar.addWidget(self.settings_btn)

        main_layout.addLayout(header_bar)

        # Divider
        divider = QFrame()
        divider.setFixedHeight(1)
        divider.setStyleSheet("background-color: #272D36;")
        main_layout.addWidget(divider)

        # -------------------------------------------------------------
        # WORKSPACE: 2-COLUMN SPLIT (Left Controls 400px, Right Table)
        # -------------------------------------------------------------
        workspace_layout = QHBoxLayout()
        workspace_layout.setSpacing(12)

        # LEFT COLUMN (Inspector & Settings)
        left_column = QWidget()
        left_column.setFixedWidth(400)
        left_layout = QVBoxLayout(left_column)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)

        # 2. FILE SRT
        self.srt_panel = QFrame()
        self.srt_panel.setProperty("panel", "true")
        srt_layout = QVBoxLayout(self.srt_panel)
        srt_layout.setContentsMargins(12, 10, 12, 10)
        srt_layout.setSpacing(4)

        srt_title = QLabel("FILE SRT")
        srt_title.setStyleSheet("font-weight: 700; font-size: 11px; color: #08A8E8; letter-spacing: 0.5px;")
        srt_layout.addWidget(srt_title)

        srt_controls = QHBoxLayout()
        srt_controls.setSpacing(8)

        self.srt_info_box = QVBoxLayout()
        self.srt_info_box.setSpacing(1)
        self.file_name_lbl = QLabel("Chưa chọn file SRT... (kéo thả hoặc nhấn Chọn)")
        self.file_name_lbl.setStyleSheet("font-size: 12px; color: #8993A3;")
        self.file_sub_lbl = QLabel("")
        self.file_sub_lbl.setStyleSheet("font-size: 11px; color: #64748B;")
        self.file_sub_lbl.setVisible(False)
        self.srt_info_box.addWidget(self.file_name_lbl)
        self.srt_info_box.addWidget(self.file_sub_lbl)

        self.choose_file_btn = QPushButton("Chọn file")
        self.choose_file_btn.setFixedHeight(28)
        self.choose_file_btn.setFixedWidth(80)
        self.choose_file_btn.clicked.connect(self._on_choose_srt)

        srt_controls.addLayout(self.srt_info_box, stretch=1)
        srt_controls.addWidget(self.choose_file_btn)
        srt_layout.addLayout(srt_controls)

        left_layout.addWidget(self.srt_panel)

        # 3. VOICE SELECTOR
        self.voice_widget = VoiceSelectorWidget(self.tts_manager)
        self.voice_widget.voice_changed.connect(self._on_voice_changed)
        left_layout.addWidget(self.voice_widget)

        # 4. SỐ LUỒNG TTS + TỐC ĐỘ (Gộp 1 panel gọn)
        params_panel = QFrame()
        params_panel.setProperty("panel", "true")
        params_panel_layout = QVBoxLayout(params_panel)
        params_panel_layout.setContentsMargins(12, 10, 12, 10)
        params_panel_layout.setSpacing(4)

        params_row = QHBoxLayout()
        params_row.setSpacing(10)

        # ⚡ Số luồng TTS
        threads_box = QVBoxLayout()
        threads_box.setSpacing(4)
        threads_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        threads_title = QLabel("⚡ SỐ LUỒNG TTS")
        threads_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        threads_title.setStyleSheet("font-weight: 700; font-size: 11px; color: #08A8E8; letter-spacing: 0.5px;")
        threads_box.addWidget(threads_title)

        spin_row = QHBoxLayout()
        spin_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.threads_spin = QSpinBox()
        self.threads_spin.setRange(1, 30)
        self.threads_spin.setValue(10)
        self.threads_spin.setFixedSize(95, 28)
        self.threads_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        spin_row.addWidget(self.threads_spin)
        threads_box.addLayout(spin_row)

        threads_hint = QLabel("💡 Đề xuất: 4–6 luồng")
        threads_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        threads_hint.setStyleSheet("font-size: 10px; color: #8993A3;")
        threads_box.addWidget(threads_hint)

        params_row.addLayout(threads_box, stretch=1)

        # 🔊 Tốc độ
        speed_box = QVBoxLayout()
        speed_box.setSpacing(4)
        speed_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        speed_title = QLabel("🔊 TỐC ĐỘ")
        speed_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        speed_title.setStyleSheet("font-weight: 700; font-size: 11px; color: #08A8E8; letter-spacing: 0.5px;")
        speed_box.addWidget(speed_title)

        combo_row = QHBoxLayout()
        combo_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.speed_combo = QComboBox()
        self.speed_combo.addItems(SPEED_OPTIONS)
        self.speed_combo.setCurrentText("1.00x")
        self.speed_combo.setFixedSize(100, 28)
        combo_row.addWidget(self.speed_combo)
        speed_box.addLayout(combo_row)

        speed_hint = QLabel("Giữ nguyên cao độ")
        speed_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        speed_hint.setStyleSheet("font-size: 10px; color: #8993A3;")
        speed_box.addWidget(speed_hint)

        params_row.addLayout(speed_box, stretch=1)
        params_panel_layout.addLayout(params_row)
        left_layout.addWidget(params_panel)

        # 5. ĐIỂM NHẤN CHÍNH: NÚT BẮT ĐẦU (PRIMARY CTA)
        action_layout = QHBoxLayout()
        action_layout.setSpacing(8)

        self.start_btn = QPushButton("▶  BẮT ĐẦU TẠO TTS")
        self.start_btn.setObjectName("startBtn")
        self.start_btn.setFixedHeight(48)
        self.start_btn.clicked.connect(self._on_start_pipeline)

        self.cancel_btn = QPushButton("✕ Dừng")
        self.cancel_btn.setObjectName("cancelBtn")
        self.cancel_btn.setFixedHeight(48)
        self.cancel_btn.setFixedWidth(80)
        self.cancel_btn.setVisible(False)
        self.cancel_btn.clicked.connect(self._on_cancel_pipeline)

        action_layout.addWidget(self.start_btn, stretch=1)
        action_layout.addWidget(self.cancel_btn)
        left_layout.addLayout(action_layout)

        # 6. TIẾN TRÌNH & THỐNG KÊ
        self.progress_panel = QFrame()
        self.progress_panel.setProperty("panel", "true")
        prog_layout = QVBoxLayout(self.progress_panel)
        prog_layout.setContentsMargins(12, 10, 12, 10)
        prog_layout.setSpacing(6)

        prog_top_row = QHBoxLayout()
        prog_title = QLabel("TIẾN TRÌNH")
        prog_title.setStyleSheet("font-weight: 700; font-size: 11px; color: #8993A3; letter-spacing: 0.5px;")
        self.prog_pct_lbl = QLabel("0%")
        self.prog_pct_lbl.setStyleSheet("font-weight: 700; font-size: 12px; color: #08A8E8; font-family: monospace;")
        prog_top_row.addWidget(prog_title)
        prog_top_row.addStretch(1)
        prog_top_row.addWidget(self.prog_pct_lbl)
        prog_layout.addLayout(prog_top_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(8)
        prog_layout.addWidget(self.progress_bar)

        prog_bottom_row = QHBoxLayout()
        self.counter_lbl = QLabel("0 / 0 câu")
        self.counter_lbl.setStyleSheet("font-size: 11px; font-weight: 600; color: #E8EDF3;")
        self.chips_lbl = QLabel("✓ 0    ⟳ 0    ✕ 0    ○ 0")
        self.chips_lbl.setStyleSheet("font-size: 11px; color: #8993A3;")
        prog_bottom_row.addWidget(self.counter_lbl)
        prog_bottom_row.addStretch(1)
        prog_bottom_row.addWidget(self.chips_lbl)
        prog_layout.addLayout(prog_bottom_row)

        left_layout.addWidget(self.progress_panel)

        # 7. OUTPUT BANNER
        self.output_banner = QFrame()
        self.output_banner.setStyleSheet("""
            QFrame {
                background-color: rgba(24, 199, 122, 0.1);
                border: 1px solid rgba(24, 199, 122, 0.4);
                border-radius: 6px;
                padding: 6px 10px;
            }
        """)
        self.output_banner.setVisible(False)
        out_layout = QHBoxLayout(self.output_banner)
        out_layout.setContentsMargins(8, 6, 8, 6)

        self.out_msg_lbl = QLabel("✓ Xuất master audio thành công")
        self.out_msg_lbl.setStyleSheet("font-size: 11px; color: #18C77A; font-weight: 600;")
        self.open_dir_btn = QPushButton("📂 Mở")
        self.open_dir_btn.setFixedHeight(26)
        self.open_dir_btn.clicked.connect(self._on_open_download_dir)

        out_layout.addWidget(self.out_msg_lbl, stretch=1)
        out_layout.addWidget(self.open_dir_btn)
        left_layout.addWidget(self.output_banner)

        left_layout.addStretch(1)
        workspace_layout.addWidget(left_column)

        # RIGHT COLUMN: BẢNG PHỤ ĐỀ SRT (Main Workspace - Full Height)
        right_panel = QFrame()
        right_panel.setProperty("panel", "true")
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(12, 10, 12, 10)
        right_layout.setSpacing(8)

        table_bar = QHBoxLayout()
        self.table_title_lbl = QLabel("PHỤ ĐỀ")
        self.table_title_lbl.setStyleSheet("font-weight: 700; font-size: 12px; color: #E8EDF3; letter-spacing: 0.5px;")

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 Tìm kiếm phụ đề...")
        self.search_input.setFixedWidth(200)
        self.search_input.setFixedHeight(26)
        self.search_input.setStyleSheet("""
            QLineEdit {
                background-color: #1E232A;
                border: 1px solid #2D3540;
                border-radius: 4px;
                padding: 2px 8px;
                font-size: 11px;
                color: #E8EDF3;
            }
            QLineEdit:focus {
                border: 1px solid #08A8E8;
            }
        """)
        self.search_input.textChanged.connect(self._on_search_text_changed)

        self.table_count_lbl = QLabel("0 dòng")
        self.table_count_lbl.setStyleSheet("font-size: 12px; color: #8993A3; font-weight: 600; font-family: monospace;")
        table_bar.addWidget(self.table_title_lbl)
        table_bar.addStretch(1)
        table_bar.addWidget(self.search_input)
        table_bar.addWidget(self.table_count_lbl)
        right_layout.addLayout(table_bar)

        self.table_model = SRTTableModel()
        self.table_view = SRTTableView(self)
        self.table_view.setModel(self.table_model)
        self.table_view.init_column_widths()
        right_layout.addWidget(self.table_view, stretch=1)

        workspace_layout.addWidget(right_panel, stretch=1)
        main_layout.addLayout(workspace_layout, stretch=1)

        self.statusBar().showMessage("Sẵn sàng. Hãy chọn file SRT.")


    def _apply_auto_theme(self) -> None:
        dark = is_dark_mode_active()
        self.setStyleSheet(get_theme_stylesheet(dark))

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        urls = event.mimeData().urls()
        if urls:
            path = Path(urls[0].toLocalFile())
            if path.suffix.lower() == ".srt":
                self._load_srt_file(path)
            else:
                QMessageBox.warning(self, "Lỗi định dạng", "Chỉ hỗ trợ file phụ đề .srt!")

    def _on_search_text_changed(self, text: str) -> None:
        """Starts/restarts 250ms single-shot timer for debounced table filtering."""
        self.search_timer.start()

    def _on_search_timer_timeout(self) -> None:
        """Executes table filter after 250ms of typing silence without lagging UI."""
        query = self.search_input.text()
        self.table_model.set_filter(query)
        matching_count = self.table_model.rowCount()
        total_count = len(self.srt_items)
        if query.strip():
            self.table_count_lbl.setText(f"{matching_count}/{total_count} dòng")
        else:
            self.table_count_lbl.setText(f"{total_count} dòng")

    def _on_choose_srt(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Chọn file phụ đề SRT", "", "Subtitle Files (*.srt)"
        )
        if file_path:
            self._load_srt_file(Path(file_path))

    def _load_srt_file(self, file_path: Path) -> None:
        try:
            items = parse_srt(file_path)
            if not items:
                QMessageBox.warning(self, "File rỗng", "File SRT không có nội dung hợp lệ.")
                return

            self.current_srt_path = file_path
            self.srt_items = items

            sel_voice = self.voice_widget.get_selected_voice_type()
            for it in self.srt_items:
                it.voice = sel_voice

            self.table_model.set_items(self.srt_items)
            self.table_view.init_column_widths()

            max_end = max((it.end_ms for it in items), default=0)
            dur_str = format_total_duration(max_end)

            self.file_name_lbl.setText(f"✓  {file_path.name}")
            self.file_name_lbl.setStyleSheet("font-weight: 700; font-size: 13px; color: #10B981;")
            self.file_sub_lbl.setText(f"{len(items)} dòng • {dur_str}")
            self.file_sub_lbl.setVisible(True)
            self.choose_file_btn.setText("Thay đổi")

            self.table_count_lbl.setText(f"{len(items)} dòng")
            self.counter_lbl.setText(f"0 / {len(items)} câu")
            self.chips_lbl.setText(f"✓ 0 hoàn thành    ⟳ 0 đang tạo    ✕ 0 lỗi    ○ {len(items)} chờ")
            self.progress_bar.setValue(0)
            self.prog_pct_lbl.setText("0%")
            self.output_banner.setVisible(False)

            self.statusBar().showMessage(f"Đã nạp file: {file_path.name} ({len(items)} dòng • {dur_str})")
        except Exception as e:
            QMessageBox.critical(self, "Lỗi nạp file", str(e))

    def _on_voice_changed(self, voice_type: str) -> None:
        for it in self.srt_items:
            it.voice = voice_type
        if self.srt_items:
            self.table_model.set_items(self.srt_items)

    def _parse_selected_speed(self) -> float:
        txt = self.speed_combo.currentText().replace("x", "").strip()
        try:
            return float(txt)
        except ValueError:
            return 1.0

    def _on_start_pipeline(self) -> None:
        if not self.srt_items or not self.current_srt_path:
            QMessageBox.warning(self, "Chưa chọn file", "Vui lòng chọn file SRT trước khi bắt đầu!")
            return

        global_voice = self.voice_widget.get_selected_voice_type()
        num_workers = self.threads_spin.value()
        speed = self._parse_selected_speed()

        self.start_btn.setEnabled(False)
        self.start_btn.setText("⏳ ĐANG TẠO TTS...")
        self.choose_file_btn.setEnabled(False)
        self.cancel_btn.setVisible(True)
        self.output_banner.setVisible(False)

        self.ui_queue = queue.Queue()
        self.tts_thread = QThread()
        self.pipeline_worker = TTSPipelineWorker(
            items=self.srt_items,
            global_voice=global_voice,
            num_workers=num_workers,
            speed=speed,
            srt_file_path=self.current_srt_path,
            ui_queue=self.ui_queue,
        )
        self.pipeline_worker.moveToThread(self.tts_thread)

        self.pipeline_worker.status_step.connect(lambda _, msg: self.statusBar().showMessage(msg))
        self.pipeline_worker.pipeline_finished.connect(self._on_pipeline_finished)

        self.ui_timer.start()
        self.tts_thread.started.connect(self.pipeline_worker.run)
        self.tts_thread.start()

    def _on_ui_timer_tick(self) -> None:
        """
        Batched UI updates every 300ms:
        1. Drains up to MAX_UI_EVENTS_PER_TICK (200) events from thread-safe ui_queue.
        2. Applies batch updates to SRTTableModel (single dataChanged for modified rows).
        3. Updates progress bar and counters at ~3.3 Hz without GUI stutters.
        """
        batch = {}
        processed_count = 0
        MAX_UI_EVENTS_PER_TICK = 200
        while processed_count < MAX_UI_EVENTS_PER_TICK:
            try:
                evt = self.ui_queue.get_nowait()
                batch[evt["id"]] = evt
                processed_count += 1
            except queue.Empty:
                break

        if batch:
            self.table_model.apply_batch_updates(batch)

        total = len(self.srt_items)
        if total > 0:
            completed = sum(1 for it in self.srt_items if it.status == "Hoàn thành")
            generating = sum(1 for it in self.srt_items if it.status in ("Đang tạo", "Đổi tốc độ"))
            failed = sum(1 for it in self.srt_items if "Lỗi" in it.status or "Thất bại" in it.status)
            pending = total - (completed + generating + failed)

            pct = int((completed / total) * 100)
            self.progress_bar.setValue(pct)
            self.prog_pct_lbl.setText(f"{pct}%")
            self.counter_lbl.setText(f"{completed} / {total} câu")
            self.chips_lbl.setText(f"✓ {completed} hoàn thành    ⚡ {generating} đang tạo    ✕ {failed} lỗi    ○ {pending} chờ")

    def _on_cancel_pipeline(self) -> None:
        if self.pipeline_worker:
            self.statusBar().showMessage("Đang yêu cầu dừng...")
            self.pipeline_worker.cancel()

    def _on_pipeline_finished(self, success: bool, message: str, final_path: str) -> None:
        self.ui_timer.stop()
        self._on_ui_timer_tick()  # Final flush of all remaining queue events

        self.start_btn.setEnabled(True)
        self.start_btn.setText("▶  BẮT ĐẦU TẠO TTS")
        self.choose_file_btn.setEnabled(True)
        self.cancel_btn.setVisible(False)

        if self.tts_thread:
            self.tts_thread.quit()
            self.tts_thread.wait()

        if success and final_path:
            self.last_output_path = Path(final_path)
            self.output_banner.setVisible(True)
            self.out_msg_lbl.setText(f"✓ Tạo TTS hoàn tất: {self.last_output_path.name} (Đã lưu tại Downloads/TTS/)")
            self.statusBar().showMessage(f"Hoàn tất: {self.last_output_path.name}")
        else:
            self.statusBar().showMessage(f"Dừng: {message}")
            if not self.pipeline_worker or not self.pipeline_worker._is_cancelled:
                QMessageBox.warning(self, "Thông báo", message)

    def _on_open_download_dir(self) -> None:
        if self.last_output_path and self.last_output_path.parent.exists():
            d_dir = self.last_output_path.parent
        else:
            d_dir = get_default_download_dir()

        d_dir.mkdir(parents=True, exist_ok=True)
        try:
            if sys.platform == "win32":
                import os
                os.startfile(str(d_dir))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(d_dir)])
            else:
                subprocess.Popen(["xdg-open", str(d_dir)])
        except Exception as e:
            QMessageBox.information(self, "Thư mục", str(d_dir))

    def _on_show_settings(self) -> None:
        info_text = (
            "<b>KAGEVIETSUB TTS v2.5</b><br><br>"
            "<b>Thư mục xuất file:</b><br>"
            "<code>Downloads/TTS/</code><br><br>"
            "<b>Định dạng âm thanh:</b><br>"
            "WAV 44.1kHz • 16-bit PCM • Giữ nguyên cao độ giọng<br><br>"
            "<b>Kiến trúc Pipeline:</b><br>"
            "• TTS Worker Pool: 1–30 workers (người dùng chọn)<br>"
            "• Streaming Speed Worker: 2–4 workers nội bộ (bỏ qua FFmpeg nếu 1.00x)<br>"
            "• Ghép timeline: Xử lý theo block, tự động mix overlap & dọn sạch temp."
        )
        QMessageBox.information(self, "Cài đặt & Thông tin", info_text)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("KAGEVIETSUB TTS")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
