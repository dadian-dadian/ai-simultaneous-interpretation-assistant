from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import replace
from pathlib import Path

from app import __version__
from app.asr import AsrClient, AsrError, AsrResult, create_asr_client
from app.audio.buffer import AudioRingBuffer
from app.audio.capture import AudioChunk, QueuedAudioCapture, SystemAudioCapture
from app.audio.vad import SileroOnnxVad, SileroVadSegmenter, VadEventType
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
        "--list-audio-devices",
        action="store_true",
        help="列出系统音频捕获设备。",
    )
    parser.add_argument(
        "--record-system-audio",
        default=None,
        help="录制系统音频并保存为 wav 文件。",
    )
    parser.add_argument(
        "--record-duration",
        type=float,
        default=3.0,
        help="系统音频录制时长，单位秒。",
    )
    parser.add_argument("--audio-sample-rate", type=int, default=16000, help="录制采样率。")
    parser.add_argument("--audio-channels", type=int, default=1, help="录制声道数。")
    parser.add_argument(
        "--preview-vad-stream",
        action="store_true",
        help="预览系统音频流的 Silero VAD 分段。",
    )
    parser.add_argument(
        "--transcribe-audio",
        default=None,
        help="识别本地 wav 音频文件并输出原文。",
    )
    parser.add_argument(
        "--preview-asr-stream",
        action="store_true",
        help="预览系统音频流的 VAD 分段和 ASR 识别。",
    )
    parser.add_argument("--stream-duration", type=float, default=5.0, help="VAD 预览时长，单位秒。")
    parser.add_argument(
        "--chunk-duration",
        type=float,
        default=0.16,
        help="音频流 chunk 时长，单位秒。",
    )
    parser.add_argument(
        "--vad-threshold",
        type=float,
        default=0.5,
        help="Silero VAD 语音概率阈值。",
    )
    parser.add_argument(
        "--vad-min-silence-ms",
        type=int,
        default=600,
        help="确认语音结束所需连续静音时长。",
    )
    parser.add_argument(
        "--asr-provider",
        default=None,
        help="覆盖 ASR 提供方，例如 mock 或 baidu-realtime。",
    )
    parser.add_argument(
        "--asr-baidu-ws-url",
        default=None,
        help="覆盖百度实时 ASR WebSocket 地址。",
    )
    parser.add_argument(
        "--asr-baidu-dev-pid",
        default=None,
        help="覆盖百度云 ASR 模型 dev_pid，默认按语言自动选择。",
    )
    parser.add_argument(
        "--asr-baidu-cuid",
        default=None,
        help="覆盖百度云 ASR cuid。",
    )
    parser.add_argument(
        "--asr-timeout",
        type=float,
        default=None,
        help="覆盖 ASR 请求超时时间，单位秒。",
    )
    parser.add_argument("--asr-language", default=None, help="ASR 识别语言，例如 en。")
    parser.add_argument("--asr-prompt", default="", help="传给 ASR 的上下文提示词。")
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
    config = apply_cli_config_overrides(config, args)

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

    if args.preview_vad_stream:
        return preview_vad_stream(
            duration_seconds=args.stream_duration,
            chunk_duration_seconds=args.chunk_duration,
            threshold=args.vad_threshold,
            min_silence_ms=args.vad_min_silence_ms,
        )

    if args.transcribe_audio:
        return transcribe_audio_file(
            input_path=Path(args.transcribe_audio),
            config=config,
            language=args.asr_language or config.source_language,
            prompt=args.asr_prompt,
        )

    if args.preview_asr_stream:
        return preview_asr_stream(
            duration_seconds=args.stream_duration,
            chunk_duration_seconds=args.chunk_duration,
            threshold=args.vad_threshold,
            min_silence_ms=args.vad_min_silence_ms,
            config=config,
            language=args.asr_language or config.source_language,
            prompt=args.asr_prompt,
        )

    if not args.no_ui:
        return launch_desktop_app(config)

    logger.info("AI 同声传译助手启动中")
    logger.info("当前 ASR 提供方：%s", config.asr_provider)
    logger.info("当前翻译提供方：%s", config.translation_provider)
    logger.info("已使用 --no-ui 跳过桌面窗口")
    return 0


def apply_cli_config_overrides(config: AppConfig, args: argparse.Namespace) -> AppConfig:
    updates: dict[str, object] = {}
    if args.asr_provider:
        updates["asr_provider"] = args.asr_provider
    if args.asr_baidu_ws_url:
        updates["asr_baidu_ws_url"] = args.asr_baidu_ws_url
    if args.asr_baidu_dev_pid:
        updates["asr_baidu_dev_pid"] = args.asr_baidu_dev_pid
    if args.asr_baidu_cuid:
        updates["asr_baidu_cuid"] = args.asr_baidu_cuid
    if args.asr_timeout is not None:
        updates["asr_timeout_seconds"] = args.asr_timeout
    if not updates:
        return config
    return replace(config, **updates)


def preview_vad_stream(
    duration_seconds: float,
    chunk_duration_seconds: float,
    threshold: float,
    min_silence_ms: int,
) -> int:
    capture = QueuedAudioCapture(
        SystemAudioCapture(sample_rate=16000, channels=1),
        chunk_duration_seconds=chunk_duration_seconds,
    )
    buffer = AudioRingBuffer(max_duration_seconds=8.0, sample_rate=16000)
    segmenter = SileroVadSegmenter(
        vad=SileroOnnxVad(threshold=threshold),
        min_silence_ms=min_silence_ms,
    )

    started_at = time.monotonic()
    chunk_count = 0
    print("开始预览系统音频 Silero VAD 分段。")
    print(
        f"时长 {duration_seconds:.1f}s，chunk {chunk_duration_seconds:.2f}s，"
        f"阈值 {threshold:.2f}"
    )

    capture.start()
    try:
        while True:
            chunk = capture.get_chunk(timeout_seconds=0.5)
            if chunk is None:
                if time.monotonic() - started_at >= duration_seconds:
                    break
                continue

            chunk_count += 1
            buffer.append(chunk)
            events = segmenter.accept_chunk(chunk)
            elapsed = time.monotonic() - started_at
            for event in events:
                if event.type == VadEventType.SPEECH_START:
                    print(f"{elapsed:6.2f}s speech_start p={event.speech_probability:.3f}")
                elif event.segment is not None:
                    print(
                        f"{elapsed:6.2f}s speech_end duration={event.segment.duration_seconds:.2f}s"
                    )

            if elapsed >= duration_seconds:
                break
    finally:
        capture.stop()

    for event in segmenter.flush():
        if event.segment is not None:
            print(f"flush speech_end duration={event.segment.duration_seconds:.2f}s")
    print(
        f"已处理 {chunk_count} 个音频块，最近缓冲 {buffer.duration_seconds:.2f}s，"
        f"丢弃旧块 {capture.dropped_chunks} 个。"
    )
    return 0


def transcribe_audio_file(
    input_path: Path,
    config: AppConfig,
    language: str,
    prompt: str,
) -> int:
    try:
        audio = AudioChunk.from_wav(input_path)
        client = create_asr_client(config)
        result = client.transcribe(audio, language=language, prompt=prompt)
    except (OSError, ValueError, AsrError) as exc:
        print(f"ASR 识别失败：{exc}", file=sys.stderr)
        return 2

    print_asr_result(result)
    return 0


def preview_asr_stream(
    duration_seconds: float,
    chunk_duration_seconds: float,
    threshold: float,
    min_silence_ms: int,
    config: AppConfig,
    language: str,
    prompt: str,
) -> int:
    try:
        client = create_asr_client(config)
    except AsrError as exc:
        print(f"ASR 初始化失败：{exc}", file=sys.stderr)
        return 2

    capture = QueuedAudioCapture(
        SystemAudioCapture(sample_rate=16000, channels=1),
        chunk_duration_seconds=chunk_duration_seconds,
    )
    buffer = AudioRingBuffer(max_duration_seconds=8.0, sample_rate=16000)
    segmenter = SileroVadSegmenter(
        vad=SileroOnnxVad(threshold=threshold),
        min_silence_ms=min_silence_ms,
    )

    started_at = time.monotonic()
    chunk_count = 0
    stream_session = None
    stream_duration_seconds = 0.0
    last_partial_text = ""
    print("开始预览系统音频 VAD + ASR。")
    print(
        f"时长 {duration_seconds:.1f}s，chunk {chunk_duration_seconds:.2f}s，"
        f"阈值 {threshold:.2f}，ASR {client.provider_name}"
    )

    capture.start()
    try:
        while True:
            chunk = capture.get_chunk(timeout_seconds=0.5)
            if chunk is None:
                if time.monotonic() - started_at >= duration_seconds:
                    break
                continue

            chunk_count += 1
            buffer.append(chunk)
            events = segmenter.accept_chunk(chunk)
            elapsed = time.monotonic() - started_at
            current_chunk_sent = False
            speech_end_event = None
            for event in events:
                if event.type == VadEventType.SPEECH_START:
                    print(f"{elapsed:6.2f}s speech_start p={event.speech_probability:.3f}")
                    if supports_streaming_asr(client):
                        try:
                            stream_session = client.start_stream(language=language, prompt=prompt)
                            preroll = buffer.recent(duration_seconds=0.5)
                            stream_events = stream_session.send_audio(preroll)
                        except AsrError as exc:
                            print(
                                f"{elapsed:6.2f}s ASR 流式识别启动失败：{exc}",
                                file=sys.stderr,
                            )
                            if stream_session is not None:
                                stream_session.close()
                                stream_session = None
                            return 2
                        stream_duration_seconds = preroll.duration_seconds
                        current_chunk_sent = True
                        last_partial_text = print_asr_stream_events(
                            stream_events,
                            prefix=f"{elapsed:6.2f}s",
                            last_partial_text=last_partial_text,
                        )
                elif event.segment is not None:
                    speech_end_event = event

            if stream_session is not None and not current_chunk_sent:
                try:
                    stream_events = stream_session.send_audio(chunk)
                except AsrError as exc:
                    print(f"{elapsed:6.2f}s ASR 流式音频发送失败：{exc}", file=sys.stderr)
                    stream_session.close()
                    stream_session = None
                    return 2
                stream_duration_seconds += chunk.duration_seconds
                last_partial_text = print_asr_stream_events(
                    stream_events,
                    prefix=f"{elapsed:6.2f}s",
                    last_partial_text=last_partial_text,
                )

            if speech_end_event is not None:
                if stream_session is not None:
                    try:
                        result = stream_session.finish(duration_seconds=stream_duration_seconds)
                    except AsrError as exc:
                        print(f"{elapsed:6.2f}s ASR 流式识别结束失败：{exc}", file=sys.stderr)
                        stream_session.close()
                        stream_session = None
                        return 2
                    print(f"{elapsed:6.2f}s speech_end duration={stream_duration_seconds:.2f}s")
                    text = result.text if result.has_text else "（空结果）"
                    print(f"{elapsed:6.2f}s asr_text {text}")
                    stream_session = None
                    stream_duration_seconds = 0.0
                    last_partial_text = ""
                elif not transcribe_segment(
                    client=client,
                    segment=speech_end_event.segment.to_audio_chunk(),
                    language=language,
                    prompt=prompt,
                    prefix=f"{elapsed:6.2f}s",
                ):
                    return 2

            if elapsed >= duration_seconds:
                break
    finally:
        capture.stop()

    for event in segmenter.flush():
        if event.segment is not None:
            if stream_session is not None:
                try:
                    result = stream_session.finish(duration_seconds=stream_duration_seconds)
                except AsrError as exc:
                    print(f"flush ASR 流式识别结束失败：{exc}", file=sys.stderr)
                    stream_session.close()
                    stream_session = None
                    return 2
                print(f"flush speech_end duration={stream_duration_seconds:.2f}s")
                print(f"flush asr_text {result.text if result.has_text else '（空结果）'}")
                stream_session = None
                stream_duration_seconds = 0.0
                last_partial_text = ""
            elif not transcribe_segment(
                client=client,
                segment=event.segment.to_audio_chunk(),
                language=language,
                prompt=prompt,
                prefix="flush",
            ):
                return 2

    print(
        f"已处理 {chunk_count} 个音频块，最近缓冲 {buffer.duration_seconds:.2f}s，"
        f"丢弃旧块 {capture.dropped_chunks} 个。"
    )
    return 0


def supports_streaming_asr(client: AsrClient) -> bool:
    return callable(getattr(client, "start_stream", None))


def print_asr_stream_events(
    events,
    prefix: str,
    last_partial_text: str,
) -> str:
    current_partial = last_partial_text
    for event in events:
        if event.is_final:
            continue
        if not event.text or event.text == current_partial:
            continue
        current_partial = event.text
        print(f"{prefix} asr_partial {event.text}")
    return current_partial


def transcribe_segment(
    client: AsrClient,
    segment: AudioChunk,
    language: str,
    prompt: str,
    prefix: str,
) -> bool:
    try:
        result = client.transcribe(segment, language=language, prompt=prompt)
    except AsrError as exc:
        print(f"{prefix} ASR 识别失败：{exc}", file=sys.stderr)
        return False

    text = result.text if result.has_text else "（空结果）"
    print(f"{prefix} speech_end duration={segment.duration_seconds:.2f}s")
    print(f"{prefix} asr_text {text}")
    return True


def print_asr_result(result: AsrResult) -> None:
    mode = "mock" if result.is_mock else result.provider
    print(f"ASR 提供方：{mode}")
    print(f"语言：{result.language or 'unknown'}")
    print(f"音频时长：{result.duration_seconds:.2f}s")
    print(f"原文：{result.text if result.has_text else '（空结果）'}")
    if result.segments:
        print("分段：")
        for index, segment in enumerate(result.segments, start=1):
            start = _format_optional_seconds(segment.start_seconds)
            end = _format_optional_seconds(segment.end_seconds)
            print(f"  {index}. {start} -> {end} {segment.text}")


def _format_optional_seconds(value: float | None) -> str:
    if value is None:
        return "--"
    return f"{value:.2f}s"


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

