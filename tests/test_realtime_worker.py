import unittest

from app.asr import AsrError, AsrResult
from app.core.config import AppConfig
from app.core.subtitle import SubtitleEventType
from app.ui.realtime_worker import RealtimeSubtitleWorker


class FakeStreamSession:
    def __init__(self, result: AsrResult | None = None, error: AsrError | None = None) -> None:
        self.result = result
        self.error = error
        self.closed = False

    def finish(self, duration_seconds: float) -> AsrResult:
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result

    def close(self) -> None:
        self.closed = True


class RealtimeSubtitleWorkerTest(unittest.TestCase):
    def test_finish_error_keeps_partial_as_final_and_warns(self) -> None:
        worker = RealtimeSubtitleWorker(AppConfig())
        events = []
        warnings = []
        worker.subtitle_event.connect(events.append)
        worker.warning_occurred.connect(warnings.append)
        session = FakeStreamSession(
            error=AsrError(
                "百度实时 ASR 识别失败：err_no=-3005，"
                "asr server not find effective speech[info:-4]"
            )
        )

        worker._finish_stream_segment(
            session,
            segment_id="asr_0002",
            duration_seconds=2.0,
            fallback_text="some people do this exercise and",
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].type, SubtitleEventType.FINAL)
        self.assertEqual(events[0].source_text, "some people do this exercise and")
        self.assertEqual(len(warnings), 1)

    def test_finish_error_without_partial_closes_session_and_warns(self) -> None:
        worker = RealtimeSubtitleWorker(AppConfig())
        events = []
        warnings = []
        worker.subtitle_event.connect(events.append)
        worker.warning_occurred.connect(warnings.append)
        session = FakeStreamSession(error=AsrError("temporary failure"))

        worker._finish_stream_segment(
            session,
            segment_id="asr_0003",
            duration_seconds=0.3,
            fallback_text="",
        )

        self.assertEqual(events, [])
        self.assertTrue(session.closed)
        self.assertEqual(len(warnings), 1)

    def test_successful_finish_prefers_final_result(self) -> None:
        worker = RealtimeSubtitleWorker(AppConfig())
        events = []
        worker.subtitle_event.connect(events.append)
        session = FakeStreamSession(
            result=AsrResult(
                text="Final sentence.",
                language="en",
                provider="fake",
                duration_seconds=1.0,
            )
        )

        worker._finish_stream_segment(
            session,
            segment_id="asr_0001",
            duration_seconds=1.0,
            fallback_text="final sentence",
        )

        self.assertEqual(events[0].source_text, "Final sentence.")

    def test_empty_successful_finish_is_skipped(self) -> None:
        worker = RealtimeSubtitleWorker(AppConfig())
        events = []
        warnings = []
        worker.subtitle_event.connect(events.append)
        worker.warning_occurred.connect(warnings.append)
        session = FakeStreamSession(
            result=AsrResult(
                text="",
                language="en",
                provider="fake",
                duration_seconds=1.0,
            )
        )

        worker._finish_stream_segment(
            session,
            segment_id="asr_0004",
            duration_seconds=1.0,
            fallback_text="",
        )

        self.assertEqual(events, [])
        self.assertEqual(len(warnings), 1)


if __name__ == "__main__":
    unittest.main()
