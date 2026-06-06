import unittest

from app.core.live_caption import LiveCaptionComposer


class LiveCaptionComposerTest(unittest.TestCase):
    def test_current_phrase_grows_from_its_beginning(self) -> None:
        composer = LiveCaptionComposer()
        words = (
            "today we're testing a real-time English subtitle system while the speaker "
            "moves quickly from one idea to the next"
        ).split()

        frame = None
        for index in range(1, len(words) + 1):
            frame = composer.compose_partial(
                "asr_0001",
                " ".join(words[:index]),
                observed_at=index * 0.16,
            )

        assert frame is not None
        self.assertEqual(len(frame.lines), 1)
        self.assertTrue(frame.active_text.startswith("today we're testing"))
        self.assertTrue(frame.active_text.endswith("to the next"))

    def test_long_partial_keeps_one_stable_phrase_and_the_current_phrase(self) -> None:
        composer = LiveCaptionComposer(max_phrase_words=12, stable_tail_words=2)
        words = (
            "today we're testing a real-time English subtitle system the speaker is talking "
            "quickly moving from one idea to the next and leaving only short pauses"
        ).split()

        frame = composer.compose_partial(
            "asr_0001",
            " ".join(words),
            observed_at=1.0,
        )

        self.assertEqual(len(frame.lines), 2)
        self.assertTrue(frame.stable_text.startswith("today we're testing"))
        self.assertTrue(frame.active_text.endswith("only short pauses"))

    def test_soft_pause_preserves_the_complete_previous_phrase(self) -> None:
        composer = LiveCaptionComposer()

        composer.compose_partial(
            "asr_0001",
            "today we're testing a real-time English subtitle system",
            observed_at=2.4,
        )
        frame = composer.compose_partial(
            "asr_0001",
            "today we're testing a real-time English subtitle system the next",
            observed_at=3.2,
        )

        self.assertEqual(
            frame.stable_text,
            "today we're testing a real-time English subtitle system",
        )
        self.assertEqual(frame.active_text, "the next")

    def test_one_new_word_after_pause_does_not_flash_as_an_orphan(self) -> None:
        composer = LiveCaptionComposer()
        composer.compose_partial(
            "asr_0001",
            "first the application captures system audio",
            observed_at=4.0,
        )

        frame = composer.compose_partial(
            "asr_0001",
            "first the application captures system audio next",
            observed_at=4.8,
        )

        self.assertEqual(
            frame.lines,
            ("first the application captures system audio",),
        )

    def test_current_phrase_does_not_drop_the_latest_word(self) -> None:
        composer = LiveCaptionComposer()

        first_frame = composer.compose_partial(
            "asr_0001",
            "sentence boundaries",
            observed_at=1.0,
        )
        second_frame = composer.compose_partial(
            "asr_0001",
            "sentence boundaries arrive",
            observed_at=1.2,
        )

        self.assertEqual(first_frame.text, "sentence boundaries")
        self.assertEqual(second_frame.text, "sentence boundaries arrive")

    def test_revision_rolls_back_an_inferred_boundary(self) -> None:
        composer = LiveCaptionComposer()
        composer.compose_partial(
            "asr_0001",
            "we test the live subtitle output every single day",
            observed_at=1.0,
        )
        composer.compose_partial(
            "asr_0001",
            "we test the live subtitle output every single day next idea",
            observed_at=1.8,
        )

        frame = composer.compose_partial(
            "asr_0001",
            "we tested the live subtitle output every single day next idea",
            observed_at=2.0,
        )

        self.assertIn("we tested", frame.text)
        self.assertNotIn("we test ", frame.text)

    def test_final_text_uses_the_latest_two_complete_sentences(self) -> None:
        composer = LiveCaptionComposer()

        frame = composer.compose_final(
            "asr_0001",
            "First, the application captures system audio. "
            "Next, it detects speech. Finally, it sends the sound.",
        )

        self.assertTrue(frame.is_final)
        self.assertEqual(frame.stable_text, "Next, it detects speech.")
        self.assertEqual(frame.active_text, "Finally, it sends the sound.")
        self.assertNotIn("First,", frame.text)

    def test_final_text_recovers_a_missing_space_after_sentence_punctuation(self) -> None:
        composer = LiveCaptionComposer()

        frame = composer.compose_final(
            "asr_0001",
            "We moved unstable words to the end of the display."
            "This made the live caption easier to follow. "
            "The final sentence remains visible.",
        )

        self.assertEqual(
            frame.stable_text,
            "This made the live caption easier to follow.",
        )
        self.assertEqual(frame.active_text, "The final sentence remains visible.")

    def test_new_segment_resets_visible_context(self) -> None:
        composer = LiveCaptionComposer()
        composer.compose_partial("asr_0001", "old segment words stay behind", observed_at=1.0)

        frame = composer.compose_partial("asr_0002", "new sentence", observed_at=2.0)

        self.assertEqual(frame.text, "new sentence")


if __name__ == "__main__":
    unittest.main()
