from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from app.ui.smooth_caption import SmoothCaptionLabel


class SubtitleOverlayWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._drag_position: QPoint | None = None
        self._font_size = 28
        self._opacity_percent = 82
        self._display_mode = "bilingual"
        self._has_distinct_translation = True

        self.setWindowTitle("悬浮字幕")
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMinimumSize(700, 204)
        self.resize(920, 232)

        self._build_ui()
        self.set_sample_caption()
        self.set_opacity_percent(self._opacity_percent)
        self.set_font_size(self._font_size)

    def _build_ui(self) -> None:
        shell = QVBoxLayout(self)
        shell.setContentsMargins(0, 0, 0, 0)

        self.container = QFrame()
        self.container.setObjectName("OverlayContainer")
        shell.addWidget(self.container)

        layout = QVBoxLayout(self.container)
        layout.setContentsMargins(22, 16, 22, 18)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(8)

        self.state_badge = QLabel("实时")
        self.state_badge.setObjectName("OverlayStateBadge")
        self.state_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.state_badge.setFixedSize(54, 24)

        self.drag_hint = QLabel("AI 同声传译")
        self.drag_hint.setObjectName("OverlayHint")

        close_button = QPushButton("×")
        close_button.setObjectName("OverlayCloseButton")
        close_button.setFixedSize(26, 26)
        close_button.clicked.connect(self.hide)

        header.addWidget(self.state_badge)
        header.addWidget(self.drag_hint)
        header.addStretch(1)
        header.addWidget(close_button)

        self.translation_label = SmoothCaptionLabel()
        self.translation_label.setObjectName("OverlayTranslation")
        self.translation_label.setWordWrap(True)
        self.translation_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.translation_label.setMinimumHeight(58)

        self.source_label = SmoothCaptionLabel()
        self.source_label.setObjectName("OverlaySource")
        self.source_label.setWordWrap(True)
        self.source_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )

        layout.addLayout(header)
        layout.addWidget(self.translation_label)
        layout.addWidget(self.source_label)

    def set_sample_caption(self) -> None:
        self.set_caption(
            source_text=(
                "Today we are going to talk about transformer models and inference latency."
            ),
            zh_text="今天我们将讨论 Transformer 模型与推理延迟。",
            state="partial",
        )

    def set_caption(self, source_text: str, zh_text: str, state: str = "partial") -> None:
        state_text = {
            "partial": "实时",
            "final": "确认",
            "updated": "已修正",
        }.get(state, "实时")

        if self.state_badge.text() != state_text:
            self.state_badge.setText(state_text)
        self._has_distinct_translation = (
            bool(zh_text.strip()) and source_text.strip() != zh_text.strip()
        )
        self.source_label.set_caption_text(source_text, animate=False)
        self.translation_label.set_caption_text(
            zh_text if self._has_distinct_translation else ""
        )
        self._apply_display_mode()

        if self.state_badge.property("captionState") != state:
            self.state_badge.setProperty("captionState", state)
            self.state_badge.style().unpolish(self.state_badge)
            self.state_badge.style().polish(self.state_badge)

    def set_font_size(self, font_size: int) -> None:
        self._font_size = font_size
        translation_font = QFont(self.translation_label.font())
        translation_font.setPointSize(font_size)
        translation_font.setWeight(QFont.Weight.DemiBold)
        self.translation_label.setFont(translation_font)

        source_font = QFont(self.source_label.font())
        source_font.setPointSize(max(10, round(font_size * 0.4)))
        source_font.setWeight(QFont.Weight.Normal)
        self.source_label.setFont(source_font)

    def set_opacity_percent(self, opacity_percent: int) -> None:
        self._opacity_percent = max(40, min(100, opacity_percent))
        self.setWindowOpacity(self._opacity_percent / 100)

    def set_display_mode(self, display_mode: str) -> None:
        self._display_mode = display_mode
        self._apply_display_mode()

    def _apply_display_mode(self) -> None:
        if self._display_mode == "source":
            self.source_label.setVisible(True)
            self.translation_label.setVisible(False)
            return

        self.translation_label.setVisible(True)
        self.source_label.setVisible(
            self._display_mode == "bilingual"
            and (self._has_distinct_translation or bool(self.source_label.text().strip()))
        )

    def mousePressEvent(self, event) -> None:  # noqa: ANN001
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_position = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
            event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: ANN001
        if event.buttons() & Qt.MouseButton.LeftButton and self._drag_position is not None:
            self.move(event.globalPosition().toPoint() - self._drag_position)
            event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: ANN001
        self._drag_position = None
        event.accept()

