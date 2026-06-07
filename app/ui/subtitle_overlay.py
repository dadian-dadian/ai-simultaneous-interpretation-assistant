from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QPoint,
    QPropertyAnimation,
    QRect,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QCursor, QFont
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QLayout,
    QPushButton,
    QScrollArea,
    QSizeGrip,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.core.chinese_caption import normalize_chinese_caption_text
from app.ui.smooth_caption import SmoothCaptionLabel


class SubtitleOverlayWindow(QWidget):
    visibility_changed = Signal(bool)
    size_mode_changed = Signal(str)

    SIZE_PRESETS = {
        "compact": QSize(680, 190),
        "standard": QSize(860, 260),
        "wide": QSize(1080, 260),
    }
    _RESIZE_MARGIN = 8

    def __init__(self) -> None:
        super().__init__()
        self._drag_position: QPoint | None = None
        self._font_size = 14
        self._opacity_percent = 92
        self._display_mode = "bilingual"
        self._has_distinct_translation = True
        self._sentence_labels: list[SmoothCaptionLabel] = []
        self._label_height_cache: dict[int, tuple[int, str, int, int]] = {}
        self._last_translation_viewport_width = 0

        self.setWindowTitle("悬浮字幕")
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self.setMinimumSize(480, 140)
        self.resize(self.SIZE_PRESETS["compact"])

        self._build_ui()
        self.set_sample_caption()
        self.set_opacity_percent(self._opacity_percent)
        self.set_font_size(self._font_size)

    def _build_ui(self) -> None:
        shell = QVBoxLayout(self)
        shell.setContentsMargins(6, 6, 6, 6)
        shell.setSpacing(0)

        self.container = QFrame()
        self.container.setObjectName("OverlayContainer")
        shell.addWidget(self.container)

        layout = QVBoxLayout(self.container)
        layout.setContentsMargins(18, 12, 12, 10)
        layout.setSpacing(6)

        self.translation_scroll = QScrollArea()
        self.translation_scroll.setObjectName("OverlayTranslationScroll")
        self.translation_scroll.setWidgetResizable(True)
        self.translation_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.translation_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.translation_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.translation_scroll.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        self._make_scroll_area_transparent(self.translation_scroll)
        self.translation_scroll.viewport().installEventFilter(self)

        self.translation_content = QWidget()
        self.translation_content.setObjectName("OverlayTranslationContent")
        self.translation_content.setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground,
            True,
        )
        self.translation_layout = QVBoxLayout(self.translation_content)
        self.translation_layout.setContentsMargins(0, 0, 0, 0)
        self.translation_layout.setSpacing(2)
        self.translation_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.translation_layout.setSizeConstraint(
            QLayout.SizeConstraint.SetMinimumSize
        )
        self.translation_scroll.setWidget(self.translation_content)

        self.divider = QFrame()
        self.divider.setObjectName("OverlayDivider")
        self.divider.setFixedHeight(1)

        self.source_scroll = QScrollArea()
        self.source_scroll.setObjectName("OverlaySourceScroll")
        self.source_scroll.setWidgetResizable(False)
        self.source_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.source_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.source_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.source_scroll.setFixedHeight(22)
        self._make_scroll_area_transparent(self.source_scroll)
        self.source_scroll.viewport().installEventFilter(self)

        self.source_label = SmoothCaptionLabel()
        self.source_label.setObjectName("OverlaySource")
        self.source_label.setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground,
            True,
        )
        self.source_label.setWordWrap(False)
        self.source_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.source_scroll.setWidget(self.source_label)

        layout.addWidget(self.translation_scroll, stretch=1)
        layout.addWidget(self.divider)
        layout.addWidget(self.source_scroll)

        self.resize_grip = QSizeGrip(self.container)
        self.resize_grip.setObjectName("OverlayResizeGrip")
        self.resize_grip.setToolTip("拖动调整字幕窗大小")
        self.resize_grip.setFixedSize(16, 16)
        self.resize_grip.hide()

        self._vertical_scroll_animation = QPropertyAnimation(
            self.translation_scroll.verticalScrollBar(),
            b"value",
            self,
        )
        self._vertical_scroll_animation.setDuration(130)
        self._vertical_scroll_animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._source_scroll_animation = QPropertyAnimation(
            self.source_scroll.horizontalScrollBar(),
            b"value",
            self,
        )
        self._source_scroll_animation.setDuration(120)
        self._source_scroll_animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._layout_refresh_timer = QTimer(self)
        self._layout_refresh_timer.setSingleShot(True)
        self._layout_refresh_timer.timeout.connect(self._refresh_viewports)
        self._settled_layout_refresh_timer = QTimer(self)
        self._settled_layout_refresh_timer.setSingleShot(True)
        self._settled_layout_refresh_timer.setInterval(60)
        self._settled_layout_refresh_timer.timeout.connect(self._refresh_viewports)
        self._scroll_snap_timer = QTimer(self)
        self._scroll_snap_timer.setSingleShot(True)
        self._scroll_snap_timer.setInterval(20)
        self._scroll_snap_timer.timeout.connect(self._snap_scrollbars_to_end)

        # Compatibility controls remain hidden; the overlay itself is subtitle-only.
        self.header = QFrame(self)
        self.header.hide()
        self.state_badge = QLabel("实时", self.header)
        self.state_badge.setObjectName("OverlayStateBadge")
        self.drag_hint = QLabel("", self.header)
        self.close_button = QPushButton("×", self.header)
        self.close_button.setObjectName("OverlayCloseButton")
        self.close_button.clicked.connect(self.hide)

        self.translation_label = self._ensure_sentence_label(0)
        self.translation_stable_label = self.translation_label
        self.completed_labels: list[SmoothCaptionLabel] = []

    def set_sample_caption(self) -> None:
        self.set_caption(
            source_text="Today we are going to discuss real-time translation.",
            zh_text=(
                "系统正在监听音频。"
                "英文识别结果会持续更新。"
                "已完成的中文字幕保持稳定。"
                "当前句子自然地继续出现"
            ),
            state="partial",
        )

    def set_caption(self, source_text: str, zh_text: str, state: str = "partial") -> None:
        self.state_badge.setText(
            {
                "partial": "实时",
                "final": "确认",
                "updated": "已修正",
                "finalizing": "确认中",
            }.get(state, "实时")
        )
        self._has_distinct_translation = (
            bool(zh_text.strip()) and source_text.strip() != zh_text.strip()
        )

        self.source_label.set_caption_text(source_text, animate=False)
        sentences = _split_display_sentences(zh_text)
        if not self._has_distinct_translation:
            sentences = []
        final_state = state in {"final", "updated"}
        self._set_translation_sentences(sentences, final_state=final_state)
        self._apply_display_mode()
        self._schedule_layout_refresh()

        if self.state_badge.property("captionState") != state:
            self.state_badge.setProperty("captionState", state)

    def _set_translation_sentences(
        self,
        sentences: list[tuple[str, bool]],
        *,
        final_state: bool,
    ) -> None:
        for index, (text, punctuation_complete) in enumerate(sentences):
            label = self._ensure_sentence_label(index)
            is_completed = final_state or punctuation_complete or index < len(sentences) - 1
            if label.property("captionCompleted") != is_completed:
                label.setProperty("captionCompleted", is_completed)
                label.setStyleSheet(
                    "color: #95a39f;" if is_completed else "color: #f1f5f3;"
                )
            self._apply_font(label)
            if label.set_caption_text(text, animate=not is_completed):
                self._label_height_cache.pop(id(label), None)
            label.show()

        for label in self._sentence_labels[len(sentences) :]:
            label.hide()
            if label.set_caption_text("", animate=False):
                self._label_height_cache.pop(id(label), None)
            label.setFixedHeight(0)

        if sentences:
            self.translation_label = self._sentence_labels[len(sentences) - 1]
            completed_count = len(sentences) if final_state else max(0, len(sentences) - 1)
            self.completed_labels = self._sentence_labels[:completed_count]
            self.translation_stable_label = (
                self.completed_labels[-1]
                if self.completed_labels
                else self.translation_label
            )
        else:
            self.translation_label = self._ensure_sentence_label(0)
            self.completed_labels = []
            self.translation_stable_label = self.translation_label

    def _ensure_sentence_label(self, index: int) -> SmoothCaptionLabel:
        while len(self._sentence_labels) <= index:
            label = SmoothCaptionLabel()
            label.setObjectName("OverlayTranslation")
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setWordWrap(True)
            label.setMargin(0)
            label.setIndent(0)
            label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            label.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Fixed,
            )
            self.translation_layout.addWidget(label)
            self._apply_font(label)
            self._sentence_labels.append(label)
        return self._sentence_labels[index]

    def set_font_size(self, font_size: int) -> None:
        self._font_size = max(12, min(22, font_size))
        for label in self._sentence_labels:
            self._apply_font(label)

        source_font = QFont(self.source_label.font())
        source_font.setPointSize(max(8, round(self._font_size * 0.5)))
        source_font.setWeight(QFont.Weight.Normal)
        self.source_label.setFont(source_font)
        self._schedule_layout_refresh()

    def _apply_font(self, label: QLabel) -> None:
        font = QFont(label.font())
        font.setPointSize(self._font_size)
        font.setWeight(QFont.Weight.Medium)
        label.setFont(font)

    def set_opacity_percent(self, opacity_percent: int) -> None:
        self._opacity_percent = max(40, min(100, opacity_percent))
        self.setWindowOpacity(self._opacity_percent / 100)

    def set_display_mode(self, display_mode: str) -> None:
        self._display_mode = display_mode
        self._apply_display_mode()
        self._schedule_layout_refresh()

    def set_size_preset(self, preset: str) -> None:
        target_size = self.SIZE_PRESETS.get(preset)
        if target_size is not None:
            self.resize(target_size)

    def _apply_display_mode(self) -> None:
        if self._display_mode == "source":
            self.translation_scroll.hide()
            for label in self._sentence_labels:
                label.hide()
            self.divider.hide()
            self.source_scroll.show()
            self.source_label.show()
            return

        self.translation_scroll.show()
        for label in self._sentence_labels:
            label.setVisible(bool(label.text().strip()))
        self.translation_label.show()
        source_visible = (
            self._display_mode == "bilingual"
            and (
                self._has_distinct_translation
                or bool(self.source_label.text().strip())
            )
        )
        self.source_scroll.setVisible(source_visible)
        self.source_label.setVisible(source_visible)
        self.divider.setVisible(source_visible)

    def _schedule_layout_refresh(self) -> None:
        if self._layout_refresh_timer.isActive():
            self._layout_refresh_timer.stop()
        self._layout_refresh_timer.start(0)
        if self._settled_layout_refresh_timer.isActive():
            self._settled_layout_refresh_timer.stop()
        self._settled_layout_refresh_timer.start()

    def _refresh_viewports(self) -> None:
        viewport_width = self.translation_scroll.viewport().width()
        if viewport_width != self._last_translation_viewport_width:
            self._last_translation_viewport_width = viewport_width
            self._label_height_cache.clear()
        self._layout_translation_sentences()
        self._layout_source_line()
        self._scroll_translation_to_bottom()
        self._scroll_source_to_end()
        if self._scroll_snap_timer.isActive():
            self._scroll_snap_timer.stop()
        self._scroll_snap_timer.start()

    def _layout_translation_sentences(self) -> None:
        width = max(120, self.translation_scroll.viewport().width() - 2)
        visible_labels = [label for label in self._sentence_labels if label.isVisible()]
        content_height = 0
        self.translation_layout.invalidate()
        for label in visible_labels:
            label.setFixedWidth(width)
            cache_key = (
                width,
                label.text(),
                label.font().pointSize(),
            )
            cached = self._label_height_cache.get(id(label))
            if cached is not None and cached[:3] == cache_key:
                height = cached[3]
            else:
                height = _wrapped_label_height(label, width)
                self._label_height_cache[id(label)] = (*cache_key, height)
            label.setFixedHeight(height)
            content_height += height
        if visible_labels:
            content_height += self.translation_layout.spacing() * (len(visible_labels) - 1)
        self.translation_content.setMinimumHeight(content_height)
        self.translation_layout.activate()
        self.translation_content.updateGeometry()

    def _layout_source_line(self) -> None:
        viewport_width = max(1, self.source_scroll.viewport().width())
        text_width = self.source_label.fontMetrics().horizontalAdvance(
            self.source_label.text()
        )
        self.source_label.resize(
            max(viewport_width, text_width + 8),
            self.source_scroll.viewport().height(),
        )

    def _scroll_translation_to_bottom(self) -> None:
        scrollbar = self.translation_scroll.verticalScrollBar()
        target = scrollbar.maximum()
        self._animate_scroll(self._vertical_scroll_animation, scrollbar.value(), target)

    def _scroll_source_to_end(self) -> None:
        scrollbar = self.source_scroll.horizontalScrollBar()
        target = scrollbar.maximum()
        self._animate_scroll(self._source_scroll_animation, scrollbar.value(), target)

    def _snap_scrollbars_to_end(self) -> None:
        self._vertical_scroll_animation.stop()
        self._source_scroll_animation.stop()
        vertical = self.translation_scroll.verticalScrollBar()
        vertical.setValue(vertical.maximum())
        horizontal = self.source_scroll.horizontalScrollBar()
        horizontal.setValue(horizontal.maximum())

    @staticmethod
    def _animate_scroll(
        animation: QPropertyAnimation,
        current: int,
        target: int,
    ) -> None:
        animation.stop()
        if current == target:
            return
        if abs(target - current) <= 12:
            target_object = animation.targetObject()
            set_value = getattr(target_object, "setValue", None)
            if callable(set_value):
                set_value(target)
                return
        animation.setStartValue(current)
        animation.setEndValue(target)
        animation.start()

    @staticmethod
    def _make_scroll_area_transparent(scroll_area: QScrollArea) -> None:
        scroll_area.setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground,
            True,
        )
        scroll_area.viewport().setAutoFillBackground(False)
        scroll_area.viewport().setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground,
            True,
        )

    def mousePressEvent(self, event) -> None:  # noqa: ANN001
        if event.button() != Qt.MouseButton.LeftButton:
            return
        edges = self._resize_edges_at(event.position().toPoint())
        handle = self.windowHandle()
        if edges and handle is not None and handle.startSystemResize(edges):
            event.accept()
            return
        if handle is not None and handle.startSystemMove():
            event.accept()
            return
        self._drag_position = (
            event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        )
        event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: ANN001
        if event.buttons() & Qt.MouseButton.LeftButton and self._drag_position is not None:
            self.move(event.globalPosition().toPoint() - self._drag_position)
            event.accept()
            return
        if event.buttons() == Qt.MouseButton.NoButton:
            self.setCursor(
                self._cursor_for_edges(
                    self._resize_edges_at(event.position().toPoint())
                )
            )

    def mouseReleaseEvent(self, event) -> None:  # noqa: ANN001
        self._drag_position = None
        event.accept()

    def enterEvent(self, event) -> None:  # noqa: ANN001
        self.resize_grip.show()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: ANN001
        self.resize_grip.hide()
        self.unsetCursor()
        super().leaveEvent(event)

    def showEvent(self, event) -> None:  # noqa: ANN001
        super().showEvent(event)
        self.visibility_changed.emit(True)
        self._schedule_layout_refresh()

    def hideEvent(self, event) -> None:  # noqa: ANN001
        super().hideEvent(event)
        self.visibility_changed.emit(False)

    def resizeEvent(self, event) -> None:  # noqa: ANN001
        super().resizeEvent(event)
        self._label_height_cache.clear()
        self.resize_grip.move(
            self.container.width() - self.resize_grip.width() - 5,
            self.container.height() - self.resize_grip.height() - 5,
        )
        self._schedule_layout_refresh()
        current_size = event.size()
        mode = next(
            (
                name
                for name, preset_size in self.SIZE_PRESETS.items()
                if preset_size == current_size
            ),
            "custom",
        )
        self.size_mode_changed.emit(mode)

    def eventFilter(self, watched, event) -> bool:  # noqa: ANN001
        if (
            event.type() == QEvent.Type.Resize
            and (
                watched is self.translation_scroll.viewport()
                or watched is self.source_scroll.viewport()
            )
        ):
            self._label_height_cache.clear()
            self._schedule_layout_refresh()
        return super().eventFilter(watched, event)

    def _resize_edges_at(self, position: QPoint) -> Qt.Edges:
        edges = Qt.Edge(0)
        if position.x() <= self._RESIZE_MARGIN:
            edges |= Qt.Edge.LeftEdge
        elif position.x() >= self.width() - self._RESIZE_MARGIN:
            edges |= Qt.Edge.RightEdge
        if position.y() <= self._RESIZE_MARGIN:
            edges |= Qt.Edge.TopEdge
        elif position.y() >= self.height() - self._RESIZE_MARGIN:
            edges |= Qt.Edge.BottomEdge
        return edges

    @staticmethod
    def _cursor_for_edges(edges: Qt.Edges) -> QCursor:
        if edges in {
            Qt.Edge.LeftEdge | Qt.Edge.TopEdge,
            Qt.Edge.RightEdge | Qt.Edge.BottomEdge,
        }:
            return QCursor(Qt.CursorShape.SizeFDiagCursor)
        if edges in {
            Qt.Edge.RightEdge | Qt.Edge.TopEdge,
            Qt.Edge.LeftEdge | Qt.Edge.BottomEdge,
        }:
            return QCursor(Qt.CursorShape.SizeBDiagCursor)
        if edges & (Qt.Edge.LeftEdge | Qt.Edge.RightEdge):
            return QCursor(Qt.CursorShape.SizeHorCursor)
        if edges & (Qt.Edge.TopEdge | Qt.Edge.BottomEdge):
            return QCursor(Qt.CursorShape.SizeVerCursor)
        return QCursor(Qt.CursorShape.ArrowCursor)


def _split_display_sentences(text: str) -> list[tuple[str, bool]]:
    sentences: list[tuple[str, bool]] = []
    for block in text.splitlines():
        normalized = normalize_chinese_caption_text(block)
        if not normalized:
            continue
        sentences.append((normalized, False))
    return sentences


def _wrapped_label_height(label: QLabel, width: int) -> int:
    metrics = label.fontMetrics()
    bounds = metrics.boundingRect(
        QRect(0, 0, max(1, width), 16_777_215),
        int(
            Qt.TextFlag.TextWordWrap
            | Qt.TextFlag.TextExpandTabs
            | Qt.AlignmentFlag.AlignLeft
        ),
        label.text(),
    )
    return max(metrics.height(), bounds.height() + 2)
