from __future__ import annotations

from app.asr.mock import MockAsrClient
from app.asr.openai_compatible import OpenAICompatibleAsrClient
from app.asr.types import AsrClient, AsrConfigurationError
from app.core.config import AppConfig


def create_asr_client(config: AppConfig) -> AsrClient:
    provider = config.asr_provider.strip().lower()
    if provider in {"mock", "demo"}:
        return MockAsrClient()
    if provider in {"openai", "openai-compatible", "http"}:
        return OpenAICompatibleAsrClient(
            api_key=config.asr_api_key,
            base_url=config.asr_base_url,
            model=config.asr_model,
            response_format=config.asr_response_format,
            timeout_seconds=config.asr_timeout_seconds,
        )
    raise AsrConfigurationError(f"不支持的 ASR_PROVIDER：{config.asr_provider}")
