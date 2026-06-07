import threading
import time
import unittest

from app.translate.stream_manager import SentenceTranslationManager, TranslationUpdate
from app.translate.types import TranslationResult


class _BlockingClient:
    def __init__(self) -> None:
        self.release = threading.Event()
        self.calls: list[str] = []

    def translate(
        self,
        text: str,
        source_language: str,
        target_language: str,
    ) -> TranslationResult:
        self.calls.append(text)
        self.release.wait(timeout=2.0)
        return TranslationResult(
            source_text=text,
            translated_text=f"ZH:{text}",
            source_language=source_language,
            target_language=target_language,
            provider="fake",
        )


class _FastClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def translate(
        self,
        text: str,
        source_language: str,
        target_language: str,
    ) -> TranslationResult:
        self.calls.append(text)
        return TranslationResult(
            source_text=text,
            translated_text=f"ZH:{text}",
            source_language=source_language,
            target_language=target_language,
            provider="fake",
        )


class SentenceTranslationManagerTest(unittest.TestCase):
    def test_translation_update_is_emitted(self) -> None:
        event = threading.Event()
        updates: list[TranslationUpdate] = []
        manager = SentenceTranslationManager(
            client=_FastClient(),
            source_language="en",
            target_language="zh-CN",
            on_update=lambda update: (updates.append(update), event.set()),
        )
        self.addCleanup(manager.stop)

        manager.submit(
            segment_id="asr_0001_s0001",
            source_version=1,
            source_text="I loved that job.",
            is_final=True,
        )

        self.assertTrue(event.wait(timeout=2.0))
        self.assertEqual(updates[0].translated_text, "ZH:I loved that job.")
        self.assertTrue(updates[0].is_final)
        self.assertTrue(manager.wait_until_idle())

    def test_stale_result_is_dropped_when_newer_version_arrives(self) -> None:
        client = _BlockingClient()
        update_event = threading.Event()
        updates: list[TranslationUpdate] = []

        def collect(update: TranslationUpdate) -> None:
            updates.append(update)
            update_event.set()

        manager = SentenceTranslationManager(
            client=client,
            source_language="en",
            target_language="zh-CN",
            on_update=collect,
        )
        self.addCleanup(manager.stop)

        manager.submit(
            segment_id="asr_0001_s0001",
            source_version=1,
            source_text="I loved",
            is_final=False,
        )
        deadline = time.monotonic() + 2.0
        while not client.calls and time.monotonic() < deadline:
            time.sleep(0.01)
        manager.submit(
            segment_id="asr_0001_s0001",
            source_version=2,
            source_text="I loved that job.",
            is_final=True,
        )
        client.release.set()

        self.assertTrue(update_event.wait(timeout=2.0))
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0].source_version, 2)
        self.assertEqual(updates[0].translated_text, "ZH:I loved that job.")

    def test_prefix_partial_result_is_emitted_when_newer_version_arrives(
        self,
    ) -> None:
        client = _BlockingClient()
        update_event = threading.Event()
        updates: list[TranslationUpdate] = []

        def collect(update: TranslationUpdate) -> None:
            updates.append(update)
            update_event.set()

        manager = SentenceTranslationManager(
            client=client,
            source_language="en",
            target_language="zh-CN",
            on_update=collect,
        )
        self.addCleanup(manager.stop)

        manager.submit(
            segment_id="asr_0001_s0001",
            source_version=1,
            source_text="I loved that early part",
            is_final=False,
            allow_source_prefix=True,
        )
        deadline = time.monotonic() + 2.0
        while not client.calls and time.monotonic() < deadline:
            time.sleep(0.01)
        manager.submit(
            segment_id="asr_0001_s0001",
            source_version=2,
            source_text="I loved that early part and then continued",
            is_final=False,
            allow_source_prefix=True,
        )
        client.release.set()

        self.assertTrue(update_event.wait(timeout=2.0))
        self.assertEqual(updates[0].source_version, 1)
        self.assertTrue(updates[0].allow_source_prefix)

    def test_pending_partial_requests_are_coalesced_to_latest(self) -> None:
        client = _BlockingClient()
        updates: list[TranslationUpdate] = []
        manager = SentenceTranslationManager(
            client=client,
            source_language="en",
            target_language="zh-CN",
            on_update=updates.append,
        )
        self.addCleanup(manager.stop)

        manager.submit(
            segment_id="asr_0001_s0001",
            source_version=1,
            source_text="one two three four five six",
            is_final=False,
            allow_source_prefix=True,
        )
        deadline = time.monotonic() + 2.0
        while not client.calls and time.monotonic() < deadline:
            time.sleep(0.01)
        manager.submit(
            segment_id="asr_0001_s0001",
            source_version=2,
            source_text="one two three four five six seven",
            is_final=False,
            allow_source_prefix=True,
        )
        manager.submit(
            segment_id="asr_0001_s0001",
            source_version=3,
            source_text="one two three four five six seven eight",
            is_final=False,
            allow_source_prefix=True,
        )
        client.release.set()

        deadline = time.monotonic() + 2.0
        while len(client.calls) < 2 and time.monotonic() < deadline:
            time.sleep(0.01)

        self.assertEqual(
            client.calls,
            [
                "one two three four five six",
                "one two three four five six seven eight",
            ],
        )

    def test_final_runs_before_pending_partial_requests(self) -> None:
        client = _BlockingClient()
        manager = SentenceTranslationManager(
            client=client,
            source_language="en",
            target_language="zh-CN",
            on_update=lambda update: None,
        )
        self.addCleanup(manager.stop)

        manager.submit(
            segment_id="asr_0001_s0001",
            source_version=1,
            source_text="first active draft",
            is_final=False,
            allow_source_prefix=True,
        )
        deadline = time.monotonic() + 2.0
        while not client.calls and time.monotonic() < deadline:
            time.sleep(0.01)
        manager.submit(
            segment_id="asr_0001_s0002",
            source_version=1,
            source_text="second pending draft",
            is_final=False,
            allow_source_prefix=True,
        )
        manager.submit(
            segment_id="asr_0001_s0001",
            source_version=2,
            source_text="first final sentence",
            is_final=True,
        )
        client.release.set()

        deadline = time.monotonic() + 2.0
        while len(client.calls) < 3 and time.monotonic() < deadline:
            time.sleep(0.01)

        self.assertEqual(client.calls[1], "first final sentence")
        self.assertEqual(client.calls[2], "second pending draft")

    def test_latest_partial_is_not_starved_by_many_finals(self) -> None:
        client = _BlockingClient()
        manager = SentenceTranslationManager(
            client=client,
            source_language="en",
            target_language="zh-CN",
            on_update=lambda update: None,
            max_queue_size=8,
        )
        self.addCleanup(manager.stop)

        manager.submit(
            segment_id="asr_0001_s0001",
            source_version=1,
            source_text="first inflight draft",
            is_final=False,
            allow_source_prefix=True,
        )
        deadline = time.monotonic() + 2.0
        while not client.calls and time.monotonic() < deadline:
            time.sleep(0.01)
        for index in range(5):
            manager.submit(
                segment_id=f"asr_0001_s{index + 2:04d}",
                source_version=1,
                source_text=f"final sentence {index}",
                is_final=True,
            )
        manager.submit(
            segment_id="asr_0001_s9999",
            source_version=1,
            source_text="latest realtime draft",
            is_final=False,
            allow_source_prefix=True,
        )
        client.release.set()

        deadline = time.monotonic() + 2.0
        while len(client.calls) < 3 and time.monotonic() < deadline:
            time.sleep(0.01)

        self.assertEqual(client.calls[1], "final sentence 0")
        self.assertEqual(client.calls[2], "latest realtime draft")

    def test_queue_size_limit_is_enforced_for_pending_requests(self) -> None:
        client = _BlockingClient()
        manager = SentenceTranslationManager(
            client=client,
            source_language="en",
            target_language="zh-CN",
            on_update=lambda update: None,
            max_queue_size=3,
        )
        self.addCleanup(manager.stop)

        manager.submit(
            segment_id="asr_0001_s0001",
            source_version=1,
            source_text="inflight draft",
            is_final=False,
            allow_source_prefix=True,
        )
        deadline = time.monotonic() + 2.0
        while not client.calls and time.monotonic() < deadline:
            time.sleep(0.01)
        for index in range(10):
            manager.submit(
                segment_id=f"asr_0001_s{index + 2:04d}",
                source_version=1,
                source_text=f"queued final {index}",
                is_final=True,
            )

        self.assertLessEqual(manager.pending_count, 4)

    def test_begin_session_invalidates_inflight_old_results(self) -> None:
        client = _BlockingClient()
        update_event = threading.Event()
        updates: list[TranslationUpdate] = []

        def collect(update: TranslationUpdate) -> None:
            updates.append(update)
            update_event.set()

        manager = SentenceTranslationManager(
            client=client,
            source_language="en",
            target_language="zh-CN",
            on_update=collect,
        )
        self.addCleanup(manager.stop)
        manager.begin_session("session-1")
        manager.submit(
            session_id="session-1",
            segment_id="asr_0001_s0001",
            source_version=1,
            source_text="old session draft",
            is_final=False,
            allow_source_prefix=True,
        )
        deadline = time.monotonic() + 2.0
        while not client.calls and time.monotonic() < deadline:
            time.sleep(0.01)

        manager.begin_session("session-2")
        client.release.set()
        time.sleep(0.05)

        self.assertFalse(update_event.is_set())
        self.assertEqual(updates, [])


if __name__ == "__main__":
    unittest.main()
