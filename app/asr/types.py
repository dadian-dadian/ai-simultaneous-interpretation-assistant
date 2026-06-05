from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.audio.capture import AudioChunk


class AsrError(RuntimeError):
    """Base exception raised by ASR providers."""


class AsrConfigurationError(AsrError):
    """Raised when an ASR provider is missing required configuration."""


@dataclass(frozen=True)
class AsrTextSegment:
    text: str
    start_seconds: float | None = None
    end_seconds: float | None = None
    confidence: float | None = None


@dataclass(frozen=True)
class AsrResult:
    text: str
    language: str
    provider: str
    duration_seconds: float
    segments: tuple[AsrTextSegment, ...] = ()
    is_mock: bool = False

    @property
    def has_text(self) -> bool:
        return bool(self.text.strip())


class AsrClient(Protocol):
    provider_name: str

    def transcribe(
        self,
        audio: AudioChunk,
        *,
        language: str = "",
        prompt: str = "",
    ) -> AsrResult:
        """Convert one speech audio chunk into source-language text."""
