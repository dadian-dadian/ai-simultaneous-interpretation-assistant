import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.config import AppConfig


class AppConfigTest(unittest.TestCase):
    def test_default_config_uses_real_translation_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch("app.core.config.project_root", return_value=Path(tmp_dir)):
                with patch.dict(os.environ, {}, clear=True):
                    config = AppConfig.from_env()

        self.assertEqual(config.asr_provider, "mock")
        self.assertEqual(config.asr_baidu_dev_pid, "auto")
        self.assertEqual(config.asr_timeout_seconds, 30.0)
        self.assertEqual(config.translation_provider, "openai-compatible")
        self.assertEqual(config.translation_base_url, "https://api.deepseek.com/v1")
        self.assertEqual(config.translation_model, "deepseek-chat")
        self.assertEqual(config.translation_timeout_seconds, 30.0)
        self.assertEqual(config.source_language, "en")
        self.assertEqual(config.target_language, "zh-CN")

    def test_baidu_asr_config_can_be_loaded_from_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch("app.core.config.project_root", return_value=Path(tmp_dir)):
                with patch.dict(
                    os.environ,
                    {
                        "ASR_PROVIDER": "baidu-realtime",
                        "ASR_APP_ID": "123",
                        "ASR_API_KEY": "app-key",
                        "ASR_BAIDU_WS_URL": "wss://example.test/realtime_asr",
                        "ASR_BAIDU_CUID": "test-cuid",
                        "ASR_BAIDU_DEV_PID": "17372",
                        "ASR_TIMEOUT_SECONDS": "12.5",
                    },
                    clear=True,
                ):
                    config = AppConfig.from_env()

        self.assertEqual(config.asr_provider, "baidu-realtime")
        self.assertEqual(config.asr_app_id, "123")
        self.assertEqual(config.asr_api_key, "app-key")
        self.assertEqual(config.asr_baidu_ws_url, "wss://example.test/realtime_asr")
        self.assertEqual(config.asr_baidu_cuid, "test-cuid")
        self.assertEqual(config.asr_baidu_dev_pid, "17372")
        self.assertEqual(config.asr_timeout_seconds, 12.5)

    def test_dotenv_file_can_be_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            dotenv_path = Path(tmp_dir) / ".env"
            dotenv_path.write_text(
                "\n".join(
                    [
                        "ASR_PROVIDER=baidu-realtime",
                        "ASR_APP_ID=123",
                        "ASR_API_KEY=app-key",
                        "ASR_BAIDU_CUID=test-cuid",
                    ]
                ),
                encoding="utf-8",
            )
            with patch("app.core.config.project_root", return_value=Path(tmp_dir)):
                with patch.dict(os.environ, {}, clear=True):
                    config = AppConfig.from_env()

        self.assertEqual(config.asr_provider, "baidu-realtime")
        self.assertEqual(config.asr_app_id, "123")
        self.assertEqual(config.asr_api_key, "app-key")
        self.assertEqual(config.asr_baidu_cuid, "test-cuid")

    def test_translation_config_can_be_loaded_from_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch("app.core.config.project_root", return_value=Path(tmp_dir)):
                with patch.dict(
                    os.environ,
                    {
                        "TRANSLATION_PROVIDER": "openai-compatible",
                        "TRANSLATION_API_KEY": "translation-key",
                        "TRANSLATION_BASE_URL": "https://example.test/v1",
                        "TRANSLATION_MODEL": "model-a",
                        "TRANSLATION_TIMEOUT_SECONDS": "9.5",
                    },
                    clear=True,
                ):
                    config = AppConfig.from_env()

        self.assertEqual(config.translation_provider, "openai-compatible")
        self.assertEqual(config.translation_api_key, "translation-key")
        self.assertEqual(config.translation_base_url, "https://example.test/v1")
        self.assertEqual(config.translation_model, "model-a")
        self.assertEqual(config.translation_timeout_seconds, 9.5)

    def test_real_environment_overrides_dotenv_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            dotenv_path = Path(tmp_dir) / ".env"
            dotenv_path.write_text("ASR_PROVIDER=mock\n", encoding="utf-8")
            with patch("app.core.config.project_root", return_value=Path(tmp_dir)):
                with patch.dict(os.environ, {"ASR_PROVIDER": "baidu-realtime"}, clear=True):
                    config = AppConfig.from_env()

        self.assertEqual(config.asr_provider, "baidu-realtime")

    def test_safe_dict_masks_api_keys(self) -> None:
        config = AppConfig(
            asr_app_id="123",
            asr_api_key="sk-test-123456",
            translation_api_key="short",
        )

        safe_config = config.to_safe_dict()

        self.assertEqual(safe_config["asr_app_id"], "123")
        self.assertEqual(safe_config["asr_api_key"], "sk-t****3456")
        self.assertEqual(safe_config["translation_api_key"], "********")


if __name__ == "__main__":
    unittest.main()

