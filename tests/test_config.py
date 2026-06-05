import os
import unittest
from unittest.mock import patch

from app.core.config import AppConfig


class AppConfigTest(unittest.TestCase):
    def test_default_config_uses_mock_providers(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = AppConfig.from_env()

        self.assertEqual(config.asr_provider, "mock")
        self.assertEqual(config.translation_provider, "mock")
        self.assertEqual(config.source_language, "en")
        self.assertEqual(config.target_language, "zh-CN")

    def test_safe_dict_masks_api_keys(self) -> None:
        config = AppConfig(asr_api_key="sk-test-123456", translation_api_key="short")

        safe_config = config.to_safe_dict()

        self.assertEqual(safe_config["asr_api_key"], "sk-t****3456")
        self.assertEqual(safe_config["translation_api_key"], "********")


if __name__ == "__main__":
    unittest.main()

