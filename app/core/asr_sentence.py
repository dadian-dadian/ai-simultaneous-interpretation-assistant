from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.asr.types import AsrResult
from app.core.subtitle import SubtitleEvent


@dataclass(frozen=True)
class SentenceId:
    speech_id: str
    sentence_index: int

    @property
    def value(self) -> str:
        return f"{self.speech_id}_s{self.sentence_index:04d}"


class AsrSentenceMapper:
    """Map each provider FIN_TEXT unit to one subtitle segment."""

    def __init__(
        self,
        speech_id: str,
        *,
        min_partial_words: int = 2,
    ) -> None:
        if not speech_id:
            raise ValueError("speech_id cannot be empty")
        if min_partial_words <= 0:
            raise ValueError("min_partial_words must be greater than 0")

        self.speech_id = speech_id
        self.min_partial_words = min_partial_words
        self._next_sentence_index = 1
        self._active_sentence_index: int | None = None
        self._current_text = ""
        self._current_was_visible = False
        self._pending_weak_final = ""
        self._provider_sentence_indexes: dict[str, int] = {}
        self._finalized_provider_ids: set[str] = set()
        self._finalized_keys: set[tuple[str, float | None, float | None]] = set()

    @property
    def current_sentence_id(self) -> str:
        sentence_index = self._active_sentence_index or self._next_sentence_index
        return SentenceId(self.speech_id, sentence_index).value

    @property
    def current_text(self) -> str:
        return self._current_text

    def accept_transcripts(self, transcripts: list[Any]) -> list[SubtitleEvent]:
        events: list[SubtitleEvent] = []
        for transcript in transcripts:
            text = normalize_asr_sentence_text(getattr(transcript, "text", ""))
            if not text:
                continue
            provider_sentence_id = str(
                getattr(transcript, "sentence_id", "")
            ).strip()
            if (
                provider_sentence_id
                and provider_sentence_id in self._finalized_provider_ids
            ):
                continue
            if getattr(transcript, "is_final", False):
                events.extend(
                    self._finalize_text(
                        text,
                        provider_sentence_id=provider_sentence_id,
                        start_seconds=getattr(transcript, "start_seconds", None),
                        end_seconds=getattr(transcript, "end_seconds", None),
                    )
                )
                continue

            event = self._update_current_partial(
                text,
                provider_sentence_id=provider_sentence_id,
            )
            if event is not None:
                events.append(event)
        return events

    def accept_finish_result(
        self,
        result: AsrResult | None,
        *,
        fallback_text: str = "",
        allow_result_text_fallback: bool = True,
    ) -> list[SubtitleEvent]:
        events: list[SubtitleEvent] = []
        if result is not None:
            for segment in result.segments:
                events.extend(
                    self._finalize_text(
                        normalize_asr_sentence_text(segment.text),
                        start_seconds=segment.start_seconds,
                        end_seconds=segment.end_seconds,
                    )
                )

        if self._pending_weak_final:
            event = self._finalize_text(
                self._pending_weak_final,
                force_boundary=True,
            )
            if event:
                events.extend(event)
            return events

        result_has_segments = result is not None and bool(result.segments)
        result_text = ""
        if allow_result_text_fallback and not result_has_segments and result is not None:
            result_text = result.text
        fallback_source = fallback_text
        if allow_result_text_fallback:
            fallback_source = fallback_source or result_text or self._current_text
        fallback = normalize_asr_sentence_text(fallback_source)
        if not fallback:
            return events
        events.extend(self._finalize_text(fallback, force_boundary=True))
        return events

    def _update_current_partial(
        self,
        text: str,
        *,
        provider_sentence_id: str = "",
    ) -> SubtitleEvent | None:
        sentence_index = self._resolve_sentence_index(provider_sentence_id)
        combined_text = _join_asr_clauses(self._pending_weak_final, text)
        if combined_text == self._current_text and self._current_was_visible:
            return None

        self._current_text = combined_text
        if (
            len(combined_text.split()) < self.min_partial_words
            and not self._current_was_visible
        ):
            return None

        self._current_was_visible = True
        sentence_id = SentenceId(self.speech_id, sentence_index).value
        return SubtitleEvent.partial(sentence_id, combined_text, combined_text)

    def _finalize_text(
        self,
        text: str,
        *,
        provider_sentence_id: str = "",
        start_seconds: float | None = None,
        end_seconds: float | None = None,
        force_boundary: bool = False,
    ) -> list[SubtitleEvent]:
        event = self._finalize_current_sentence(
            normalize_asr_sentence_text(text),
            provider_sentence_id=provider_sentence_id,
            start_seconds=start_seconds,
            end_seconds=end_seconds,
            force_boundary=force_boundary,
        )
        return [] if event is None else [event]

    def _finalize_current_sentence(
        self,
        text: str,
        *,
        provider_sentence_id: str = "",
        start_seconds: float | None = None,
        end_seconds: float | None = None,
        force_boundary: bool = False,
    ) -> SubtitleEvent | None:
        if not text:
            return None
        key = (text.casefold(), start_seconds, end_seconds)
        if key in self._finalized_keys:
            return None

        sentence_index = self._resolve_sentence_index(provider_sentence_id)
        combined_text = _join_asr_clauses(self._pending_weak_final, text)
        self._finalized_keys.add(key)
        if provider_sentence_id:
            self._finalized_provider_ids.add(provider_sentence_id)

        if not force_boundary and _has_weak_trailing_boundary(combined_text):
            self._pending_weak_final = combined_text
            self._current_text = combined_text
            self._current_was_visible = True
            sentence_id = SentenceId(self.speech_id, sentence_index).value
            return SubtitleEvent.partial(sentence_id, combined_text, combined_text)

        sentence_id = SentenceId(self.speech_id, sentence_index).value
        event = SubtitleEvent.final(sentence_id, combined_text, combined_text)
        self._pending_weak_final = ""
        self._active_sentence_index = None
        self._current_text = ""
        self._current_was_visible = False
        return event

    def _resolve_sentence_index(self, provider_sentence_id: str) -> int:
        if provider_sentence_id:
            existing = self._provider_sentence_indexes.get(provider_sentence_id)
            if existing is not None:
                return existing

        if self._active_sentence_index is None:
            self._active_sentence_index = self._next_sentence_index
            self._next_sentence_index += 1

        sentence_index = self._active_sentence_index
        if provider_sentence_id:
            self._provider_sentence_indexes[provider_sentence_id] = sentence_index
        return sentence_index


def normalize_asr_sentence_text(text: str) -> str:
    spaced = re.sub(r"([.!?])(?=[A-Z0-9])", r"\1 ", text.strip())
    return " ".join(spaced.split())


def split_asr_final_text(text: str) -> list[str]:
    normalized = normalize_asr_sentence_text(text)
    return [normalized] if normalized else []


_WEAK_TRAILING_WORDS = {
    "about",
    "among",
    "and",
    "as",
    "at",
    "because",
    "between",
    "but",
    "by",
    "for",
    "from",
    "if",
    "in",
    "including",
    "into",
    "like",
    "of",
    "on",
    "or",
    "over",
    "than",
    "that",
    "through",
    "to",
    "under",
    "whether",
    "which",
    "while",
    "who",
    "with",
    "within",
    "without",
}


def _has_weak_trailing_boundary(text: str) -> bool:
    words = text.split()
    if len(words) < 4:
        return False
    trailing_word = words[-1].casefold().strip(".,!?;:\"'()[]{}")
    return trailing_word in _WEAK_TRAILING_WORDS


def _join_asr_clauses(prefix: str, suffix: str) -> str:
    left = normalize_asr_sentence_text(prefix)
    right = normalize_asr_sentence_text(suffix)
    if not left:
        return right
    if not right:
        return left
    if right.casefold().startswith(left.casefold()):
        return right

    left = left.rstrip(".,!?;: ")
    left_words = left.split()
    right_words = right.split()
    max_overlap = min(8, len(left_words), len(right_words))
    overlap = 0
    for size in range(max_overlap, 0, -1):
        left_tail = [word.casefold().strip(".,!?;:\"'()[]{}") for word in left_words[-size:]]
        right_head = [
            word.casefold().strip(".,!?;:\"'()[]{}")
            for word in right_words[:size]
        ]
        if left_tail == right_head:
            overlap = size
            break
    remainder = " ".join(right_words[overlap:])
    return normalize_asr_sentence_text(f"{left} {remainder}")
