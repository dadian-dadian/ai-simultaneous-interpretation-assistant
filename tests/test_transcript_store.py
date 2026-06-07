import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from app.core.subtitle import SubtitleSegment
from app.core.transcript_session import (
    TranscriptSession,
    TranscriptSessionStatus,
)
from app.storage import TranscriptPersistence, TranscriptStore


class TranscriptStoreTest(unittest.TestCase):
    def test_store_saves_loads_and_sorts_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = TranscriptStore(Path(tmp_dir))
            older = _create_session("older", hour=8)
            newer = _create_session("newer", hour=9)
            older.finish()
            newer.finish()

            store.save_session(older)
            store.save_session(newer)

            self.assertEqual(store.load_session("older"), older)
            self.assertEqual(
                [session.session_id for session in store.list_sessions()],
                ["newer", "older"],
            )

    def test_running_sessions_are_recovered_as_interrupted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = TranscriptStore(Path(tmp_dir))
            running = _create_session("running", hour=9)
            store.save_session(running)

            recovered_count = store.recover_interrupted_sessions()
            recovered = store.load_session("running")

            self.assertEqual(recovered_count, 1)
            self.assertIsNotNone(recovered)
            assert recovered is not None
            self.assertEqual(recovered.status, TranscriptSessionStatus.INTERRUPTED)
            self.assertTrue(recovered.ended_at)

    def test_background_persistence_flushes_latest_coalesced_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = TranscriptStore(Path(tmp_dir))
            persistence = TranscriptPersistence(store, coalesce_seconds=2.0)
            session = _create_session("live", hour=9)

            for version in range(1, 20):
                session.upsert_segment(
                    SubtitleSegment(
                        segment_id="asr_0001",
                        source_text=f"growing source {version}",
                        version=version,
                    )
                )
                persistence.schedule(session)

            self.assertTrue(persistence.flush())
            restored = store.load_session("live")
            self.assertIsNotNone(restored)
            assert restored is not None
            self.assertEqual(
                restored.segments[0].source_text,
                "growing source 19",
            )
            self.assertIsNone(persistence.last_error)
            self.assertTrue(persistence.close())

    def test_schedule_defers_full_serialization_to_background_writer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = TranscriptStore(Path(tmp_dir))
            persistence = TranscriptPersistence(store, coalesce_seconds=60.0)
            session = _create_session("deferred", hour=9)
            session.upsert_segment(
                SubtitleSegment(
                    segment_id="asr_0001",
                    source_text="live partial",
                    version=1,
                )
            )

            with patch.object(
                session,
                "to_dict",
                wraps=session.to_dict,
            ) as to_dict:
                persistence.schedule(session)
                self.assertEqual(to_dict.call_count, 0)
                self.assertTrue(persistence.flush())
                self.assertEqual(to_dict.call_count, 1)

            self.assertTrue(persistence.close())

    def test_background_persistence_reports_write_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            invalid_root = Path(tmp_dir) / "not-a-directory"
            invalid_root.write_text("occupied", encoding="utf-8")
            persistence = TranscriptPersistence(
                TranscriptStore(invalid_root),
                coalesce_seconds=0.0,
            )

            persistence.schedule(
                _create_session("write-error", hour=9),
                urgent=True,
            )

            self.assertTrue(persistence.flush())
            self.assertIsNotNone(persistence.last_error)
            self.assertTrue(persistence.close())


def _create_session(session_id: str, *, hour: int) -> TranscriptSession:
    return TranscriptSession.create(
        session_id=session_id,
        started_at=datetime(2026, 6, 7, hour, tzinfo=UTC),
        asr_provider="baidu-realtime",
        translation_provider="baidu-mt",
        source_language="en",
        target_language="zh-CN",
        recognition_mode="balanced",
    )


if __name__ == "__main__":
    unittest.main()
