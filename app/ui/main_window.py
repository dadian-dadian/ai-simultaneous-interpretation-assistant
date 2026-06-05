from __future__ import annotations

import sys

from PySide6.QtCore import Qt, QThread, QTimer
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
from app.core.demo_stream import DemoSubtitleScript, build_default_demo_script
from app.core.subtitle import SubtitleEvent, SubtitleSegment, SubtitleSegmentStatus, SubtitleState
from app.ui.realtime_worker import RealtimeSubtitleWorker
from app.ui.subtitle_overlay import SubtitleOverlayWindow
from app.ui.theme import apply_app_theme


class MainWindow(QMainWindow):
    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self.config = config
        self.subtitle_state = SubtitleState()
        self.demo_script: DemoSubtitleScript = build_default_demo_script()
        self.demo_step_index = 0
        self.demo_timer = QTimer(self)
        self.demo_timer.setSingleShot(True)
        self.demo_timer.timeout.connect(self._advance_demo_stream)
        self.realtime_thread: QThread | None = None
        self.realtime_worker: RealtimeSubtitleWorker | None = None

        self.overlay = SubtitleOverlayWindow()
        self.status_label: QLabel | None = None
        self.start_button: QPushButton | None = None
        self.pause_button: QPushButton | None = None
        self.stop_button: QPushButton | None = None
        self.overlay_toggle: QPushButton | None = None
        self.font_size_slider: QSlider | None = None
        self.opacity_slider: QSlider | None = None
        self.display_mode_combo: QComboBox | None = None
        self.source_caption_label: QLabel | None = None
        self.translation_caption_label: QLabel | None = None
        self.correction_hint_label: QLabel | None = None
        self.history_list: QListWidget | None = None

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
        self.status_label = status

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
            button.setMinimumHeight(42)
            controls.addWidget(button)

        start.clicked.connect(self._start_subtitle_stream)
        pause.clicked.connect(self._pause_subtitle_stream)
        stop.clicked.connect(self._stop_subtitle_stream)

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

        source = QLabel("等待字幕流启动。")
        source.setObjectName("SourceCaption")
        source.setWordWrap(True)
        self.source_caption_label = source

        translation = QLabel("点击“开始”后，系统将开始监听系统音频或运行内置演示。")
        translation.setObjectName("TranslatedCaption")
        translation.setWordWrap(True)
        self.translation_caption_label = translation

        correction = QLabel("实时模式：MID_TEXT 会显示为临时字幕，FIN_TEXT 会确认当前字幕。")
        correction.setObjectName("CorrectionHint")
        correction.setWordWrap(True)
        self.correction_hint_label = correction

        layout.addWidget(source)
        layout.addWidget(translation)
        layout.addWidget(correction)
        layout.addStretch(1)
        return frame

    def _build_history_list(self) -> QListWidget:
        history = QListWidget()
        history.setObjectName("HistoryList")
        history.addItem("点击“开始”查看字幕历史。")
        self.history_list = history

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

    def _start_subtitle_stream(self) -> None:
        if self._is_realtime_running():
            return

        if self.config.asr_provider.strip().lower() == "mock":
            self._start_demo_stream()
            return

        self.demo_timer.stop()
        self._reset_realtime_state()
        self._show_overlay()
        self._set_transport_running(True)
        self._set_status("启动中")

        thread = QThread(self)
        worker = RealtimeSubtitleWorker(self.config)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.subtitle_event.connect(self._handle_realtime_subtitle_event)
        worker.status_changed.connect(self._set_status)
        worker.error_occurred.connect(self._handle_realtime_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._handle_realtime_finished)

        self.realtime_thread = thread
        self.realtime_worker = worker
        thread.start()

    def _pause_subtitle_stream(self) -> None:
        if self._is_realtime_running():
            self._stop_realtime_worker()
            self._set_status("暂停")
            if self.correction_hint_label is not None:
                self.correction_hint_label.setText("已暂停实时识别，点击“开始”可重新监听系统音频。")
            return
        self._pause_demo_stream()

    def _stop_subtitle_stream(self) -> None:
        if self._is_realtime_running():
            self._stop_realtime_worker()
            self._hide_overlay()
            self._reset_realtime_state()
            self._set_status("待机")
            return
        self._stop_demo_stream()

    def _is_realtime_running(self) -> bool:
        return self.realtime_thread is not None and self.realtime_thread.isRunning()

    def _stop_realtime_worker(self) -> None:
        if self.realtime_worker is not None:
            self.realtime_worker.stop()

    def _handle_realtime_subtitle_event(self, event: SubtitleEvent) -> None:
        segment = self.subtitle_state.apply(event)
        self._render_subtitle_event(event, segment)

    def _handle_realtime_error(self, message: str) -> None:
        self._set_status("异常")
        if self.correction_hint_label is not None:
            self.correction_hint_label.setText(message)

    def _handle_realtime_finished(self) -> None:
        self.realtime_thread = None
        self.realtime_worker = None
        self._set_transport_running(False)
        if (
            self.status_label is not None
            and self.status_label.text() not in {"异常", "暂停", "待机"}
        ):
            self._set_status("待机")

    def _set_transport_running(self, running: bool) -> None:
        if self.start_button is not None:
            self.start_button.setEnabled(not running)
        if self.pause_button is not None:
            self.pause_button.setEnabled(True)
        if self.stop_button is not None:
            self.stop_button.setEnabled(True)

    def _start_demo_stream(self) -> None:
        if self.demo_step_index >= len(self.demo_script):
            self._reset_demo_state()
        self._show_overlay()
        self._set_status("演示中")
        self._advance_demo_stream()

    def _pause_demo_stream(self) -> None:
        if self.demo_timer.isActive():
            self.demo_timer.stop()
            self._set_status("暂停")
            return
        if 0 < self.demo_step_index < len(self.demo_script):
            self._set_status("演示中")
            self._schedule_next_demo_step()

    def _stop_demo_stream(self) -> None:
        self.demo_timer.stop()
        self._hide_overlay()
        self._reset_demo_state()
        self._set_status("待机")

    def _advance_demo_stream(self) -> None:
        if self.demo_step_index >= len(self.demo_script):
            self._set_status("完成")
            return

        step = self.demo_script[self.demo_step_index]
        segment = self.subtitle_state.apply(step.event)
        self._render_subtitle_event(step.event, segment)
        self.demo_step_index += 1

        if self.demo_step_index < len(self.demo_script):
            self._schedule_next_demo_step()
        else:
            self._set_status("完成")

    def _schedule_next_demo_step(self) -> None:
        step = self.demo_script[self.demo_step_index]
        self.demo_timer.start(step.delay_ms)

    def _render_subtitle_event(self, event: SubtitleEvent, segment: SubtitleSegment) -> None:
        if self.source_caption_label is not None:
            self.source_caption_label.setText(segment.source_text)
        if self.translation_caption_label is not None:
            self.translation_caption_label.setText(segment.zh_text)
        if self.correction_hint_label is not None:
            self.correction_hint_label.setText(self._build_event_hint(event, segment))

        self.overlay.set_caption(
            source_text=segment.source_text,
            zh_text=segment.zh_text,
            state=segment.status.value,
        )
        self._render_history()

    def _render_history(self) -> None:
        if self.history_list is None:
            return

        self.history_list.clear()
        for segment in self.subtitle_state.segments():
            item = QListWidgetItem(self._format_history_item(segment))
            item.setData(Qt.ItemDataRole.UserRole, segment.segment_id)
            self.history_list.addItem(item)
        self.history_list.scrollToBottom()

    def _build_event_hint(self, event: SubtitleEvent, segment: SubtitleSegment) -> str:
        if segment.status == SubtitleSegmentStatus.UPDATED:
            reason = event.reason or "context_correction"
            return f"已修正：{reason}"
        if segment.status == SubtitleSegmentStatus.FINAL:
            if segment.segment_id.startswith("asr_") and segment.source_text == segment.zh_text:
                return "FIN_TEXT：当前语音段已确认，翻译模块接入后会替换为中文字幕。"
            return "正式字幕：当前语音段已稳定。"
        if segment.segment_id.startswith("asr_") and segment.source_text == segment.zh_text:
            return "MID_TEXT：实时识别中的临时字幕，后续 FIN_TEXT 会回写确认。"
        return "临时字幕：优先保证低延迟，后续上下文可能回写修正。"

    def _format_history_item(self, segment: SubtitleSegment) -> str:
        state_label = {
            SubtitleSegmentStatus.PARTIAL: "实时",
            SubtitleSegmentStatus.FINAL: "确认",
            SubtitleSegmentStatus.UPDATED: "修正",
        }[segment.status]
        revision_marker = " · 已回写" if segment.revisions else ""
        if segment.source_text == segment.zh_text:
            return f"{state_label}{revision_marker}  {segment.source_text}"
        return f"{state_label}{revision_marker}  {segment.zh_text}\n{segment.source_text}"

    def _reset_realtime_state(self) -> None:
        self.subtitle_state = SubtitleState()
        if self.source_caption_label is not None:
            self.source_caption_label.setText("等待系统音频中的语音。")
        if self.translation_caption_label is not None:
            self.translation_caption_label.setText("实时 ASR 已准备，识别结果会先以原文字幕展示。")
        if self.correction_hint_label is not None:
            self.correction_hint_label.setText("MID_TEXT 作为临时字幕，FIN_TEXT 作为正式字幕。")
        if self.history_list is not None:
            self.history_list.clear()
            self.history_list.addItem("实时字幕历史将在这里更新。")
        self.overlay.set_caption(
            source_text="等待系统音频中的语音。",
            zh_text="实时 ASR 已准备。",
            state=SubtitleSegmentStatus.PARTIAL.value,
        )

    def _reset_demo_state(self) -> None:
        self.subtitle_state = SubtitleState()
        self.demo_script = build_default_demo_script()
        self.demo_step_index = 0
        if self.source_caption_label is not None:
            self.source_caption_label.setText("等待模拟字幕流启动。")
        if self.translation_caption_label is not None:
            self.translation_caption_label.setText("点击“开始”后，系统将演示临时字幕、正式字幕和历史修正。")
        if self.correction_hint_label is not None:
            self.correction_hint_label.setText(
                "演示模式：使用内置技术分享字幕脚本，不调用外部 AI 服务。"
            )
        if self.history_list is not None:
            self.history_list.clear()
            self.history_list.addItem("点击“开始”查看模拟字幕历史。")
        self.overlay.set_sample_caption()

    def _set_status(self, status: str) -> None:
        if self.status_label is not None:
            self.status_label.setText(status)

    def closeEvent(self, event) -> None:  # noqa: ANN001
        self.demo_timer.stop()
        if self.realtime_worker is not None:
            self.realtime_worker.stop()
        if self.realtime_thread is not None and self.realtime_thread.isRunning():
            self.realtime_thread.quit()
            self.realtime_thread.wait(2000)
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
