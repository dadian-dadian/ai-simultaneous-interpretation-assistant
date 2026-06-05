from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontDatabase, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QSlider,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from app.core.config import AppConfig
from app.ui.subtitle_overlay import SubtitleOverlayWindow
from app.ui.theme import apply_app_theme


class MainWindow(QMainWindow):
    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self.config = config
        self.overlay = SubtitleOverlayWindow()
        self.overlay_toggle: QPushButton | None = None
        self.font_size_slider: QSlider | None = None
        self.opacity_slider: QSlider | None = None
        self.display_mode_combo: QComboBox | None = None

        self.setWindowTitle("AI 同声传译助手")
        self.setMinimumSize(1120, 720)
        self.resize(1220, 760)

        root = QWidget()
        root.setObjectName("AppRoot")
        self.setCentralWidget(root)

        shell = QVBoxLayout(root)
        shell.setContentsMargins(24, 22, 24, 22)
        shell.setSpacing(18)

        shell.addWidget(self._build_header())
        shell.addLayout(self._build_content(), stretch=1)
        shell.addWidget(self._build_status_bar())
        self._sync_overlay_from_controls()

    def _build_header(self) -> QWidget:
        header = QFrame()
        header.setObjectName("Header")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        title_block = QVBoxLayout()
        title_block.setSpacing(4)

        title = QLabel("AI 同声传译助手")
        title.setObjectName("WindowTitle")
        subtitle = QLabel("系统音频捕获 · 实时字幕 · 上下文修正")
        subtitle.setObjectName("WindowSubtitle")

        title_block.addWidget(title)
        title_block.addWidget(subtitle)

        status = QLabel("待机")
        status.setObjectName("StatusBadge")
        status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status.setFixedSize(72, 32)

        layout.addLayout(title_block, stretch=1)
        layout.addWidget(status)
        return header

    def _build_content(self) -> QHBoxLayout:
        content = QHBoxLayout()
        content.setSpacing(18)

        content.addWidget(self._build_control_panel(), stretch=4)
        content.addWidget(self._build_settings_panel(), stretch=2)
        return content

    def _build_control_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("Panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(18)

        layout.addLayout(self._build_transport_controls())

        live_title = QLabel("实时字幕")
        live_title.setObjectName("SectionTitle")
        layout.addWidget(live_title)
        layout.addWidget(self._build_live_caption(), stretch=1)

        history_title = QLabel("双语历史")
        history_title.setObjectName("SectionTitle")
        layout.addWidget(history_title)
        layout.addWidget(self._build_history_list(), stretch=2)

        return panel

    def _build_transport_controls(self) -> QHBoxLayout:
        controls = QHBoxLayout()
        controls.setSpacing(10)

        style = self.style()
        start = QPushButton("开始")
        start.setObjectName("PrimaryButton")
        start.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_MediaPlay))

        pause = QPushButton("暂停")
        pause.setObjectName("GhostButton")
        pause.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_MediaPause))

        stop = QPushButton("停止")
        stop.setObjectName("GhostButton")
        stop.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_MediaStop))

        for button in (start, pause, stop):
            button.setMinimumHeight(42)
            controls.addWidget(button)

        start.clicked.connect(self._show_overlay)
        stop.clicked.connect(self._hide_overlay)

        self.overlay_toggle = QPushButton("悬浮字幕")
        self.overlay_toggle.setObjectName("GhostButton")
        self.overlay_toggle.setCheckable(True)
        self.overlay_toggle.setMinimumHeight(42)
        self.overlay_toggle.clicked.connect(self._toggle_overlay)
        controls.addWidget(self.overlay_toggle)

        controls.addStretch(1)

        latency = QLabel("延迟目标 1.5s")
        latency.setObjectName("MetricPill")
        latency.setAlignment(Qt.AlignmentFlag.AlignCenter)
        latency.setFixedSize(116, 34)
        controls.addWidget(latency)

        return controls

    def _build_live_caption(self) -> QWidget:
        frame = QFrame()
        frame.setObjectName("LiveCaption")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)

        source = QLabel("Today we are going to talk about transformer models and inference latency.")
        source.setObjectName("SourceCaption")
        source.setWordWrap(True)

        translation = QLabel("今天我们将讨论 Transformer 模型与推理延迟。")
        translation.setObjectName("TranslatedCaption")
        translation.setWordWrap(True)

        correction = QLabel("术语已统一：inference latency → 推理延迟")
        correction.setObjectName("CorrectionHint")
        correction.setWordWrap(True)

        layout.addWidget(source)
        layout.addWidget(translation)
        layout.addWidget(correction)
        layout.addStretch(1)
        return frame

    def _build_history_list(self) -> QListWidget:
        history = QListWidget()
        history.setObjectName("HistoryList")
        samples = [
            ("final", "The model uses attention to align tokens.", "该模型使用注意力机制对齐 token。"),
            ("updated", "AI agents can use tools automatically.", "AI 智能体可以自动使用工具。"),
            ("partial", "We need to reduce latency without losing context.", "我们需要在不丢失上下文的情况下降低延迟……"),
        ]

        for state, source, translation in samples:
            item = QListWidgetItem(f"{state.upper()}  {translation}\n{source}")
            item.setSizeHint(item.sizeHint().expandedTo(item.sizeHint()))
            history.addItem(item)

        return history

    def _build_settings_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("Panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(18)

        layout.addWidget(self._build_audio_section())
        layout.addWidget(self._build_mode_section())
        layout.addWidget(self._build_subtitle_section())
        layout.addStretch(1)

        return panel

    def _build_audio_section(self) -> QWidget:
        section = self._section("音频源")
        layout = section.layout()

        device = QComboBox()
        device.addItems(["默认系统输出", "扬声器 / 耳机", "虚拟音频设备"])
        device.setObjectName("Input")
        layout.addWidget(device)

        return section

    def _build_mode_section(self) -> QWidget:
        section = self._section("翻译模式")
        layout = section.layout()

        button_row = QHBoxLayout()
        button_row.setSpacing(8)

        group = QButtonGroup(section)
        group.setExclusive(True)
        for index, name in enumerate(("低延迟", "均衡", "高准确")):
            button = QPushButton(name)
            button.setObjectName("SegmentButton")
            button.setCheckable(True)
            button.setMinimumHeight(36)
            button.setChecked(index == 1)
            group.addButton(button)
            button_row.addWidget(button)

        layout.addLayout(button_row)
        return section

    def _build_subtitle_section(self) -> QWidget:
        section = self._section("字幕样式")
        layout = section.layout()

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)

        font_label = QLabel("字号")
        font_label.setObjectName("FieldLabel")
        font_size = QSlider(Qt.Orientation.Horizontal)
        font_size.setObjectName("Slider")
        font_size.setRange(18, 42)
        font_size.setValue(28)
        font_size.valueChanged.connect(self._update_overlay_font_size)
        self.font_size_slider = font_size

        opacity_label = QLabel("透明度")
        opacity_label.setObjectName("FieldLabel")
        opacity = QSlider(Qt.Orientation.Horizontal)
        opacity.setObjectName("Slider")
        opacity.setRange(40, 100)
        opacity.setValue(82)
        opacity.valueChanged.connect(self._update_overlay_opacity)
        self.opacity_slider = opacity

        mode_label = QLabel("显示")
        mode_label.setObjectName("FieldLabel")
        mode = QComboBox()
        mode.setObjectName("Input")
        mode.addItems(["双语字幕", "仅中文字幕", "仅原文字幕"])
        mode.currentIndexChanged.connect(self._update_overlay_display_mode)
        self.display_mode_combo = mode

        grid.addWidget(font_label, 0, 0)
        grid.addWidget(font_size, 0, 1)
        grid.addWidget(opacity_label, 1, 0)
        grid.addWidget(opacity, 1, 1)
        grid.addWidget(mode_label, 2, 0)
        grid.addWidget(mode, 2, 1)
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

    def _build_status_bar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("BottomBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(14)

        items = [
            f"ASR：{self.config.asr_provider}",
            f"翻译：{self.config.translation_provider}",
            f"语言：{self.config.source_language} → {self.config.target_language}",
            f"字幕：{self.config.subtitle_mode}",
        ]

        for text in items:
            label = QLabel(text)
            label.setObjectName("BottomMeta")
            layout.addWidget(label)

        layout.addStretch(1)
        return bar

    def _sync_overlay_from_controls(self) -> None:
        if self.font_size_slider is not None:
            self.overlay.set_font_size(self.font_size_slider.value())
        if self.opacity_slider is not None:
            self.overlay.set_opacity_percent(self.opacity_slider.value())
        if self.display_mode_combo is not None:
            self._update_overlay_display_mode(self.display_mode_combo.currentIndex())

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

    def closeEvent(self, event) -> None:  # noqa: ANN001
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
