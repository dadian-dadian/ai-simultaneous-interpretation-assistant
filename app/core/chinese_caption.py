from __future__ import annotations

import re
from collections import OrderedDict
from dataclasses import dataclass, field

_HARD_SENTENCE_RE = re.compile(r".+?[。！？!?]+[”’\"』」）》】）)]*")
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
    def lines(self) -> tuple[str, ...]:
        stable_lines = tuple(
            line.strip()
            for line in self.stable_text.splitlines()
            if line.strip()
        )
        if not self.active_text:
            return stable_lines
        return (*stable_lines, self.active_text)

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


@dataclass
class _ChineseSegmentState:
    source_version: int = 0
    previous_draft: str = ""
    latest_text: str = ""
    committed_sentences: list[str] = field(default_factory=list)
    active_text: str = ""
    is_final: bool = False


class ChineseCaptionComposer:
    """Keep committed Chinese sentences stable while revising only the tail."""

    def __init__(self, *, max_visible_lines: int | None = 2) -> None:
        if max_visible_lines is not None and max_visible_lines <= 0:
            raise ValueError("max_visible_lines must be greater than 0")
        self.max_visible_lines = max_visible_lines
        self._segments: OrderedDict[str, _ChineseSegmentState] = OrderedDict()

    def reset(self) -> None:
        self._segments.clear()

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
        self._segments.move_to_end(segment_id)
        if source_version < state.source_version or state.is_final or not text:
            return self.current_frame()

        state.source_version = source_version
        state.previous_draft = text
        state.latest_text = text
        state.active_text = text
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
        self._segments.move_to_end(segment_id)
        if source_version < state.source_version or not text:
            return self.current_frame()

        state.source_version = source_version
        state.previous_draft = text
        state.latest_text = text
        state.committed_sentences = [text]
        state.active_text = ""
        state.is_final = True
        return self.current_frame()

    def current_frame(self) -> ChineseCaptionFrame:
        active_text = ""
        active_is_final = False
        for state in self._segments.values():
            if state.active_text:
                active_text = state.active_text
                active_is_final = False
            elif state.is_final and state.committed_sentences:
                active_is_final = True

        committed = self._recent_committed_sentences(
            reserve_active=bool(active_text),
        )
        visible: list[str] = committed
        if active_text:
            visible = [*visible, active_text]
        if self.max_visible_lines is not None:
            visible = visible[-self.max_visible_lines :]
        if not visible:
            return ChineseCaptionFrame()
        if len(visible) == 1:
            return ChineseCaptionFrame(
                active_text=visible[0],
                is_final=active_is_final and not active_text,
            )
        return ChineseCaptionFrame(
            stable_text="\n".join(visible[:-1]),
            active_text=visible[-1],
            is_final=active_is_final and not active_text,
        )

    def _recent_committed_sentences(self, *, reserve_active: bool) -> list[str]:
        if self.max_visible_lines is None:
            return [
                sentence
                for state in self._segments.values()
                for sentence in state.committed_sentences
            ]

        limit = self.max_visible_lines - int(reserve_active)
        if limit <= 0:
            return []

        recent_reversed: list[str] = []
        for state in reversed(self._segments.values()):
            for sentence in reversed(state.committed_sentences):
                recent_reversed.append(sentence)
                if len(recent_reversed) >= limit:
                    return list(reversed(recent_reversed))
        return list(reversed(recent_reversed))


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


def _split_complete_sentences(text: str) -> tuple[list[str], str]:
    sentences: list[str] = []
    end = 0
    for match in _HARD_SENTENCE_RE.finditer(text):
        prefix = text[end : match.start()].strip()
        sentence = f"{prefix}{match.group(0)}".strip()
        if sentence:
            sentences.append(sentence)
        end = match.end()
    return sentences, text[end:].strip()


def _matching_committed_prefix(
    committed: list[str],
    current: list[str],
) -> int:
    count = 0
    for committed_sentence, current_sentence in zip(committed, current, strict=False):
        if committed_sentence != current_sentence:
            break
        count += 1
    return count


def _active_tail(text: str, committed: list[str]) -> str:
    offset = 0
    for sentence in committed:
        index = text.find(sentence, offset)
        if index < 0:
            return _last_uncommitted_piece(text, committed)
        offset = index + len(sentence)
    return text[offset:].strip()


def _last_uncommitted_piece(text: str, committed: list[str]) -> str:
    sentences, tail = _split_complete_sentences(text)
    candidates = [
        sentence
        for sentence in sentences
        if sentence not in committed
    ]
    if tail:
        candidates.append(tail)
    return candidates[-1] if candidates else ""
