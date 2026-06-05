from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from app import __version__
from app.audio.capture import SystemAudioCapture
from app.core.config import AppConfig
from app.core.logging import configure_logging


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-interpreter",
        description="Windows 桌面端 AI 同声传译助手启动入口。",
    )
    parser.add_argument("--version", action="store_true", help="显示当前应用版本。")
    parser.add_argument("--show-config", action="store_true", help="打印当前配置并退出。")
    parser.add_argument("--list-audio-devices", action="store_true", help="列出系统音频捕获设备。")
    parser.add_argument("--record-system-audio", default=None, help="录制系统音频并保存为 wav 文件。")
    parser.add_argument("--record-duration", type=float, default=3.0, help="系统音频录制时长，单位秒。")
    parser.add_argument("--audio-sample-rate", type=int, default=16000, help="录制采样率。")
    parser.add_argument("--audio-channels", type=int, default=1, help="录制声道数。")
    parser.add_argument(
        "--log-level",
        default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="覆盖日志级别。",
    )
    parser.add_argument("--no-ui", action="store_true", help="仅启动命令行骨架，不打开桌面窗口。")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    config = AppConfig.from_env()
    if args.log_level:
        config = config.with_log_level(args.log_level)

    configure_logging(config.log_level)
    logger = logging.getLogger(__name__)

    if args.version:
        print(__version__)
        return 0

    if args.show_config:
        print(json.dumps(config.to_safe_dict(), ensure_ascii=False, indent=2))
        return 0

    if args.list_audio_devices:
        return list_audio_devices(args.audio_sample_rate, args.audio_channels)

    if args.record_system_audio:
        return record_system_audio(
            output_path=Path(args.record_system_audio),
            duration_seconds=args.record_duration,
            sample_rate=args.audio_sample_rate,
            channels=args.audio_channels,
        )

    if not args.no_ui:
        return launch_desktop_app(config)

    logger.info("AI 同声传译助手启动中")
    logger.info("当前 ASR 提供方：%s", config.asr_provider)
    logger.info("当前翻译提供方：%s", config.translation_provider)
    logger.info("已使用 --no-ui 跳过桌面窗口")
    return 0


def list_audio_devices(sample_rate: int, channels: int) -> int:
    capture = SystemAudioCapture(sample_rate=sample_rate, channels=channels)
    devices = capture.list_loopback_devices()
    if not devices:
        print("未找到可用的系统音频 loopback 设备。")
        return 1

    for index, device in enumerate(devices, start=1):
        marker = "默认" if device.is_default else "可用"
        print(f"{index}. [{marker}] {device.name} ({device.channels} channels)")
        print(f"   id: {device.id}")
    return 0


def record_system_audio(
    output_path: Path,
    duration_seconds: float,
    sample_rate: int,
    channels: int,
) -> int:
    capture = SystemAudioCapture(sample_rate=sample_rate, channels=channels)
    chunk = capture.record_seconds(duration_seconds=duration_seconds)
    saved_path = chunk.save_wav(output_path)
    print(f"已保存系统音频：{saved_path}")
    print(
        f"时长 {chunk.duration_seconds:.2f}s，采样率 {chunk.sample_rate}Hz，"
        f"声道 {chunk.channels}，RMS {chunk.rms:.6f}"
    )
    return 0


def launch_desktop_app(config: AppConfig) -> int:
    try:
        from app.ui.main_window import run_main_window
    except ModuleNotFoundError as exc:
        if exc.name != "PySide6":
            raise
        print("缺少 PySide6 依赖，请先执行：uv sync", file=sys.stderr)
        return 2

    return run_main_window(config)


if __name__ == "__main__":
    raise SystemExit(main())

