from __future__ import annotations

import re
from dataclasses import dataclass, field

_SENTENCE_END_RE = re.compile(r"[.!?][\"')\]]*$")
_CLAUSE_END_RE = re.compile(r"[,;:][\"')\]]*$")
_LEADING_CONNECTORS = {
    "although",
    "and",
    "because",
    "but",
    "finally",
    "first",
    "however",
    "if",
    "meanwhile",
    "next",
    "second",
    "so",
    "then",
    "therefore",
    "though",
    "when",
    "while",
    "which",
    "yet",
}


@dataclass(frozen=True)
class LiveCaptionFrame:
    stable_text: str = ""
    active_text: str = ""
    is_final: bool = False

    @property
    def lines(self) -> tuple[str, ...]:
        return tuple(text for text in (self.stable_text, self.active_text) if text)

    @property
    def text(self) -> str:
        return "\n".join(self.lines)

    @property
    def word_count(self) -> int:
        return sum(len(line.split()) for line in self.lines)


@dataclass
class _ComposerState:
    segment_id: str
    words: list[str] = field(default_factory=list)
    phrase_boundaries: list[int] = field(default_factory=list)
    last_update_at: float | None = None


class LiveCaptionComposer:
    """Keep one complete stable phrase above one continuously growing phrase."""

    def __init__(
        self,
        *,
        max_phrase_words: int = 18,
        min_phrase_words: int = 5,
        stable_tail_words: int = 3,
        soft_pause_seconds: float = 0.55,
        min_pause_words: int = 3,
        min_active_words: int = 2,
        hidden_tail_words: int = 0,
        max_line_words: int | None = None,
        **legacy_options: int,
    ) -> None:
        # max_line_words used to control visual wrapping. Keep it as an alias so
        # callers can move to semantic phrase limits without breaking.
        if max_line_words is not None:
            max_phrase_words = max_line_words
        legacy_options.pop("max_line_characters", None)
        legacy_options.pop("min_line_words", None)
        legacy_options.pop("max_visible_lines", None)
        if legacy_options:
            option = next(iter(legacy_options))
            raise TypeError(f"unexpected option: {option}")
        if max_phrase_words <= 0:
            raise ValueError("max_phrase_words must be greater than 0")
        if not 0 < min_phrase_words <= max_phrase_words:
            raise ValueError("min_phrase_words must be between 1 and max_phrase_words")
        if stable_tail_words < 0:
            raise ValueError("stable_tail_words cannot be negative")
        if soft_pause_seconds <= 0:
            raise ValueError("soft_pause_seconds must be greater than 0")
        if min_pause_words <= 0:
            raise ValueError("min_pause_words must be greater than 0")
        if min_active_words <= 0:
            raise ValueError("min_active_words must be greater than 0")
        if hidden_tail_words < 0:
            raise ValueError("hidden_tail_words cannot be negative")

        self.max_phrase_words = max_phrase_words
        self.min_phrase_words = min_phrase_words
        self.stable_tail_words = stable_tail_words
        self.soft_pause_seconds = soft_pause_seconds
        self.min_pause_words = min_pause_words
        self.min_active_words = min_active_words
        self.hidden_tail_words = hidden_tail_words
        self._state: _ComposerState | None = None

    def reset(self) -> None:
        self._state = None

    def compose_partial(
        self,
        segment_id: str,
        text: str,
        *,
        observed_at: float | None = None,
    ) -> LiveCaptionFrame:
        words = _split_words(text)
        state = self._ensure_state(segment_id)
        previous_words = state.words
        common_prefix = _common_prefix_length(previous_words, words)
        self._rollback_revised_boundaries(state, common_prefix)

        has_soft_pause = (
            observed_at is not None
            and state.last_update_at is not None
            and observed_at - state.last_update_at >= self.soft_pause_seconds
        )
        if has_soft_pause:
            self._commit_boundary(
                state,
                common_prefix,
                minimum_words=self.min_pause_words,
            )

        state.words = words
        self._commit_overlong_phrases(state)
        if observed_at is not None:
            state.last_update_at = observed_at
        return self._build_frame(state, is_final=False)

    def compose_final(self, segment_id: str, text: str) -> LiveCaptionFrame:
        state = self._ensure_state(segment_id)
        previous_words = state.words
        words = _split_words(text)
        common_prefix = _common_prefix_length(previous_words, words)
        state.words = words
        state.phrase_boundaries = [
            boundary for boundary in state.phrase_boundaries if boundary <= common_prefix
        ]

        punctuated_boundaries = _punctuated_boundaries(words)
        if punctuated_boundaries:
            state.phrase_boundaries = punctuated_boundaries
        else:
            self._commit_overlong_phrases(state, reserve_tail=False)
        return self._build_frame(state, is_final=True)

    def _ensure_state(self, segment_id: str) -> _ComposerState:
        if self._state is None or self._state.segment_id != segment_id:
            self._state = _ComposerState(segment_id=segment_id)
        return self._state

    def _rollback_revised_boundaries(
        self,
        state: _ComposerState,
        common_prefix: int,
    ) -> None:
        state.phrase_boundaries = [
            boundary for boundary in state.phrase_boundaries if boundary <= common_prefix
        ]

    def _commit_boundary(
        self,
        state: _ComposerState,
        boundary: int,
        *,
        minimum_words: int,
    ) -> bool:
        previous_boundary = state.phrase_boundaries[-1] if state.phrase_boundaries else 0
        if boundary - previous_boundary < minimum_words:
            return False
        state.phrase_boundaries.append(boundary)
        return True

    def _commit_overlong_phrases(
        self,
        state: _ComposerState,
        *,
        reserve_tail: bool = True,
    ) -> None:
        stable_count = len(state.words)
        if reserve_tail:
            stable_count = max(0, stable_count - self.stable_tail_words)

        start = state.phrase_boundaries[-1] if state.phrase_boundaries else 0
        while stable_count - start >= self.max_phrase_words:
            available = state.words[start:stable_count]
            relative_cut = _choose_phrase_cut(
                available,
                max_phrase_words=self.max_phrase_words,
                min_phrase_words=self.min_phrase_words,
            )
            boundary = start + relative_cut
            if boundary <= start:
                break
            state.phrase_boundaries.append(boundary)
            start = boundary

    def _build_frame(
        self,
        state: _ComposerState,
        *,
        is_final: bool,
    ) -> LiveCaptionFrame:
        boundaries = state.phrase_boundaries
        active_start = boundaries[-1] if boundaries else 0
        stable_start = boundaries[-2] if len(boundaries) >= 2 else 0

        stable_words = state.words[stable_start:active_start]
        active_words = state.words[active_start:]
        if not is_final and self.hidden_tail_words:
            active_words = active_words[: max(0, len(active_words) - self.hidden_tail_words)]
        if stable_words and len(active_words) < self.min_active_words:
            active_words = []

        return LiveCaptionFrame(
            stable_text=" ".join(stable_words),
            active_text=" ".join(active_words),
            is_final=is_final,
        )


def _split_words(text: str) -> list[str]:
    normalized = re.sub(r"([.!?])(?=[A-Z])", r"\1 ", text.strip())
    return normalized.split()


def _common_prefix_length(left: list[str], right: list[str]) -> int:
    length = 0
    for left_word, right_word in zip(left, right, strict=False):
        if _comparison_key(left_word) != _comparison_key(right_word):
            break
        length += 1
    return length


def _comparison_key(word: str) -> str:
    return word.casefold().strip(".,!?;:\"'()[]{}")


def _choose_phrase_cut(
    words: list[str],
    *,
    max_phrase_words: int,
    min_phrase_words: int,
) -> int:
    upper_bound = min(max_phrase_words, len(words))
    for index in range(upper_bound, min_phrase_words - 1, -1):
        if _SENTENCE_END_RE.search(words[index - 1]):
            return index
    for index in range(upper_bound, min_phrase_words - 1, -1):
        if _CLAUSE_END_RE.search(words[index - 1]):
            return index
    for index in range(upper_bound - 1, min_phrase_words - 1, -1):
        if _comparison_key(words[index]) in _LEADING_CONNECTORS:
            return index
    return upper_bound


def _punctuated_boundaries(words: list[str]) -> list[int]:
    boundaries: list[int] = []
    for index, word in enumerate(words, start=1):
        if index < len(words) and _SENTENCE_END_RE.search(word):
            boundaries.append(index)
    return boundaries
