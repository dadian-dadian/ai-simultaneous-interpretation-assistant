from __future__ import annotations

import argparse
import json
import logging
import sys

from app import __version__
from app.core.config import AppConfig
from app.core.logging import configure_logging


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-interpreter",
        description="Windows 桌面端 AI 同声传译助手启动入口。",
    )
    parser.add_argument("--version", action="store_true", help="显示当前应用版本。")
    parser.add_argument("--show-config", action="store_true", help="打印当前配置并退出。")
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

    if not args.no_ui:
        return launch_desktop_app(config)

    logger.info("AI 同声传译助手启动中")
    logger.info("当前 ASR 提供方：%s", config.asr_provider)
    logger.info("当前翻译提供方：%s", config.translation_provider)
    logger.info("已使用 --no-ui 跳过桌面窗口")
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

