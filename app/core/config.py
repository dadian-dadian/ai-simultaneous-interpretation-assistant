from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class AppConfig:
    asr_provider: str = "mock"
    asr_app_id: str = ""
    asr_api_key: str = ""
    asr_baidu_ws_url: str = "wss://vop.baidu.com/realtime_asr"
    asr_baidu_cuid: str = "ai_interpreter_windows"
    asr_baidu_dev_pid: str = "auto"
    asr_timeout_seconds: float = 30.0
    translation_provider: str = "mock"
    translation_api_key: str = ""
    partial_translation_provider: str = ""
    partial_translation_app_id: str = ""
    partial_translation_api_key: str = ""
    partial_translation_secret_key: str = ""
    partial_translation_timeout_seconds: float = 10.0
    source_language: str = "en"
    target_language: str = "zh-CN"
    subtitle_mode: str = "bilingual"
    transcript_storage_dir: str = ""
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> AppConfig:
        load_dotenv(dotenv_path=project_root() / ".env", override=False, encoding="utf-8-sig")
        return cls(
            asr_provider=os.getenv("ASR_PROVIDER", cls.asr_provider),
            asr_app_id=os.getenv("ASR_APP_ID", cls.asr_app_id),
            asr_api_key=os.getenv("ASR_API_KEY", cls.asr_api_key),
            asr_baidu_ws_url=os.getenv("ASR_BAIDU_WS_URL", cls.asr_baidu_ws_url),
            asr_baidu_cuid=os.getenv("ASR_BAIDU_CUID", cls.asr_baidu_cuid),
            asr_baidu_dev_pid=os.getenv("ASR_BAIDU_DEV_PID", cls.asr_baidu_dev_pid),
            asr_timeout_seconds=_env_float(
                "ASR_TIMEOUT_SECONDS",
                cls.asr_timeout_seconds,
            ),
            translation_provider=os.getenv(
                "TRANSLATION_PROVIDER",
                cls.translation_provider,
            ),
            translation_api_key=os.getenv(
                "TRANSLATION_API_KEY",
                cls.translation_api_key,
            ),
            partial_translation_provider=os.getenv(
                "PARTIAL_TRANSLATION_PROVIDER",
                cls.partial_translation_provider,
            ),
            partial_translation_app_id=os.getenv(
                "PARTIAL_TRANSLATION_APP_ID",
                cls.partial_translation_app_id,
            ),
            partial_translation_api_key=os.getenv(
                "PARTIAL_TRANSLATION_API_KEY",
                cls.partial_translation_api_key,
            ),
            partial_translation_secret_key=(
                os.getenv("PARTIAL_TRANSLATION_SECRET_KEY")
                or os.getenv("PARTIAL_TRANSLATION_SECRET")
                or cls.partial_translation_secret_key
            ),
            partial_translation_timeout_seconds=_env_float(
                "PARTIAL_TRANSLATION_TIMEOUT_SECONDS",
                cls.partial_translation_timeout_seconds,
            ),
            source_language=os.getenv("SOURCE_LANGUAGE", cls.source_language),
            target_language=os.getenv("TARGET_LANGUAGE", cls.target_language),
            subtitle_mode=os.getenv("SUBTITLE_MODE", cls.subtitle_mode),
            transcript_storage_dir=os.getenv(
                "TRANSCRIPT_STORAGE_DIR",
                cls.transcript_storage_dir,
            ),
            log_level=os.getenv("LOG_LEVEL", cls.log_level),
        )

    @property
    def active_translation_provider(self) -> str:
        return self.partial_translation_provider.strip() or self.translation_provider

    def with_log_level(self, log_level: str) -> AppConfig:
        return AppConfig(
            asr_provider=self.asr_provider,
            asr_app_id=self.asr_app_id,
            asr_api_key=self.asr_api_key,
            asr_baidu_ws_url=self.asr_baidu_ws_url,
            asr_baidu_cuid=self.asr_baidu_cuid,
            asr_baidu_dev_pid=self.asr_baidu_dev_pid,
            asr_timeout_seconds=self.asr_timeout_seconds,
            translation_provider=self.translation_provider,
            translation_api_key=self.translation_api_key,
            partial_translation_provider=self.partial_translation_provider,
            partial_translation_app_id=self.partial_translation_app_id,
            partial_translation_api_key=self.partial_translation_api_key,
            partial_translation_secret_key=self.partial_translation_secret_key,
            partial_translation_timeout_seconds=self.partial_translation_timeout_seconds,
            source_language=self.source_language,
            target_language=self.target_language,
            subtitle_mode=self.subtitle_mode,
            transcript_storage_dir=self.transcript_storage_dir,
            log_level=log_level,
        )

    def to_safe_dict(self) -> dict[str, object]:
        return {
            "asr_provider": self.asr_provider,
            "asr_app_id": self.asr_app_id,
            "asr_api_key": self._mask_secret(self.asr_api_key),
            "asr_baidu_ws_url": self.asr_baidu_ws_url,
            "asr_baidu_cuid": self.asr_baidu_cuid,
            "asr_baidu_dev_pid": self.asr_baidu_dev_pid,
            "asr_timeout_seconds": self.asr_timeout_seconds,
            "translation_provider": self.translation_provider,
            "translation_api_key": self._mask_secret(self.translation_api_key),
            "partial_translation_provider": self.partial_translation_provider,
            "partial_translation_app_id": self.partial_translation_app_id,
            "partial_translation_api_key": self._mask_secret(
                self.partial_translation_api_key
            ),
            "partial_translation_secret_key": self._mask_secret(
                self.partial_translation_secret_key
            ),
            "partial_translation_timeout_seconds": (
                self.partial_translation_timeout_seconds
            ),
            "source_language": self.source_language,
            "target_language": self.target_language,
            "subtitle_mode": self.subtitle_mode,
            "transcript_storage_dir": self.transcript_storage_dir,
            "log_level": self.log_level,
        }

    @staticmethod
    def _mask_secret(value: str) -> str:
        if not value:
            return ""
        if len(value) <= 8:
            return "********"
        return f"{value[:4]}****{value[-4:]}"


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _env_float(name: str, default: float) -> float:
    raw_value = os.getenv(name)
    if not raw_value:
        return default
    try:
        return float(raw_value)
    except ValueError:
        return default
