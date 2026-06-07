from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass, field

from app.translate.types import TranslationClient

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TranslationRequest:
    segment_id: str
    source_version: int
    source_text: str
    source_language: str
    target_language: str
    is_final: bool
    allow_source_prefix: bool = False
    session_id: str = "default"
    submitted_at: float = field(default_factory=time.monotonic)


@dataclass(frozen=True)
class TranslationUpdate:
    segment_id: str
    source_version: int
    source_text: str
    translated_text: str
    source_language: str
    target_language: str
    provider: str
    is_final: bool
    allow_source_prefix: bool = False
    session_id: str = "default"


class SentenceTranslationManager:
    """Serialize provider calls while coalescing replaceable MID requests."""

    def __init__(
        self,
        *,
        client: TranslationClient,
        source_language: str,
        target_language: str,
        on_update: Callable[[TranslationUpdate], None],
        max_queue_size: int = 32,
    ) -> None:
        if max_queue_size <= 0:
            raise ValueError("max_queue_size must be greater than 0")
        self.client = client
        self.source_language = source_language
        self.target_language = target_language
        self.on_update = on_update
        self.max_queue_size = max_queue_size

        self._condition = threading.Condition()
        self._pending_finals: deque[TranslationRequest] = deque()
        self._pending_partials: OrderedDict[
            tuple[str, str],
            TranslationRequest,
        ] = OrderedDict()
        self._latest_requests: dict[tuple[str, str], TranslationRequest] = {}
        self._final_requested: set[tuple[str, str]] = set()
        self._emitted_partial_words: dict[tuple[str, str], int] = {}
        self._active_session_id = "default"
        self._inflight = False
        self._served_final_since_partial = False
        self._closed = False
        self._thread = threading.Thread(
            target=self._run,
            name="sentence-translation-manager",
            daemon=True,
        )
        self._thread.start()

    @property
    def pending_count(self) -> int:
        with self._condition:
            return (
                len(self._pending_finals)
                + len(self._pending_partials)
                + int(self._inflight)
            )

    def wait_until_idle(self, timeout_seconds: float = 5.0) -> bool:
        deadline = time.monotonic() + timeout_seconds
        with self._condition:
            while (
                self._inflight
                or self._pending_finals
                or self._pending_partials
            ):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(remaining)
            return True

    def begin_session(self, session_id: str) -> None:
        normalized = session_id.strip()
        if not normalized:
            raise ValueError("session_id cannot be empty")
        with self._condition:
            if self._closed:
                return
            self._active_session_id = normalized
            self._pending_finals.clear()
            self._pending_partials.clear()
            self._latest_requests.clear()
            self._final_requested.clear()
            self._emitted_partial_words.clear()
            self._condition.notify_all()

    def submit(
        self,
        *,
        segment_id: str,
        source_version: int,
        source_text: str,
        is_final: bool,
        allow_source_prefix: bool = False,
        session_id: str | None = None,
    ) -> None:
        normalized_text = source_text.strip()
        if not normalized_text:
            return

        with self._condition:
            if self._closed:
                return
            active_session_id = self._active_session_id
            request_session_id = session_id or active_session_id
            if request_session_id != active_session_id:
                return

            request = TranslationRequest(
                segment_id=segment_id,
                source_version=source_version,
                source_text=normalized_text,
                source_language=self.source_language,
                target_language=self.target_language,
                is_final=is_final,
                allow_source_prefix=allow_source_prefix,
                session_id=request_session_id,
            )
            key = _request_key(request)
            if not is_final and key in self._final_requested:
                return

            self._latest_requests[key] = request
            if is_final:
                self._final_requested.add(key)
                self._pending_partials.pop(key, None)
                self._remove_pending_final(key)
                self._pending_finals.append(request)
            else:
                self._pending_partials[key] = request
                self._pending_partials.move_to_end(key)
            self._trim_pending_locked()
            self._condition.notify()

    def stop(self, timeout_seconds: float = 2.0) -> None:
        with self._condition:
            if self._closed:
                return
            self._closed = True
            self._pending_finals.clear()
            self._pending_partials.clear()
            self._condition.notify_all()
        self._thread.join(timeout_seconds)
        close_client = getattr(self.client, "close", None)
        if callable(close_client):
            close_client()

    def _run(self) -> None:
        warm_up = getattr(self.client, "warm_up", None)
        if callable(warm_up):
            try:
                warm_up()
            except Exception:  # noqa: BLE001
                logger.debug("Translation client warm-up failed", exc_info=True)
        while True:
            request = self._next_request()
            if request is None:
                return
            try:
                if not self._should_execute(request):
                    continue
                result = self.client.translate(
                    request.source_text,
                    request.source_language,
                    request.target_language,
                )
                if not self._should_emit(request):
                    continue
                self.on_update(
                    TranslationUpdate(
                        segment_id=request.segment_id,
                        source_version=request.source_version,
                        source_text=request.source_text,
                        translated_text=result.translated_text,
                        source_language=result.source_language,
                        target_language=result.target_language,
                        provider=result.provider,
                        is_final=request.is_final,
                        allow_source_prefix=request.allow_source_prefix,
                        session_id=request.session_id,
                    )
                )
            except Exception:  # noqa: BLE001
                logger.exception("Translation failed for %s", request.segment_id)
            finally:
                self._mark_request_complete()

    def _next_request(self) -> TranslationRequest | None:
        with self._condition:
            while (
                not self._closed
                and not self._pending_finals
                and not self._pending_partials
            ):
                self._condition.wait()
            if self._closed:
                return None
            if self._pending_partials and (
                not self._pending_finals or self._served_final_since_partial
            ):
                _, request = self._pending_partials.popitem(last=True)
                self._served_final_since_partial = False
            elif self._pending_finals:
                request = self._pending_finals.popleft()
                self._served_final_since_partial = True
            else:
                _, request = self._pending_partials.popitem(last=True)
                self._served_final_since_partial = False
            self._inflight = True
            return request

    def _mark_request_complete(self) -> None:
        with self._condition:
            self._inflight = False
            self._condition.notify_all()

    def _should_execute(self, request: TranslationRequest) -> bool:
        with self._condition:
            if request.session_id != self._active_session_id:
                return False
            latest = self._latest_requests.get(_request_key(request))
            if latest is None:
                return False
            if request.is_final:
                return _same_source_revision(request, latest)
            return not latest.is_final

    def _should_emit(self, request: TranslationRequest) -> bool:
        with self._condition:
            if request.session_id != self._active_session_id:
                return False
            key = _request_key(request)
            latest = self._latest_requests.get(key)
            if latest is None:
                return False
            if request.is_final:
                return _same_source_revision(request, latest)
            if key in self._final_requested or latest.is_final:
                return False
            if not request.allow_source_prefix:
                return _same_source_revision(request, latest)
            if not _is_source_prefix(request.source_text, latest.source_text):
                return False

            translated_words = len(request.source_text.split())
            if translated_words < self._emitted_partial_words.get(key, 0):
                return False
            self._emitted_partial_words[key] = translated_words
            return True

    def _remove_pending_final(self, key: tuple[str, str]) -> None:
        if not self._pending_finals:
            return
        self._pending_finals = deque(
            request
            for request in self._pending_finals
            if _request_key(request) != key
        )

    def _trim_pending_locked(self) -> None:
        while len(self._pending_finals) + len(self._pending_partials) > self.max_queue_size:
            if len(self._pending_partials) > 1:
                _, dropped = self._pending_partials.popitem(last=False)
                self._forget_request_if_latest(dropped)
                continue
            if self._pending_finals:
                dropped = self._pending_finals.popleft()
                self._forget_request_if_latest(dropped)
                continue
            if self._pending_partials:
                _, dropped = self._pending_partials.popitem(last=False)
                self._forget_request_if_latest(dropped)
                continue
            return

    def _forget_request_if_latest(self, request: TranslationRequest) -> None:
        key = _request_key(request)
        if self._latest_requests.get(key) == request:
            self._latest_requests.pop(key, None)
        if request.is_final:
            self._final_requested.discard(key)


def _request_key(request: TranslationRequest) -> tuple[str, str]:
    return request.session_id, request.segment_id


def _same_source_revision(
    left: TranslationRequest,
    right: TranslationRequest,
) -> bool:
    return (
        left.source_version == right.source_version
        and left.source_text == right.source_text
        and left.is_final == right.is_final
    )


def _is_source_prefix(prefix_text: str, full_text: str) -> bool:
    prefix_words = prefix_text.casefold().split()
    full_words = full_text.casefold().split()
    if not prefix_words or len(prefix_words) > len(full_words):
        return False
    return prefix_words == full_words[: len(prefix_words)]
