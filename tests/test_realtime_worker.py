import unittest

import numpy as np

from app.asr import AsrError, AsrResult, AsrTextSegment
from app.asr.baidu import BaiduRealtimeTranscript
from app.audio.buffer import AudioRingBuffer
from app.audio.capture import AudioChunk
from app.core.asr_sentence import AsrSentenceMapper
from app.core.config import AppConfig
from app.core.recognition_profile import get_recognition_profile
from app.core.subtitle import SubtitleEventType
from app.ui.realtime_worker import RealtimeSubtitleWorker


class FakeStreamSession:
    def __init__(self, result: AsrResult | None = None, error: AsrError | None = None) -> None:
        self.result = result
        self.error = error
        self.closed = False
        self.finish_called = False

    def finish(self, duration_seconds: float) -> AsrResult:
        self.finish_called = True
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result

    def close(self) -> None:
        self.closed = True


class FakeRealtimeSession:
    def __init__(
        self,
        *,
        send_error: AsrError | None = None,
        transcripts: list[BaiduRealtimeTranscript] | None = None,
    ) -> None:
        self.send_error = send_error
        self.transcripts = transcripts or []
        self.closed = False
        self.sent_audio: list[AudioChunk] = []

    def send_audio(self, audio: AudioChunk) -> list[BaiduRealtimeTranscript]:
        self.sent_audio.append(audio)
        if self.send_error is not None:
            raise self.send_error
        return self.transcripts

    def close(self) -> None:
        self.closed = True


class FakeRealtimeClient:
    provider_name = "fake-streaming"

    def __init__(self, sessions: list[FakeRealtimeSession]) -> None:
        self.sessions = sessions

    def start_stream(self, *, language: str = "en", prompt: str = "") -> FakeRealtimeSession:
        del language, prompt
        return self.sessions.pop(0)


class RealtimeSubtitleWorkerTest(unittest.TestCase):
    def _buffer_with_audio(self) -> AudioRingBuffer:
        buffer = AudioRingBuffer(max_duration_seconds=2.0, sample_rate=16000)
        buffer.append(
            AudioChunk(
                samples=np.zeros((3200, 1), dtype=np.float32),
                sample_rate=16000,
            )
        )
        return buffer

    def test_finish_error_keeps_partial_unconfirmed_and_warns(self) -> None:
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
        mapper = AsrSentenceMapper("asr_0002")
        mapper.accept_transcripts(
            [BaiduRealtimeTranscript(text="some people do this exercise and", is_final=False)]
        )

        worker._finish_stream_segment(
            session,
            sentence_mapper=mapper,
            duration_seconds=2.0,
        )

        self.assertEqual(events, [])
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
            sentence_mapper=AsrSentenceMapper("asr_0003"),
            duration_seconds=0.3,
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
                segments=(AsrTextSegment("Final sentence.", 0.0, 1.0),),
            )
        )

        worker._finish_stream_segment(
            session,
            sentence_mapper=AsrSentenceMapper("asr_0001"),
            duration_seconds=1.0,
        )

        self.assertEqual(events[0].segment_id, "asr_0001_s0001")
        self.assertEqual(events[0].source_text, "Final sentence.")

    def test_rollover_stream_segment_does_not_promote_partial_to_final(self) -> None:
        worker = RealtimeSubtitleWorker(AppConfig())
        events = []
        worker.subtitle_event.connect(events.append)
        session = FakeStreamSession()
        mapper = AsrSentenceMapper("asr_0005")
        mapper.accept_transcripts(
            [BaiduRealtimeTranscript(text="this is a very long continuing thought")]
        )

        worker._rollover_stream_segment(session, sentence_mapper=mapper)

        self.assertTrue(session.closed)
        self.assertFalse(session.finish_called)
        self.assertEqual(events, [])

    def test_rollover_can_be_disabled_for_tests_or_fallback_modes(self) -> None:
        worker = RealtimeSubtitleWorker(
            AppConfig(),
            max_stream_duration_seconds=0,
        )

        self.assertFalse(worker._should_rollover_stream(100.0))

    def test_recognition_profiles_enable_stream_rollover_for_long_speech(self) -> None:
        profile = get_recognition_profile("balanced")
        worker = RealtimeSubtitleWorker(
            AppConfig(),
            max_stream_duration_seconds=profile.max_stream_duration_seconds,
        )

        self.assertGreater(profile.max_stream_duration_seconds, 0)
        self.assertTrue(
            worker._should_rollover_stream(profile.max_stream_duration_seconds)
        )

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
            sentence_mapper=AsrSentenceMapper("asr_0004"),
            duration_seconds=1.0,
        )

        self.assertEqual(events, [])
        self.assertEqual(len(warnings), 1)

    def test_streaming_fin_text_is_emitted_as_sentence_final(self) -> None:
        worker = RealtimeSubtitleWorker(AppConfig())
        events = []
        worker.subtitle_event.connect(events.append)
        mapper = AsrSentenceMapper("asr_0001")

        worker._emit_transcripts(
            mapper,
            [
                BaiduRealtimeTranscript(text="I love", is_final=False),
                BaiduRealtimeTranscript(text="I love that job.", is_final=True),
                BaiduRealtimeTranscript(text="And I", is_final=False),
            ],
        )

        self.assertEqual(
            [(event.type, event.segment_id, event.source_text) for event in events],
            [
                (SubtitleEventType.PARTIAL, "asr_0001_s0001", "I love"),
                (SubtitleEventType.FINAL, "asr_0001_s0001", "I love that job."),
                (SubtitleEventType.PARTIAL, "asr_0001_s0002", "And I"),
            ],
        )

    def test_stream_start_send_failure_closes_session_and_warns(self) -> None:
        worker = RealtimeSubtitleWorker(AppConfig())
        warnings = []
        worker.warning_occurred.connect(warnings.append)
        bad_session = FakeRealtimeSession(send_error=AsrError("socket is already closed"))
        client = FakeRealtimeClient([bad_session])

        session, duration = worker._try_start_stream_segment(
            client,
            self._buffer_with_audio(),
            sentence_mapper=AsrSentenceMapper("asr_0001"),
            preroll_seconds=0.32,
            warning_prefix="实时 ASR 连接启动失败",
        )

        self.assertIsNone(session)
        self.assertEqual(duration, 0.0)
        self.assertTrue(bad_session.closed)
        self.assertEqual(len(warnings), 1)

    def test_stream_restart_can_emit_preroll_transcripts_after_send_failure(
        self,
    ) -> None:
        worker = RealtimeSubtitleWorker(AppConfig())
        events = []
        warnings = []
        worker.subtitle_event.connect(events.append)
        worker.warning_occurred.connect(warnings.append)
        good_session = FakeRealtimeSession(
            transcripts=[
                BaiduRealtimeTranscript(text="reconnected stream", is_final=False)
            ]
        )
        client = FakeRealtimeClient([good_session])

        session, duration = worker._try_start_stream_segment(
            client,
            self._buffer_with_audio(),
            sentence_mapper=AsrSentenceMapper("asr_0001"),
            preroll_seconds=0.32,
            warning_prefix="实时 ASR 连接已断开，已尝试自动重连",
            cause=AsrError("socket is already closed"),
        )

        self.assertIs(session, good_session)
        self.assertGreater(duration, 0)
        self.assertEqual(warnings, [])
        self.assertEqual(events[0].source_text, "reconnected stream")


if __name__ == "__main__":
    unittest.main()
