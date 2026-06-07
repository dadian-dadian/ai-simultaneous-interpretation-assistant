from __future__ import annotations

from app.asr.types import AsrResult, AsrTextSegment
from app.audio.capture import AudioChunk

DEFAULT_MOCK_TRANSCRIPT = (
    "Welcome. The live transcript will appear here as the conversation continues."
)


class MockAsrClient:
    provider_name = "mock"

    def __init__(self, transcript: str = DEFAULT_MOCK_TRANSCRIPT) -> None:
        self.transcript = transcript

    def transcribe(
        self,
        audio: AudioChunk,
        *,
        language: str = "en",
        prompt: str = "",
    ) -> AsrResult:
        text = self.transcript.strip()
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
            ),
            is_mock=True,
        )
