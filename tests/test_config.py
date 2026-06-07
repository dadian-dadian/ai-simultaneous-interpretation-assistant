import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.config import AppConfig


class AppConfigTest(unittest.TestCase):
    def test_default_config_uses_mock_providers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch("app.core.config.project_root", return_value=Path(tmp_dir)):
                with patch.dict(os.environ, {}, clear=True):
                    config = AppConfig.from_env()

        self.assertEqual(config.asr_provider, "mock")
        self.assertEqual(config.asr_baidu_dev_pid, "auto")
        self.assertEqual(config.asr_timeout_seconds, 30.0)
        self.assertEqual(config.translation_provider, "mock")
        self.assertEqual(config.partial_translation_provider, "")
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

    def test_real_environment_overrides_dotenv_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            dotenv_path = Path(tmp_dir) / ".env"
            dotenv_path.write_text("ASR_PROVIDER=mock\n", encoding="utf-8")
            with patch("app.core.config.project_root", return_value=Path(tmp_dir)):
                with patch.dict(os.environ, {"ASR_PROVIDER": "baidu-realtime"}, clear=True):
                    config = AppConfig.from_env()

        self.assertEqual(config.asr_provider, "baidu-realtime")

    def test_partial_translation_config_can_be_loaded_from_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch("app.core.config.project_root", return_value=Path(tmp_dir)):
                with patch.dict(
                    os.environ,
                    {
                        "PARTIAL_TRANSLATION_PROVIDER": "baidu-mt",
                        "PARTIAL_TRANSLATION_APP_ID": "app-id",
                        "PARTIAL_TRANSLATION_API_KEY": "api-key",
                        "PARTIAL_TRANSLATION_SECRET_KEY": "secret-key",
                        "PARTIAL_TRANSLATION_TIMEOUT_SECONDS": "3.5",
                    },
                    clear=True,
                ):
                    config = AppConfig.from_env()

        self.assertEqual(config.partial_translation_provider, "baidu-mt")
        self.assertEqual(config.partial_translation_app_id, "app-id")
        self.assertEqual(config.partial_translation_api_key, "api-key")
        self.assertEqual(config.partial_translation_secret_key, "secret-key")
        self.assertEqual(config.partial_translation_timeout_seconds, 3.5)

    def test_legacy_partial_translation_secret_is_supported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch("app.core.config.project_root", return_value=Path(tmp_dir)):
                with patch.dict(
                    os.environ,
                    {"PARTIAL_TRANSLATION_SECRET": "legacy-secret"},
                    clear=True,
                ):
                    config = AppConfig.from_env()

        self.assertEqual(config.partial_translation_secret_key, "legacy-secret")

    def test_active_translation_provider_prefers_partial_provider(self) -> None:
        config = AppConfig(
            translation_provider="openai-compatible",
            partial_translation_provider="baidu-mt",
        )

        self.assertEqual(config.active_translation_provider, "baidu-mt")

    def test_safe_dict_masks_api_keys(self) -> None:
        config = AppConfig(
            asr_app_id="123",
            asr_api_key="sk-test-123456",
            translation_api_key="short",
            partial_translation_api_key="partial-api-key",
            partial_translation_secret_key="partial-secret-key",
        )

        safe_config = config.to_safe_dict()

        self.assertEqual(safe_config["asr_app_id"], "123")
        self.assertEqual(safe_config["asr_api_key"], "sk-t****3456")
        self.assertEqual(safe_config["translation_api_key"], "********")
        self.assertEqual(safe_config["partial_translation_api_key"], "part****-key")
        self.assertEqual(
            safe_config["partial_translation_secret_key"],
            "part****-key",
        )


if __name__ == "__main__":
    unittest.main()

