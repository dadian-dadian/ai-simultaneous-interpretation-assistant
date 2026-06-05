import unittest
from unittest.mock import patch

import numpy as np

from app.asr import (
    AsrConfigurationError,
    MockAsrClient,
    OpenAICompatibleAsrClient,
    create_asr_client,
)
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


class OpenAICompatibleAsrClientTest(unittest.TestCase):
    def test_client_posts_wav_multipart_and_parses_json(self) -> None:
        audio = AudioChunk(samples=np.zeros((16000, 1), dtype=np.float32), sample_rate=16000)
        response = FakeHttpResponse(
            b'{"text":"hello world","language":"en","duration":1.0,'
            b'"segments":[{"text":"hello","start":0,"end":0.5}]}'
        )
        client = OpenAICompatibleAsrClient(api_key="secret", model="gpt-test")

        with patch(
            "app.asr.openai_compatible.urllib.request.urlopen",
            return_value=response,
        ) as urlopen:
            result = client.transcribe(audio, language="en", prompt="technical talk")

        request = urlopen.call_args.args[0]
        body = request.data
        self.assertEqual(request.full_url, "https://api.openai.com/v1/audio/transcriptions")
        self.assertEqual(request.get_header("Authorization"), "Bearer secret")
        self.assertIn(b'name="model"', body)
        self.assertIn(b"gpt-test", body)
        self.assertIn(b'name="file"; filename="speech.wav"', body)
        self.assertIn(b"RIFF", body)
        self.assertEqual(result.text, "hello world")
        self.assertEqual(result.language, "en")
        self.assertEqual(len(result.segments), 1)

    def test_client_requires_api_key(self) -> None:
        with self.assertRaises(AsrConfigurationError):
            OpenAICompatibleAsrClient(api_key="")


class AsrFactoryTest(unittest.TestCase):
    def test_factory_returns_mock_client_by_default(self) -> None:
        client = create_asr_client(AppConfig())

        self.assertIsInstance(client, MockAsrClient)

    def test_factory_returns_openai_compatible_client(self) -> None:
        config = AppConfig(asr_provider="openai-compatible", asr_api_key="secret")

        client = create_asr_client(config)

        self.assertIsInstance(client, OpenAICompatibleAsrClient)


if __name__ == "__main__":
    unittest.main()
