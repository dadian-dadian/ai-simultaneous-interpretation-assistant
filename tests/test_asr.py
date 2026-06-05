import json
import unittest
from unittest.mock import patch

import numpy as np
import websocket

from app.asr import (
    AsrConfigurationError,
    BaiduRealtimeAsrClient,
    MockAsrClient,
    create_asr_client,
)
from app.asr.baidu import resolve_baidu_dev_pid
from app.audio.capture import AudioChunk
from app.core.config import AppConfig


class FakeWebSocket:
    def __init__(self, messages: list[str]) -> None:
        self.messages = messages
        self.text_frames: list[str] = []
        self.binary_frames: list[bytes] = []
        self.closed = False

    def send(self, payload: str) -> None:
        self.text_frames.append(payload)

    def send_binary(self, payload: bytes) -> None:
        self.binary_frames.append(payload)

    def recv(self) -> str:
        if not self.messages:
            raise websocket.WebSocketConnectionClosedException("closed")
        return self.messages.pop(0)

    def close(self) -> None:
        self.closed = True


class MockAsrClientTest(unittest.TestCase):
    def test_mock_client_returns_deterministic_transcript(self) -> None:
        audio = AudioChunk(samples=np.zeros((16000, 1), dtype=np.float32), sample_rate=16000)

        result = MockAsrClient("Hello world").transcribe(audio, language="en")

        self.assertEqual(result.text, "Hello world")
        self.assertEqual(result.language, "en")
        self.assertTrue(result.is_mock)
        self.assertEqual(result.duration_seconds, 1.0)


class BaiduRealtimeAsrClientTest(unittest.TestCase):
    def test_client_sends_start_audio_and_finish_frames(self) -> None:
        audio = AudioChunk(samples=np.zeros((16000, 1), dtype=np.float32), sample_rate=16000)
        fake_ws = FakeWebSocket(
            messages=[
                '{"type":"START","err_no":0}',
                '{"type":"MID_TEXT","err_no":0,"result":"hello"}',
                '{"type":"FIN_TEXT","err_no":0,"result":"hello world",'
                '"start_time":0,"end_time":1000}',
            ]
        )
        client = BaiduRealtimeAsrClient(app_id="123", app_key="app-key", cuid="test-cuid")

        with patch("app.asr.baidu.websocket.create_connection", return_value=fake_ws) as connect:
            result = client.transcribe(audio, language="en")

        self.assertTrue(connect.call_args.args[0].startswith("wss://vop.baidu.com/realtime_asr?sn="))
        start_frame = json.loads(fake_ws.text_frames[0])
        finish_frame = json.loads(fake_ws.text_frames[-1])
        self.assertEqual(start_frame["type"], "START")
        self.assertEqual(start_frame["data"]["appid"], 123)
        self.assertEqual(start_frame["data"]["appkey"], "app-key")
        self.assertEqual(start_frame["data"]["dev_pid"], 17372)
        self.assertEqual(start_frame["data"]["cuid"], "test-cuid")
        self.assertEqual(start_frame["data"]["format"], "pcm")
        self.assertEqual(start_frame["data"]["sample"], 16000)
        self.assertEqual(finish_frame["type"], "FINISH")
        self.assertGreater(len(fake_ws.binary_frames), 0)
        self.assertTrue(fake_ws.closed)
        self.assertEqual(result.text, "hello world")
        self.assertEqual(result.segments[0].start_seconds, 0.0)
        self.assertEqual(result.segments[0].end_seconds, 1.0)

    def test_client_raises_clear_error_for_start_failure(self) -> None:
        audio = AudioChunk(samples=np.zeros((16000, 1), dtype=np.float32), sample_rate=16000)
        fake_ws = FakeWebSocket(messages=['{"type":"START","err_no":3301,"err_msg":"bad key"}'])
        client = BaiduRealtimeAsrClient(app_id="123", app_key="app-key")

        with patch("app.asr.baidu.websocket.create_connection", return_value=fake_ws):
            with self.assertRaisesRegex(RuntimeError, "START 失败"):
                client.transcribe(audio, language="en")

    def test_client_requires_app_id_and_app_key(self) -> None:
        with self.assertRaises(AsrConfigurationError):
            BaiduRealtimeAsrClient(app_key="app-key")
        with self.assertRaises(AsrConfigurationError):
            BaiduRealtimeAsrClient(app_id="123")

    def test_resolve_dev_pid_uses_realtime_models(self) -> None:
        self.assertEqual(resolve_baidu_dev_pid(language="en", configured="auto"), 17372)
        self.assertEqual(resolve_baidu_dev_pid(language="zh-CN", configured="auto"), 15372)
        self.assertEqual(resolve_baidu_dev_pid(language="en", configured="80001"), 80001)


class AsrFactoryTest(unittest.TestCase):
    def test_factory_returns_mock_client_by_default(self) -> None:
        client = create_asr_client(AppConfig())

        self.assertIsInstance(client, MockAsrClient)

    def test_factory_returns_baidu_realtime_client(self) -> None:
        config = AppConfig(
            asr_provider="baidu-realtime",
            asr_app_id="123",
            asr_api_key="app-key",
        )

        client = create_asr_client(config)

        self.assertIsInstance(client, BaiduRealtimeAsrClient)


if __name__ == "__main__":
    unittest.main()
