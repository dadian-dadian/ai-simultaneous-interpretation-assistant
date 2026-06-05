import unittest

from app.core.recognition_profile import (
    get_recognition_profile,
    recognition_mode_from_index,
)


class RecognitionProfileTest(unittest.TestCase):
    def test_balanced_profile_uses_default_stability_params(self) -> None:
        profile = get_recognition_profile("balanced")

        self.assertEqual(profile.label, "均衡")
        self.assertEqual(profile.min_silence_ms, 800)
        self.assertEqual(profile.preroll_seconds, 0.8)
        self.assertEqual(profile.queue_size, 32)

    def test_low_latency_profile_is_more_aggressive(self) -> None:
        profile = get_recognition_profile("low-latency")

        self.assertEqual(profile.min_silence_ms, 500)
        self.assertEqual(profile.preroll_seconds, 0.6)
        self.assertEqual(profile.queue_size, 32)

    def test_high_accuracy_profile_uses_larger_queue(self) -> None:
        profile = get_recognition_profile("high-accuracy")

        self.assertEqual(profile.min_silence_ms, 1100)
        self.assertEqual(profile.preroll_seconds, 1.0)
        self.assertEqual(profile.queue_size, 64)

    def test_recognition_mode_from_index_maps_ui_buttons(self) -> None:
        self.assertEqual(recognition_mode_from_index(0), "low-latency")
        self.assertEqual(recognition_mode_from_index(1), "balanced")
        self.assertEqual(recognition_mode_from_index(2), "high-accuracy")

    def test_unknown_mode_raises_clear_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "不支持的识别模式"):
            get_recognition_profile("unknown")


if __name__ == "__main__":
    unittest.main()
