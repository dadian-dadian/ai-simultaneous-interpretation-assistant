from __future__ import annotations

import json
import queue
import threading
import time
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
    sentence_id: str = ""


@dataclass(frozen=True)
class BaiduRealtimeSessionConfig:
    provider_name: str
    language: str
    sample_rate: int
    frame_ms: int
    timeout_seconds: float


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

        session = self.start_stream(language=language, prompt=prompt, sample_rate=audio.sample_rate)
        try:
            session.send_audio(audio)
            return session.finish(duration_seconds=audio.duration_seconds)
        except Exception:
            session.close()
            raise

    def start_stream(
        self,
        *,
        language: str = "en",
        prompt: str = "",
        sample_rate: int = 16000,
    ) -> BaiduRealtimeAsrSession:
        if sample_rate != 16000:
            raise AsrError("百度实时 ASR WebSocket 固定要求 16000Hz PCM 音频。")

        sn = str(uuid.uuid4())
        try:
            connection = websocket.create_connection(
                f"{self.ws_url}?sn={sn}",
                timeout=self.timeout_seconds,
            )
        except websocket.WebSocketException as exc:
            raise AsrError(f"无法连接百度实时 ASR WebSocket：{exc}") from exc

        try:
            connection.send(
                json.dumps(
                    {
                        "type": "START",
                        "data": {
                            "appid": _parse_app_id(self.app_id),
                            "appkey": self.app_key,
                            "dev_pid": resolve_baidu_dev_pid(
                                language=language,
                                configured=self.dev_pid,
                            ),
                            "cuid": self.cuid,
                            "format": "pcm",
                            "sample": sample_rate,
                        },
                    },
                    ensure_ascii=False,
                )
            )
        except websocket.WebSocketException as exc:
            connection.close()
            raise AsrError(f"百度实时 ASR WebSocket START 发送失败：{exc}") from exc

        return BaiduRealtimeAsrSession(
            connection=connection,
            config=BaiduRealtimeSessionConfig(
                provider_name=self.provider_name,
                language=language,
                sample_rate=sample_rate,
                frame_ms=BAIDU_AUDIO_FRAME_MS,
                timeout_seconds=self.timeout_seconds,
            ),
        )


class BaiduRealtimeAsrSession:
    def __init__(
        self,
        *,
        connection,
        config: BaiduRealtimeSessionConfig,
    ) -> None:
        self.connection = connection
        self.config = config
        self._pending_pcm = b""
        self._transcripts: list[BaiduRealtimeTranscript] = []
        self._closed = False
        self._send_lock = threading.Lock()
        self._transcripts_lock = threading.Lock()
        self._received_events: queue.Queue[BaiduRealtimeTranscript] = queue.Queue()
        self._receive_error: AsrError | None = None
        self._receiver_done = threading.Event()
        self._receiver_thread = threading.Thread(
            target=self._receive_loop,
            name="baidu-realtime-asr-receiver",
            daemon=True,
        )
        self._frame_bytes = int(config.sample_rate * 2 * config.frame_ms / 1000)
        if self._frame_bytes <= 0:
            raise ValueError("frame_ms is too small")
        self._receiver_thread.start()

    def send_audio(self, audio: AudioChunk) -> list[BaiduRealtimeTranscript]:
        if self._closed:
            raise AsrError("百度实时 ASR WebSocket 会话已经关闭。")
        if audio.sample_rate != self.config.sample_rate:
            raise AsrError("音频采样率与百度实时 ASR 会话采样率不一致。")

        return self.send_pcm(_to_mono_pcm16(audio.samples))

    def send_pcm(self, pcm_payload: bytes) -> list[BaiduRealtimeTranscript]:
        if self._closed:
            raise AsrError("百度实时 ASR WebSocket 会话已经关闭。")

        self._pending_pcm += pcm_payload
        events: list[BaiduRealtimeTranscript] = []
        while len(self._pending_pcm) >= self._frame_bytes:
            frame = self._pending_pcm[: self._frame_bytes]
            self._pending_pcm = self._pending_pcm[self._frame_bytes :]
            try:
                with self._send_lock:
                    self.connection.send_binary(frame)
            except websocket.WebSocketException as exc:
                raise AsrError(f"百度实时 ASR WebSocket 音频发送失败：{exc}") from exc
            events.extend(self._drain_received_events())
        return events

    def finish(self, duration_seconds: float) -> AsrResult:
        if self._closed:
            return self._build_result(duration_seconds)

        try:
            with self._send_lock:
                if self._pending_pcm:
                    self.connection.send_binary(self._pending_pcm)
                    self._pending_pcm = b""
                self.connection.send(json.dumps({"type": "FINISH"}))
            self._wait_for_finish_events()
        except websocket.WebSocketException as exc:
            raise AsrError(f"百度实时 ASR WebSocket 结束失败：{exc}") from exc
        finally:
            self.close()
        return self._build_result(duration_seconds)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.connection.close()
        self._receiver_done.wait(timeout=0.5)

    def _build_result(self, duration_seconds: float) -> AsrResult:
        with self._transcripts_lock:
            transcripts = list(self._transcripts)
        final_segments = tuple(
            AsrTextSegment(
                text=item.text,
                start_seconds=item.start_seconds,
                end_seconds=item.end_seconds,
            )
            for item in transcripts
            if item.is_final and item.text
        )
        text = " ".join(segment.text.strip() for segment in final_segments if segment.text.strip())
        if not text:
            text = next(
                (
                    item.text.strip()
                    for item in reversed(transcripts)
                    if item.text.strip()
                ),
                "",
            )
        return AsrResult(
            text=text,
            language=self.config.language,
            provider=self.config.provider_name,
            duration_seconds=duration_seconds,
            segments=final_segments,
        )

    def _receive_loop(self) -> None:
        try:
            self.connection.settimeout(min(0.5, self.config.timeout_seconds))
            while not self._closed:
                try:
                    message = self.connection.recv()
                except websocket.WebSocketConnectionClosedException:
                    break
                except websocket.WebSocketTimeoutException:
                    continue
                except TimeoutError:
                    continue
                except OSError:
                    if self._closed:
                        break
                    raise

                if message in {"", b""}:
                    break
                for event in self._events_from_message(message):
                    self._received_events.put(event)
        except AsrError as exc:
            self._receive_error = exc
        except websocket.WebSocketException as exc:
            self._receive_error = AsrError(
                f"百度实时 ASR WebSocket 接收失败：{exc}"
            )
        finally:
            self._receiver_done.set()

    def _drain_received_events(self) -> list[BaiduRealtimeTranscript]:
        events: list[BaiduRealtimeTranscript] = []
        while True:
            try:
                events.append(self._received_events.get_nowait())
            except queue.Empty:
                break
        if self._receive_error is not None:
            error = self._receive_error
            self._receive_error = None
            raise error
        return events

    def _wait_for_finish_events(self) -> None:
        deadline = time.monotonic() + min(self.config.timeout_seconds, 2.5)
        idle_after_final_seconds = 0.35
        last_event_at = time.monotonic()
        seen_final = self._has_final_transcript() or any(
            event.is_final for event in self._drain_received_events()
        )
        while time.monotonic() < deadline:
            drained = self._drain_received_events()
            if drained:
                last_event_at = time.monotonic()
                seen_final = seen_final or any(event.is_final for event in drained)
            if self._receiver_done.is_set():
                return
            if seen_final and time.monotonic() - last_event_at >= idle_after_final_seconds:
                break
            time.sleep(0.02)

        with self._transcripts_lock:
            has_transcripts = bool(self._transcripts)
        if not has_transcripts and self._receive_error is not None:
            error = self._receive_error
            self._receive_error = None
            raise error
        if not has_transcripts:
            raise AsrError("百度实时 ASR WebSocket 等待识别结果超时。")

    def _has_final_transcript(self) -> bool:
        with self._transcripts_lock:
            return any(event.is_final for event in self._transcripts)

    def _events_from_message(self, message: str | bytes) -> list[BaiduRealtimeTranscript]:
        events: list[BaiduRealtimeTranscript] = []
        payload = _parse_ws_message(message)

        response_type = payload.get("type")
        if response_type == "HEARTBEAT":
            return events

        err_no = int(payload.get("err_no", 0))
        if err_no != 0:
            with self._transcripts_lock:
                has_transcripts = bool(self._transcripts)
            if err_no == -3005 and has_transcripts:
                return events
            err_msg = payload.get("err_msg") or "unknown error"
            if response_type == "START":
                raise AsrError(f"百度实时 ASR START 失败：err_no={err_no}，{err_msg}")
            raise AsrError(f"百度实时 ASR 识别失败：err_no={err_no}，{err_msg}")

        if response_type == "START":
            return events

        result = str(payload.get("result", "")).strip()
        sentence_id = str(payload.get("sn", "")).strip()
        if response_type == "MID_TEXT":
            event = BaiduRealtimeTranscript(
                text=result,
                is_final=False,
                sentence_id=sentence_id,
            )
            events.append(event)
            with self._transcripts_lock:
                self._transcripts.append(event)
        elif response_type == "FIN_TEXT":
            event = BaiduRealtimeTranscript(
                text=result,
                start_seconds=_milliseconds_to_seconds(payload.get("start_time")),
                end_seconds=_milliseconds_to_seconds(payload.get("end_time")),
                is_final=True,
                sentence_id=sentence_id,
            )
            events.append(event)
            with self._transcripts_lock:
                self._transcripts.append(event)

        return events


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
