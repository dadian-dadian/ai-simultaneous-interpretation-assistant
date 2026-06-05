import unittest

from PySide6.QtWidgets import QApplication

from app.core.config import AppConfig
from app.core.recognition_profile import get_recognition_profile
from app.core.subtitle import SubtitleSegmentStatus
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

    def test_main_window_maps_recognition_mode_buttons(self) -> None:
        window = MainWindow(AppConfig())

        window.recognition_mode_buttons[2].setChecked(True)
        profile = window._selected_recognition_profile()

        self.assertEqual(profile.mode, "high-accuracy")
        self.assertEqual(profile.queue_size, 64)

    def test_main_window_shows_dropped_chunks_warning(self) -> None:
        window = MainWindow(AppConfig())
        window._active_recognition_profile = get_recognition_profile("balanced")

        window._handle_dropped_chunks_changed(8)

        self.assertEqual(window.dropped_chunks_label.text(), "丢帧：8")
        self.assertIn("识别处理可能跟不上", window.correction_hint_label.text())

    def test_main_window_advances_demo_stream_once(self) -> None:
        window = MainWindow(AppConfig())

        window._advance_demo_stream()
        window.demo_timer.stop()

        segment = window.subtitle_state.get("seg_001")
        self.assertIsNotNone(segment)
        assert segment is not None
        self.assertEqual(segment.status, SubtitleSegmentStatus.PARTIAL)
        self.assertIn("Transformer", window.translation_caption_label.text())
        self.assertEqual(window.history_list.count(), 1)


if __name__ == "__main__":
    unittest.main()
