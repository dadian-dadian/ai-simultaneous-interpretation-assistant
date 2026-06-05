import unittest
from concurrent.futures import Future

from app.core.config import AppConfig
from app.core.subtitle import SubtitleEventType
from app.ui.realtime_worker import RealtimeSubtitleWorker


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


if __name__ == "__main__":
    unittest.main()
