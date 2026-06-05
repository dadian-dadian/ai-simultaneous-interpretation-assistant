import os
import unittest
from unittest.mock import patch

from app.core.config import AppConfig


class AppConfigTest(unittest.TestCase):
    def test_default_config_uses_mock_providers(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = AppConfig.from_env()

        self.assertEqual(config.asr_provider, "mock")
        self.assertEqual(config.asr_baidu_dev_pid, "auto")
        self.assertEqual(config.asr_timeout_seconds, 30.0)
        self.assertEqual(config.translation_provider, "mock")
        self.assertEqual(config.source_language, "en")
        self.assertEqual(config.target_language, "zh-CN")

    def test_baidu_asr_config_can_be_loaded_from_env(self) -> None:
        with patch.dict(
            os.environ,
            {
                "ASR_PROVIDER": "baidu-cloud",
                "ASR_API_KEY": "api-key",
                "ASR_SECRET_KEY": "secret-key",
                "ASR_ACCESS_TOKEN": "token",
                "ASR_BAIDU_ENDPOINT": "https://example.test/server_api",
                "ASR_BAIDU_TOKEN_ENDPOINT": "https://example.test/oauth/token",
                "ASR_BAIDU_CUID": "test-cuid",
                "ASR_BAIDU_DEV_PID": "1737",
                "ASR_TIMEOUT_SECONDS": "12.5",
            },
            clear=True,
        ):
            config = AppConfig.from_env()

        self.assertEqual(config.asr_provider, "baidu-cloud")
        self.assertEqual(config.asr_api_key, "api-key")
        self.assertEqual(config.asr_secret_key, "secret-key")
        self.assertEqual(config.asr_access_token, "token")
        self.assertEqual(config.asr_baidu_endpoint, "https://example.test/server_api")
        self.assertEqual(config.asr_baidu_token_endpoint, "https://example.test/oauth/token")
        self.assertEqual(config.asr_baidu_cuid, "test-cuid")
        self.assertEqual(config.asr_baidu_dev_pid, "1737")
        self.assertEqual(config.asr_timeout_seconds, 12.5)

    def test_safe_dict_masks_api_keys(self) -> None:
        config = AppConfig(
            asr_api_key="sk-test-123456",
            asr_secret_key="secret-123456",
            asr_access_token="token-123456",
            translation_api_key="short",
        )

        safe_config = config.to_safe_dict()

        self.assertEqual(safe_config["asr_api_key"], "sk-t****3456")
        self.assertEqual(safe_config["asr_secret_key"], "secr****3456")
        self.assertEqual(safe_config["asr_access_token"], "toke****3456")
        self.assertEqual(safe_config["translation_api_key"], "********")


if __name__ == "__main__":
    unittest.main()

