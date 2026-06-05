from __future__ import annotations

from app.core.config import AppConfig
from app.translate.openai_compatible import OpenAICompatibleTranslator
from app.translate.types import TranslationConfigurationError, TranslatorClient


def create_translator_client(config: AppConfig) -> TranslatorClient:
    provider = config.translation_provider.strip().lower().replace("_", "-")
    if provider in {"openai-compatible", "openai", "deepseek", "siliconflow", "kimi"}:
        return OpenAICompatibleTranslator(
            api_key=config.translation_api_key,
            base_url=config.translation_base_url,
            model=config.translation_model,
            timeout_seconds=config.translation_timeout_seconds,
        )

    raise TranslationConfigurationError(
        f"不支持的翻译提供方：{config.translation_provider}。当前仅支持 openai-compatible。"
    )
