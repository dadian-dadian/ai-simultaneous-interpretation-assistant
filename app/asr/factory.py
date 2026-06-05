from __future__ import annotations

from app.asr.baidu import BaiduCloudAsrClient
from app.asr.mock import MockAsrClient
from app.asr.types import AsrClient, AsrConfigurationError
from app.core.config import AppConfig


def create_asr_client(config: AppConfig) -> AsrClient:
    provider = config.asr_provider.strip().lower()
    if provider in {"mock", "demo"}:
        return MockAsrClient()
    if provider in {"baidu", "baidu-cloud", "domestic"}:
        return BaiduCloudAsrClient(
            api_key=config.asr_api_key,
            secret_key=config.asr_secret_key,
            access_token=config.asr_access_token,
            endpoint=config.asr_baidu_endpoint,
            token_endpoint=config.asr_baidu_token_endpoint,
            cuid=config.asr_baidu_cuid,
            dev_pid=config.asr_baidu_dev_pid,
            timeout_seconds=config.asr_timeout_seconds,
        )
    raise AsrConfigurationError(f"不支持的 ASR_PROVIDER：{config.asr_provider}")
