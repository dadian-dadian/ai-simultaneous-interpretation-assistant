import json
import unittest
from unittest.mock import patch

from app.core.config import AppConfig
from app.translate import (
    OpenAICompatibleTranslator,
    TranslationConfigurationError,
    TranslationError,
    TranslationRequest,
    create_translator_client,
)


class FakeHttpResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")


class FakeStreamHttpResponse:
    def __init__(self, lines: list[str]) -> None:
        self.lines = [line.encode("utf-8") for line in lines]
        self.index = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def readline(self) -> bytes:
        if self.index >= len(self.lines):
            return b""
        line = self.lines[self.index]
        self.index += 1
        return line


class OpenAICompatibleTranslatorTest(unittest.TestCase):
    def test_translate_posts_chat_completion_request(self) -> None:
        translator = OpenAICompatibleTranslator(
            api_key="translation-key",
            base_url="https://example.test/v1",
            model="model-a",
        )
        captured = {}

        def fake_urlopen(request, timeout: float):
            captured["url"] = request.full_url
            captured["timeout"] = timeout
            captured["auth"] = request.headers["Authorization"]
            captured["body"] = json.loads(request.data.decode("utf-8"))
            return FakeHttpResponse(
                {"choices": [{"message": {"content": "我们正在测试实时字幕。"}}]}
            )

        with patch("app.translate.openai_compatible.urllib.request.urlopen", fake_urlopen):
            result = translator.translate(
                TranslationRequest(
                    source_text="We are testing real time subtitles.",
                    source_language="en",
                    target_language="zh-CN",
                    context=("The speaker is discussing ASR.",),
                )
            )

        self.assertEqual(captured["url"], "https://example.test/v1/chat/completions")
        self.assertEqual(captured["auth"], "Bearer translation-key")
        self.assertEqual(captured["timeout"], 30.0)
        self.assertEqual(captured["body"]["model"], "model-a")
        self.assertFalse(captured["body"]["stream"])
        self.assertIn("上下文", captured["body"]["messages"][1]["content"])
        self.assertEqual(result.text, "我们正在测试实时字幕。")

    def test_stream_translate_yields_chat_completion_deltas(self) -> None:
        translator = OpenAICompatibleTranslator(
            api_key="translation-key",
            base_url="https://example.test/v1",
            model="model-a",
        )
        captured = {}

        def fake_urlopen(request, timeout: float):
            captured["url"] = request.full_url
            captured["timeout"] = timeout
            captured["accept"] = request.headers["Accept"]
            captured["body"] = json.loads(request.data.decode("utf-8"))
            return FakeStreamHttpResponse(
                [
                    ": keep-alive\n",
                    "\n",
                    'data: {"choices":[{"delta":{"content":"我们"}}]}\n',
                    'data: {"choices":[{"delta":{"content":"正在测试"}}]}\n',
                    "data: [DONE]\n",
                ]
            )

        with patch("app.translate.openai_compatible.urllib.request.urlopen", fake_urlopen):
            chunks = list(
                translator.stream_translate(
                    TranslationRequest(
                        source_text="We are testing.",
                        source_language="en",
                        target_language="zh-CN",
                    )
                )
            )

        self.assertEqual(captured["url"], "https://example.test/v1/chat/completions")
        self.assertEqual(captured["timeout"], 30.0)
        self.assertEqual(captured["accept"], "text/event-stream")
        self.assertTrue(captured["body"]["stream"])
        self.assertEqual(chunks, ["我们", "正在测试"])

    def test_translate_requires_real_model_config(self) -> None:
        with self.assertRaises(TranslationConfigurationError):
            OpenAICompatibleTranslator(api_key="", base_url="https://example.test/v1", model="m")
        with self.assertRaises(TranslationConfigurationError):
            OpenAICompatibleTranslator(api_key="key", base_url="", model="m")
        with self.assertRaises(TranslationConfigurationError):
            OpenAICompatibleTranslator(api_key="key", base_url="https://example.test/v1", model="")

    def test_translate_raises_for_malformed_response(self) -> None:
        translator = OpenAICompatibleTranslator(
            api_key="translation-key",
            base_url="https://example.test/v1",
            model="model-a",
        )

        with patch(
            "app.translate.openai_compatible.urllib.request.urlopen",
            return_value=FakeHttpResponse({"choices": []}),
        ):
            with self.assertRaisesRegex(TranslationError, "choices"):
                translator.translate(
                    TranslationRequest(
                        source_text="hello",
                        source_language="en",
                        target_language="zh-CN",
                    )
                )


class TranslationFactoryTest(unittest.TestCase):
    def test_factory_returns_openai_compatible_translator(self) -> None:
        translator = create_translator_client(
            AppConfig(
                translation_provider="openai-compatible",
                translation_api_key="translation-key",
                translation_base_url="https://example.test/v1",
                translation_model="model-a",
            )
        )

        self.assertIsInstance(translator, OpenAICompatibleTranslator)

    def test_factory_rejects_mock_provider(self) -> None:
        with self.assertRaisesRegex(TranslationConfigurationError, "仅支持 openai-compatible"):
            create_translator_client(AppConfig(translation_provider="mock"))


if __name__ == "__main__":
    unittest.main()
