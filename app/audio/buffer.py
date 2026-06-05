from __future__ import annotations

import numpy as np

from app.audio.capture import AudioChunk


class AudioRingBuffer:
    def __init__(self, max_duration_seconds: float, sample_rate: int) -> None:
        if max_duration_seconds <= 0:
            raise ValueError("max_duration_seconds must be greater than 0")
        if sample_rate <= 0:
            raise ValueError("sample_rate must be greater than 0")

        self.max_duration_seconds = max_duration_seconds
        self.sample_rate = sample_rate
        self.max_samples = int(max_duration_seconds * sample_rate)
        self._samples = np.empty((0,), dtype=np.float32)

    def append(self, chunk: AudioChunk) -> None:
        if chunk.sample_rate != self.sample_rate:
            raise ValueError("chunk sample_rate does not match ring buffer sample_rate")

        samples = _to_mono_float32(chunk.samples)
        self._samples = np.concatenate([self._samples, samples])
        if self._samples.shape[0] > self.max_samples:
            self._samples = self._samples[-self.max_samples :]

    def recent(self, duration_seconds: float | None = None) -> AudioChunk:
        if duration_seconds is None:
            samples = self._samples
        else:
            if duration_seconds <= 0:
                raise ValueError("duration_seconds must be greater than 0")
            sample_count = int(duration_seconds * self.sample_rate)
            samples = self._samples[-sample_count:]
        return AudioChunk(samples=samples.reshape(-1, 1), sample_rate=self.sample_rate)

    def clear(self) -> None:
        self._samples = np.empty((0,), dtype=np.float32)

    @property
    def duration_seconds(self) -> float:
        return self._samples.shape[0] / self.sample_rate


def _to_mono_float32(samples: np.ndarray) -> np.ndarray:
    data = np.asarray(samples, dtype=np.float32)
    if data.ndim == 1:
        return data
    if data.shape[1] == 1:
        return data[:, 0]
    return np.mean(data, axis=1, dtype=np.float32)

