from __future__ import annotations

import json
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Any

from app.asr.types import AsrConfigurationError, AsrError, AsrResult, AsrTextSegment
from app.audio.capture import AudioChunk


@dataclass(frozen=True)
class MultipartFile:
    field_name: str
    filename: str
    content_type: str
    payload: bytes


class OpenAICompatibleAsrClient:
    provider_name = "openai-compatible"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        model: str = "gpt-4o-mini-transcribe",
        response_format: str = "json",
        timeout_seconds: float = 30.0,
    ) -> None:
        if not api_key:
            raise AsrConfigurationError("使用真实 ASR 服务时需要设置 ASR_API_KEY。")
        if not base_url:
            raise AsrConfigurationError("ASR_BASE_URL 不能为空。")
        if not model:
            raise AsrConfigurationError("ASR_MODEL 不能为空。")
        if timeout_seconds <= 0:
            raise AsrConfigurationError("ASR_TIMEOUT_SECONDS 必须大于 0。")

        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.response_format = response_format
        self.timeout_seconds = timeout_seconds

    def transcribe(
        self,
        audio: AudioChunk,
        *,
        language: str = "en",
        prompt: str = "",
    ) -> AsrResult:
        fields = {
            "model": self.model,
            "response_format": self.response_format,
        }
        if language:
            fields["language"] = language
        if prompt:
            fields["prompt"] = prompt

        payload = self._post_transcription(
            fields=fields,
            file=MultipartFile(
                field_name="file",
                filename="speech.wav",
                content_type="audio/wav",
                payload=audio.to_wav_bytes(),
            ),
        )
        return self._parse_result(payload, audio=audio, fallback_language=language)

    def _post_transcription(self, fields: dict[str, str], file: MultipartFile) -> bytes:
        boundary = uuid.uuid4().hex
        body = _encode_multipart(fields=fields, file=file, boundary=boundary)
        request = urllib.request.Request(
            url=f"{self.base_url}/audio/transcriptions",
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Accept": "application/json, text/plain",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace").strip()
            raise AsrError(f"ASR 服务返回错误 HTTP {exc.code}：{detail}") from exc
        except urllib.error.URLError as exc:
            raise AsrError(f"无法连接 ASR 服务：{exc.reason}") from exc

    def _parse_result(
        self,
        payload: bytes,
        *,
        audio: AudioChunk,
        fallback_language: str,
    ) -> AsrResult:
        body = payload.decode("utf-8", errors="replace").strip()
        if self.response_format == "text":
            return AsrResult(
                text=body,
                language=fallback_language,
                provider=self.provider_name,
                duration_seconds=audio.duration_seconds,
            )

        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            raise AsrError("ASR 服务返回的内容不是有效 JSON。") from exc

        if not isinstance(data, dict):
            raise AsrError("ASR 服务返回的 JSON 结构不符合预期。")

        text = str(data.get("text", "")).strip()
        language = str(data.get("language") or fallback_language)
        duration_seconds = _float_or_default(data.get("duration"), audio.duration_seconds)
        segments = tuple(_parse_segments(data.get("segments")))
        return AsrResult(
            text=text,
            language=language,
            provider=self.provider_name,
            duration_seconds=duration_seconds,
            segments=segments,
        )


def _encode_multipart(
    *,
    fields: dict[str, str],
    file: MultipartFile,
    boundary: str,
) -> bytes:
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("utf-8"),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"),
                str(value).encode("utf-8"),
                b"\r\n",
            ]
        )

    chunks.extend(
        [
            f"--{boundary}\r\n".encode("utf-8"),
            (
                f'Content-Disposition: form-data; name="{file.field_name}"; '
                f'filename="{file.filename}"\r\n'
            ).encode("utf-8"),
            f"Content-Type: {file.content_type}\r\n\r\n".encode("utf-8"),
            file.payload,
            b"\r\n",
            f"--{boundary}--\r\n".encode("utf-8"),
        ]
    )
    return b"".join(chunks)


def _parse_segments(value: Any) -> list[AsrTextSegment]:
    if not isinstance(value, list):
        return []

    segments: list[AsrTextSegment] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "")).strip()
        if not text:
            continue
        segments.append(
            AsrTextSegment(
                text=text,
                start_seconds=_float_or_none(item.get("start")),
                end_seconds=_float_or_none(item.get("end")),
                confidence=_float_or_none(item.get("confidence")),
            )
        )
    return segments


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _float_or_default(value: Any, default: float) -> float:
    parsed = _float_or_none(value)
    if parsed is None:
        return default
    return parsed
