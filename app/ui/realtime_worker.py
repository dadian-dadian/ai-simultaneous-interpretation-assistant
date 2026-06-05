from __future__ import annotations

from threading import Event
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot

from app.asr import AsrClient, AsrError, create_asr_client
from app.audio.buffer import AudioRingBuffer
from app.audio.capture import QueuedAudioCapture, SystemAudioCapture
from app.audio.vad import SileroOnnxVad, SileroVadSegmenter, VadEventType
from app.core.config import AppConfig
from app.core.subtitle import SubtitleEvent


class RealtimeSubtitleWorker(QObject):
    subtitle_event = Signal(object)
    status_changed = Signal(str)
    error_occurred = Signal(str)
    finished = Signal()

    def __init__(
        self,
        config: AppConfig,
        *,
        chunk_duration_seconds: float = 0.16,
        vad_threshold: float = 0.5,
        vad_min_silence_ms: int = 600,
        queue_size: int = 32,
    ) -> None:
        super().__init__()
        self.config = config
        self.chunk_duration_seconds = chunk_duration_seconds
        self.vad_threshold = vad_threshold
        self.vad_min_silence_ms = vad_min_silence_ms
        self.queue_size = queue_size
        self._stop_event = Event()
        self._queued_capture: QueuedAudioCapture | None = None

    @Slot()
    def run(self) -> None:
        self._stop_event.clear()
        stream_session = None
        stream_duration_seconds = 0.0
        active_segment_id = ""
        last_partial_text = ""
        segment_index = 0

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
            self.status_changed.emit("监听中")

            while not self._stop_event.is_set():
                chunk = self._queued_capture.get_chunk(timeout_seconds=0.25)
                if chunk is None:
                    continue

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
                            preroll = buffer.recent(duration_seconds=0.5)
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
            self.subtitle_event.emit(SubtitleEvent.partial(segment_id, text, text))
        return current_text

    def _emit_final_text(self, segment_id: str, text: str) -> None:
        display_text = _normalize_asr_text(text) or "（未识别到清晰语音）"
        self.subtitle_event.emit(SubtitleEvent.final(segment_id, display_text, display_text))


def supports_streaming_asr(client: AsrClient) -> bool:
    return callable(getattr(client, "start_stream", None))


def _normalize_asr_text(text: str) -> str:
    return " ".join(text.strip().split())
