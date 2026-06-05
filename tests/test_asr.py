import json
import unittest
from unittest.mock import patch

import numpy as np

from app.asr import (
    AsrConfigurationError,
    BaiduCloudAsrClient,
    MockAsrClient,
    create_asr_client,
)
from app.asr.baidu import resolve_baidu_dev_pid
from app.audio.capture import AudioChunk
from app.core.config import AppConfig


class FakeHttpResponse:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        return False

    def read(self) -> bytes:
        return self.payload


class MockAsrClientTest(unittest.TestCase):
    def test_mock_client_returns_deterministic_transcript(self) -> None:
        audio = AudioChunk(samples=np.zeros((16000, 1), dtype=np.float32), sample_rate=16000)

        result = MockAsrClient("Hello world").transcribe(audio, language="en")

        self.assertEqual(result.text, "Hello world")
        self.assertEqual(result.language, "en")
        self.assertTrue(result.is_mock)
        self.assertEqual(result.duration_seconds, 1.0)


class BaiduCloudAsrClientTest(unittest.TestCase):
    def test_client_posts_baidu_json_with_api_key_header(self) -> None:
        audio = AudioChunk(samples=np.zeros((16000, 1), dtype=np.float32), sample_rate=16000)
        response = FakeHttpResponse(b'{"err_no":0,"result":["hello world"],"sn":"test-sn"}')
        client = BaiduCloudAsrClient(api_key="api-key", cuid="test-cuid")

        with patch("app.asr.baidu.urllib.request.urlopen", return_value=response) as urlopen:
            result = client.transcribe(audio, language="en")

        request = urlopen.call_args.args[0]
        body = json.loads(request.data.decode())
        self.assertEqual(request.full_url, "http://vop.baidu.com/server_api")
        self.assertEqual(request.get_header("Authorization"), "Bearer api-key")
        self.assertEqual(body["format"], "pcm")
        self.assertEqual(body["rate"], 16000)
        self.assertEqual(body["channel"], 1)
        self.assertEqual(body["cuid"], "test-cuid")
        self.assertEqual(body["dev_pid"], 1737)
        self.assertGreater(body["len"], 0)
        self.assertNotIn("token", body)
        self.assertEqual(result.text, "hello world")
        self.assertEqual(result.language, "en")

    def test_client_can_fetch_access_token_with_secret_key(self) -> None:
        audio = AudioChunk(samples=np.zeros((16000, 1), dtype=np.float32), sample_rate=16000)
        token_response = FakeHttpResponse(b'{"access_token":"access-token"}')
        asr_response = FakeHttpResponse(b'{"err_no":0,"result":["hello world"]}')
        client = BaiduCloudAsrClient(api_key="api-key", secret_key="secret")

        with patch(
            "app.asr.baidu.urllib.request.urlopen",
            side_effect=[token_response, asr_response],
        ) as urlopen:
            result = client.transcribe(audio, language="en")

        token_request = urlopen.call_args_list[0].args[0]
        asr_request = urlopen.call_args_list[1].args[0]
        body = json.loads(asr_request.data.decode())
        self.assertIn("grant_type=client_credentials", token_request.full_url)
        self.assertEqual(body["token"], "access-token")
        self.assertIsNone(asr_request.get_header("Authorization"))
        self.assertEqual(result.text, "hello world")

    def test_client_raises_clear_error_for_baidu_failure(self) -> None:
        audio = AudioChunk(samples=np.zeros((16000, 1), dtype=np.float32), sample_rate=16000)
        response = FakeHttpResponse(b'{"err_no":3301,"err_msg":"audio quality error"}')
        client = BaiduCloudAsrClient(api_key="api-key")

        with patch("app.asr.baidu.urllib.request.urlopen", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "err_no=3301"):
                client.transcribe(audio, language="en")

    def test_client_requires_credential(self) -> None:
        with self.assertRaises(AsrConfigurationError):
            BaiduCloudAsrClient()

    def test_resolve_dev_pid_uses_english_model_for_english(self) -> None:
        self.assertEqual(resolve_baidu_dev_pid(language="en", configured="auto"), 1737)
        self.assertEqual(resolve_baidu_dev_pid(language="zh-CN", configured="auto"), 1537)
        self.assertEqual(resolve_baidu_dev_pid(language="en", configured="80001"), 80001)


class AsrFactoryTest(unittest.TestCase):
    def test_factory_returns_mock_client_by_default(self) -> None:
        client = create_asr_client(AppConfig())

        self.assertIsInstance(client, MockAsrClient)

    def test_factory_returns_baidu_cloud_client(self) -> None:
        config = AppConfig(asr_provider="baidu-cloud", asr_api_key="api-key")

        client = create_asr_client(config)

        self.assertIsInstance(client, BaiduCloudAsrClient)


if __name__ == "__main__":
    unittest.main()
