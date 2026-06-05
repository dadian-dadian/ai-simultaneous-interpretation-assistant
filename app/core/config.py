from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AppConfig:
    asr_provider: str = "mock"
    asr_api_key: str = ""
    asr_base_url: str = "https://api.openai.com/v1"
    asr_model: str = "gpt-4o-mini-transcribe"
    asr_response_format: str = "json"
    asr_timeout_seconds: float = 30.0
    translation_provider: str = "mock"
    translation_api_key: str = ""
    source_language: str = "en"
    target_language: str = "zh-CN"
    subtitle_mode: str = "bilingual"
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> AppConfig:
        return cls(
            asr_provider=os.getenv("ASR_PROVIDER", cls.asr_provider),
            asr_api_key=os.getenv("ASR_API_KEY", cls.asr_api_key),
            asr_base_url=os.getenv("ASR_BASE_URL", cls.asr_base_url),
            asr_model=os.getenv("ASR_MODEL", cls.asr_model),
            asr_response_format=os.getenv("ASR_RESPONSE_FORMAT", cls.asr_response_format),
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
            source_language=os.getenv("SOURCE_LANGUAGE", cls.source_language),
            target_language=os.getenv("TARGET_LANGUAGE", cls.target_language),
            subtitle_mode=os.getenv("SUBTITLE_MODE", cls.subtitle_mode),
            log_level=os.getenv("LOG_LEVEL", cls.log_level),
        )

    def with_log_level(self, log_level: str) -> AppConfig:
        return AppConfig(
            asr_provider=self.asr_provider,
            asr_api_key=self.asr_api_key,
            asr_base_url=self.asr_base_url,
            asr_model=self.asr_model,
            asr_response_format=self.asr_response_format,
            asr_timeout_seconds=self.asr_timeout_seconds,
            translation_provider=self.translation_provider,
            translation_api_key=self.translation_api_key,
            source_language=self.source_language,
            target_language=self.target_language,
            subtitle_mode=self.subtitle_mode,
            log_level=log_level,
        )

    def to_safe_dict(self) -> dict[str, object]:
        return {
            "asr_provider": self.asr_provider,
            "asr_api_key": self._mask_secret(self.asr_api_key),
            "asr_base_url": self.asr_base_url,
            "asr_model": self.asr_model,
            "asr_response_format": self.asr_response_format,
            "asr_timeout_seconds": self.asr_timeout_seconds,
            "translation_provider": self.translation_provider,
            "translation_api_key": self._mask_secret(self.translation_api_key),
            "source_language": self.source_language,
            "target_language": self.target_language,
            "subtitle_mode": self.subtitle_mode,
            "log_level": self.log_level,
        }

    @staticmethod
    def _mask_secret(value: str) -> str:
        if not value:
            return ""
        if len(value) <= 8:
            return "********"
        return f"{value[:4]}****{value[-4:]}"


def _env_float(name: str, default: float) -> float:
    raw_value = os.getenv(name)
    if not raw_value:
        return default
    try:
        return float(raw_value)
    except ValueError:
        return default

