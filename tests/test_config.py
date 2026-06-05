import os
import unittest
from unittest.mock import patch

from app.core.config import AppConfig


class AppConfigTest(unittest.TestCase):
    def test_default_config_uses_mock_providers(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = AppConfig.from_env()

        self.assertEqual(config.asr_provider, "mock")
        self.assertEqual(config.asr_model, "gpt-4o-mini-transcribe")
        self.assertEqual(config.asr_timeout_seconds, 30.0)
        self.assertEqual(config.translation_provider, "mock")
        self.assertEqual(config.source_language, "en")
        self.assertEqual(config.target_language, "zh-CN")

    def test_asr_http_config_can_be_loaded_from_env(self) -> None:
        with patch.dict(
            os.environ,
            {
                "ASR_PROVIDER": "openai-compatible",
                "ASR_API_KEY": "secret",
                "ASR_BASE_URL": "https://example.test/v1",
                "ASR_MODEL": "asr-test",
                "ASR_RESPONSE_FORMAT": "verbose_json",
                "ASR_TIMEOUT_SECONDS": "12.5",
            },
            clear=True,
        ):
            config = AppConfig.from_env()

        self.assertEqual(config.asr_provider, "openai-compatible")
        self.assertEqual(config.asr_api_key, "secret")
        self.assertEqual(config.asr_base_url, "https://example.test/v1")
        self.assertEqual(config.asr_model, "asr-test")
        self.assertEqual(config.asr_response_format, "verbose_json")
        self.assertEqual(config.asr_timeout_seconds, 12.5)

    def test_safe_dict_masks_api_keys(self) -> None:
        config = AppConfig(asr_api_key="sk-test-123456", translation_api_key="short")

        safe_config = config.to_safe_dict()

        self.assertEqual(safe_config["asr_api_key"], "sk-t****3456")
        self.assertEqual(safe_config["translation_api_key"], "********")


if __name__ == "__main__":
    unittest.main()

