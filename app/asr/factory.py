from __future__ import annotations

from app.asr.baidu import BaiduRealtimeAsrClient
from app.asr.mock import MockAsrClient
from app.asr.types import AsrClient, AsrConfigurationError
from app.core.config import AppConfig


def create_asr_client(config: AppConfig) -> AsrClient:
    provider = config.asr_provider.strip().lower()
    if provider in {"mock", "demo"}:
        return MockAsrClient()
    if provider in {"baidu", "baidu-realtime", "baidu-cloud", "domestic"}:
        return BaiduRealtimeAsrClient(
            app_id=config.asr_app_id,
            app_key=config.asr_api_key,
            ws_url=config.asr_baidu_ws_url,
            cuid=config.asr_baidu_cuid,
            dev_pid=config.asr_baidu_dev_pid,
            timeout_seconds=config.asr_timeout_seconds,
        )
    raise AsrConfigurationError(f"不支持的 ASR_PROVIDER：{config.asr_provider}")
