from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation
from PySide6.QtWidgets import QGraphicsOpacityEffect, QLabel


class SmoothCaptionLabel(QLabel):
    """Update growing captions directly and animate only full-line rollovers."""

    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        super().__init__(*args, **kwargs)
        self._opacity_effect = QGraphicsOpacityEffect(self)
        self._opacity_effect.setOpacity(1.0)
        self.setGraphicsEffect(self._opacity_effect)

        self._rollover_animation = QPropertyAnimation(
            self._opacity_effect,
            b"opacity",
            self,
        )
        self._rollover_animation.setDuration(90)
        self._rollover_animation.setStartValue(0.94)
        self._rollover_animation.setEndValue(1.0)
        self._rollover_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._rollover_count = 0

    def set_caption_text(self, text: str, *, animate: bool = True) -> bool:
        if text == self.text():
            return False

        old_lines = tuple(self.text().splitlines())
        new_lines = tuple(text.splitlines())
        should_animate = animate and _is_line_rollover(old_lines, new_lines)

        self.setText(text)
        if should_animate:
            self._rollover_count += 1
            self._rollover_animation.stop()
            self._opacity_effect.setOpacity(0.94)
            self._rollover_animation.start()
        elif not animate:
            self._rollover_animation.stop()
            self._opacity_effect.setOpacity(1.0)
        elif self._rollover_animation.state() != QPropertyAnimation.State.Running:
            self._opacity_effect.setOpacity(1.0)
        return True


def _is_line_rollover(old_lines: tuple[str, ...], new_lines: tuple[str, ...]) -> bool:
    if len(old_lines) < 2 or len(new_lines) < 2:
        return False
    if old_lines == new_lines:
        return False
    if new_lines[0].startswith(old_lines[0]) or old_lines[0].startswith(new_lines[0]):
        return False
    return True
