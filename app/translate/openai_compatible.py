from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Iterator
from typing import Any

from app.translate.types import (
    TranslationConfigurationError,
    TranslationError,
    TranslationRequest,
    TranslationResult,
)


class OpenAICompatibleTranslator:
    provider_name = "openai-compatible"

    def __init__(
        self,
        *,
        api_key: str = "",
        base_url: str = "",
        model: str = "",
        timeout_seconds: float = 30.0,
    ) -> None:
        if not api_key:
            raise TranslationConfigurationError(
                "使用真实翻译模型时需要设置 TRANSLATION_API_KEY。"
            )
        if not base_url:
            raise TranslationConfigurationError("TRANSLATION_BASE_URL 不能为空。")
        if not model:
            raise TranslationConfigurationError("TRANSLATION_MODEL 不能为空。")
        if timeout_seconds <= 0:
            raise TranslationConfigurationError("TRANSLATION_TIMEOUT_SECONDS 必须大于 0。")

        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds

    def translate(self, request: TranslationRequest) -> TranslationResult:
        source_text = _normalize_text(request.source_text)
        if not source_text:
            return TranslationResult(
                text="",
                provider=self.provider_name,
                model=self.model,
                source_language=request.source_language,
                target_language=request.target_language,
            )

        payload = _build_chat_completion_payload(
            model=self.model,
            request=request,
            source_text=source_text,
            stream=False,
        )

        response = self._post_json(_chat_completions_url(self.base_url), payload)
        translated_text = _extract_translation_text(response)
        return TranslationResult(
            text=translated_text,
            provider=self.provider_name,
            model=self.model,
            source_language=request.source_language,
            target_language=request.target_language,
        )

    def stream_translate(self, request: TranslationRequest) -> Iterator[str]:
        source_text = _normalize_text(request.source_text)
        if not source_text:
            return

        payload = _build_chat_completion_payload(
            model=self.model,
            request=request,
            source_text=source_text,
            stream=True,
        )
        for chunk in self._post_stream(_chat_completions_url(self.base_url), payload):
            delta = _extract_stream_delta(chunk)
            if delta:
                yield delta

    def _post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        request = self._build_request(url, payload, accept="application/json")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                response_body = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise TranslationError(
                f"翻译接口返回 HTTP {exc.code}：{_shorten_error_body(error_body)}"
            ) from exc
        except urllib.error.URLError as exc:
            raise TranslationError(f"无法连接翻译接口：{exc.reason}") from exc
        except TimeoutError as exc:
            raise TranslationError("翻译接口请求超时。") from exc

        try:
            parsed = json.loads(response_body)
        except json.JSONDecodeError as exc:
            raise TranslationError("翻译接口返回的内容不是有效 JSON。") from exc
        if not isinstance(parsed, dict):
            raise TranslationError("翻译接口返回的 JSON 结构不符合预期。")
        return parsed

    def _post_stream(self, url: str, payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
        request = self._build_request(url, payload, accept="text/event-stream")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                while True:
                    raw_line = response.readline()
                    if not raw_line:
                        break
                    event_payload = _parse_sse_line(raw_line)
                    if event_payload is None:
                        continue
                    if event_payload == "[DONE]":
                        break
                    try:
                        parsed = json.loads(event_payload)
                    except json.JSONDecodeError as exc:
                        raise TranslationError("翻译接口返回的流式内容不是有效 JSON。") from exc
                    if not isinstance(parsed, dict):
                        raise TranslationError("翻译接口返回的流式 JSON 结构不符合预期。")
                    yield parsed
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise TranslationError(
                f"翻译接口返回 HTTP {exc.code}：{_shorten_error_body(error_body)}"
            ) from exc
        except urllib.error.URLError as exc:
            raise TranslationError(f"无法连接翻译接口：{exc.reason}") from exc
        except TimeoutError as exc:
            raise TranslationError("翻译接口请求超时。") from exc

    def _build_request(
        self,
        url: str,
        payload: dict[str, Any],
        *,
        accept: str,
    ) -> urllib.request.Request:
        request = urllib.request.Request(
            url=url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": accept,
            },
            method="POST",
        )
        return request


def _build_chat_completion_payload(
    *,
    model: str,
    request: TranslationRequest,
    source_text: str,
    stream: bool,
) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": _build_system_prompt(
                    source_language=request.source_language,
                    target_language=request.target_language,
                ),
            },
            {
                "role": "user",
                "content": _build_user_prompt(source_text, request.context),
            },
        ],
        "temperature": 0.2,
        "stream": stream,
    }


def _build_system_prompt(source_language: str, target_language: str) -> str:
    return (
        "你是一个专业的同声传译字幕翻译器。"
        f"请将 {source_language} 内容翻译为 {target_language}。"
        "要求：只输出译文，不解释；表达自然、简洁；保留必要的技术术语；"
        "不要添加原文中没有的信息。"
    )


def _build_user_prompt(source_text: str, context: tuple[str, ...]) -> str:
    if not context:
        return f"待翻译原文：\n{source_text}"

    context_lines = "\n".join(f"- {item}" for item in context if item.strip())
    return f"上下文（仅供理解，不要翻译这一部分）：\n{context_lines}\n\n待翻译原文：\n{source_text}"


def _chat_completions_url(base_url: str) -> str:
    if base_url.endswith("/chat/completions"):
        return base_url
    return f"{base_url}/chat/completions"


def _extract_translation_text(response: dict[str, Any]) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise TranslationError("翻译接口响应缺少 choices。")

    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        raise TranslationError("翻译接口响应 choices 结构不符合预期。")
    message = first_choice.get("message")
    if not isinstance(message, dict):
        raise TranslationError("翻译接口响应缺少 message。")
    content = message.get("content")
    if not isinstance(content, str):
        raise TranslationError("翻译接口响应缺少文本 content。")
    return _normalize_text(content)


def _extract_stream_delta(response: dict[str, Any]) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""

    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        return ""
    delta = first_choice.get("delta")
    if isinstance(delta, dict):
        content = delta.get("content")
        if isinstance(content, str):
            return content

    message = first_choice.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content
    return ""


def _parse_sse_line(raw_line: bytes) -> str | None:
    line = raw_line.decode("utf-8", errors="replace").strip()
    if not line or line.startswith(":"):
        return None
    if not line.startswith("data:"):
        return None
    return line.removeprefix("data:").strip()


def _normalize_text(text: str) -> str:
    return " ".join(text.strip().split())


def _shorten_error_body(text: str, limit: int = 300) -> str:
    normalized = _normalize_text(text)
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[:limit]}..."
