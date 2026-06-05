from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

import numpy as np

from app.asr.types import AsrConfigurationError, AsrError, AsrResult, AsrTextSegment
from app.audio.capture import AudioChunk

BAIDU_STANDARD_ASR_ENDPOINT = "http://vop.baidu.com/server_api"
BAIDU_TOKEN_ENDPOINT = "https://aip.baidubce.com/oauth/2.0/token"


@dataclass(frozen=True)
class BaiduAsrPayload:
    body: bytes
    headers: dict[str, str]


class BaiduCloudAsrClient:
    provider_name = "baidu-cloud"

    def __init__(
        self,
        *,
        api_key: str = "",
        secret_key: str = "",
        access_token: str = "",
        endpoint: str = BAIDU_STANDARD_ASR_ENDPOINT,
        token_endpoint: str = BAIDU_TOKEN_ENDPOINT,
        cuid: str = "ai_interpreter_windows",
        dev_pid: str = "auto",
        timeout_seconds: float = 30.0,
    ) -> None:
        if not api_key and not access_token:
            raise AsrConfigurationError(
                "使用百度云 ASR 时需要设置 ASR_API_KEY，或直接设置 ASR_ACCESS_TOKEN。"
            )
        if not endpoint:
            raise AsrConfigurationError("ASR_BAIDU_ENDPOINT 不能为空。")
        if timeout_seconds <= 0:
            raise AsrConfigurationError("ASR_TIMEOUT_SECONDS 必须大于 0。")

        self.api_key = api_key
        self.secret_key = secret_key
        self._access_token = access_token
        self.endpoint = endpoint
        self.token_endpoint = token_endpoint
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
            raise AsrError("百度短语音识别当前仅支持 16000Hz 或 8000Hz，本项目默认使用 16000Hz。")

        pcm_payload = _to_mono_pcm16(audio.samples)
        dev_pid = resolve_baidu_dev_pid(language=language, configured=self.dev_pid)
        payload = self._build_payload(
            pcm_payload=pcm_payload,
            sample_rate=audio.sample_rate,
            dev_pid=dev_pid,
        )
        response = self._post_json(payload)
        text = _parse_baidu_result(response)
        return AsrResult(
            text=text,
            language=language,
            provider=self.provider_name,
            duration_seconds=audio.duration_seconds,
            segments=(
                AsrTextSegment(
                    text=text,
                    start_seconds=0.0,
                    end_seconds=audio.duration_seconds,
                ),
            )
            if text
            else (),
        )

    def _build_payload(
        self,
        *,
        pcm_payload: bytes,
        sample_rate: int,
        dev_pid: int,
    ) -> BaiduAsrPayload:
        request_body: dict[str, Any] = {
            "format": "pcm",
            "rate": sample_rate,
            "channel": 1,
            "cuid": self.cuid,
            "dev_pid": dev_pid,
            "speech": base64.b64encode(pcm_payload).decode(),
            "len": len(pcm_payload),
        }
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        token = self._get_access_token_if_needed()
        if token:
            request_body["token"] = token
        else:
            headers["Authorization"] = f"Bearer {self.api_key}"

        return BaiduAsrPayload(
            body=json.dumps(request_body, ensure_ascii=False).encode(),
            headers=headers,
        )

    def _get_access_token_if_needed(self) -> str:
        if self._access_token:
            return self._access_token
        if not self.secret_key:
            return ""

        query = urllib.parse.urlencode(
            {
                "grant_type": "client_credentials",
                "client_id": self.api_key,
                "client_secret": self.secret_key,
            }
        )
        request = urllib.request.Request(
            url=f"{self.token_endpoint}?{query}",
            data=b"",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace").strip()
            raise AsrError(f"百度云 ASR token 获取失败 HTTP {exc.code}：{detail}") from exc
        except urllib.error.URLError as exc:
            raise AsrError(f"无法连接百度云 ASR 鉴权服务：{exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise AsrError("百度云 ASR token 接口返回的内容不是有效 JSON。") from exc

        token = str(data.get("access_token", "")).strip()
        if not token:
            error = data.get("error") or "unknown_error"
            description = data.get("error_description") or "未返回 access_token"
            raise AsrError(f"百度云 ASR token 获取失败：{error}，{description}")

        self._access_token = token
        return token

    def _post_json(self, payload: BaiduAsrPayload) -> dict[str, Any]:
        request = urllib.request.Request(
            url=self.endpoint,
            data=payload.body,
            headers=payload.headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                body = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace").strip()
            raise AsrError(f"百度云 ASR 服务返回错误 HTTP {exc.code}：{detail}") from exc
        except urllib.error.URLError as exc:
            raise AsrError(f"无法连接百度云 ASR 服务：{exc.reason}") from exc

        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            raise AsrError("百度云 ASR 服务返回的内容不是有效 JSON。") from exc
        if not isinstance(data, dict):
            raise AsrError("百度云 ASR 服务返回的 JSON 结构不符合预期。")
        return data


def resolve_baidu_dev_pid(*, language: str, configured: str) -> int:
    value = configured.strip().lower()
    if value and value != "auto":
        try:
            return int(value)
        except ValueError as exc:
            raise AsrConfigurationError("ASR_BAIDU_DEV_PID 必须是整数或 auto。") from exc

    lang = language.strip().lower()
    if lang in {"en", "en-us", "en-gb", "english"}:
        return 1737
    if lang in {"yue", "ct", "cantonese"}:
        return 1637
    if lang in {"sc", "sichuan", "sichuanese"}:
        return 1837
    return 1537


def _parse_baidu_result(data: dict[str, Any]) -> str:
    err_no = int(data.get("err_no", -1))
    if err_no != 0:
        err_msg = data.get("err_msg") or "unknown error"
        sn = data.get("sn") or ""
        suffix = f"，sn={sn}" if sn else ""
        raise AsrError(f"百度云 ASR 识别失败：err_no={err_no}，{err_msg}{suffix}")

    result = data.get("result")
    if not isinstance(result, list) or not result:
        return ""
    return str(result[0]).strip()


def _to_mono_pcm16(samples: np.ndarray) -> bytes:
    data = np.asarray(samples, dtype=np.float32)
    if data.ndim == 2 and data.shape[1] > 1:
        data = np.mean(data, axis=1, dtype=np.float32)
    else:
        data = data.reshape(-1)

    clipped = np.clip(data, -1.0, 1.0)
    pcm = (clipped * 32767).astype(np.int16)
    return pcm.tobytes()
