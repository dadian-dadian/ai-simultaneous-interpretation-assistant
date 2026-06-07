import unittest
from datetime import UTC, datetime

from app.core.subtitle import SubtitleSegment, SubtitleSegmentStatus
from app.core.transcript_session import (
    TranscriptSession,
    TranscriptSessionStatus,
)


class TranscriptSessionTest(unittest.TestCase):
    def test_session_keeps_all_segments_independently_from_subtitle_state_limit(
        self,
    ) -> None:
        session = _create_session()

        for index in range(120):
            session.upsert_segment(
                SubtitleSegment(
                    segment_id=f"asr_{index:04d}",
                    source_text=f"source {index}",
                    status=SubtitleSegmentStatus.FINAL,
                    version=1,
                )
            )

        self.assertEqual(len(session.segments), 120)
        self.assertEqual(session.segments[0].source_text, "source 0")
        self.assertEqual(session.segments[-1].source_text, "source 119")

    def test_upsert_replaces_segment_without_changing_order(self) -> None:
        session = _create_session()
        session.upsert_segment(
            SubtitleSegment(segment_id="asr_0001", source_text="first", version=1)
        )
        session.upsert_segment(
            SubtitleSegment(segment_id="asr_0002", source_text="second", version=1)
        )

        session.upsert_segment(
            SubtitleSegment(
                segment_id="asr_0001",
                source_text="first final",
                zh_text="第一句",
                status=SubtitleSegmentStatus.FINAL,
                version=2,
            )
        )

        self.assertEqual(
            [segment.segment_id for segment in session.segments],
            ["asr_0001", "asr_0002"],
        )
        self.assertEqual(session.segments[0].zh_text, "第一句")
        self.assertEqual(session.translated_segment_count, 1)

    def test_session_round_trips_through_dict(self) -> None:
        session = _create_session()
        session.upsert_segment(
            SubtitleSegment(
                segment_id="asr_0001",
                source_text="Hello.",
                zh_text="你好。",
                translation_source_text="Hello.",
                status=SubtitleSegmentStatus.FINAL,
                version=3,
            )
        )
        session.finish(
            TranscriptSessionStatus.STOPPED,
            ended_at=datetime(2026, 6, 7, 9, 1, tzinfo=UTC),
        )

        restored = TranscriptSession.from_dict(session.to_dict())

        self.assertEqual(restored, session)
        self.assertEqual(restored.segments[0].to_subtitle_segment().zh_text, "你好。")
        self.assertEqual(restored.duration_seconds, 60.0)

    def test_pause_and_resume_keep_session_open(self) -> None:
        session = _create_session()

        session.pause()
        self.assertEqual(session.status, TranscriptSessionStatus.PAUSED)
        self.assertTrue(session.is_open)

        session.resume()
        self.assertEqual(session.status, TranscriptSessionStatus.RUNNING)
        self.assertTrue(session.is_open)


def _create_session() -> TranscriptSession:
    return TranscriptSession.create(
        session_id="session-1",
        started_at=datetime(2026, 6, 7, 9, 0, tzinfo=UTC),
        asr_provider="baidu-realtime",
        translation_provider="baidu-mt",
        source_language="en",
        target_language="zh-CN",
        recognition_mode="balanced",
    )


if __name__ == "__main__":
    unittest.main()
