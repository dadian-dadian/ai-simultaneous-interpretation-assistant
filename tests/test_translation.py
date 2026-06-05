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
        self.assertIn("上下文", captured["body"]["messages"][1]["content"])
        self.assertEqual(result.text, "我们正在测试实时字幕。")

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
