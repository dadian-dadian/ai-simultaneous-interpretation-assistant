from __future__ import annotations

from app.core.config import AppConfig
from app.translate.baidu_mt import BaiduMtTranslationClient
from app.translate.types import TranslationClient, TranslationConfigurationError

_DISABLED_PROVIDERS = {"", "none", "off", "disabled"}


def create_partial_translation_client(config: AppConfig) -> TranslationClient | None:
    provider = config.partial_translation_provider.strip().lower()
    if provider in _DISABLED_PROVIDERS:
        return None
    if provider == "baidu-mt":
        return BaiduMtTranslationClient(
            app_id=config.partial_translation_app_id,
            api_key=config.partial_translation_api_key,
            secret_key=config.partial_translation_secret_key,
            timeout_seconds=config.partial_translation_timeout_seconds,
        )
    raise TranslationConfigurationError(
        f"Unsupported PARTIAL_TRANSLATION_PROVIDER: {config.partial_translation_provider}"
    )
