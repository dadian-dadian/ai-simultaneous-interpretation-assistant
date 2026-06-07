import http.client
import json
import unittest
from hashlib import md5
from urllib.parse import parse_qs
from urllib.request import Request

from app.core.config import AppConfig
from app.translate.baidu_mt import BaiduMtTranslationClient
from app.translate.factory import create_partial_translation_client
from app.translate.language_codes import to_baidu_mt_language
from app.translate.types import TranslationConfigurationError, TranslationError


class _FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")


class _FakeOpener:
    def __init__(self, responses: list[dict[str, object]]) -> None:
        self.responses = list(responses)
        self.requests: list[Request] = []

    def __call__(self, request: Request, *, timeout: float) -> _FakeResponse:
        self.requests.append(request)
        return _FakeResponse(self.responses.pop(0))


class _FakePersistentResponse:
    def __init__(self, payload: dict[str, object], status: int = 200) -> None:
        self.payload = payload
        self.status = status

    def read(self) -> bytes:
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")


class _FakePersistentConnection:
    def __init__(
        self,
        host: str,
        *,
        port: int | None,
        timeout: float,
        responses: list[dict[str, object]],
        fail_response: bool = False,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.responses = responses
        self.fail_response = fail_response
        self.requests: list[tuple[str, str, bytes, dict[str, str]]] = []
        self.closed = False
        self.connect_calls = 0

    def connect(self) -> None:
        self.connect_calls += 1

    def request(
        self,
        method: str,
        path: str,
        *,
        body: bytes,
        headers: dict[str, str],
    ) -> None:
        self.requests.append((method, path, body, headers))

    def getresponse(self) -> _FakePersistentResponse:
        if self.fail_response:
            self.fail_response = False
            raise http.client.RemoteDisconnected("connection closed")
        return _FakePersistentResponse(self.responses.pop(0))

    def close(self) -> None:
        self.closed = True


class _FakeConnectionFactory:
    def __init__(
        self,
        responses: list[dict[str, object]],
        *,
        fail_first_response: bool = False,
    ) -> None:
        self.responses = list(responses)
        self.fail_first_response = fail_first_response
        self.connections: list[_FakePersistentConnection] = []

    def __call__(
        self,
        host: str,
        *,
        port: int | None,
        timeout: float,
    ) -> _FakePersistentConnection:
        connection = _FakePersistentConnection(
            host,
            port=port,
            timeout=timeout,
            responses=self.responses,
            fail_response=self.fail_first_response and not self.connections,
        )
        self.connections.append(connection)
        return connection


class BaiduMtTranslationClientTest(unittest.TestCase):
    def test_language_codes_are_normalized_for_baidu_mt(self) -> None:
        self.assertEqual(to_baidu_mt_language("en-US"), "en")
        self.assertEqual(to_baidu_mt_language("zh-CN"), "zh")
        self.assertEqual(to_baidu_mt_language("zh_Hans"), "zh")

    def test_client_fetches_token_and_translates_text(self) -> None:
        opener = _FakeOpener(
            [
                {"access_token": "token-1", "expires_in": 3600},
                {
                    "result": {
                        "trans_result": [
                            {"src": "I loved that job.", "dst": "我喜欢那份工作。"}
                        ]
                    }
                },
            ]
        )
        client = BaiduMtTranslationClient(
            api_key="api",
            secret_key="secret",
            opener=opener,
        )

        result = client.translate("I loved that job.", "en-US", "zh-CN")

        self.assertEqual(result.translated_text, "我喜欢那份工作。")
        self.assertEqual(result.provider, "baidu-mt")
        self.assertEqual(len(opener.requests), 2)
        translate_body = json.loads(opener.requests[1].data.decode("utf-8"))
        self.assertEqual(translate_body["from"], "en")
        self.assertEqual(translate_body["to"], "zh")

    def test_token_is_cached(self) -> None:
        current_time = 1000.0
        opener = _FakeOpener(
            [
                {"access_token": "token-1", "expires_in": 3600},
                {"result": {"trans_result": [{"dst": "一"}]}},
                {"result": {"trans_result": [{"dst": "二"}]}},
            ]
        )
        client = BaiduMtTranslationClient(
            api_key="api",
            secret_key="secret",
            opener=opener,
            now=lambda: current_time,
        )

        client.translate("one", "en", "zh-CN")
        client.translate("two", "en", "zh-CN")

        self.assertEqual(len(opener.requests), 3)
        self.assertIn("access_token=token-1", opener.requests[1].full_url)
        self.assertIn("access_token=token-1", opener.requests[2].full_url)

    def test_app_id_mode_uses_baidu_fanyi_signature(self) -> None:
        opener = _FakeOpener(
            [
                {
                    "from": "en",
                    "to": "zh",
                    "trans_result": [{"src": "hello", "dst": "你好"}],
                }
            ]
        )
        client = BaiduMtTranslationClient(
            app_id="appid",
            api_key="",
            secret_key="secret",
            opener=opener,
            salt_factory=lambda: "salt",
        )

        result = client.translate("hello", "en", "zh-CN")

        self.assertEqual(result.translated_text, "你好")
        self.assertEqual(len(opener.requests), 1)
        payload = parse_qs(opener.requests[0].data.decode("utf-8"))
        expected_sign = md5(b"appidhellosaltsecret").hexdigest()
        self.assertEqual(payload["appid"], ["appid"])
        self.assertEqual(payload["salt"], ["salt"])
        self.assertEqual(payload["sign"], [expected_sign])

    def test_default_transport_reuses_persistent_https_connection(self) -> None:
        factory = _FakeConnectionFactory(
            [
                {"trans_result": [{"dst": "一"}]},
                {"trans_result": [{"dst": "二"}]},
            ]
        )
        client = BaiduMtTranslationClient(
            app_id="appid",
            api_key="",
            secret_key="secret",
            salt_factory=lambda: "salt",
            connection_factory=factory,
        )

        client.warm_up()
        first = client.translate("one", "en", "zh-CN")
        second = client.translate("two", "en", "zh-CN")
        client.close()

        self.assertEqual(first.translated_text, "一")
        self.assertEqual(second.translated_text, "二")
        self.assertEqual(len(factory.connections), 1)
        connection = factory.connections[0]
        self.assertEqual(len(connection.requests), 2)
        self.assertEqual(connection.connect_calls, 1)
        self.assertEqual(connection.requests[0][1], "/api/trans/vip/translate")
        self.assertEqual(connection.requests[0][3]["Connection"], "keep-alive")
        self.assertTrue(connection.closed)

    def test_persistent_transport_reconnects_after_remote_disconnect(self) -> None:
        factory = _FakeConnectionFactory(
            [{"trans_result": [{"dst": "你好"}]}],
            fail_first_response=True,
        )
        client = BaiduMtTranslationClient(
            app_id="appid",
            api_key="",
            secret_key="secret",
            connection_factory=factory,
        )

        result = client.translate("hello", "en", "zh-CN")
        client.close()

        self.assertEqual(result.translated_text, "你好")
        self.assertEqual(len(factory.connections), 2)
        self.assertTrue(factory.connections[0].closed)

    def test_missing_credentials_raise_configuration_error(self) -> None:
        with self.assertRaises(TranslationConfigurationError):
            BaiduMtTranslationClient(api_key="", secret_key="secret")
        with self.assertRaises(TranslationConfigurationError):
            BaiduMtTranslationClient(api_key="api", secret_key="")

    def test_translation_error_response_is_raised(self) -> None:
        opener = _FakeOpener(
            [
                {"access_token": "token-1", "expires_in": 3600},
                {"error_code": 336007, "error_msg": "unsupported language"},
            ]
        )
        client = BaiduMtTranslationClient(
            api_key="api",
            secret_key="secret",
            opener=opener,
        )

        with self.assertRaises(TranslationError):
            client.translate("hello", "en", "zh-CN")


class PartialTranslationFactoryTest(unittest.TestCase):
    def test_disabled_partial_translation_returns_none(self) -> None:
        client = create_partial_translation_client(AppConfig())

        self.assertIsNone(client)

    def test_baidu_mt_provider_creates_client(self) -> None:
        client = create_partial_translation_client(
            AppConfig(
                partial_translation_provider="baidu-mt",
                partial_translation_api_key="api",
                partial_translation_secret_key="secret",
            )
        )

        self.assertIsInstance(client, BaiduMtTranslationClient)


if __name__ == "__main__":
    unittest.main()
