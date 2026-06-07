import unittest

from app.translate.incremental import IncrementalTranslationPlanner


class IncrementalTranslationPlannerTest(unittest.TestCase):
    def test_default_first_request_uses_four_stable_words(self) -> None:
        planner = IncrementalTranslationPlanner()
        planner.observe_partial(
            segment_id="segment",
            source_version=1,
            source_text="this morning I want",
            observed_at=1.0,
        )

        plan = planner.observe_partial(
            segment_id="segment",
            source_version=2,
            source_text="this morning I want to",
            observed_at=1.2,
        )

        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.source_text, "this morning I want")

    def test_waits_for_stable_prefix_before_first_request(self) -> None:
        planner = IncrementalTranslationPlanner(
            initial_words=4,
            initial_unstable_tail_words=1,
            unstable_tail_words=1,
        )

        first = planner.observe_partial(
            segment_id="asr_0001_s0001",
            source_version=1,
            source_text="one two three four",
            observed_at=1.0,
        )
        second = planner.observe_partial(
            segment_id="asr_0001_s0001",
            source_version=2,
            source_text="one two three four five six",
            observed_at=1.2,
        )

        self.assertIsNone(first)
        self.assertIsNone(second)

        plan = planner.observe_partial(
            segment_id="asr_0001_s0001",
            source_version=3,
            source_text="one two three four five six seven",
            observed_at=1.4,
        )

        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.source_text, "one two three four five")

    def test_mid_burst_is_rate_limited_even_when_text_keeps_growing(self) -> None:
        planner = IncrementalTranslationPlanner(
            initial_words=3,
            min_growth_words=2,
            unstable_tail_words=0,
            min_interval_seconds=1.0,
            max_interval_seconds=2.0,
        )
        planner.observe_partial(
            segment_id="segment",
            source_version=1,
            source_text="one two three",
            observed_at=0.0,
        )
        first = planner.observe_partial(
            segment_id="segment",
            source_version=2,
            source_text="one two three four",
            observed_at=0.2,
        )
        blocked = planner.observe_partial(
            segment_id="segment",
            source_version=3,
            source_text="one two three four five six",
            observed_at=0.6,
        )
        next_plan = planner.observe_partial(
            segment_id="segment",
            source_version=4,
            source_text="one two three four five six seven",
            observed_at=1.3,
        )

        self.assertIsNotNone(first)
        self.assertIsNone(blocked)
        self.assertIsNotNone(next_plan)

    def test_unstable_tail_revision_is_not_submitted(self) -> None:
        planner = IncrementalTranslationPlanner(
            initial_words=3,
            initial_unstable_tail_words=1,
            unstable_tail_words=1,
        )
        planner.observe_partial(
            segment_id="segment",
            source_version=1,
            source_text="we build a reliable soft",
            observed_at=0.0,
        )
        plan = planner.observe_partial(
            segment_id="segment",
            source_version=2,
            source_text="we build a reliable software",
            observed_at=0.2,
        )

        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.source_text, "we build a")

    def test_final_always_uses_full_source_and_resets_partial_state(self) -> None:
        planner = IncrementalTranslationPlanner(initial_words=2, unstable_tail_words=0)
        planner.observe_partial(
            segment_id="segment",
            source_version=1,
            source_text="one two",
            observed_at=0.0,
        )
        planner.observe_partial(
            segment_id="segment",
            source_version=2,
            source_text="one two three",
            observed_at=0.2,
        )

        final = planner.observe_final(
            segment_id="segment",
            source_version=3,
            source_text="One two three.",
        )

        self.assertIsNotNone(final)
        assert final is not None
        self.assertTrue(final.is_final)
        self.assertEqual(final.source_text, "One two three.")


if __name__ == "__main__":
    unittest.main()
