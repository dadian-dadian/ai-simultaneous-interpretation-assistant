from __future__ import annotations

import re
from collections import OrderedDict
from dataclasses import dataclass

_CJK_CHARACTER_CLASS = r"\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
_SPACE_BEFORE_PUNCTUATION_RE = re.compile(r"\s+([，。！？；：、,.!?;:）》」』】）])")
_SPACE_AFTER_OPENING_PUNCTUATION_RE = re.compile(r"([《「『【（])\s+")
_SPACE_AROUND_DASH_RE = re.compile(r"\s*([—–…])\s*")
_SPACE_BETWEEN_CJK_RE = re.compile(
    rf"(?<=[{_CJK_CHARACTER_CLASS}])\s+(?=[{_CJK_CHARACTER_CLASS}])"
)
_SPACE_AFTER_CJK_PUNCTUATION_RE = re.compile(
    rf"(?<=[，。！？；：、])\s+(?=[{_CJK_CHARACTER_CLASS}])"
)


@dataclass(frozen=True)
class ChineseCaptionFrame:
    stable_text: str = ""
    active_text: str = ""
    is_final: bool = False

    @property
    def stable_lines(self) -> tuple[str, ...]:
        return tuple(
            line.strip()
            for line in self.stable_text.splitlines()
            if line.strip()
        )

    @property
    def lines(self) -> tuple[str, ...]:
        stable_lines = self.stable_lines
        if not self.active_text:
            return stable_lines
        return (*stable_lines, self.active_text)

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


@dataclass
class _ChineseSegmentState:
    source_version: int = 0
    latest_text: str = ""
    is_final: bool = False


class ChineseCaptionComposer:
    """Keep translated blocks in source order while revising only the latest block."""

    def __init__(self, *, max_visible_lines: int | None = 2) -> None:
        if max_visible_lines is not None and max_visible_lines <= 0:
            raise ValueError("max_visible_lines must be greater than 0")
        self.max_visible_lines = max_visible_lines
        self._segments: OrderedDict[str, _ChineseSegmentState] = OrderedDict()

    def reset(self) -> None:
        self._segments.clear()

    @property
    def latest_segment_id(self) -> str:
        return next(reversed(self._segments), "") if self._segments else ""

    def observe_segment(self, segment_id: str) -> ChineseCaptionFrame:
        if segment_id not in self._segments:
            self._segments[segment_id] = _ChineseSegmentState()
        return self.current_frame()

    def is_segment_final(self, segment_id: str) -> bool:
        state = self._segments.get(segment_id)
        return state is not None and state.is_final

    def accept_draft(
        self,
        *,
        segment_id: str,
        source_version: int,
        translated_text: str,
    ) -> ChineseCaptionFrame:
        text = _normalize_translation(translated_text)
        state = self._segments.setdefault(segment_id, _ChineseSegmentState())
        if source_version < state.source_version or state.is_final or not text:
            return self.current_frame()

        state.source_version = source_version
        state.latest_text = text
        return self.current_frame()

    def accept_final(
        self,
        *,
        segment_id: str,
        source_version: int,
        translated_text: str,
    ) -> ChineseCaptionFrame:
        text = _normalize_translation(translated_text)
        state = self._segments.setdefault(segment_id, _ChineseSegmentState())
        if source_version < state.source_version or not text:
            return self.current_frame()

        state.source_version = source_version
        state.latest_text = text
        state.is_final = True
        return self.current_frame()

    def current_frame(self) -> ChineseCaptionFrame:
        if not self._segments:
            return ChineseCaptionFrame()

        states = list(self._segments.values())
        latest = states[-1]
        stable_blocks = [
            state.latest_text
            for state in states[:-1]
            if state.latest_text
        ]
        active_text = latest.latest_text
        if self.max_visible_lines is not None:
            stable_limit = self.max_visible_lines - int(bool(active_text))
            stable_blocks = (
                stable_blocks[-stable_limit:]
                if stable_limit > 0
                else []
            )
        return ChineseCaptionFrame(
            stable_text="\n".join(stable_blocks),
            active_text=active_text,
            is_final=latest.is_final and bool(active_text),
        )


def _normalize_translation(text: str) -> str:
    return normalize_chinese_caption_text(text)


def normalize_chinese_caption_text(text: str) -> str:
    """Normalize provider whitespace without removing useful Latin-word spacing."""
    normalized = " ".join(text.strip().split())
    normalized = _SPACE_BEFORE_PUNCTUATION_RE.sub(r"\1", normalized)
    normalized = _SPACE_AFTER_OPENING_PUNCTUATION_RE.sub(r"\1", normalized)
    normalized = _SPACE_AROUND_DASH_RE.sub(r"\1", normalized)
    normalized = _SPACE_BETWEEN_CJK_RE.sub("", normalized)
    return _SPACE_AFTER_CJK_PUNCTUATION_RE.sub("", normalized)
