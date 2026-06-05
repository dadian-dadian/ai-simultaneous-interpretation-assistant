from __future__ import annotations

import time
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from threading import Event, Lock
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot

from app.asr import AsrClient, AsrError, create_asr_client
from app.audio.buffer import AudioRingBuffer
from app.audio.capture import QueuedAudioCapture, SystemAudioCapture
from app.audio.vad import SileroOnnxVad, SileroVadSegmenter, VadEventType
from app.core.config import AppConfig
from app.core.subtitle import SubtitleEvent
from app.translate import (
    TranslationError,
    TranslationRequest,
    TranslatorClient,
    create_translator_client,
)

EMPTY_SPEECH_TEXT = "（未识别到清晰语音）"


class RealtimeSubtitleWorker(QObject):
    subtitle_event = Signal(object)
    status_changed = Signal(str)
    dropped_chunks_changed = Signal(int)
    error_occurred = Signal(str)
    translation_error_occurred = Signal(str)
    finished = Signal()

    def __init__(
        self,
        config: AppConfig,
        *,
        chunk_duration_seconds: float = 0.16,
        vad_threshold: float = 0.5,
        vad_min_silence_ms: int = 800,
        preroll_seconds: float = 0.8,
        queue_size: int = 32,
        dropped_chunks_warn_threshold: int = 8,
        partial_translation_debounce_seconds: float = 0.8,
        final_context_sentences: int = 3,
        min_partial_delta_chars: int = 12,
    ) -> None:
        super().__init__()
        self.config = config
        self.chunk_duration_seconds = chunk_duration_seconds
        self.vad_threshold = vad_threshold
        self.vad_min_silence_ms = vad_min_silence_ms
        self.preroll_seconds = preroll_seconds
        self.queue_size = queue_size
        self.dropped_chunks_warn_threshold = dropped_chunks_warn_threshold
        self.partial_translation_debounce_seconds = partial_translation_debounce_seconds
        self.final_context_sentences = final_context_sentences
        self.min_partial_delta_chars = min_partial_delta_chars
        self._stop_event = Event()
        self._queued_capture: QueuedAudioCapture | None = None
        self._last_reported_dropped_chunks = 0
        self._translation_executor: ThreadPoolExecutor | None = None
        self._translator: TranslatorClient | None = None
        self._translation_lock = Lock()
        self._translation_closed = False
        self._context_sources: deque[str] = deque(maxlen=final_context_sentences)
        self._latest_source_by_segment: dict[str, str] = {}
        self._partial_zh_by_segment: dict[str, str] = {}
        self._finalized_segments: set[str] = set()
        self._last_partial_translation_at: dict[str, float] = {}
        self._last_partial_translation_source: dict[str, str] = {}

    @Slot()
    def run(self) -> None:
        self._stop_event.clear()
        self._reset_translation_state()
        stream_session = None
        stream_duration_seconds = 0.0
        active_segment_id = ""
        last_partial_text = ""
        segment_index = 0

        try:
            client = create_asr_client(self.config)
            self._translator = create_translator_client(self.config)
            self._translation_executor = ThreadPoolExecutor(
                max_workers=2,
                thread_name_prefix="translation",
            )
            capture = SystemAudioCapture(sample_rate=16000, channels=1)
            buffer = AudioRingBuffer(max_duration_seconds=8.0, sample_rate=16000)
            segmenter = SileroVadSegmenter(
                vad=SileroOnnxVad(threshold=self.vad_threshold),
                min_silence_ms=self.vad_min_silence_ms,
            )
            self._queued_capture = QueuedAudioCapture(
                capture,
                chunk_duration_seconds=self.chunk_duration_seconds,
                max_chunks=self.queue_size,
            )
            self._queued_capture.start()
            self._last_reported_dropped_chunks = 0
            self.dropped_chunks_changed.emit(0)
            self.status_changed.emit("监听中")

            while not self._stop_event.is_set():
                chunk = self._queued_capture.get_chunk(timeout_seconds=0.25)
                if chunk is None:
                    continue

                self._report_dropped_chunks()
                buffer.append(chunk)
                vad_events = segmenter.accept_chunk(chunk)
                current_chunk_sent = False
                speech_end = None

                for event in vad_events:
                    if event.type == VadEventType.SPEECH_START:
                        segment_index += 1
                        active_segment_id = f"asr_{segment_index:04d}"
                        last_partial_text = ""
                        stream_duration_seconds = 0.0
                        self.status_changed.emit("识别中")

                        if supports_streaming_asr(client):
                            stream_session = client.start_stream(
                                language=self.config.source_language,
                                prompt="",
                            )
                            preroll = buffer.recent(duration_seconds=self.preroll_seconds)
                            last_partial_text = self._emit_partial_transcripts(
                                active_segment_id,
                                stream_session.send_audio(preroll),
                                last_partial_text,
                            )
                            stream_duration_seconds = preroll.duration_seconds
                            current_chunk_sent = True
                    elif event.segment is not None:
                        speech_end = event

                if stream_session is not None and not current_chunk_sent:
                    last_partial_text = self._emit_partial_transcripts(
                        active_segment_id,
                        stream_session.send_audio(chunk),
                        last_partial_text,
                    )
                    stream_duration_seconds += chunk.duration_seconds

                if speech_end is not None:
                    if stream_session is not None:
                        result = stream_session.finish(duration_seconds=stream_duration_seconds)
                        stream_session = None
                        self._emit_final_text(active_segment_id, result.text)
                    else:
                        result = client.transcribe(
                            speech_end.segment.to_audio_chunk(),
                            language=self.config.source_language,
                            prompt="",
                        )
                        self._emit_final_text(active_segment_id, result.text)

                    active_segment_id = ""
                    stream_duration_seconds = 0.0
                    last_partial_text = ""
                    self.status_changed.emit("监听中")

            if stream_session is not None:
                stream_session.close()
        except AsrError as exc:
            self.error_occurred.emit(f"ASR 识别失败：{exc}")
        except TranslationError as exc:
            self.error_occurred.emit(f"翻译初始化失败：{exc}")
        except RuntimeError as exc:
            self.error_occurred.emit(f"音频采集失败：{exc}")
        except Exception as exc:  # noqa: BLE001
            self.error_occurred.emit(f"实时字幕线程异常：{exc}")
        finally:
            if stream_session is not None:
                stream_session.close()
            if self._queued_capture is not None:
                self._queued_capture.stop()
                self._queued_capture = None
            self._shutdown_translation_executor()
            self.finished.emit()

    @Slot()
    def stop(self) -> None:
        self._stop_event.set()
        if self._queued_capture is not None:
            self._queued_capture.stop()

    def _emit_partial_transcripts(
        self,
        segment_id: str,
        transcripts: list[Any],
        last_partial_text: str,
    ) -> str:
        current_text = last_partial_text
        for transcript in transcripts:
            if getattr(transcript, "is_final", False):
                continue
            text = _normalize_asr_text(getattr(transcript, "text", ""))
            if not text or text == current_text:
                continue
            current_text = text
            zh_text = self._remember_partial_source(segment_id, text)
            self.subtitle_event.emit(SubtitleEvent.partial(segment_id, text, zh_text))
            self._schedule_partial_translation(segment_id, text)
        return current_text

    def _emit_final_text(self, segment_id: str, text: str) -> None:
        display_text = _normalize_asr_text(text) or EMPTY_SPEECH_TEXT
        zh_text, context = self._finalize_segment(segment_id, display_text)
        self.subtitle_event.emit(SubtitleEvent.final(segment_id, display_text, zh_text))
        if display_text != EMPTY_SPEECH_TEXT:
            self._schedule_final_translation(segment_id, display_text, zh_text, context)

    def _report_dropped_chunks(self) -> None:
        if self._queued_capture is None:
            return
        dropped_chunks = self._queued_capture.dropped_chunks
        if dropped_chunks == self._last_reported_dropped_chunks:
            return
        self._last_reported_dropped_chunks = dropped_chunks
        self.dropped_chunks_changed.emit(dropped_chunks)

    def _reset_translation_state(self) -> None:
        with self._translation_lock:
            self._translation_closed = False
            self._context_sources = deque(maxlen=self.final_context_sentences)
            self._latest_source_by_segment = {}
            self._partial_zh_by_segment = {}
            self._finalized_segments = set()
            self._last_partial_translation_at = {}
            self._last_partial_translation_source = {}

    def _shutdown_translation_executor(self) -> None:
        with self._translation_lock:
            self._translation_closed = True
        if self._translation_executor is not None:
            self._translation_executor.shutdown(wait=False, cancel_futures=True)
            self._translation_executor = None
        self._translator = None

    def _remember_partial_source(self, segment_id: str, source_text: str) -> str:
        with self._translation_lock:
            self._latest_source_by_segment[segment_id] = source_text
            return self._partial_zh_by_segment.get(segment_id, source_text)

    def _finalize_segment(self, segment_id: str, source_text: str) -> tuple[str, tuple[str, ...]]:
        with self._translation_lock:
            self._latest_source_by_segment[segment_id] = source_text
            self._finalized_segments.add(segment_id)
            zh_text = self._partial_zh_by_segment.get(segment_id, source_text)
            context = tuple(self._context_sources)
            if source_text != EMPTY_SPEECH_TEXT:
                self._context_sources.append(source_text)
            return zh_text, context

    def _schedule_partial_translation(self, segment_id: str, source_text: str) -> None:
        executor = self._translation_executor
        translator = self._translator
        if executor is None or translator is None:
            return

        now = time.monotonic()
        with self._translation_lock:
            if self._translation_closed or segment_id in self._finalized_segments:
                return
            if len(source_text) < self.min_partial_delta_chars:
                return
            last_source = self._last_partial_translation_source.get(segment_id, "")
            if source_text == last_source:
                return
            last_at = self._last_partial_translation_at.get(segment_id, 0.0)
            if now - last_at < self.partial_translation_debounce_seconds:
                return
            source_delta = abs(len(source_text) - len(last_source))
            if last_source and source_delta < self.min_partial_delta_chars:
                return
            self._last_partial_translation_at[segment_id] = now
            self._last_partial_translation_source[segment_id] = source_text
            context = tuple(self._context_sources)

        future = executor.submit(self._translate_source, source_text, context)
        future.add_done_callback(
            lambda task: self._handle_partial_translation_result(segment_id, source_text, task)
        )

    def _schedule_final_translation(
        self,
        segment_id: str,
        source_text: str,
        current_zh_text: str,
        context: tuple[str, ...],
    ) -> None:
        executor = self._translation_executor
        if executor is None or self._translator is None:
            return

        future = executor.submit(self._translate_source, source_text, context)
        future.add_done_callback(
            lambda task: self._handle_final_translation_result(
                segment_id,
                source_text,
                current_zh_text,
                task,
            )
        )

    def _translate_source(self, source_text: str, context: tuple[str, ...]) -> str:
        translator = self._translator
        if translator is None:
            raise TranslationError("翻译器尚未初始化。")
        result = translator.translate(
            TranslationRequest(
                source_text=source_text,
                source_language=self.config.source_language,
                target_language=self.config.target_language,
                context=context,
            )
        )
        return result.text

    def _handle_partial_translation_result(
        self,
        segment_id: str,
        source_text: str,
        future: Future[str],
    ) -> None:
        try:
            zh_text = _normalize_asr_text(future.result())
        except TranslationError as exc:
            self.translation_error_occurred.emit(f"翻译失败：{exc}")
            return
        except Exception as exc:  # noqa: BLE001
            self.translation_error_occurred.emit(f"翻译线程异常：{exc}")
            return

        if not zh_text:
            return
        with self._translation_lock:
            if self._translation_closed:
                return
            if segment_id in self._finalized_segments:
                return
            if self._latest_source_by_segment.get(segment_id) != source_text:
                return
            self._partial_zh_by_segment[segment_id] = zh_text
        self.subtitle_event.emit(SubtitleEvent.partial(segment_id, source_text, zh_text))

    def _handle_final_translation_result(
        self,
        segment_id: str,
        source_text: str,
        old_zh_text: str,
        future: Future[str],
    ) -> None:
        try:
            zh_text = _normalize_asr_text(future.result())
        except TranslationError as exc:
            self.translation_error_occurred.emit(f"翻译失败：{exc}")
            return
        except Exception as exc:  # noqa: BLE001
            self.translation_error_occurred.emit(f"翻译线程异常：{exc}")
            return

        if not zh_text or zh_text == old_zh_text:
            return
        with self._translation_lock:
            if self._translation_closed:
                return
            if self._latest_source_by_segment.get(segment_id) != source_text:
                return
            self._partial_zh_by_segment[segment_id] = zh_text
        self.subtitle_event.emit(
            SubtitleEvent.update(
                segment_id=segment_id,
                source_text=source_text,
                zh_text=zh_text,
                old_source_text=source_text,
                old_zh_text=old_zh_text,
                reason="translation_final",
            )
        )


def supports_streaming_asr(client: AsrClient) -> bool:
    return callable(getattr(client, "start_stream", None))


def _normalize_asr_text(text: str) -> str:
    return " ".join(text.strip().split())
