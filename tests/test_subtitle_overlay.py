import unittest

from PySide6.QtWidgets import QApplication

from app.core.config import AppConfig
from app.ui.main_window import MainWindow
from app.ui.subtitle_overlay import SubtitleOverlayWindow


def get_qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class SubtitleOverlayWindowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = get_qapp()

    def test_caption_text_can_be_updated(self) -> None:
        overlay = SubtitleOverlayWindow()

        overlay.set_caption("hello", "你好", "updated")

        self.assertEqual(overlay.source_label.text(), "hello")
        self.assertEqual(overlay.translation_label.text(), "你好")
        self.assertEqual(overlay.state_badge.text(), "已修正")

    def test_display_mode_controls_visible_labels(self) -> None:
        overlay = SubtitleOverlayWindow()

        overlay.set_display_mode("zh")
        self.assertFalse(overlay.translation_label.isHidden())
        self.assertTrue(overlay.source_label.isHidden())

        overlay.set_display_mode("source")
        self.assertTrue(overlay.translation_label.isHidden())
        self.assertFalse(overlay.source_label.isHidden())

    def test_opacity_is_clamped(self) -> None:
        overlay = SubtitleOverlayWindow()

        overlay.set_opacity_percent(10)
        self.assertEqual(overlay.windowOpacity(), 0.4)

        overlay.set_opacity_percent(120)
        self.assertEqual(overlay.windowOpacity(), 1.0)


class MainWindowOverlayIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = get_qapp()

    def test_main_window_creates_overlay_window(self) -> None:
        window = MainWindow(AppConfig())

        self.assertIsInstance(window.overlay, SubtitleOverlayWindow)
        self.assertFalse(window.overlay.isVisible())

        window._show_overlay()
        self.assertTrue(window.overlay.isVisible())

        window._hide_overlay()
        self.assertFalse(window.overlay.isVisible())


if __name__ == "__main__":
    unittest.main()
