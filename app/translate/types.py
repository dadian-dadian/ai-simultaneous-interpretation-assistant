from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol


class TranslationError(RuntimeError):
    """Base exception raised by translation providers."""


class TranslationConfigurationError(TranslationError):
    """Raised when a translation provider is missing required configuration."""


@dataclass(frozen=True)
class TranslationRequest:
    source_text: str
    source_language: str
    target_language: str
    context: tuple[str, ...] = ()


@dataclass(frozen=True)
class TranslationResult:
    text: str
    provider: str
    model: str
    source_language: str
    target_language: str

    @property
    def has_text(self) -> bool:
        return bool(self.text.strip())


class TranslatorClient(Protocol):
    provider_name: str

    def translate(self, request: TranslationRequest) -> TranslationResult:
        """Translate one source-language text into the configured target language."""

    def stream_translate(self, request: TranslationRequest) -> Iterator[str]:
        """Yield translated text deltas as soon as the provider streams them."""
