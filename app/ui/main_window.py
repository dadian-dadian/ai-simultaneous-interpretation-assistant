from __future__ import annotations

import sys
import time
import uuid
from datetime import datetime

from PySide6.QtCore import QPoint, QRect, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QFontDatabase, QFontMetrics, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QSlider,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from app.core.chinese_caption import ChineseCaptionComposer
from app.core.config import AppConfig
from app.core.demo_stream import DemoSubtitleScript, build_default_demo_script
from app.core.recognition_profile import (
    RecognitionProfile,
    get_recognition_profile,
    recognition_mode_from_index,
)
from app.core.subtitle import (
    SubtitleEvent,
    SubtitleEventType,
    SubtitleSegment,
    SubtitleSegmentStatus,
    SubtitleState,
)
from app.core.transcript_session import (
    TranscriptSession,
    TranscriptSessionStatus,
)
from app.storage import (
    TranscriptPersistence,
    TranscriptStore,
    default_transcript_storage_dir,
)
from app.translate import (
    IncrementalTranslationPlanner,
    SentenceTranslationManager,
    TranslationConfigurationError,
    TranslationUpdate,
    create_partial_translation_client,
)
from app.ui.realtime_worker import RealtimeSubtitleWorker
from app.ui.smooth_caption import SmoothCaptionLabel
from app.ui.subtitle_overlay import SubtitleOverlayWindow
from app.ui.theme import apply_app_theme


class _WindowTitleBar(QFrame):
    def __init__(self, window: QMainWindow) -> None:
        super().__init__(window)
        self._window = window
        self._drag_position: QPoint | None = None
        self.setObjectName("TitleBar")
        self.setFixedHeight(40)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 6, 0)
        layout.setSpacing(8)

        mark = QLabel("译")
        mark.setObjectName("TitleBarMark")
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setFixedSize(22, 22)

        title = QLabel("AI 同声传译助手")
        title.setObjectName("TitleBarTitle")

        minimize = QPushButton("—")
        maximize = QPushButton("□")
        close = QPushButton("×")
        for button in (minimize, maximize, close):
            button.setObjectName("WindowButton")
            button.setFixedSize(36, 28)
        close.setObjectName("WindowCloseButton")

        minimize.clicked.connect(window.showMinimized)
        maximize.clicked.connect(self._toggle_maximized)
        close.clicked.connect(window.close)

        layout.addWidget(mark)
        layout.addWidget(title)
        layout.addStretch(1)
        layout.addWidget(minimize)
        layout.addWidget(maximize)
        layout.addWidget(close)

    def _toggle_maximized(self) -> None:
        if self._window.isMaximized():
            self._window.showNormal()
        else:
            self._window.showMaximized()

    def mousePressEvent(self, event) -> None:  # noqa: ANN001
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self._window.windowHandle()
            if handle is not None and handle.startSystemMove():
                event.accept()
                return
            self._drag_position = (
                event.globalPosition().toPoint() - self._window.frameGeometry().topLeft()
            )
            event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: ANN001
        if event.buttons() & Qt.MouseButton.LeftButton and self._drag_position is not None:
            self._window.move(event.globalPosition().toPoint() - self._drag_position)
            event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: ANN001
        self._drag_position = None
        event.accept()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: ANN001
        if event.button() == Qt.MouseButton.LeftButton:
            self._toggle_maximized()
            event.accept()


class _HistoryItemWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("HistoryEntry")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 10)
        layout.setSpacing(3)

        self.source_label = QLabel()
        self.source_label.setObjectName("HistorySource")
        self.source_label.setWordWrap(True)

        self.translation_label = QLabel()
        self.translation_label.setObjectName("HistoryTranslation")
        self.translation_label.setWordWrap(True)

        layout.addWidget(self.source_label)
        layout.addWidget(self.translation_label)

    def set_content(self, source_text: str, translation_text: str) -> None:
        self.source_label.setText(source_text)
        self.translation_label.setText(translation_text)
        self.translation_label.setVisible(bool(translation_text))

    def recommended_height(self, width: int) -> int:
        content_width = max(220, width - 24)
        source_height = _wrapped_text_height(
            QFontMetrics(self.source_label.font()),
            self.source_label.text(),
            content_width,
        )
        translation_height = 0
        if self.translation_label.isVisible():
            translation_height = _wrapped_text_height(
                QFontMetrics(self.translation_label.font()),
                self.translation_label.text(),
                content_width,
            )
        spacing = 3 if translation_height else 0
        return max(46, 19 + source_height + spacing + translation_height)


class _HistoryEmptyWidget(QWidget):
    def __init__(
        self,
        title_text: str = "还没有转译内容",
        subtitle_text: str = "开始转译后，中英文内容会按时间顺序保存在这里",
    ) -> None:
        super().__init__()
        self.setObjectName("HistoryEmpty")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(6)
        layout.addStretch(1)

        mark = QLabel("译")
        mark.setObjectName("HistoryEmptyMark")
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setFixedSize(40, 40)

        mark_row = QHBoxLayout()
        mark_row.addStretch(1)
        mark_row.addWidget(mark)
        mark_row.addStretch(1)

        title = QLabel(title_text)
        title.setObjectName("HistoryEmptyTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        subtitle = QLabel(subtitle_text)
        subtitle.setObjectName("HistoryEmptySubtitle")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setWordWrap(True)

        layout.addLayout(mark_row)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addStretch(1)


class MainWindow(QMainWindow):
    translation_ready = Signal(object)
    realtime_subtitle_event = Signal(int, object)
    realtime_status_changed = Signal(int, str)
    realtime_dropped_chunks_changed = Signal(int, int)
    realtime_error_occurred = Signal(int, str)
    realtime_warning_occurred = Signal(int, str)
    realtime_thread_finished = Signal(int)

    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self.config = config
        self.transcript_store = TranscriptStore(
            default_transcript_storage_dir(config.transcript_storage_dir)
        )
        self.transcript_persistence = TranscriptPersistence(self.transcript_store)
        self._current_transcript_session: TranscriptSession | None = None
        self._saved_transcript_sessions: dict[str, TranscriptSession] = {}
        self._transcript_history_loaded = False
        self._transcript_recovery_checked = False
        self._history_view_mode = "current"
        self._realtime_stop_intent = ""
        self.subtitle_state = SubtitleState()
        self.chinese_caption_composer = ChineseCaptionComposer(max_visible_lines=64)
        self.translation_planner = IncrementalTranslationPlanner()
        self._translation_session_id = uuid.uuid4().hex
        self.demo_script: DemoSubtitleScript = build_default_demo_script()
        self.demo_step_index = 0
        self.demo_timer = QTimer(self)
        self.demo_timer.setSingleShot(True)
        self.demo_timer.timeout.connect(self._advance_demo_stream)
        self.realtime_render_timer = QTimer(self)
        self.realtime_render_timer.setSingleShot(True)
        self.realtime_render_timer.setInterval(80)
        self.realtime_render_timer.timeout.connect(self._flush_realtime_render)
        self._pending_realtime_render: tuple[
            SubtitleEvent,
            SubtitleSegment,
            str,
        ] | None = None
        self._realtime_generation = 0
        self._accept_realtime_generation: int | None = None
        self.realtime_thread: QThread | None = None
        self.realtime_worker: RealtimeSubtitleWorker | None = None
        self.translation_manager: SentenceTranslationManager | None = None
        self._accepted_partial_translation_words: dict[str, int] = {}
        self._translation_startup_warning = ""
        self.translation_ready.connect(self._handle_translation_update)
        self.realtime_subtitle_event.connect(
            self._handle_realtime_subtitle_event_for_generation,
            Qt.ConnectionType.QueuedConnection,
        )
        self.realtime_status_changed.connect(
            self._set_status_for_generation,
            Qt.ConnectionType.QueuedConnection,
        )
        self.realtime_dropped_chunks_changed.connect(
            self._handle_dropped_chunks_changed_for_generation,
            Qt.ConnectionType.QueuedConnection,
        )
        self.realtime_error_occurred.connect(
            self._handle_realtime_error_for_generation,
            Qt.ConnectionType.QueuedConnection,
        )
        self.realtime_warning_occurred.connect(
            self._handle_realtime_warning_for_generation,
            Qt.ConnectionType.QueuedConnection,
        )
        self.realtime_thread_finished.connect(
            self._handle_realtime_finished_for_generation,
            Qt.ConnectionType.QueuedConnection,
        )

        self.overlay = SubtitleOverlayWindow()
        self.overlay.visibility_changed.connect(self._sync_overlay_toggle_state)
        self.overlay.size_mode_changed.connect(self._sync_overlay_size_mode)
        self.status_label: QLabel | None = None
        self.start_button: QPushButton | None = None
        self.pause_button: QPushButton | None = None
        self.stop_button: QPushButton | None = None
        self.overlay_toggle: QPushButton | None = None
        self.font_size_slider: QSlider | None = None
        self.opacity_slider: QSlider | None = None
        self.display_mode_combo: QComboBox | None = None
        self.overlay_size_combo: QComboBox | None = None
        self.source_caption_label: SmoothCaptionLabel | None = None
        self.translation_stable_caption_label: SmoothCaptionLabel | None = None
        self.translation_caption_label: SmoothCaptionLabel | None = None
        self.correction_hint_label: QLabel | None = None
        self.history_list: QListWidget | None = None
        self.history_count_label: QLabel | None = None
        self.history_current_button: QPushButton | None = None
        self.history_saved_button: QPushButton | None = None
        self.history_session_combo: QComboBox | None = None
        self._history_items: dict[str, QListWidgetItem] = {}
        self.recognition_mode_group: QButtonGroup | None = None
        self.recognition_mode_buttons: list[QPushButton] = []
        self.latency_hint_label: QLabel | None = None
        self.dropped_chunks_label: QLabel | None = None
        self._active_recognition_profile: RecognitionProfile | None = None
        self._dropped_chunks_warned = False

        self.setWindowTitle("AI 同声传译助手")
        self.setWindowFlags(
            Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
        )
        self.setMinimumSize(960, 620)
        self.resize(1120, 700)

        root = QWidget()
        root.setObjectName("AppRoot")
        self.setCentralWidget(root)
        self._create_hidden_caption_state(root)

        shell = QVBoxLayout(root)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        shell.addWidget(_WindowTitleBar(self))

        surface = QWidget()
        surface.setObjectName("MainSurface")
        surface_layout = QVBoxLayout(surface)
        surface_layout.setContentsMargins(22, 16, 22, 22)
        surface_layout.setSpacing(14)
        surface_layout.addWidget(self._build_header())
        surface_layout.addLayout(self._build_content(), stretch=1)
        shell.addWidget(surface, stretch=1)
        self._sync_overlay_from_controls()
        self._start_translation_manager()

    def _create_hidden_caption_state(self, parent: QWidget) -> None:
        self.source_caption_label = SmoothCaptionLabel(parent=parent)
        self.source_caption_label.hide()
        self.translation_stable_caption_label = SmoothCaptionLabel(parent=parent)
        self.translation_stable_caption_label.hide()
        self.translation_caption_label = SmoothCaptionLabel(parent=parent)
        self.translation_caption_label.hide()

    def _build_header(self) -> QWidget:
        header = QFrame()
        header.setObjectName("Header")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        title_block = QVBoxLayout()
        title_block.setSpacing(4)

        title = QLabel("实时转译")
        title.setObjectName("WindowTitle")
        subtitle = QLabel("系统声音  ·  英语 → 简体中文")
        subtitle.setObjectName("WindowSubtitle")

        title_block.addWidget(title)
        title_block.addWidget(subtitle)

        status = QLabel("待机")
        status.setObjectName("StatusBadge")
        status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status.setFixedSize(68, 28)
        self.status_label = status

        layout.addLayout(title_block, stretch=1)
        layout.addWidget(status)
        return header

    def _build_content(self) -> QHBoxLayout:
        content = QHBoxLayout()
        content.setSpacing(14)

        sidebar = self._build_control_panel()
        sidebar.setFixedWidth(336)
        content.addWidget(sidebar)
        content.addWidget(self._build_history_panel(), stretch=1)
        return content

    def _build_control_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("Panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 17, 18, 16)
        layout.setSpacing(15)

        layout.addLayout(self._build_transport_controls())
        layout.addWidget(self._build_audio_section())
        layout.addWidget(self._build_mode_section())
        layout.addWidget(self._divider())
        layout.addWidget(self._build_subtitle_section())
        layout.addStretch(1)

        hint = QLabel("准备就绪")
        hint.setObjectName("StatusNote")
        hint.setWordWrap(True)
        self.correction_hint_label = hint
        layout.addWidget(hint)

        dropped_chunks = QLabel("丢帧：0")
        dropped_chunks.hide()
        self.dropped_chunks_label = dropped_chunks

        return panel

    def _build_transport_controls(self) -> QVBoxLayout:
        controls = QVBoxLayout()
        controls.setSpacing(10)

        heading = QHBoxLayout()
        heading.setSpacing(8)
        title = QLabel("转译控制")
        title.setObjectName("SectionTitle")
        heading.addWidget(title)
        heading.addStretch(1)

        latency = QLabel(get_recognition_profile("balanced").latency_hint)
        latency.setObjectName("MetricPill")
        latency.setAlignment(Qt.AlignmentFlag.AlignCenter)
        latency.setFixedSize(100, 26)
        self.latency_hint_label = latency
        heading.addWidget(latency)
        controls.addLayout(heading)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)

        style = self.style()
        start = QPushButton("开始转译")
        start.setObjectName("PrimaryButton")
        start.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        self.start_button = start

        pause = QPushButton("暂停")
        pause.setObjectName("GhostButton")
        pause.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_MediaPause))
        self.pause_button = pause

        stop = QPushButton("停止")
        stop.setObjectName("GhostButton")
        stop.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_MediaStop))
        self.stop_button = stop

        for button in (start, pause, stop):
            button.setMinimumHeight(40)
            button_row.addWidget(button)

        start.clicked.connect(self._start_subtitle_stream)
        pause.clicked.connect(self._pause_subtitle_stream)
        stop.clicked.connect(self._stop_subtitle_stream)

        self.overlay_toggle = QPushButton("显示字幕窗")
        self.overlay_toggle.setObjectName("GhostButton")
        self.overlay_toggle.setCheckable(True)
        self.overlay_toggle.setMinimumHeight(36)
        self.overlay_toggle.clicked.connect(self._toggle_overlay)
        controls.addLayout(button_row)
        controls.addWidget(self.overlay_toggle)

        return controls

    def _build_history_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("HistoryPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)

        heading = QHBoxLayout()
        heading.setSpacing(8)

        title = QLabel("转译记录")
        title.setObjectName("HistoryTitle")
        count = QLabel("0 条")
        count.setObjectName("HistoryCount")
        count.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.history_count_label = count

        heading.addWidget(title)
        heading.addStretch(1)
        heading.addWidget(count)

        subtitle = QLabel("中文优先展示，英文作为上下文参考")
        subtitle.setObjectName("HistorySubtitle")

        mode_row = QHBoxLayout()
        mode_row.setSpacing(8)
        mode_group = QButtonGroup(panel)
        mode_group.setExclusive(True)

        current_button = QPushButton("当前")
        current_button.setObjectName("SegmentButton")
        current_button.setCheckable(True)
        current_button.setChecked(True)
        current_button.setFixedHeight(32)
        current_button.clicked.connect(
            lambda _checked=False: self._set_history_view_mode("current")
        )
        self.history_current_button = current_button

        saved_button = QPushButton("历史")
        saved_button.setObjectName("SegmentButton")
        saved_button.setCheckable(True)
        saved_button.setFixedHeight(32)
        saved_button.clicked.connect(
            lambda _checked=False: self._set_history_view_mode("saved")
        )
        self.history_saved_button = saved_button

        mode_group.addButton(current_button)
        mode_group.addButton(saved_button)
        mode_row.addWidget(current_button)
        mode_row.addWidget(saved_button)
        mode_row.addStretch(1)

        session_combo = QComboBox()
        session_combo.setObjectName("Input")
        session_combo.setMinimumWidth(250)
        session_combo.setVisible(False)
        session_combo.currentIndexChanged.connect(
            self._handle_saved_session_selected
        )
        self.history_session_combo = session_combo

        layout.addLayout(heading)
        layout.addWidget(subtitle)
        layout.addLayout(mode_row)
        layout.addWidget(session_combo)
        layout.addWidget(self._build_history_list(), stretch=1)
        return panel

    def _divider(self) -> QFrame:
        divider = QFrame()
        divider.setObjectName("Divider")
        divider.setFixedHeight(1)
        return divider

    def _build_history_list(self) -> QListWidget:
        history = QListWidget()
        history.setObjectName("HistoryList")
        history.setWordWrap(True)
        history.setTextElideMode(Qt.TextElideMode.ElideNone)
        history.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        history.setResizeMode(QListView.ResizeMode.Adjust)
        history.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        history.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        history.setSpacing(0)
        self.history_list = history
        self._install_history_placeholder()

        return history

    def _build_audio_section(self) -> QWidget:
        section = self._section("音频源")
        layout = section.layout()

        device = QLabel("默认系统输出")
        device.setObjectName("InputValue")
        layout.addWidget(device)

        return section

    def _build_mode_section(self) -> QWidget:
        section = self._section("转译模式")
        layout = section.layout()

        button_row = QHBoxLayout()
        button_row.setSpacing(8)

        group = QButtonGroup(section)
        group.setExclusive(True)
        self.recognition_mode_group = group
        self.recognition_mode_buttons = []
        for index, name in enumerate(("低延迟", "均衡", "高准确")):
            button = QPushButton(name)
            button.setObjectName("SegmentButton")
            button.setCheckable(True)
            button.setMinimumHeight(36)
            button.setChecked(index == 1)
            group.addButton(button)
            button.clicked.connect(self._update_recognition_mode_hint)
            button_row.addWidget(button)
            self.recognition_mode_buttons.append(button)

        layout.addLayout(button_row)
        return section

    def _build_subtitle_section(self) -> QWidget:
        section = self._section("字幕样式")
        layout = section.layout()

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)

        font_label = QLabel("字号")
        font_label.setObjectName("FieldLabel")
        font_size = QSlider(Qt.Orientation.Horizontal)
        font_size.setObjectName("Slider")
        font_size.setRange(12, 22)
        font_size.setValue(14)
        font_size.valueChanged.connect(self._update_overlay_font_size)
        self.font_size_slider = font_size

        opacity_label = QLabel("透明度")
        opacity_label.setObjectName("FieldLabel")
        opacity = QSlider(Qt.Orientation.Horizontal)
        opacity.setObjectName("Slider")
        opacity.setRange(40, 100)
        opacity.setValue(92)
        opacity.valueChanged.connect(self._update_overlay_opacity)
        self.opacity_slider = opacity

        mode_label = QLabel("显示")
        mode_label.setObjectName("FieldLabel")
        mode = QComboBox()
        mode.setObjectName("Input")
        mode.addItems(["双语字幕", "仅中文字幕", "仅原文字幕"])
        mode.setCurrentIndex(
            {
                "bilingual": 0,
                "zh": 1,
                "source": 2,
            }.get(self.config.subtitle_mode.strip().lower(), 0)
        )
        mode.currentIndexChanged.connect(self._update_overlay_display_mode)
        self.display_mode_combo = mode

        size_label = QLabel("窗口")
        size_label.setObjectName("FieldLabel")
        size = QComboBox()
        size.setObjectName("Input")
        size.addItems(["紧凑", "标准", "宽屏", "自定义"])
        size.setCurrentIndex(0)
        size.currentIndexChanged.connect(self._update_overlay_size_preset)
        self.overlay_size_combo = size

        grid.addWidget(font_label, 0, 0)
        grid.addWidget(font_size, 0, 1)
        grid.addWidget(opacity_label, 1, 0)
        grid.addWidget(opacity, 1, 1)
        grid.addWidget(mode_label, 2, 0)
        grid.addWidget(mode, 2, 1)
        grid.addWidget(size_label, 3, 0)
        grid.addWidget(size, 3, 1)
        layout.addLayout(grid)

        return section

    def _section(self, title_text: str) -> QFrame:
        section = QFrame()
        section.setObjectName("Section")
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        title = QLabel(title_text)
        title.setObjectName("SectionTitle")
        layout.addWidget(title)
        return section

    def _sync_overlay_from_controls(self) -> None:
        if self.font_size_slider is not None:
            self.overlay.set_font_size(self.font_size_slider.value())
        if self.opacity_slider is not None:
            self.overlay.set_opacity_percent(self.opacity_slider.value())
        if self.display_mode_combo is not None:
            self._update_overlay_display_mode(self.display_mode_combo.currentIndex())
        if self.overlay_size_combo is not None:
            self._update_overlay_size_preset(self.overlay_size_combo.currentIndex())

    def _start_translation_manager(self) -> None:
        if self.translation_manager is not None:
            return
        try:
            client = create_partial_translation_client(self.config)
        except TranslationConfigurationError as exc:
            self._translation_startup_warning = str(exc)
            if self.correction_hint_label is not None:
                self.correction_hint_label.setText(self._translation_startup_warning)
            return
        if client is None:
            return

        self.translation_manager = SentenceTranslationManager(
            client=client,
            source_language=self.config.source_language,
            target_language=self.config.target_language,
            on_update=self.translation_ready.emit,
        )
        self.translation_manager.begin_session(self._translation_session_id)

    def _stop_translation_manager(self) -> None:
        if self.translation_manager is None:
            return
        self.translation_manager.stop()
        self.translation_manager = None

    def _show_overlay(self) -> None:
        if not self.overlay.isVisible():
            screen_geometry = self.screen().availableGeometry()
            target_x = screen_geometry.center().x() - self.overlay.width() // 2
            target_y = screen_geometry.bottom() - self.overlay.height() - 48
            self.overlay.move(target_x, target_y)
            self.overlay.show()
        if self.overlay_toggle is not None:
            self.overlay_toggle.setChecked(True)

    def _hide_overlay(self) -> None:
        self.overlay.hide()
        if self.overlay_toggle is not None:
            self.overlay_toggle.setChecked(False)

    def _toggle_overlay(self, checked: bool) -> None:
        if checked:
            self._show_overlay()
        else:
            self._hide_overlay()

    def _sync_overlay_toggle_state(self, visible: bool) -> None:
        if self.overlay_toggle is None:
            return
        self.overlay_toggle.blockSignals(True)
        self.overlay_toggle.setChecked(visible)
        self.overlay_toggle.blockSignals(False)

    def _update_overlay_font_size(self, value: int) -> None:
        self.overlay.set_font_size(value)

    def _update_overlay_opacity(self, value: int) -> None:
        self.overlay.set_opacity_percent(value)

    def _update_overlay_display_mode(self, index: int) -> None:
        mode = {
            0: "bilingual",
            1: "zh",
            2: "source",
        }.get(index, "bilingual")
        self.overlay.set_display_mode(mode)

    def _update_overlay_size_preset(self, index: int) -> None:
        preset = {
            0: "compact",
            1: "standard",
            2: "wide",
        }.get(index)
        if preset is not None:
            self.overlay.set_size_preset(preset)

    def _sync_overlay_size_mode(self, mode: str) -> None:
        if self.overlay_size_combo is None:
            return
        index = {
            "compact": 0,
            "standard": 1,
            "wide": 2,
            "custom": 3,
        }.get(mode, 3)
        self.overlay_size_combo.blockSignals(True)
        self.overlay_size_combo.setCurrentIndex(index)
        self.overlay_size_combo.blockSignals(False)

    def _start_subtitle_stream(self) -> None:
        if self._is_realtime_running():
            return

        if self.config.asr_provider.strip().lower() == "mock":
            self._start_demo_stream()
            return

        self.demo_timer.stop()
        profile = self._selected_recognition_profile()
        if self._is_current_transcript_paused():
            self._resume_transcript_session()
            self._set_history_view_mode("current")
        else:
            self._reset_realtime_state()
            self._begin_transcript_session(profile.mode)
        self._realtime_generation += 1
        generation = self._realtime_generation
        self._accept_realtime_generation = generation
        self._realtime_stop_intent = ""
        self._show_overlay()
        self._set_transport_running(True)
        self._set_status("准备中")

        self._active_recognition_profile = profile
        self._dropped_chunks_warned = False
        self._set_dropped_chunks_display(0)
        if self.correction_hint_label is not None:
            self.correction_hint_label.setText(
                f"{profile.label}模式已开启，正在聆听播放内容。"
            )

        thread = QThread(self)
        worker = RealtimeSubtitleWorker(
            self.config,
            vad_min_silence_ms=profile.min_silence_ms,
            preroll_seconds=profile.preroll_seconds,
            queue_size=profile.queue_size,
            dropped_chunks_warn_threshold=profile.dropped_chunks_warn_threshold,
            max_stream_duration_seconds=profile.max_stream_duration_seconds,
            segment_id_prefix=f"asr_{generation:04d}",
        )
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.subtitle_event.connect(
            lambda event, generation=generation: self.realtime_subtitle_event.emit(
                generation,
                event,
            )
        )
        worker.status_changed.connect(
            lambda status, generation=generation: self.realtime_status_changed.emit(
                generation,
                status,
            )
        )
        worker.dropped_chunks_changed.connect(
            lambda dropped, generation=generation: self.realtime_dropped_chunks_changed.emit(
                generation,
                dropped,
            )
        )
        worker.error_occurred.connect(
            lambda message, generation=generation: self.realtime_error_occurred.emit(
                generation,
                message,
            )
        )
        worker.warning_occurred.connect(
            lambda message, generation=generation: self.realtime_warning_occurred.emit(
                generation,
                message,
            )
        )
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(
            lambda generation=generation: self.realtime_thread_finished.emit(
                generation
            )
        )

        self.realtime_thread = thread
        self.realtime_worker = worker
        self._set_recognition_mode_controls_enabled(False)
        thread.start()

    def _pause_subtitle_stream(self) -> None:
        if self._is_realtime_running():
            self._realtime_stop_intent = "pause"
            self._stop_realtime_worker()
            self._pause_transcript_session()
            self._set_status("暂停")
            if self.correction_hint_label is not None:
                self.correction_hint_label.setText(
                    "转译已暂停，点击“开始转译”继续聆听。"
                )
            return
        self._pause_demo_stream()

    def _stop_subtitle_stream(self) -> None:
        if self.config.asr_provider.strip().lower() == "mock":
            self._stop_demo_stream()
            return
        if self._is_realtime_running():
            self._realtime_stop_intent = "stop"
            self._stop_realtime_worker()
        self._finalize_transcript_session(TranscriptSessionStatus.STOPPED)
        self._hide_overlay()
        self._set_status("待机")

    def _is_realtime_running(self) -> bool:
        return self.realtime_thread is not None and self.realtime_thread.isRunning()

    def _stop_realtime_worker(self) -> None:
        self._accept_realtime_generation = None
        if self.realtime_worker is not None:
            self.realtime_worker.stop()

    def _is_accepted_realtime_generation(self, generation: int) -> bool:
        return generation == self._accept_realtime_generation

    def _handle_realtime_subtitle_event_for_generation(
        self,
        generation: int,
        event: SubtitleEvent,
    ) -> None:
        if not self._is_accepted_realtime_generation(generation):
            return
        self._handle_realtime_subtitle_event(event)

    def _set_status_for_generation(self, generation: int, status: str) -> None:
        if not self._is_accepted_realtime_generation(generation):
            return
        self._set_status(status)

    def _handle_dropped_chunks_changed_for_generation(
        self,
        generation: int,
        dropped_chunks: int,
    ) -> None:
        if not self._is_accepted_realtime_generation(generation):
            return
        self._handle_dropped_chunks_changed(dropped_chunks)

    def _handle_realtime_error_for_generation(
        self,
        generation: int,
        message: str,
    ) -> None:
        if not self._is_accepted_realtime_generation(generation):
            return
        self._handle_realtime_error(message)

    def _handle_realtime_warning_for_generation(
        self,
        generation: int,
        message: str,
    ) -> None:
        if not self._is_accepted_realtime_generation(generation):
            return
        self._handle_realtime_warning(message)

    def _handle_realtime_finished_for_generation(self, generation: int) -> None:
        if generation != self._realtime_generation:
            return
        self._accept_realtime_generation = None
        self._handle_realtime_finished()

    def _handle_realtime_subtitle_event(self, event: SubtitleEvent) -> None:
        has_incoming_translation = (
            bool(event.zh_text.strip())
            and event.source_text.strip() != event.zh_text.strip()
        )
        event = self._with_preserved_translation(event)
        segment = self.subtitle_state.apply(event)
        if _is_realtime_asr_segment(segment):
            self.chinese_caption_composer.observe_segment(segment.segment_id)
        self._record_transcript_segment(
            segment,
            urgent=event.type != SubtitleEventType.PARTIAL,
        )
        if has_incoming_translation and _is_realtime_asr_segment(segment):
            if event.type == SubtitleEventType.FINAL:
                self.chinese_caption_composer.accept_final(
                    segment_id=segment.segment_id,
                    source_version=segment.version,
                    translated_text=event.zh_text,
                )
            elif event.type == SubtitleEventType.PARTIAL:
                self.chinese_caption_composer.accept_draft(
                    segment_id=segment.segment_id,
                    source_version=segment.version,
                    translated_text=event.zh_text,
                )
        display_text = self._compose_realtime_display_text(event, segment)
        self._maybe_submit_translation(event, segment)
        if event.type == SubtitleEventType.PARTIAL:
            self._pending_realtime_render = (event, segment, display_text)
            if not self.realtime_render_timer.isActive():
                self.realtime_render_timer.start()
            return

        self.realtime_render_timer.stop()
        self._pending_realtime_render = None
        self._render_subtitle_event(event, segment, display_text=display_text)

    def _flush_realtime_render(self) -> None:
        pending = self._pending_realtime_render
        self._pending_realtime_render = None
        if pending is None:
            return
        event, segment, display_text = pending
        self._render_subtitle_event(event, segment, display_text=display_text)

    def _with_preserved_translation(self, event: SubtitleEvent) -> SubtitleEvent:
        if event.type not in {SubtitleEventType.PARTIAL, SubtitleEventType.FINAL}:
            return event
        if event.source_text.strip() != event.zh_text.strip():
            return event

        previous = self.subtitle_state.get(event.segment_id)
        if previous is None:
            return event
        if not _has_distinct_translation(previous):
            return event
        if not _is_compatible_source_update(previous.source_text, event.source_text):
            return event

        if event.type == SubtitleEventType.FINAL:
            return SubtitleEvent.final(
                event.segment_id,
                event.source_text,
                previous.zh_text,
                translation_source_text=(
                    previous.translation_source_text or previous.source_text
                ),
            )
        return SubtitleEvent.partial(
            event.segment_id,
            event.source_text,
            previous.zh_text,
            translation_source_text=(
                previous.translation_source_text or previous.source_text
            ),
        )

    def _maybe_submit_translation(
        self,
        event: SubtitleEvent,
        segment: SubtitleSegment,
    ) -> None:
        if self.translation_manager is None:
            return
        if not _is_realtime_asr_segment(segment):
            return
        if event.type not in {SubtitleEventType.PARTIAL, SubtitleEventType.FINAL}:
            return
        if not segment.source_text.strip():
            return

        is_final = event.type == SubtitleEventType.FINAL
        if is_final:
            self._accepted_partial_translation_words.pop(segment.segment_id, None)
            plan = self.translation_planner.observe_final(
                segment_id=segment.segment_id,
                source_version=segment.version,
                source_text=segment.source_text,
            )
        else:
            plan = self.translation_planner.observe_partial(
                segment_id=segment.segment_id,
                source_version=segment.version,
                source_text=segment.source_text,
                observed_at=time.monotonic(),
            )
        if plan is None:
            return

        self.translation_manager.submit(
            session_id=self._translation_session_id,
            segment_id=plan.segment_id,
            source_version=plan.source_version,
            source_text=plan.source_text,
            is_final=plan.is_final,
            allow_source_prefix=not plan.is_final,
        )

    def _handle_translation_update(self, update: object) -> None:
        if not isinstance(update, TranslationUpdate):
            return
        if update.session_id not in {"default", self._translation_session_id}:
            return
        translated_text = update.translated_text.strip()
        if not translated_text:
            return

        current = self.subtitle_state.get(update.segment_id)
        if current is None:
            return

        if update.is_final:
            if current.version != update.source_version:
                return
            if current.source_text.strip() != update.source_text.strip():
                return
            event = SubtitleEvent.final(
                update.segment_id,
                current.source_text,
                translated_text,
                translation_source_text=update.source_text,
            )
            self.chinese_caption_composer.accept_final(
                segment_id=update.segment_id,
                source_version=update.source_version,
                translated_text=translated_text,
            )
        else:
            if current.status != SubtitleSegmentStatus.PARTIAL:
                return
            if update.allow_source_prefix:
                if not _is_source_prefix(update.source_text, current.source_text):
                    return
                translated_words = len(update.source_text.split())
                accepted_words = self._accepted_partial_translation_words.get(
                    update.segment_id,
                    0,
                )
                if translated_words < accepted_words:
                    return
                self._accepted_partial_translation_words[update.segment_id] = (
                    translated_words
                )
            elif current.source_text.strip() != update.source_text.strip():
                return
            event = SubtitleEvent.partial(
                update.segment_id,
                current.source_text,
                translated_text,
                translation_source_text=update.source_text,
            )
            self.chinese_caption_composer.accept_draft(
                segment_id=update.segment_id,
                source_version=update.source_version,
                translated_text=translated_text,
            )

        segment = self.subtitle_state.apply(event)
        self._record_transcript_segment(segment, urgent=update.is_final)
        display_text = self._compose_realtime_display_text(event, segment)
        self._render_translation_update(event, segment, display_text=display_text)

    def _render_translation_update(
        self,
        event: SubtitleEvent,
        segment: SubtitleSegment,
        *,
        display_text: str,
    ) -> None:
        latest = self._latest_realtime_segment()
        if latest is None or latest.segment_id == segment.segment_id:
            self._render_subtitle_event(event, segment, display_text=display_text)
            return

        self._render_history_segment(segment)
        latest_display_text = self._compose_realtime_display_text(event, latest)
        self._render_subtitle_event(
            event,
            latest,
            display_text=latest_display_text,
        )

    def _latest_realtime_segment(self) -> SubtitleSegment | None:
        latest_segment_id = self.chinese_caption_composer.latest_segment_id
        if latest_segment_id:
            latest = self.subtitle_state.get(latest_segment_id)
            if latest is not None:
                return latest

        fallback: SubtitleSegment | None = None
        for segment in reversed(self.subtitle_state.segments()):
            if _is_realtime_asr_segment(segment):
                if fallback is None:
                    fallback = segment
                if segment.status == SubtitleSegmentStatus.PARTIAL:
                    return segment
        return fallback

    def _handle_realtime_error(self, message: str) -> None:
        self._realtime_stop_intent = "error"
        self._finalize_transcript_session(
            TranscriptSessionStatus.FAILED,
            error_message=message,
        )
        self._set_status("异常")
        if self.correction_hint_label is not None:
            self.correction_hint_label.setText(message)

    def _handle_realtime_warning(self, message: str) -> None:
        if self.correction_hint_label is not None:
            self.correction_hint_label.setText(message)

    def _handle_realtime_finished(self) -> None:
        if (
            self._current_transcript_session is not None
            and self._current_transcript_session.status
            == TranscriptSessionStatus.RUNNING
            and not self._realtime_stop_intent
        ):
            self._finalize_transcript_session(
                TranscriptSessionStatus.INTERRUPTED,
                error_message="字幕服务意外中断",
            )
        self.realtime_thread = None
        self.realtime_worker = None
        self._active_recognition_profile = None
        self._set_recognition_mode_controls_enabled(True)
        self._set_transport_running(False)
        if (
            self.status_label is not None
            and self.status_label.text() not in {"异常", "暂停", "待机"}
        ):
            self._set_status("待机")

    def _selected_recognition_profile(self) -> RecognitionProfile:
        if self.recognition_mode_group is None:
            return get_recognition_profile("balanced")

        for index, button in enumerate(self.recognition_mode_buttons):
            if button.isChecked():
                return get_recognition_profile(recognition_mode_from_index(index))
        return get_recognition_profile("balanced")

    def _update_recognition_mode_hint(self) -> None:
        profile = self._selected_recognition_profile()
        if self.latency_hint_label is not None:
            self.latency_hint_label.setText(profile.latency_hint)

    def _set_recognition_mode_controls_enabled(self, enabled: bool) -> None:
        for button in self.recognition_mode_buttons:
            button.setEnabled(enabled)

    def _set_dropped_chunks_display(self, dropped_chunks: int) -> None:
        if self.dropped_chunks_label is not None:
            self.dropped_chunks_label.setText(f"丢帧：{dropped_chunks}")

    def _handle_dropped_chunks_changed(self, dropped_chunks: int) -> None:
        self._set_dropped_chunks_display(dropped_chunks)
        profile = self._active_recognition_profile
        if profile is None or self.correction_hint_label is None:
            return

        if dropped_chunks < profile.dropped_chunks_warn_threshold:
            return

        if self._dropped_chunks_warned:
            return

        self._dropped_chunks_warned = True
        self.correction_hint_label.setText(
            "音频处理出现积压，字幕可能会有短暂延迟。"
            "可尝试切换到高准确模式，或关闭占用较高的程序。"
        )

    def _set_transport_running(self, running: bool) -> None:
        if self.start_button is not None:
            self.start_button.setEnabled(not running)
        if self.pause_button is not None:
            self.pause_button.setEnabled(True)
        if self.stop_button is not None:
            self.stop_button.setEnabled(True)

    def _start_demo_stream(self) -> None:
        if self._is_current_transcript_paused():
            self._resume_transcript_session()
            self._set_history_view_mode("current")
        elif (
            self._current_transcript_session is None
            or not self._current_transcript_session.is_open
        ):
            self._reset_demo_state()
            self._begin_transcript_session("demo")
        self._show_overlay()
        self._set_status("演示中")
        self._advance_demo_stream()

    def _pause_demo_stream(self) -> None:
        if self.demo_timer.isActive():
            self.demo_timer.stop()
            self._pause_transcript_session()
            self._set_status("暂停")
            return
        if 0 < self.demo_step_index < len(self.demo_script):
            self._resume_transcript_session()
            self._set_status("演示中")
            self._schedule_next_demo_step()

    def _stop_demo_stream(self) -> None:
        self.demo_timer.stop()
        self._hide_overlay()
        self._finalize_transcript_session(TranscriptSessionStatus.STOPPED)
        self._set_status("待机")

    def _advance_demo_stream(self) -> None:
        if self.demo_step_index >= len(self.demo_script):
            self._set_status("完成")
            return

        step = self.demo_script[self.demo_step_index]
        segment = self.subtitle_state.apply(step.event)
        self._record_transcript_segment(
            segment,
            urgent=step.event.type != SubtitleEventType.PARTIAL,
        )
        self._render_subtitle_event(step.event, segment)
        self.demo_step_index += 1

        if self.demo_step_index < len(self.demo_script):
            self._schedule_next_demo_step()
        else:
            self._set_status("完成")
            self._finalize_transcript_session(TranscriptSessionStatus.STOPPED)

    def _schedule_next_demo_step(self) -> None:
        step = self.demo_script[self.demo_step_index]
        self.demo_timer.start(step.delay_ms)

    def _compose_realtime_display_text(
        self,
        event: SubtitleEvent,
        segment: SubtitleSegment,
    ) -> str:
        del event
        return " ".join(segment.source_text.split())

    def _render_subtitle_event(
        self,
        event: SubtitleEvent,
        segment: SubtitleSegment,
        *,
        display_text: str | None = None,
    ) -> None:
        source_display_text = segment.source_text if display_text is None else display_text
        translation_frame_is_final = False
        overlay_stable_line_count: int | None = None
        if _is_realtime_asr_segment(segment):
            source_display_text = self._build_realtime_source_display(
                segment,
                source_display_text,
            )
            translation_frame = self.chinese_caption_composer.current_frame()
            translation_display_text = translation_frame.text
            translation_frame_is_final = translation_frame.is_final
            stable_translation = translation_frame.stable_text
            active_translation = translation_frame.active_text
            overlay_stable_line_count = len(translation_frame.stable_lines)
        else:
            translation_display_text = self._translation_display_for_segment(segment)
            translation_lines = [
                line.strip()
                for line in translation_display_text.splitlines()
                if line.strip()
            ][-4:]
            stable_translation = "\n".join(translation_lines[:-1])
            active_translation = translation_lines[-1] if translation_lines else ""
        if self.source_caption_label is not None:
            self.source_caption_label.set_caption_text(
                source_display_text,
                animate=False,
            )
        if self.translation_stable_caption_label is not None:
            self.translation_stable_caption_label.set_caption_text(
                stable_translation,
                animate=False,
            )
        if self.translation_caption_label is not None:
            self.translation_caption_label.set_caption_text(active_translation)
        if self.correction_hint_label is not None:
            hint = self._build_event_hint(event, segment)
            if hint != self.correction_hint_label.text():
                self.correction_hint_label.setText(hint)

        overlay_state = segment.status.value
        if (
            _is_realtime_asr_segment(segment)
            and translation_frame_is_final
            and translation_display_text.strip()
            and overlay_state == SubtitleSegmentStatus.PARTIAL.value
        ):
            overlay_state = SubtitleSegmentStatus.FINAL.value
        if (
            _is_realtime_asr_segment(segment)
            and segment.status == SubtitleSegmentStatus.FINAL
            and not self.chinese_caption_composer.is_segment_final(segment.segment_id)
        ):
            overlay_state = "finalizing"
        self.overlay.set_caption(
            source_text=source_display_text,
            zh_text=translation_display_text,
            state=overlay_state,
            stable_line_count=overlay_stable_line_count,
        )
        self._render_history_segment(segment)

    def _translation_display_for_segment(self, segment: SubtitleSegment) -> str:
        return segment.zh_text if _has_distinct_translation(segment) else ""

    def _build_realtime_source_display(
        self,
        segment: SubtitleSegment,
        current_display_text: str,
    ) -> str:
        del segment
        return " ".join(current_display_text.split())

    def _render_history_segment(self, segment: SubtitleSegment) -> None:
        if self._history_view_mode != "current":
            return
        self._upsert_history_segment(segment, scroll_to_bottom=True)

    def _upsert_history_segment(
        self,
        segment: SubtitleSegment,
        *,
        scroll_to_bottom: bool,
    ) -> None:
        if self.history_list is None:
            return

        item = self._history_items.get(segment.segment_id)
        if item is None:
            if (
                not self._history_items
                and self.history_list.count() == 1
                and self.history_list.item(0).data(Qt.ItemDataRole.UserRole) is None
            ):
                self.history_list.clear()
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, segment.segment_id)
            item.setForeground(QBrush(QColor(0, 0, 0, 0)))
            self.history_list.addItem(item)
            self._history_items[segment.segment_id] = item

        text = self._format_history_item(segment)
        if item.text() != text:
            item.setText(text)
        source_text, translation_text = self._history_text_parts(segment)
        entry = self.history_list.itemWidget(item)
        if not isinstance(entry, _HistoryItemWidget):
            entry = _HistoryItemWidget()
            self.history_list.setItemWidget(item, entry)
        entry.set_content(source_text, translation_text)
        self._resize_history_item(item, entry)

        self._update_history_count()
        if scroll_to_bottom:
            self.history_list.scrollToBottom()

    def _build_event_hint(self, event: SubtitleEvent, segment: SubtitleSegment) -> str:
        if segment.status == SubtitleSegmentStatus.UPDATED:
            return "已结合上下文优化译文"
        if segment.status == SubtitleSegmentStatus.FINAL:
            if segment.segment_id.startswith("asr_") and segment.source_text == segment.zh_text:
                return "原文已确认，正在完善译文"
            return "本句已完成"
        if segment.segment_id.startswith("asr_") and segment.source_text == segment.zh_text:
            return "正在聆听并生成字幕"
        return "译文正在同步更新"

    def _format_history_item(self, segment: SubtitleSegment) -> str:
        source_text, translation_text = self._history_text_parts(segment)
        if not translation_text:
            return source_text
        return f"{source_text}\n{translation_text}"

    def _history_text_parts(self, segment: SubtitleSegment) -> tuple[str, str]:
        source_text = " ".join(segment.source_text.split())
        translation_text = ""
        if _has_distinct_translation(segment):
            if segment.translation_source_text.strip():
                source_text = " ".join(segment.translation_source_text.split())
            translation_text = " ".join(segment.zh_text.split())
        return source_text, translation_text

    def _resize_history_item(
        self,
        item: QListWidgetItem,
        entry: _HistoryItemWidget,
    ) -> None:
        if self.history_list is None:
            return
        width = max(280, self.history_list.viewport().width() - 4)
        item.setSizeHint(QSize(width, entry.recommended_height(width)))

    def _resize_history_items(self) -> None:
        if self.history_list is None:
            return
        if not self._history_items and self.history_list.count() == 1:
            placeholder = self.history_list.item(0)
            if placeholder.data(Qt.ItemDataRole.UserRole) is None:
                height = max(180, self.history_list.viewport().height() - 10)
                placeholder.setSizeHint(
                    QSize(self.history_list.viewport().width() - 4, height)
                )
        for item in self._history_items.values():
            entry = self.history_list.itemWidget(item)
            if isinstance(entry, _HistoryItemWidget):
                self._resize_history_item(item, entry)

    def _update_history_count(self) -> None:
        if self.history_count_label is not None:
            self.history_count_label.setText(f"{len(self._history_items)} 条")

    def _set_history_view_mode(self, mode: str) -> None:
        if mode not in {"current", "saved"}:
            return
        self._history_view_mode = mode
        if self.history_current_button is not None:
            self.history_current_button.setChecked(mode == "current")
        if self.history_saved_button is not None:
            self.history_saved_button.setChecked(mode == "saved")
        if self.history_session_combo is not None:
            self.history_session_combo.setVisible(mode == "saved")

        if mode == "current":
            self._render_transcript_session(
                self._current_transcript_session,
                empty_title="还没有转译内容",
                empty_subtitle="开始转译后，本次内容会实时保存在这里",
            )
            return

        self._load_transcript_history()
        self._refresh_saved_session_selector()
        self._handle_saved_session_selected(
            self.history_session_combo.currentIndex()
            if self.history_session_combo is not None
            else -1
        )

    def _load_transcript_history(self, *, force: bool = False) -> None:
        if self._transcript_history_loaded and not force:
            return
        self._recover_interrupted_transcripts()
        sessions = self.transcript_store.list_sessions()
        current = self._current_transcript_session
        if current is not None and current.is_open:
            sessions = [
                session
                for session in sessions
                if session.session_id != current.session_id
            ]
        self._saved_transcript_sessions = {
            session.session_id: session for session in sessions
        }
        self._transcript_history_loaded = True

    def _recover_interrupted_transcripts(self) -> None:
        if self._transcript_recovery_checked:
            return
        self.transcript_store.recover_interrupted_sessions()
        self._transcript_recovery_checked = True

    def _refresh_saved_session_selector(self) -> None:
        combo = self.history_session_combo
        if combo is None:
            return
        selected_session_id = combo.currentData()
        sessions = list(self._saved_transcript_sessions.values())
        combo.blockSignals(True)
        combo.clear()
        for session in sessions:
            combo.addItem(self._format_transcript_session_label(session), session.session_id)
        if selected_session_id:
            for index in range(combo.count()):
                if combo.itemData(index) == selected_session_id:
                    combo.setCurrentIndex(index)
                    break
        combo.blockSignals(False)

    def _handle_saved_session_selected(self, index: int) -> None:
        if self._history_view_mode != "saved":
            return
        combo = self.history_session_combo
        if combo is None or index < 0:
            self._render_transcript_session(
                None,
                empty_title="还没有历史记录",
                empty_subtitle="完成一次转译后，可在这里回看完整的中英文记录",
            )
            return
        session_id = combo.itemData(index)
        session = self._saved_transcript_sessions.get(str(session_id))
        if session is None:
            session = self.transcript_store.load_session(str(session_id))
        self._render_transcript_session(
            session,
            empty_title="本次记录没有内容",
            empty_subtitle="这次转译中没有可保存的语音内容",
        )

    def _render_transcript_session(
        self,
        session: TranscriptSession | None,
        *,
        empty_title: str,
        empty_subtitle: str,
    ) -> None:
        if self.history_list is None:
            return
        self.history_list.setUpdatesEnabled(False)
        self.history_list.clear()
        self._history_items.clear()
        if session is None or not session.segments:
            self._install_history_placeholder(
                title_text=empty_title,
                subtitle_text=empty_subtitle,
            )
        else:
            for segment in session.segments:
                self._upsert_history_segment(
                    segment.to_subtitle_segment(),
                    scroll_to_bottom=False,
                )
        self.history_list.setUpdatesEnabled(True)
        self._update_history_count()
        self._resize_history_items()
        self.history_list.scrollToTop()

    def _format_transcript_session_label(self, session: TranscriptSession) -> str:
        started_at = datetime.fromisoformat(session.started_at).astimezone()
        status_text = {
            TranscriptSessionStatus.RUNNING: "进行中",
            TranscriptSessionStatus.PAUSED: "已暂停",
            TranscriptSessionStatus.STOPPED: "已完成",
            TranscriptSessionStatus.INTERRUPTED: "意外中断",
            TranscriptSessionStatus.FAILED: "异常结束",
        }[session.status]
        duration = _format_duration(session.duration_seconds)
        return (
            f"{started_at:%m-%d %H:%M} · {len(session.segments)} 条"
            f" · {duration} · {status_text}"
        )

    def _reset_history_placeholder(
        self,
        *,
        title_text: str = "还没有转译内容",
        subtitle_text: str = "开始转译后，中英文内容会按时间顺序保存在这里",
    ) -> None:
        if self.history_list is None:
            return
        self.history_list.clear()
        self._history_items.clear()
        self._install_history_placeholder(
            title_text=title_text,
            subtitle_text=subtitle_text,
        )
        self._update_history_count()

    def _install_history_placeholder(
        self,
        *,
        title_text: str = "还没有转译内容",
        subtitle_text: str = "开始转译后，中英文内容会按时间顺序保存在这里",
    ) -> None:
        if self.history_list is None:
            return
        item = QListWidgetItem(subtitle_text)
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        item.setForeground(QBrush(QColor(0, 0, 0, 0)))
        self.history_list.addItem(item)
        self.history_list.setItemWidget(
            item,
            _HistoryEmptyWidget(title_text, subtitle_text),
        )
        QTimer.singleShot(0, self._resize_history_items)

    def _begin_transcript_session(self, recognition_mode: str) -> None:
        self._recover_interrupted_transcripts()
        if (
            self._current_transcript_session is not None
            and self._current_transcript_session.is_open
        ):
            self._finalize_transcript_session(
                TranscriptSessionStatus.INTERRUPTED,
                error_message="新的监听会话已开始",
            )
        self._current_transcript_session = TranscriptSession.create(
            asr_provider=self.config.asr_provider,
            translation_provider=self.config.active_translation_provider,
            source_language=self.config.source_language,
            target_language=self.config.target_language,
            recognition_mode=recognition_mode,
        )
        self.transcript_persistence.schedule(
            self._current_transcript_session,
            urgent=True,
        )
        self._transcript_history_loaded = False
        self._set_history_view_mode("current")

    def _record_transcript_segment(
        self,
        segment: SubtitleSegment,
        *,
        urgent: bool,
    ) -> None:
        session = self._current_transcript_session
        if session is None or not session.is_open:
            return
        session.upsert_segment(segment)
        self.transcript_persistence.schedule(session, urgent=urgent)

    def _pause_transcript_session(self) -> None:
        session = self._current_transcript_session
        if session is None:
            return
        session.pause()
        self.transcript_persistence.schedule(session, urgent=True)

    def _resume_transcript_session(self) -> None:
        session = self._current_transcript_session
        if session is None:
            return
        session.resume()
        self.transcript_persistence.schedule(session, urgent=True)

    def _is_current_transcript_paused(self) -> bool:
        return (
            self._current_transcript_session is not None
            and self._current_transcript_session.status
            == TranscriptSessionStatus.PAUSED
        )

    def _finalize_transcript_session(
        self,
        status: TranscriptSessionStatus,
        *,
        error_message: str = "",
    ) -> None:
        session = self._current_transcript_session
        if session is None or not session.is_open:
            return
        session.finish(status, error_message=error_message)
        self.transcript_persistence.schedule(session, urgent=True)
        flushed = self.transcript_persistence.flush()
        persistence_error = self.transcript_persistence.last_error
        if (
            (not flushed or persistence_error is not None)
            and self.correction_hint_label is not None
        ):
            detail = str(persistence_error) if persistence_error is not None else "写入超时"
            self.correction_hint_label.setText(f"转译记录保存失败：{detail}")
        self._transcript_history_loaded = False
        if self._history_view_mode == "saved":
            self._load_transcript_history(force=True)
            self._refresh_saved_session_selector()
            combo = self.history_session_combo
            if combo is not None:
                for index in range(combo.count()):
                    if combo.itemData(index) == session.session_id:
                        combo.setCurrentIndex(index)
                        break
                self._handle_saved_session_selected(combo.currentIndex())

    def _reset_realtime_state(self) -> None:
        self.realtime_render_timer.stop()
        self._pending_realtime_render = None
        self.subtitle_state = SubtitleState()
        self.chinese_caption_composer.reset()
        self.translation_planner.reset()
        self._accepted_partial_translation_words.clear()
        self._translation_session_id = uuid.uuid4().hex
        if self.translation_manager is not None:
            self.translation_manager.begin_session(self._translation_session_id)
        self._dropped_chunks_warned = False
        self._set_dropped_chunks_display(0)
        if self.source_caption_label is not None:
            self.source_caption_label.set_caption_text(
                "正在聆听播放内容…",
                animate=False,
            )
        if self.translation_stable_caption_label is not None:
            self.translation_stable_caption_label.set_caption_text("", animate=False)
            self.translation_stable_caption_label.hide()
        if self.translation_caption_label is not None:
            self.translation_caption_label.set_caption_text(
                "翻译会随着声音实时呈现",
                animate=False,
            )
        if self.correction_hint_label is not None:
            self.correction_hint_label.setText("准备就绪")
        self._reset_history_placeholder()
        self.overlay.set_caption(
            source_text="",
            zh_text="正在聆听，字幕即将出现",
            state=SubtitleSegmentStatus.PARTIAL.value,
        )

    def _reset_demo_state(self) -> None:
        self.realtime_render_timer.stop()
        self._pending_realtime_render = None
        self.subtitle_state = SubtitleState()
        self.chinese_caption_composer.reset()
        self.translation_planner.reset()
        self._accepted_partial_translation_words.clear()
        self.demo_script = build_default_demo_script()
        self.demo_step_index = 0
        if self.source_caption_label is not None:
            self.source_caption_label.set_caption_text(
                "演示内容即将开始",
                animate=False,
            )
        if self.translation_stable_caption_label is not None:
            self.translation_stable_caption_label.set_caption_text("", animate=False)
            self.translation_stable_caption_label.hide()
        if self.translation_caption_label is not None:
            self.translation_caption_label.set_caption_text(
                "字幕会随着内容自然呈现",
                animate=False,
            )
        if self.correction_hint_label is not None:
            self.correction_hint_label.setText("字幕演示已就绪")
        self._reset_history_placeholder()
        self.overlay.set_sample_caption()

    def _set_status(self, status: str) -> None:
        if self.status_label is not None:
            self.status_label.setText(status)

    def resizeEvent(self, event) -> None:  # noqa: ANN001
        super().resizeEvent(event)
        QTimer.singleShot(0, self._resize_history_items)

    def closeEvent(self, event) -> None:  # noqa: ANN001
        self.demo_timer.stop()
        self.realtime_render_timer.stop()
        self._realtime_stop_intent = "close"
        self._accept_realtime_generation = None
        if self.realtime_worker is not None:
            self.realtime_worker.stop()
        if self.realtime_thread is not None and self.realtime_thread.isRunning():
            self.realtime_thread.quit()
            self.realtime_thread.wait(2000)
        self._finalize_transcript_session(TranscriptSessionStatus.INTERRUPTED)
        self.transcript_persistence.close()
        self._stop_translation_manager()
        self.overlay.close()
        super().closeEvent(event)


def run_main_window(config: AppConfig) -> int:
    app = QApplication.instance()
    owns_app = app is None
    if app is None:
        app = QApplication(sys.argv)

    app.setApplicationName("AI 同声传译助手")
    app.setWindowIcon(QIcon())
    app.setFont(QFont(_select_ui_font_family(), 10))
    apply_app_theme(app)

    window = MainWindow(config)
    window.show()

    if owns_app:
        return app.exec()
    return 0


def _select_ui_font_family() -> str:
    available_fonts = set(QFontDatabase.families())
    candidates = [
        "Microsoft YaHei UI",
        "Microsoft YaHei",
        "DengXian",
        "SimHei",
        "Arial",
    ]
    for family in candidates:
        if family in available_fonts:
            return family
    return candidates[0]


def _is_realtime_asr_segment(segment: SubtitleSegment) -> bool:
    return segment.segment_id.startswith("asr_")


def _has_distinct_translation(segment: SubtitleSegment) -> bool:
    return bool(segment.zh_text.strip()) and (
        segment.source_text.strip() != segment.zh_text.strip()
    )


def _is_compatible_source_update(old_text: str, new_text: str) -> bool:
    old_words = _normalized_words(old_text)
    new_words = _normalized_words(new_text)
    if not old_words or not new_words:
        return False
    common_prefix = 0
    for old_word, new_word in zip(old_words, new_words, strict=False):
        if old_word != new_word:
            break
        common_prefix += 1
    shorter_length = min(len(old_words), len(new_words))
    return common_prefix >= max(1, shorter_length - 1)


def _is_source_prefix(prefix_text: str, full_text: str) -> bool:
    prefix_words = _normalized_words(prefix_text)
    full_words = _normalized_words(full_text)
    if not prefix_words:
        return False
    if len(prefix_words) > len(full_words):
        return False
    return prefix_words == full_words[: len(prefix_words)]


def _normalized_words(text: str) -> list[str]:
    return text.casefold().split()


def _format_duration(duration_seconds: float) -> str:
    total_seconds = max(0, int(duration_seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def _wrapped_text_height(metrics: QFontMetrics, text: str, width: int) -> int:
    if not text:
        return 0
    bounds = metrics.boundingRect(
        QRect(0, 0, width, 10_000),
        Qt.TextFlag.TextWordWrap,
        text,
    )
    return bounds.height()
