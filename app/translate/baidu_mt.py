from __future__ import annotations

import hashlib
import http.client
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from app.translate.language_codes import to_baidu_mt_language
from app.translate.types import (
    TranslationConfigurationError,
    TranslationError,
    TranslationResult,
)

DEFAULT_TOKEN_URL = "https://aip.baidubce.com/oauth/2.0/token"
DEFAULT_TRANSLATE_URL = "https://aip.baidubce.com/rpc/2.0/mt/texttrans/v1"
DEFAULT_FANYI_TRANSLATE_URL = "https://api.fanyi.baidu.com/api/trans/vip/translate"


@dataclass
class _AccessToken:
    value: str
    expires_at: float


class BaiduMtTranslationClient:
    provider = "baidu-mt"

    def __init__(
        self,
        *,
        api_key: str,
        secret_key: str,
        app_id: str = "",
        timeout_seconds: float = 10.0,
        token_url: str = DEFAULT_TOKEN_URL,
        translate_url: str = DEFAULT_TRANSLATE_URL,
        fanyi_translate_url: str = DEFAULT_FANYI_TRANSLATE_URL,
        opener: Any = urlopen,
        connection_factory: Any = http.client.HTTPSConnection,
        now: Any = time.time,
        salt_factory: Any = None,
    ) -> None:
        if not app_id.strip() and not api_key.strip():
            raise TranslationConfigurationError(
                "PARTIAL_TRANSLATION_API_KEY or PARTIAL_TRANSLATION_APP_ID is required "
                "for baidu-mt"
            )
        if not secret_key.strip():
            raise TranslationConfigurationError(
                "PARTIAL_TRANSLATION_SECRET_KEY is required for baidu-mt"
            )

        self.api_key = api_key.strip()
        self.secret_key = secret_key.strip()
        self.app_id = app_id.strip()
        self.timeout_seconds = timeout_seconds
        self.token_url = token_url
        self.translate_url = translate_url
        self.fanyi_translate_url = fanyi_translate_url
        self._opener = opener
        self._connection_factory = connection_factory
        self._persistent_http = opener is urlopen
        self._connections: dict[str, http.client.HTTPSConnection] = {}
        self._now = now
        self._salt_factory = salt_factory or (lambda: secrets.token_hex(8))
        self._token: _AccessToken | None = None

    def translate(
        self,
        text: str,
        source_language: str,
        target_language: str,
    ) -> TranslationResult:
        source_text = text.strip()
        if not source_text:
            return TranslationResult(
                source_text=text,
                translated_text="",
                source_language=source_language,
                target_language=target_language,
                provider=self.provider,
            )

        if self.app_id:
            response = self._post_form(
                self.fanyi_translate_url,
                self._build_fanyi_payload(
                    source_text,
                    source_language,
                    target_language,
                ),
            )
        else:
            payload = {
                "q": source_text,
                "from": to_baidu_mt_language(source_language),
                "to": to_baidu_mt_language(target_language),
            }
            response = self._post_json(
                f"{self.translate_url}?access_token={self._get_access_token()}",
                payload,
            )
        translated_text = self._parse_translation_response(response)
        return TranslationResult(
            source_text=source_text,
            translated_text=translated_text,
            source_language=source_language,
            target_language=target_language,
            provider=self.provider,
        )

    def _get_access_token(self) -> str:
        now = self._now()
        if self._token is not None and self._token.expires_at > now:
            return self._token.value

        response = self._post_form(
            self.token_url,
            {
                "grant_type": "client_credentials",
                "client_id": self.api_key,
                "client_secret": self.secret_key,
            },
        )
        access_token = str(response.get("access_token", "")).strip()
        if not access_token:
            message = response.get("error_description") or response.get("error") or response
            raise TranslationError(f"Baidu MT token request failed: {message}")

        expires_in = _safe_float(response.get("expires_in"), default=2592000.0)
        self._token = _AccessToken(
            value=access_token,
            expires_at=now + max(60.0, expires_in - 60.0),
        )
        return access_token

    def _build_fanyi_payload(
        self,
        text: str,
        source_language: str,
        target_language: str,
    ) -> dict[str, str]:
        salt = str(self._salt_factory())
        sign_source = f"{self.app_id}{text}{salt}{self.secret_key}"
        sign = hashlib.md5(sign_source.encode("utf-8")).hexdigest()  # noqa: S324
        return {
            "q": text,
            "from": to_baidu_mt_language(source_language),
            "to": to_baidu_mt_language(target_language),
            "appid": self.app_id,
            "salt": salt,
            "sign": sign,
        }

    def _post_form(self, url: str, payload: dict[str, str]) -> dict[str, Any]:
        body = "&".join(
            f"{_quote_url_part(key)}={_quote_url_part(value)}"
            for key, value in payload.items()
        ).encode("utf-8")
        if self._persistent_http:
            return self._open_persistent_json(
                url,
                body=body,
                content_type="application/x-www-form-urlencoded",
            )
        request = Request(
            url,
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        return self._open_json(request)

    def _post_json(self, url: str, payload: dict[str, str]) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if self._persistent_http:
            return self._open_persistent_json(
                url,
                body=body,
                content_type="application/json; charset=utf-8",
            )
        request = Request(
            url,
            data=body,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        return self._open_json(request)

    def _open_json(self, request: Request) -> dict[str, Any]:
        try:
            with self._opener(request, timeout=self.timeout_seconds) as response:
                body = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise TranslationError(f"Baidu MT HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise TranslationError(f"Baidu MT network error: {exc.reason}") from exc
        except OSError as exc:
            raise TranslationError(f"Baidu MT request failed: {exc}") from exc

        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as exc:
            raise TranslationError("Baidu MT returned invalid JSON") from exc
        if not isinstance(parsed, dict):
            raise TranslationError("Baidu MT returned an unexpected response")
        return parsed

    def close(self) -> None:
        connections = list(self._connections.values())
        self._connections.clear()
        for connection in connections:
            connection.close()

    def warm_up(self) -> None:
        if not self._persistent_http:
            return
        url = self.fanyi_translate_url if self.app_id else self.token_url
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname:
            return
        connection = self._persistent_connection(parsed.hostname, parsed.port)
        try:
            connection.connect()
        except (OSError, TimeoutError, http.client.HTTPException):
            self._discard_connection(parsed.hostname)

    def _open_persistent_json(
        self,
        url: str,
        *,
        body: bytes,
        content_type: str,
    ) -> dict[str, Any]:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise TranslationError("Baidu MT persistent transport requires HTTPS")
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"

        last_error: Exception | None = None
        for attempt in range(2):
            try:
                connection = self._persistent_connection(
                    parsed.hostname,
                    parsed.port,
                )
                connection.request(
                    "POST",
                    path,
                    body=body,
                    headers={
                        "Content-Type": content_type,
                        "Connection": "keep-alive",
                    },
                )
                response = connection.getresponse()
                payload = response.read().decode("utf-8")
                if response.status >= 400:
                    raise TranslationError(
                        f"Baidu MT HTTP {response.status}: {payload}"
                    )
                return _parse_json_object(payload)
            except TranslationError:
                raise
            except (OSError, TimeoutError, http.client.HTTPException) as exc:
                last_error = exc
                self._discard_connection(parsed.hostname)
                if attempt == 0:
                    continue
        raise TranslationError(f"Baidu MT request failed: {last_error}") from last_error

    def _persistent_connection(
        self,
        hostname: str,
        port: int | None,
    ) -> http.client.HTTPSConnection:
        connection = self._connections.get(hostname)
        if connection is None:
            connection = self._connection_factory(
                hostname,
                port=port,
                timeout=self.timeout_seconds,
            )
            self._connections[hostname] = connection
        return connection

    def _discard_connection(self, hostname: str) -> None:
        connection = self._connections.pop(hostname, None)
        if connection is not None:
            connection.close()

    @staticmethod
    def _parse_translation_response(response: dict[str, Any]) -> str:
        if "error_code" in response:
            message = response.get("error_msg") or response
            raise TranslationError(f"Baidu MT translation failed: {message}")

        result = response.get("result", response)
        if not isinstance(result, dict):
            raise TranslationError("Baidu MT response is missing result")
        trans_result = result.get("trans_result")
        if not isinstance(trans_result, list):
            raise TranslationError("Baidu MT response is missing trans_result")

        translated_lines = [
            str(item.get("dst", "")).strip()
            for item in trans_result
            if isinstance(item, dict) and str(item.get("dst", "")).strip()
        ]
        if not translated_lines:
            raise TranslationError("Baidu MT response did not include translated text")
        return "\n".join(translated_lines)


def _quote_url_part(value: str) -> str:
    from urllib.parse import quote_plus

    return quote_plus(value)


def _safe_float(value: Any, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_json_object(body: str) -> dict[str, Any]:
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise TranslationError("Baidu MT returned invalid JSON") from exc
    if not isinstance(parsed, dict):
        raise TranslationError("Baidu MT returned an unexpected response")
    return parsed
