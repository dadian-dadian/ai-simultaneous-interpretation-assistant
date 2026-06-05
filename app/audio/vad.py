from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import numpy as np
import onnxruntime as ort

from app.audio.capture import AudioChunk

SILERO_SAMPLE_RATE = 16000
SILERO_FRAME_SIZE = 512


class VadEventType(StrEnum):
    SPEECH_START = "speech_start"
    SPEECH_END = "speech_end"


@dataclass(frozen=True)
class VadFrameResult:
    speech_probability: float
    is_speech: bool


@dataclass(frozen=True)
class SpeechSegment:
    samples: np.ndarray
    sample_rate: int
    start_seconds: float
    end_seconds: float

    @property
    def duration_seconds(self) -> float:
        return max(0.0, self.end_seconds - self.start_seconds)

    def to_audio_chunk(self) -> AudioChunk:
        return AudioChunk(samples=self.samples.reshape(-1, 1), sample_rate=self.sample_rate)


@dataclass(frozen=True)
class VadSegmentEvent:
    type: VadEventType
    segment: SpeechSegment | None = None
    speech_probability: float = 0.0


class SileroOnnxVad:
    def __init__(
        self,
        model_path: str | Path | None = None,
        sample_rate: int = SILERO_SAMPLE_RATE,
        threshold: float = 0.5,
    ) -> None:
        if sample_rate != SILERO_SAMPLE_RATE:
            raise ValueError("Silero ONNX VAD currently expects 16000 Hz audio")
        if not 0 < threshold < 1:
            raise ValueError("threshold must be between 0 and 1")

        self.sample_rate = sample_rate
        self.threshold = threshold
        self.model_path = Path(model_path) if model_path else default_silero_model_path()
        self.session = ort.InferenceSession(
            str(self.model_path),
            providers=["CPUExecutionProvider"],
        )
        self.reset()

    def reset(self) -> None:
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._context = np.zeros((1, 64), dtype=np.float32)

    def predict(self, frame: np.ndarray) -> VadFrameResult:
        frame_data = np.asarray(frame, dtype=np.float32).reshape(-1)
        if frame_data.shape[0] != SILERO_FRAME_SIZE:
            raise ValueError(f"Silero VAD frame must contain {SILERO_FRAME_SIZE} samples")

        model_input = np.concatenate([self._context, frame_data.reshape(1, -1)], axis=1)
        output, state = self.session.run(
            None,
            {
                "input": model_input,
                "state": self._state,
                "sr": np.array(self.sample_rate, dtype=np.int64),
            },
        )
        self._state = state
        self._context = model_input[:, -64:]
        probability = float(output[0][0])
        return VadFrameResult(
            speech_probability=probability,
            is_speech=probability >= self.threshold,
        )


class SileroVadSegmenter:
    def __init__(
        self,
        vad: SileroOnnxVad,
        min_silence_ms: int = 600,
        speech_pad_ms: int = 96,
    ) -> None:
        if min_silence_ms <= 0:
            raise ValueError("min_silence_ms must be greater than 0")
        if speech_pad_ms < 0:
            raise ValueError("speech_pad_ms cannot be negative")

        self.vad = vad
        self.min_silence_frames = _ms_to_frame_count(min_silence_ms)
        self.speech_pad_frames = _ms_to_frame_count(speech_pad_ms)
        self.reset()

    def reset(self) -> None:
        self.vad.reset()
        self._pending_samples = np.empty((0,), dtype=np.float32)
        self._pre_speech_frames: list[np.ndarray] = []
        self._active_frames: list[np.ndarray] = []
        self._silence_frames = 0
        self._processed_samples = 0
        self._segment_start_sample = 0
        self._in_speech = False

    def accept_chunk(self, chunk: AudioChunk) -> list[VadSegmentEvent]:
        if chunk.sample_rate != self.vad.sample_rate:
            raise ValueError("chunk sample_rate does not match Silero VAD sample_rate")

        self._pending_samples = np.concatenate([self._pending_samples, _to_mono(chunk.samples)])
        events: list[VadSegmentEvent] = []

        while self._pending_samples.shape[0] >= SILERO_FRAME_SIZE:
            frame = self._pending_samples[:SILERO_FRAME_SIZE]
            self._pending_samples = self._pending_samples[SILERO_FRAME_SIZE:]
            events.extend(self._accept_frame(frame))
            self._processed_samples += SILERO_FRAME_SIZE

        return events

    def flush(self) -> list[VadSegmentEvent]:
        if not self._in_speech:
            return []

        if self._pending_samples.size:
            padded = np.zeros((SILERO_FRAME_SIZE,), dtype=np.float32)
            padded[: self._pending_samples.shape[0]] = self._pending_samples
            self._active_frames.append(padded)
            self._pending_samples = np.empty((0,), dtype=np.float32)

        segment = self._finish_segment()
        return [VadSegmentEvent(type=VadEventType.SPEECH_END, segment=segment)]

    def _accept_frame(self, frame: np.ndarray) -> list[VadSegmentEvent]:
        result = self.vad.predict(frame)
        if result.is_speech:
            return self._accept_speech_frame(frame, result.speech_probability)
        return self._accept_silence_frame(frame, result.speech_probability)

    def _accept_speech_frame(self, frame: np.ndarray, probability: float) -> list[VadSegmentEvent]:
        self._silence_frames = 0
        if not self._in_speech:
            self._in_speech = True
            self._segment_start_sample = max(
                0,
                self._processed_samples
                - len(self._pre_speech_frames) * SILERO_FRAME_SIZE,
            )
            self._active_frames = [*self._pre_speech_frames, frame]
            self._pre_speech_frames = []
            return [VadSegmentEvent(type=VadEventType.SPEECH_START, speech_probability=probability)]

        self._active_frames.append(frame)
        return []

    def _accept_silence_frame(self, frame: np.ndarray, probability: float) -> list[VadSegmentEvent]:
        if not self._in_speech:
            self._pre_speech_frames.append(frame)
            if self.speech_pad_frames > 0:
                self._pre_speech_frames = self._pre_speech_frames[-self.speech_pad_frames :]
            else:
                self._pre_speech_frames = []
            return []

        self._active_frames.append(frame)
        self._silence_frames += 1
        if self._silence_frames < self.min_silence_frames:
            return []

        segment = self._finish_segment()
        return [
            VadSegmentEvent(
                type=VadEventType.SPEECH_END,
                segment=segment,
                speech_probability=probability,
            )
        ]

    def _finish_segment(self) -> SpeechSegment:
        if self._silence_frames > 0:
            keep_frames = max(1, len(self._active_frames) - self._silence_frames)
            self._active_frames = self._active_frames[:keep_frames]

        samples = np.concatenate(self._active_frames).astype(np.float32)
        start_seconds = self._segment_start_sample / self.vad.sample_rate
        end_seconds = start_seconds + samples.shape[0] / self.vad.sample_rate
        segment = SpeechSegment(
            samples=samples,
            sample_rate=self.vad.sample_rate,
            start_seconds=start_seconds,
            end_seconds=end_seconds,
        )

        self._active_frames = []
        self._silence_frames = 0
        self._in_speech = False
        return segment


def default_silero_model_path() -> Path:
    return Path(__file__).resolve().parents[2] / "assets" / "models" / "silero_vad.onnx"


def _to_mono(samples: np.ndarray) -> np.ndarray:
    data = np.asarray(samples, dtype=np.float32)
    if data.ndim == 1:
        return data
    if data.shape[1] == 1:
        return data[:, 0]
    return np.mean(data, axis=1, dtype=np.float32)


def _ms_to_frame_count(value_ms: int) -> int:
    frame_ms = SILERO_FRAME_SIZE / SILERO_SAMPLE_RATE * 1000
    return max(1, int(round(value_ms / frame_ms)))
