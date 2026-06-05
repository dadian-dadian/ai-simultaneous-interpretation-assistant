from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class SubtitleEventType(StrEnum):
    PARTIAL = "segment.partial"
    FINAL = "segment.final"
    UPDATE = "segment.update"


class SubtitleSegmentStatus(StrEnum):
    PARTIAL = "partial"
    FINAL = "final"
    UPDATED = "updated"


@dataclass(frozen=True)
class SubtitleEvent:
    type: SubtitleEventType
    segment_id: str
    source_text: str = ""
    zh_text: str = ""
    old_source_text: str = ""
    old_zh_text: str = ""
    reason: str = ""

    @classmethod
    def partial(cls, segment_id: str, source_text: str, zh_text: str) -> "SubtitleEvent":
        return cls(
            type=SubtitleEventType.PARTIAL,
            segment_id=segment_id,
            source_text=source_text,
            zh_text=zh_text,
        )

    @classmethod
    def final(cls, segment_id: str, source_text: str, zh_text: str) -> "SubtitleEvent":
        return cls(
            type=SubtitleEventType.FINAL,
            segment_id=segment_id,
            source_text=source_text,
            zh_text=zh_text,
        )

    @classmethod
    def update(
        cls,
        segment_id: str,
        source_text: str,
        zh_text: str,
        reason: str,
        old_source_text: str = "",
        old_zh_text: str = "",
    ) -> "SubtitleEvent":
        return cls(
            type=SubtitleEventType.UPDATE,
            segment_id=segment_id,
            source_text=source_text,
            zh_text=zh_text,
            old_source_text=old_source_text,
            old_zh_text=old_zh_text,
            reason=reason,
        )

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SubtitleEvent":
        return cls(
            type=SubtitleEventType(payload["type"]),
            segment_id=payload["segment_id"],
            source_text=payload.get("source_text", ""),
            zh_text=payload.get("zh_text", ""),
            old_source_text=payload.get("old_source_text", ""),
            old_zh_text=payload.get("old_zh_text", ""),
            reason=payload.get("reason", ""),
        )

    def to_dict(self) -> dict[str, str]:
        payload = {
            "type": self.type.value,
            "segment_id": self.segment_id,
            "source_text": self.source_text,
            "zh_text": self.zh_text,
        }
        if self.old_source_text:
            payload["old_source_text"] = self.old_source_text
        if self.old_zh_text:
            payload["old_zh_text"] = self.old_zh_text
        if self.reason:
            payload["reason"] = self.reason
        return payload


@dataclass(frozen=True)
class SubtitleRevision:
    old_source_text: str
    old_zh_text: str
    reason: str


@dataclass
class SubtitleSegment:
    segment_id: str
    source_text: str = ""
    zh_text: str = ""
    status: SubtitleSegmentStatus = SubtitleSegmentStatus.PARTIAL
    version: int = 0
    revisions: list[SubtitleRevision] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "segment_id": self.segment_id,
            "source_text": self.source_text,
            "zh_text": self.zh_text,
            "status": self.status.value,
            "version": self.version,
            "revisions": [
                {
                    "old_source_text": revision.old_source_text,
                    "old_zh_text": revision.old_zh_text,
                    "reason": revision.reason,
                }
                for revision in self.revisions
            ],
        }


class SubtitleState:
    def __init__(self, max_segments: int = 80) -> None:
        if max_segments <= 0:
            raise ValueError("max_segments must be greater than 0")
        self.max_segments = max_segments
        self._segments: OrderedDict[str, SubtitleSegment] = OrderedDict()

    def apply(self, event: SubtitleEvent) -> SubtitleSegment:
        if event.type == SubtitleEventType.PARTIAL:
            return self._apply_partial(event)
        if event.type == SubtitleEventType.FINAL:
            return self._apply_final(event)
        if event.type == SubtitleEventType.UPDATE:
            return self._apply_update(event)
        raise ValueError(f"Unsupported subtitle event type: {event.type}")

    def get(self, segment_id: str) -> SubtitleSegment | None:
        return self._segments.get(segment_id)

    def segments(self) -> list[SubtitleSegment]:
        return list(self._segments.values())

    def recent(self, limit: int = 3) -> list[SubtitleSegment]:
        if limit <= 0:
            return []
        return self.segments()[-limit:]

    def to_dict_list(self) -> list[dict[str, Any]]:
        return [segment.to_dict() for segment in self.segments()]

    def _apply_partial(self, event: SubtitleEvent) -> SubtitleSegment:
        segment = self._segments.get(event.segment_id)
        if segment is None:
            segment = SubtitleSegment(segment_id=event.segment_id)
            self._segments[event.segment_id] = segment
        elif segment.status != SubtitleSegmentStatus.PARTIAL:
            return segment

        segment.source_text = event.source_text
        segment.zh_text = event.zh_text
        segment.version += 1
        self._touch(event.segment_id)
        self._trim()
        return segment

    def _apply_final(self, event: SubtitleEvent) -> SubtitleSegment:
        segment = self._segments.get(event.segment_id)
        if segment is None:
            segment = SubtitleSegment(segment_id=event.segment_id)
            self._segments[event.segment_id] = segment

        changed = segment.source_text != event.source_text or segment.zh_text != event.zh_text
        segment.source_text = event.source_text
        segment.zh_text = event.zh_text
        segment.status = SubtitleSegmentStatus.FINAL
        if changed:
            segment.version += 1
        self._touch(event.segment_id)
        self._trim()
        return segment

    def _apply_update(self, event: SubtitleEvent) -> SubtitleSegment:
        segment = self._segments.get(event.segment_id)
        if segment is None:
            raise KeyError(f"Cannot update unknown subtitle segment: {event.segment_id}")

        old_source_text = event.old_source_text or segment.source_text
        old_zh_text = event.old_zh_text or segment.zh_text
        segment.revisions.append(
            SubtitleRevision(
                old_source_text=old_source_text,
                old_zh_text=old_zh_text,
                reason=event.reason,
            )
        )
        segment.source_text = event.source_text
        segment.zh_text = event.zh_text
        segment.status = SubtitleSegmentStatus.UPDATED
        segment.version += 1
        self._touch(event.segment_id)
        return segment

    def _touch(self, segment_id: str) -> None:
        self._segments.move_to_end(segment_id)

    def _trim(self) -> None:
        while len(self._segments) > self.max_segments:
            self._segments.popitem(last=False)
