import unittest

from app.core.demo_stream import build_default_demo_script
from app.core.subtitle import SubtitleEventType


class DemoSubtitleScriptTest(unittest.TestCase):
    def test_default_script_contains_streaming_and_update_events(self) -> None:
        script = build_default_demo_script()
        event_types = [step.event.type for step in script.steps]

        self.assertIn(SubtitleEventType.PARTIAL, event_types)
        self.assertIn(SubtitleEventType.FINAL, event_types)
        self.assertIn(SubtitleEventType.UPDATE, event_types)
        self.assertTrue(script.contains_update())

    def test_update_events_target_existing_segments(self) -> None:
        script = build_default_demo_script()
        seen_segment_ids: set[str] = set()

        for step in script.steps:
            if step.event.type == SubtitleEventType.UPDATE:
                self.assertIn(step.event.segment_id, seen_segment_ids)
            else:
                seen_segment_ids.add(step.event.segment_id)

    def test_step_delays_are_positive(self) -> None:
        script = build_default_demo_script()

        self.assertTrue(all(step.delay_ms > 0 for step in script.steps))


if __name__ == "__main__":
    unittest.main()

