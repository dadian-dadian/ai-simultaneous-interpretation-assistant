import unittest

from app.core.subtitle import (
    SubtitleEvent,
    SubtitleEventType,
    SubtitleSegmentStatus,
    SubtitleState,
)


class SubtitleEventTest(unittest.TestCase):
    def test_event_can_round_trip_through_dict(self) -> None:
        event = SubtitleEvent.update(
            segment_id="seg_001",
            source_text="AI agents can use tools.",
            zh_text="AI 智能体可以使用工具。",
            old_zh_text="AI 代理可以使用工具。",
            reason="terminology_consistency",
        )

        parsed = SubtitleEvent.from_dict(event.to_dict())

        self.assertEqual(parsed.type, SubtitleEventType.UPDATE)
        self.assertEqual(parsed.segment_id, "seg_001")
        self.assertEqual(parsed.zh_text, "AI 智能体可以使用工具。")
        self.assertEqual(parsed.old_zh_text, "AI 代理可以使用工具。")
        self.assertEqual(parsed.reason, "terminology_consistency")


class SubtitleStateTest(unittest.TestCase):
    def test_partial_event_creates_segment(self) -> None:
        state = SubtitleState()

        segment = state.apply(
            SubtitleEvent.partial(
                segment_id="seg_001",
                source_text="The model uses attention",
                zh_text="这个模型使用注意力……",
            )
        )

        self.assertEqual(segment.segment_id, "seg_001")
        self.assertEqual(segment.status, SubtitleSegmentStatus.PARTIAL)
        self.assertEqual(segment.version, 1)

    def test_final_event_confirms_existing_segment(self) -> None:
        state = SubtitleState()
        state.apply(SubtitleEvent.partial("seg_001", "The model uses", "这个模型使用……"))

        segment = state.apply(
            SubtitleEvent.final(
                segment_id="seg_001",
                source_text="The model uses attention to align tokens.",
                zh_text="该模型使用注意力机制对齐 token。",
            )
        )

        self.assertEqual(segment.status, SubtitleSegmentStatus.FINAL)
        self.assertEqual(segment.source_text, "The model uses attention to align tokens.")
        self.assertEqual(segment.zh_text, "该模型使用注意力机制对齐 token。")
        self.assertEqual(segment.version, 2)

    def test_update_event_rewrites_existing_segment(self) -> None:
        state = SubtitleState()
        state.apply(
            SubtitleEvent.final(
                segment_id="seg_001",
                source_text="I study AI agents.",
                zh_text="我研究 AI 代理。",
            )
        )

        segment = state.apply(
            SubtitleEvent.update(
                segment_id="seg_001",
                source_text="I study AI agents that can use tools.",
                zh_text="我研究能够使用工具的 AI 智能体。",
                reason="context_correction",
            )
        )

        self.assertEqual(segment.status, SubtitleSegmentStatus.UPDATED)
        self.assertEqual(segment.zh_text, "我研究能够使用工具的 AI 智能体。")
        self.assertEqual(segment.revisions[0].old_zh_text, "我研究 AI 代理。")
        self.assertEqual(segment.revisions[0].reason, "context_correction")

    def test_update_unknown_segment_raises_error(self) -> None:
        state = SubtitleState()

        with self.assertRaises(KeyError):
            state.apply(
                SubtitleEvent.update(
                    segment_id="missing",
                    source_text="hello",
                    zh_text="你好",
                    reason="context_correction",
                )
            )

    def test_late_partial_does_not_overwrite_confirmed_segment(self) -> None:
        state = SubtitleState()
        state.apply(SubtitleEvent.final("seg_001", "finished", "已确认"))

        segment = state.apply(SubtitleEvent.partial("seg_001", "unfinished", "未确认……"))

        self.assertEqual(segment.status, SubtitleSegmentStatus.FINAL)
        self.assertEqual(segment.source_text, "finished")
        self.assertEqual(segment.zh_text, "已确认")

    def test_state_trims_old_segments(self) -> None:
        state = SubtitleState(max_segments=2)

        state.apply(SubtitleEvent.final("seg_001", "one", "一"))
        state.apply(SubtitleEvent.final("seg_002", "two", "二"))
        state.apply(SubtitleEvent.final("seg_003", "three", "三"))

        self.assertIsNone(state.get("seg_001"))
        self.assertEqual([segment.segment_id for segment in state.segments()], ["seg_002", "seg_003"])

    def test_recent_returns_latest_segments(self) -> None:
        state = SubtitleState()

        state.apply(SubtitleEvent.final("seg_001", "one", "一"))
        state.apply(SubtitleEvent.final("seg_002", "two", "二"))
        state.apply(SubtitleEvent.final("seg_003", "three", "三"))

        self.assertEqual([segment.segment_id for segment in state.recent(2)], ["seg_002", "seg_003"])


if __name__ == "__main__":
    unittest.main()
