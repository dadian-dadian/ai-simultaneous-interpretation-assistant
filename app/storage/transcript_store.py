from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.transcript_session import (
    TranscriptSession,
    TranscriptSessionStatus,
)


def default_transcript_storage_dir(override: str = "") -> Path:
    if override.strip():
        return Path(override).expanduser()
    local_app_data = os.getenv("LOCALAPPDATA")
    if local_app_data:
        base = Path(local_app_data)
    else:
        base = Path.home() / ".local" / "share"
    return base / "ai-simultaneous-interpretation-assistant" / "transcripts"


class TranscriptStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def save_session(self, session: TranscriptSession) -> None:
        self.save_payload(session.to_dict())

    def save_payload(self, payload: dict[str, Any]) -> None:
        session_id = str(payload["session_id"])
        target = self._session_path(session_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as file:
                json.dump(payload, file, ensure_ascii=False, indent=2)
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

    def load_session(self, session_id: str) -> TranscriptSession | None:
        path = self._session_path(session_id)
        if not path.exists():
            return None
        return self._load_path(path)

    def list_sessions(self, *, limit: int | None = 100) -> list[TranscriptSession]:
        if not self.root.exists():
            return []
        sessions: list[TranscriptSession] = []
        for path in self.root.glob("*.json"):
            try:
                sessions.append(self._load_path(path))
            except (KeyError, TypeError, ValueError, json.JSONDecodeError, OSError):
                continue
        sessions.sort(key=lambda session: session.started_at, reverse=True)
        if limit is None:
            return sessions
        return sessions[: max(0, limit)]

    def recover_interrupted_sessions(self) -> int:
        recovered = 0
        for session in self.list_sessions(limit=None):
            if not session.is_open:
                continue
            session.finish(TranscriptSessionStatus.INTERRUPTED)
            self.save_session(session)
            recovered += 1
        return recovered

    def _load_path(self, path: Path) -> TranscriptSession:
        with path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
        if not isinstance(payload, dict):
            raise TypeError("transcript payload must be a JSON object")
        return TranscriptSession.from_dict(payload)

    def _session_path(self, session_id: str) -> Path:
        if not session_id or Path(session_id).name != session_id:
            raise ValueError("invalid transcript session id")
        return self.root / f"{session_id}.json"


class TranscriptPersistence:
    def __init__(
        self,
        store: TranscriptStore,
        *,
        coalesce_seconds: float = 0.4,
    ) -> None:
        self.store = store
        self.coalesce_seconds = max(0.0, coalesce_seconds)
        self._condition = threading.Condition()
        self._pending: dict[str, TranscriptSession] = {}
        self._urgent: set[str] = set()
        self._writing = 0
        self._closed = False
        self._thread: threading.Thread | None = None
        self._last_error: Exception | None = None

    @property
    def last_error(self) -> Exception | None:
        with self._condition:
            return self._last_error

    def schedule(self, session: TranscriptSession, *, urgent: bool = False) -> None:
        session_id = session.session_id
        with self._condition:
            if self._closed:
                return
            self._ensure_thread_locked()
            self._pending[session_id] = session
            if urgent:
                self._urgent.add(session_id)
            self._condition.notify_all()

    def flush(self, timeout_seconds: float = 3.0) -> bool:
        deadline = time.monotonic() + max(0.0, timeout_seconds)
        with self._condition:
            self._urgent.update(self._pending)
            self._condition.notify_all()
            while self._pending or self._writing:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(remaining)
            return True

    def close(self, timeout_seconds: float = 3.0) -> bool:
        flushed = self.flush(timeout_seconds)
        with self._condition:
            self._closed = True
            self._condition.notify_all()
            thread = self._thread
        if thread is not None:
            thread.join(max(0.0, timeout_seconds))
        return flushed and (thread is None or not thread.is_alive())

    def _ensure_thread_locked(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run,
            name="transcript-persistence",
            daemon=True,
        )
        self._thread.start()

    def _run(self) -> None:
        while True:
            with self._condition:
                while not self._pending and not self._closed:
                    self._condition.wait()
                if self._closed and not self._pending:
                    return

                if not self._urgent and self.coalesce_seconds:
                    deadline = time.monotonic() + self.coalesce_seconds
                    while not self._urgent and not self._closed:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            break
                        self._condition.wait(remaining)

                sessions = list(self._pending.values())
                self._pending.clear()
                self._urgent.clear()
                self._writing += len(sessions)

            batch_error: Exception | None = None
            for session in sessions:
                try:
                    self.store.save_session(session)
                except Exception as exc:  # noqa: BLE001
                    batch_error = exc
            with self._condition:
                self._last_error = batch_error
                self._writing -= len(sessions)
                self._condition.notify_all()
