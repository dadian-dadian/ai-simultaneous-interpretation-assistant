from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

import numpy as np
import websocket

from app.asr.types import AsrConfigurationError, AsrError, AsrResult, AsrTextSegment
from app.audio.capture import AudioChunk

BAIDU_REALTIME_ASR_WS_URL = "wss://vop.baidu.com/realtime_asr"
BAIDU_AUDIO_FRAME_MS = 160


@dataclass(frozen=True)
class BaiduRealtimeTranscript:
    text: str
    start_seconds: float | None = None
    end_seconds: float | None = None
    is_final: bool = False


class BaiduRealtimeAsrClient:
    provider_name = "baidu-realtime"

    def __init__(
        self,
        *,
        app_id: str = "",
        app_key: str = "",
        ws_url: str = BAIDU_REALTIME_ASR_WS_URL,
        cuid: str = "ai_interpreter_windows",
        dev_pid: str = "auto",
        timeout_seconds: float = 30.0,
    ) -> None:
        if not app_id:
            raise AsrConfigurationError("使用百度实时 ASR WebSocket 时需要设置 ASR_APP_ID。")
        if not app_key:
            raise AsrConfigurationError("使用百度实时 ASR WebSocket 时需要设置 ASR_API_KEY。")
        if not ws_url:
            raise AsrConfigurationError("ASR_BAIDU_WS_URL 不能为空。")
        if timeout_seconds <= 0:
            raise AsrConfigurationError("ASR_TIMEOUT_SECONDS 必须大于 0。")

        self.app_id = app_id
        self.app_key = app_key
        self.ws_url = ws_url.rstrip("?")
        self.cuid = cuid
        self.dev_pid = dev_pid
        self.timeout_seconds = timeout_seconds

    def transcribe(
        self,
        audio: AudioChunk,
        *,
        language: str = "en",
        prompt: str = "",
    ) -> AsrResult:
        if audio.sample_rate != 16000:
            raise AsrError("百度实时 ASR WebSocket 固定要求 16000Hz PCM 音频。")

        dev_pid = resolve_baidu_dev_pid(language=language, configured=self.dev_pid)
        pcm_payload = _to_mono_pcm16(audio.samples)
        transcripts = self._recognize_pcm(
            pcm_payload=pcm_payload,
            sample_rate=audio.sample_rate,
            dev_pid=dev_pid,
        )
        final_segments = tuple(
            AsrTextSegment(
                text=item.text,
                start_seconds=item.start_seconds,
                end_seconds=item.end_seconds,
            )
            for item in transcripts
            if item.is_final and item.text
        )
        text = "".join(segment.text for segment in final_segments).strip()
        return AsrResult(
            text=text,
            language=language,
            provider=self.provider_name,
            duration_seconds=audio.duration_seconds,
            segments=final_segments,
        )

    def _recognize_pcm(
        self,
        *,
        pcm_payload: bytes,
        sample_rate: int,
        dev_pid: int,
    ) -> list[BaiduRealtimeTranscript]:
        sn = str(uuid.uuid4())
        try:
            connection = websocket.create_connection(
                f"{self.ws_url}?sn={sn}",
                timeout=self.timeout_seconds,
            )
        except websocket.WebSocketException as exc:
            raise AsrError(f"无法连接百度实时 ASR WebSocket：{exc}") from exc

        transcripts: list[BaiduRealtimeTranscript] = []
        try:
            connection.send(
                json.dumps(
                    {
                        "type": "START",
                        "data": {
                            "appid": _parse_app_id(self.app_id),
                            "appkey": self.app_key,
                            "dev_pid": dev_pid,
                            "cuid": self.cuid,
                            "format": "pcm",
                            "sample": sample_rate,
                        },
                    },
                    ensure_ascii=False,
                )
            )
            for frame in _split_pcm_frames(
                pcm_payload,
                sample_rate=sample_rate,
                frame_ms=BAIDU_AUDIO_FRAME_MS,
            ):
                connection.send_binary(frame)
            connection.send(json.dumps({"type": "FINISH"}))
            transcripts.extend(self._receive_transcripts(connection))
        except websocket.WebSocketException as exc:
            raise AsrError(f"百度实时 ASR WebSocket 连接异常：{exc}") from exc
        finally:
            connection.close()
        return transcripts

    def _receive_transcripts(self, connection) -> list[BaiduRealtimeTranscript]:
        transcripts: list[BaiduRealtimeTranscript] = []
        while True:
            try:
                message = connection.recv()
            except websocket.WebSocketConnectionClosedException:
                break
            except websocket.WebSocketTimeoutException:
                if transcripts:
                    break
                raise AsrError("百度实时 ASR WebSocket 等待识别结果超时。") from None

            if message in {"", b""}:
                break
            payload = _parse_ws_message(message)

            response_type = payload.get("type")
            if response_type == "HEARTBEAT":
                continue

            err_no = int(payload.get("err_no", 0))
            if err_no != 0:
                err_msg = payload.get("err_msg") or "unknown error"
                if response_type == "START":
                    raise AsrError(f"百度实时 ASR START 失败：err_no={err_no}，{err_msg}")
                raise AsrError(f"百度实时 ASR 识别失败：err_no={err_no}，{err_msg}")

            if response_type == "START":
                continue

            result = str(payload.get("result", "")).strip()
            if response_type == "MID_TEXT":
                transcripts.append(BaiduRealtimeTranscript(text=result, is_final=False))
            elif response_type == "FIN_TEXT":
                transcripts.append(
                    BaiduRealtimeTranscript(
                        text=result,
                        start_seconds=_milliseconds_to_seconds(payload.get("start_time")),
                        end_seconds=_milliseconds_to_seconds(payload.get("end_time")),
                        is_final=True,
                    )
                )

        return transcripts


def resolve_baidu_dev_pid(*, language: str, configured: str) -> int:
    value = configured.strip().lower()
    if value and value != "auto":
        try:
            return int(value)
        except ValueError as exc:
            raise AsrConfigurationError("ASR_BAIDU_DEV_PID 必须是整数或 auto。") from exc

    lang = language.strip().lower()
    if lang in {"en", "en-us", "en-gb", "english"}:
        return 17372
    if lang in {"yue", "ct", "cantonese", "sc", "sichuan", "sichuanese"}:
        return 15376
    return 15372


def _parse_ws_message(message: str | bytes) -> dict[str, Any]:
    if isinstance(message, bytes):
        message = message.decode("utf-8", errors="replace")
    try:
        payload = json.loads(message)
    except json.JSONDecodeError as exc:
        raise AsrError("百度实时 ASR WebSocket 返回的内容不是有效 JSON。") from exc
    if not isinstance(payload, dict):
        raise AsrError("百度实时 ASR WebSocket 返回的 JSON 结构不符合预期。")
    return payload


def _parse_app_id(value: str) -> int:
    try:
        return int(value)
    except ValueError as exc:
        raise AsrConfigurationError("ASR_APP_ID 必须是百度控制台中的整数 AppID。") from exc


def _milliseconds_to_seconds(value: Any) -> float | None:
    try:
        return float(value) / 1000
    except (TypeError, ValueError):
        return None


def _split_pcm_frames(pcm_payload: bytes, *, sample_rate: int, frame_ms: int) -> list[bytes]:
    bytes_per_frame = int(sample_rate * 2 * frame_ms / 1000)
    if bytes_per_frame <= 0:
        raise ValueError("frame_ms is too small")
    return [
        pcm_payload[start : start + bytes_per_frame]
        for start in range(0, len(pcm_payload), bytes_per_frame)
        if pcm_payload[start : start + bytes_per_frame]
    ]


def _to_mono_pcm16(samples: np.ndarray) -> bytes:
    data = np.asarray(samples, dtype=np.float32)
    if data.ndim == 2 and data.shape[1] > 1:
        data = np.mean(data, axis=1, dtype=np.float32)
    else:
        data = data.reshape(-1)

    clipped = np.clip(data, -1.0, 1.0)
    pcm = (clipped * 32767).astype(np.int16)
    return pcm.tobytes()
