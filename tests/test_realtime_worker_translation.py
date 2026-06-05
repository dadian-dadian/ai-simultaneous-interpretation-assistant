import unittest
from collections.abc import Iterator
from concurrent.futures import Future

from app.core.config import AppConfig
from app.core.subtitle import SubtitleEventType
from app.translate import TranslationRequest, TranslationResult
from app.ui.realtime_worker import TRANSLATING_TEXT, RealtimeSubtitleWorker


class FakeStreamingTranslator:
    provider_name = "fake"

    def __init__(self, chunks: list[str]) -> None:
        self.chunks = chunks
        self.requests: list[TranslationRequest] = []

    def translate(self, request: TranslationRequest) -> TranslationResult:
        self.requests.append(request)
        return TranslationResult(
            text="".join(self.chunks),
            provider=self.provider_name,
            model="fake-model",
            source_language=request.source_language,
            target_language=request.target_language,
        )

    def stream_translate(self, request: TranslationRequest) -> Iterator[str]:
        self.requests.append(request)
        yield from self.chunks


class RealtimeWorkerTranslationTest(unittest.TestCase):
    def test_final_translation_result_updates_final_segment(self) -> None:
        worker = RealtimeSubtitleWorker(AppConfig(translation_api_key="translation-key"))
        events = []
        worker.subtitle_event.connect(events.append)
        worker._reset_translation_state()

        current_zh, _context = worker._finalize_segment("asr_0001", "hello world")
        future: Future[str] = Future()
        future.set_result("你好，世界")

        worker._handle_final_translation_result(
            segment_id="asr_0001",
            source_text="hello world",
            old_zh_text=current_zh,
            future=future,
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].type, SubtitleEventType.UPDATE)
        self.assertEqual(events[0].zh_text, "你好，世界")
        self.assertEqual(events[0].reason, "translation_final")

    def test_stale_partial_translation_is_discarded(self) -> None:
        worker = RealtimeSubtitleWorker(AppConfig(translation_api_key="translation-key"))
        events = []
        worker.subtitle_event.connect(events.append)
        worker._reset_translation_state()
        worker._remember_partial_source("asr_0001", "newer source text")
        future: Future[str] = Future()
        future.set_result("旧译文")

        worker._handle_partial_translation_result(
            segment_id="asr_0001",
            source_text="old source text",
            future=future,
        )

        self.assertEqual(events, [])

    def test_partial_translation_for_prefix_updates_latest_source(self) -> None:
        worker = RealtimeSubtitleWorker(AppConfig(translation_api_key="translation-key"))
        events = []
        worker.subtitle_event.connect(events.append)
        worker._reset_translation_state()
        worker._remember_partial_source(
            "asr_0001",
            "today we are testing a real time subtitle translator",
        )
        future: Future[str] = Future()
        future.set_result("今天我们正在测试")

        worker._handle_partial_translation_result(
            segment_id="asr_0001",
            source_text="today we are testing",
            future=future,
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].type, SubtitleEventType.PARTIAL)
        self.assertEqual(
            events[0].source_text,
            "today we are testing a real time subtitle translator",
        )
        self.assertEqual(events[0].zh_text, "今天我们正在测试")

    def test_partial_source_uses_translating_placeholder_before_first_translation(self) -> None:
        worker = RealtimeSubtitleWorker(AppConfig(translation_api_key="translation-key"))
        worker._reset_translation_state()

        zh_text = worker._remember_partial_source("asr_0001", "hello world")

        self.assertEqual(zh_text, TRANSLATING_TEXT)

    def test_stream_partial_translation_emits_each_translation_delta(self) -> None:
        worker = RealtimeSubtitleWorker(AppConfig(translation_api_key="translation-key"))
        worker._translator = FakeStreamingTranslator(["今天", "我们正在测试"])
        events = []
        worker.subtitle_event.connect(events.append)
        worker._reset_translation_state()
        worker._remember_partial_source(
            "asr_0001",
            "today we are testing a real time subtitle translator",
        )
        worker._partial_translation_versions["asr_0001"] = 1

        worker._stream_partial_translation(
            segment_id="asr_0001",
            source_text="today we are testing",
            context=(),
            version=1,
        )

        self.assertEqual(len(events), 2)
        self.assertTrue(all(event.type == SubtitleEventType.PARTIAL for event in events))
        self.assertEqual(
            events[0].source_text,
            "today we are testing a real time subtitle translator",
        )
        self.assertEqual(events[0].zh_text, "今天")
        self.assertEqual(events[1].zh_text, "今天我们正在测试")

    def test_stream_partial_translation_discards_stale_version(self) -> None:
        worker = RealtimeSubtitleWorker(AppConfig(translation_api_key="translation-key"))
        worker._translator = FakeStreamingTranslator(["旧译文"])
        events = []
        worker.subtitle_event.connect(events.append)
        worker._reset_translation_state()
        worker._remember_partial_source("asr_0001", "today we are testing")
        worker._partial_translation_versions["asr_0001"] = 2

        worker._stream_partial_translation(
            segment_id="asr_0001",
            source_text="today we are testing",
            context=(),
            version=1,
        )

        self.assertEqual(events, [])


if __name__ == "__main__":
    unittest.main()
