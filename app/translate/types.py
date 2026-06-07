from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class TranslationError(RuntimeError):
    """Base error raised by translation clients."""


class TranslationConfigurationError(TranslationError):
    """Raised when a translation client is missing required configuration."""


@dataclass(frozen=True)
class TranslationResult:
    source_text: str
    translated_text: str
    source_language: str
    target_language: str
    provider: str


class TranslationClient(Protocol):
    def translate(
        self,
        text: str,
        source_language: str,
        target_language: str,
    ) -> TranslationResult:
        """Translate text from source_language to target_language."""
