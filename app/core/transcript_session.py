from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from threading import RLock
from typing import Any
from uuid import uuid4

from app.core.subtitle import (
    SubtitleRevision,
    SubtitleSegment,
    SubtitleSegmentStatus,
)


class TranscriptSessionStatus(StrEnum):
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    INTERRUPTED = "interrupted"
    FAILED = "failed"


@dataclass
class TranscriptSegment:
    segment_id: str
    source_text: str = ""
    zh_text: str = ""
    translation_source_text: str = ""
    status: SubtitleSegmentStatus = SubtitleSegmentStatus.PARTIAL
    version: int = 0
    revisions: list[SubtitleRevision] = field(default_factory=list)
    updated_at: str = field(default_factory=lambda: _utc_now().isoformat())

    @classmethod
    def from_subtitle_segment(
        cls,
        segment: SubtitleSegment,
        *,
        updated_at: datetime | None = None,
    ) -> TranscriptSegment:
        return cls(
            segment_id=segment.segment_id,
            source_text=segment.source_text,
            zh_text=segment.zh_text,
            translation_source_text=segment.translation_source_text,
            status=segment.status,
            version=segment.version,
            revisions=list(segment.revisions),
            updated_at=(updated_at or _utc_now()).isoformat(),
        )

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> TranscriptSegment:
        return cls(
            segment_id=str(payload["segment_id"]),
            source_text=str(payload.get("source_text", "")),
            zh_text=str(payload.get("zh_text", "")),
            translation_source_text=str(
                payload.get("translation_source_text", "")
            ),
            status=SubtitleSegmentStatus(
                payload.get("status", SubtitleSegmentStatus.PARTIAL.value)
            ),
            version=int(payload.get("version", 0)),
            revisions=[
                SubtitleRevision(
                    old_source_text=str(revision.get("old_source_text", "")),
                    old_zh_text=str(revision.get("old_zh_text", "")),
                    reason=str(revision.get("reason", "")),
                )
                for revision in payload.get("revisions", [])
            ],
            updated_at=str(payload.get("updated_at", _utc_now().isoformat())),
        )

    def to_subtitle_segment(self) -> SubtitleSegment:
        return SubtitleSegment(
            segment_id=self.segment_id,
            source_text=self.source_text,
            zh_text=self.zh_text,
            translation_source_text=self.translation_source_text,
            status=self.status,
            version=self.version,
            revisions=list(self.revisions),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "segment_id": self.segment_id,
            "source_text": self.source_text,
            "zh_text": self.zh_text,
            "translation_source_text": self.translation_source_text,
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
            "updated_at": self.updated_at,
        }


@dataclass
class TranscriptSession:
    session_id: str
    started_at: str
    status: TranscriptSessionStatus
    asr_provider: str
    translation_provider: str
    source_language: str
    target_language: str
    recognition_mode: str
    ended_at: str = ""
    error_message: str = ""
    segments: list[TranscriptSegment] = field(default_factory=list)
    _segment_positions: dict[str, int] = field(
        init=False,
        repr=False,
        compare=False,
    )
    _lock: RLock = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        self._lock = RLock()
        self._segment_positions = {
            segment.segment_id: index for index, segment in enumerate(self.segments)
        }

    @classmethod
    def create(
        cls,
        *,
        asr_provider: str,
        translation_provider: str,
        source_language: str,
        target_language: str,
        recognition_mode: str,
        started_at: datetime | None = None,
        session_id: str | None = None,
    ) -> TranscriptSession:
        return cls(
            session_id=session_id or uuid4().hex,
            started_at=(started_at or _utc_now()).isoformat(),
            status=TranscriptSessionStatus.RUNNING,
            asr_provider=asr_provider,
            translation_provider=translation_provider,
            source_language=source_language,
            target_language=target_language,
            recognition_mode=recognition_mode,
        )

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> TranscriptSession:
        return cls(
            session_id=str(payload["session_id"]),
            started_at=str(payload["started_at"]),
            ended_at=str(payload.get("ended_at", "")),
            status=TranscriptSessionStatus(
                payload.get("status", TranscriptSessionStatus.INTERRUPTED.value)
            ),
            asr_provider=str(payload.get("asr_provider", "")),
            translation_provider=str(payload.get("translation_provider", "")),
            source_language=str(payload.get("source_language", "")),
            target_language=str(payload.get("target_language", "")),
            recognition_mode=str(payload.get("recognition_mode", "")),
            error_message=str(payload.get("error_message", "")),
            segments=[
                TranscriptSegment.from_dict(segment)
                for segment in payload.get("segments", [])
            ],
        )

    @property
    def is_open(self) -> bool:
        with self._lock:
            return self.status in {
                TranscriptSessionStatus.RUNNING,
                TranscriptSessionStatus.PAUSED,
            }

    @property
    def duration_seconds(self) -> float:
        with self._lock:
            started_at = _parse_datetime(self.started_at)
            ended_at = (
                _parse_datetime(self.ended_at) if self.ended_at else _utc_now()
            )
        return max(0.0, (ended_at - started_at).total_seconds())

    @property
    def translated_segment_count(self) -> int:
        with self._lock:
            return sum(
                bool(segment.zh_text.strip())
                and segment.zh_text.strip() != segment.source_text.strip()
                for segment in self.segments
            )

    def upsert_segment(
        self,
        segment: SubtitleSegment,
        *,
        updated_at: datetime | None = None,
    ) -> TranscriptSegment:
        snapshot = TranscriptSegment.from_subtitle_segment(
            segment,
            updated_at=updated_at,
        )
        with self._lock:
            position = self._segment_positions.get(segment.segment_id)
            if position is None:
                self._segment_positions[segment.segment_id] = len(self.segments)
                self.segments.append(snapshot)
            else:
                self.segments[position] = snapshot
        return snapshot

    def pause(self) -> None:
        with self._lock:
            if self.status == TranscriptSessionStatus.RUNNING:
                self.status = TranscriptSessionStatus.PAUSED

    def resume(self) -> None:
        with self._lock:
            if self.status == TranscriptSessionStatus.PAUSED:
                self.status = TranscriptSessionStatus.RUNNING

    def finish(
        self,
        status: TranscriptSessionStatus = TranscriptSessionStatus.STOPPED,
        *,
        ended_at: datetime | None = None,
        error_message: str = "",
    ) -> None:
        if status in {
            TranscriptSessionStatus.RUNNING,
            TranscriptSessionStatus.PAUSED,
        }:
            raise ValueError("finished sessions require a terminal status")
        with self._lock:
            self.status = status
            self.ended_at = (ended_at or _utc_now()).isoformat()
            self.error_message = error_message

    def to_dict(self) -> dict[str, Any]:
        with self._lock:
            return {
                "schema_version": 1,
                "session_id": self.session_id,
                "started_at": self.started_at,
                "ended_at": self.ended_at,
                "status": self.status.value,
                "asr_provider": self.asr_provider,
                "translation_provider": self.translation_provider,
                "source_language": self.source_language,
                "target_language": self.target_language,
                "recognition_mode": self.recognition_mode,
                "error_message": self.error_message,
                "segments": [segment.to_dict() for segment in self.segments],
            }


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
