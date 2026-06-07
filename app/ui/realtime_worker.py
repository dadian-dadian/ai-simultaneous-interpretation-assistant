from __future__ import annotations

import time
from threading import Event
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot

from app.asr import AsrClient, AsrError, create_asr_client
from app.audio.buffer import AudioRingBuffer
from app.audio.capture import AudioChunk, QueuedAudioCapture, SystemAudioCapture
from app.audio.vad import SileroOnnxVad, SileroVadSegmenter, VadEventType
from app.core.asr_sentence import AsrSentenceMapper, normalize_asr_sentence_text
from app.core.config import AppConfig
from app.core.subtitle import SubtitleEvent


class RealtimeSubtitleWorker(QObject):
    subtitle_event = Signal(object)
    status_changed = Signal(str)
    dropped_chunks_changed = Signal(int)
    error_occurred = Signal(str)
    warning_occurred = Signal(str)
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
        max_stream_duration_seconds: float = 0.0,
        rollover_preroll_seconds: float = 0.32,
    ) -> None:
        super().__init__()
        self.config = config
        self.chunk_duration_seconds = chunk_duration_seconds
        self.vad_threshold = vad_threshold
        self.vad_min_silence_ms = vad_min_silence_ms
        self.preroll_seconds = preroll_seconds
        self.queue_size = queue_size
        self.dropped_chunks_warn_threshold = dropped_chunks_warn_threshold
        self.max_stream_duration_seconds = max_stream_duration_seconds
        self.rollover_preroll_seconds = rollover_preroll_seconds
        self._stop_event = Event()
        self._queued_capture: QueuedAudioCapture | None = None
        self._last_reported_dropped_chunks = 0

    @Slot()
    def run(self) -> None:
        self._stop_event.clear()
        stream_session = None
        stream_duration_seconds = 0.0
        active_segment_id = ""
        sentence_mapper: AsrSentenceMapper | None = None
        segment_index = 0
        next_stream_retry_at = 0.0

        try:
            client = create_asr_client(self.config)
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
                        sentence_mapper = AsrSentenceMapper(active_segment_id)
                        stream_duration_seconds = 0.0
                        self.status_changed.emit("识别中")

                        if supports_streaming_asr(client):
                            stream_session, stream_duration_seconds = (
                                self._try_start_stream_segment(
                                    client,
                                    buffer,
                                    sentence_mapper=sentence_mapper,
                                    preroll_seconds=self.preroll_seconds,
                                    warning_prefix="实时 ASR 连接启动失败",
                                )
                            )
                            current_chunk_sent = stream_session is not None
                            next_stream_retry_at = (
                                0.0
                                if stream_session is not None
                                else time.monotonic() + 1.0
                            )
                    elif event.segment is not None:
                        speech_end = event

                if (
                    active_segment_id
                    and stream_session is None
                    and sentence_mapper is not None
                    and speech_end is None
                    and supports_streaming_asr(client)
                    and time.monotonic() >= next_stream_retry_at
                ):
                    stream_session, stream_duration_seconds = (
                        self._try_start_stream_segment(
                            client,
                            buffer,
                            sentence_mapper=sentence_mapper,
                            preroll_seconds=self.rollover_preroll_seconds,
                            warning_prefix="实时 ASR 连接恢复失败",
                        )
                    )
                    current_chunk_sent = stream_session is not None
                    next_stream_retry_at = (
                        0.0
                        if stream_session is not None
                        else time.monotonic() + 1.0
                    )

                if stream_session is not None and not current_chunk_sent:
                    if sentence_mapper is None:
                        sentence_mapper = AsrSentenceMapper(active_segment_id)
                    try:
                        self._emit_transcripts(
                            sentence_mapper,
                            stream_session.send_audio(chunk),
                        )
                        stream_duration_seconds += chunk.duration_seconds
                    except AsrError as exc:
                        stream_session.close()
                        stream_session, stream_duration_seconds = (
                            self._try_start_stream_segment(
                                client,
                                buffer,
                                sentence_mapper=sentence_mapper,
                                preroll_seconds=self.rollover_preroll_seconds,
                                warning_prefix=(
                                    "实时 ASR 连接已断开，已尝试自动重连"
                                ),
                                cause=exc,
                            )
                        )
                        current_chunk_sent = stream_session is not None
                        next_stream_retry_at = (
                            0.0
                            if stream_session is not None
                            else time.monotonic() + 1.0
                        )
                    if speech_end is None and self._should_rollover_stream(
                        stream_duration_seconds
                    ):
                        self._rollover_stream_segment(
                            stream_session,
                            sentence_mapper=sentence_mapper,
                        )
                        segment_index += 1
                        active_segment_id = f"asr_{segment_index:04d}"
                        sentence_mapper = AsrSentenceMapper(active_segment_id)
                        stream_session, stream_duration_seconds = self._try_start_stream_segment(
                            client,
                            buffer,
                            sentence_mapper=sentence_mapper,
                            preroll_seconds=self.rollover_preroll_seconds,
                            warning_prefix="实时 ASR 会话轮转失败",
                        )
                        current_chunk_sent = stream_session is not None
                        next_stream_retry_at = (
                            0.0
                            if stream_session is not None
                            else time.monotonic() + 1.0
                        )

                if speech_end is not None:
                    if stream_session is not None:
                        finishing_session = stream_session
                        stream_session = None
                        if sentence_mapper is None:
                            sentence_mapper = AsrSentenceMapper(active_segment_id)
                        self._finish_stream_segment(
                            finishing_session,
                            sentence_mapper=sentence_mapper,
                            duration_seconds=stream_duration_seconds,
                        )
                    else:
                        self._transcribe_segment(
                            client,
                            segment_id=active_segment_id,
                            audio=speech_end.segment.to_audio_chunk(),
                        )

                    active_segment_id = ""
                    stream_duration_seconds = 0.0
                    sentence_mapper = None
                    self.status_changed.emit("监听中")

            if stream_session is not None:
                stream_session.close()
        except AsrError as exc:
            self.error_occurred.emit(f"ASR 识别失败：{exc}")
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
            self.finished.emit()

    @Slot()
    def stop(self) -> None:
        self._stop_event.set()
        if self._queued_capture is not None:
            self._queued_capture.stop()

    def _emit_transcripts(
        self,
        sentence_mapper: AsrSentenceMapper,
        transcripts: list[Any],
    ) -> None:
        for event in sentence_mapper.accept_transcripts(transcripts):
            self.subtitle_event.emit(event)

    def _emit_final_text(self, segment_id: str, text: str) -> None:
        display_text = normalize_asr_sentence_text(text) or "（未识别到清晰语音）"
        self.subtitle_event.emit(SubtitleEvent.final(segment_id, display_text, display_text))

    def _start_stream_segment(
        self,
        client: AsrClient,
        buffer: AudioRingBuffer,
        *,
        sentence_mapper: AsrSentenceMapper,
        preroll_seconds: float,
    ) -> tuple[Any, float]:
        stream_session = client.start_stream(
            language=self.config.source_language,
            prompt="",
        )
        preroll = buffer.recent(duration_seconds=preroll_seconds)
        try:
            self._emit_transcripts(
                sentence_mapper,
                stream_session.send_audio(preroll),
            )
        except Exception:
            stream_session.close()
            raise
        return stream_session, preroll.duration_seconds

    def _try_start_stream_segment(
        self,
        client: AsrClient,
        buffer: AudioRingBuffer,
        *,
        sentence_mapper: AsrSentenceMapper,
        preroll_seconds: float,
        warning_prefix: str,
        cause: AsrError | None = None,
    ) -> tuple[Any | None, float]:
        try:
            return self._start_stream_segment(
                client,
                buffer,
                sentence_mapper=sentence_mapper,
                preroll_seconds=preroll_seconds,
            )
        except AsrError as exc:
            if cause is not None:
                self.warning_occurred.emit(f"{warning_prefix}：{cause}；重连失败：{exc}")
            else:
                self.warning_occurred.emit(f"{warning_prefix}：{exc}")
            return None, 0.0

    def _should_rollover_stream(self, duration_seconds: float) -> bool:
        return (
            self.max_stream_duration_seconds > 0
            and duration_seconds >= self.max_stream_duration_seconds
        )

    def _rollover_stream_segment(
        self,
        stream_session: Any,
        *,
        sentence_mapper: AsrSentenceMapper,
    ) -> None:
        del sentence_mapper
        stream_session.close()

    def _finish_stream_segment(
        self,
        stream_session: Any,
        *,
        sentence_mapper: AsrSentenceMapper,
        duration_seconds: float,
    ) -> None:
        try:
            result = stream_session.finish(duration_seconds=duration_seconds)
        except AsrError as exc:
            stream_session.close()
            self.warning_occurred.emit(f"当前语音段未能确认，已继续监听：{exc}")
            return

        events = sentence_mapper.accept_finish_result(
            result,
            allow_result_text_fallback=False,
        )
        if not events:
            self.warning_occurred.emit("当前语音段未识别到清晰语音，已继续监听。")
            return
        for event in events:
            self.subtitle_event.emit(event)

    def _transcribe_segment(
        self,
        client: AsrClient,
        *,
        segment_id: str,
        audio: AudioChunk,
    ) -> None:
        try:
            result = client.transcribe(
                audio,
                language=self.config.source_language,
                prompt="",
            )
        except AsrError as exc:
            self.warning_occurred.emit(f"当前语音段未识别，已继续监听：{exc}")
            return
        final_text = normalize_asr_sentence_text(result.text)
        if not final_text:
            self.warning_occurred.emit("当前语音段未识别到清晰语音，已继续监听。")
            return
        self._emit_final_text(segment_id, final_text)

    def _report_dropped_chunks(self) -> None:
        if self._queued_capture is None:
            return
        dropped_chunks = self._queued_capture.dropped_chunks
        if dropped_chunks == self._last_reported_dropped_chunks:
            return
        self._last_reported_dropped_chunks = dropped_chunks
        self.dropped_chunks_changed.emit(dropped_chunks)


def supports_streaming_asr(client: AsrClient) -> bool:
    return callable(getattr(client, "start_stream", None))
