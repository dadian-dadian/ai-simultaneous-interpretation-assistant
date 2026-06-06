import unittest

from PySide6.QtWidgets import QApplication

from app.ui.smooth_caption import SmoothCaptionLabel


def get_qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class SmoothCaptionLabelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = get_qapp()

    def test_same_text_does_not_trigger_an_update(self) -> None:
        label = SmoothCaptionLabel()
        label.set_caption_text("the current line")

        changed = label.set_caption_text("the current line")

        self.assertFalse(changed)

    def test_growing_line_updates_without_rollover_animation(self) -> None:
        label = SmoothCaptionLabel()
        label.set_caption_text("first line\ncurrent words", animate=False)

        label.set_caption_text("first line\ncurrent words continue")

        self.assertEqual(label.text(), "first line\ncurrent words continue")
        self.assertEqual(label._opacity_effect.opacity(), 1.0)
        self.assertEqual(label._rollover_count, 0)

    def test_line_rollover_triggers_one_short_animation(self) -> None:
        label = SmoothCaptionLabel()
        label.set_caption_text("previous phrase\ncurrent phrase", animate=False)

        label.set_caption_text("current phrase\nnew words")

        self.assertEqual(label._rollover_count, 1)


if __name__ == "__main__":
    unittest.main()
