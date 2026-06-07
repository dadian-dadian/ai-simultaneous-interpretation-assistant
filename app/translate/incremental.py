from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field


@dataclass(frozen=True)
class IncrementalTranslationPlan:
    segment_id: str
    source_version: int
    source_text: str
    is_final: bool


@dataclass
class _SegmentPlanningState:
    snapshots: deque[list[str]] = field(default_factory=lambda: deque(maxlen=2))
    last_submitted_text: str = ""
    last_submitted_at: float = 0.0


class IncrementalTranslationPlanner:
    """Observe every MID update and emit only stable, rate-limited prefixes."""

    def __init__(
        self,
        *,
        initial_words: int = 4,
        min_growth_words: int = 4,
        initial_unstable_tail_words: int = 0,
        unstable_tail_words: int = 1,
        min_interval_seconds: float = 1.2,
        max_interval_seconds: float = 2.4,
    ) -> None:
        if initial_words <= 0:
            raise ValueError("initial_words must be greater than 0")
        if min_growth_words <= 0:
            raise ValueError("min_growth_words must be greater than 0")
        if initial_unstable_tail_words < 0 or unstable_tail_words < 0:
            raise ValueError("unstable tail words cannot be negative")
        if min_interval_seconds <= 0:
            raise ValueError("min_interval_seconds must be greater than 0")
        if max_interval_seconds < min_interval_seconds:
            raise ValueError("max_interval_seconds cannot be smaller than min_interval_seconds")

        self.initial_words = initial_words
        self.min_growth_words = min_growth_words
        self.initial_unstable_tail_words = initial_unstable_tail_words
        self.unstable_tail_words = unstable_tail_words
        self.min_interval_seconds = min_interval_seconds
        self.max_interval_seconds = max_interval_seconds
        self._segments: dict[str, _SegmentPlanningState] = {}

    def reset(self) -> None:
        self._segments.clear()

    def observe_partial(
        self,
        *,
        segment_id: str,
        source_version: int,
        source_text: str,
        observed_at: float,
    ) -> IncrementalTranslationPlan | None:
        words = source_text.split()
        if not words:
            return None

        state = self._segments.setdefault(segment_id, _SegmentPlanningState())
        state.snapshots.append(words)
        if len(state.snapshots) < 2:
            return None

        stable_count = _common_prefix_length(tuple(state.snapshots))
        unstable_tail_words = (
            self.unstable_tail_words
            if state.last_submitted_text
            else self.initial_unstable_tail_words
        )
        stable_count = max(0, stable_count - unstable_tail_words)
        if stable_count < self.initial_words:
            return None

        candidate = " ".join(words[:stable_count])
        if candidate == state.last_submitted_text:
            return None

        if state.last_submitted_text:
            elapsed = observed_at - state.last_submitted_at
            growth = stable_count - len(state.last_submitted_text.split())
            if elapsed < self.min_interval_seconds:
                return None
            if growth < self.min_growth_words and elapsed < self.max_interval_seconds:
                return None

        state.last_submitted_text = candidate
        state.last_submitted_at = observed_at
        return IncrementalTranslationPlan(
            segment_id=segment_id,
            source_version=source_version,
            source_text=candidate,
            is_final=False,
        )

    def observe_final(
        self,
        *,
        segment_id: str,
        source_version: int,
        source_text: str,
    ) -> IncrementalTranslationPlan | None:
        normalized = source_text.strip()
        if not normalized:
            return None
        self._segments.pop(segment_id, None)
        return IncrementalTranslationPlan(
            segment_id=segment_id,
            source_version=source_version,
            source_text=normalized,
            is_final=True,
        )


def _common_prefix_length(snapshots: tuple[list[str], ...]) -> int:
    if not snapshots:
        return 0
    shortest = min(len(words) for words in snapshots)
    for index in range(shortest):
        comparison = _comparison_key(snapshots[0][index])
        if any(_comparison_key(words[index]) != comparison for words in snapshots[1:]):
            return index
    return shortest


def _comparison_key(word: str) -> str:
    return word.casefold().strip(".,!?;:\"'()[]{}")
