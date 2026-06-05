from __future__ import annotations

import io
import queue
import wave
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from threading import Event, Lock, Thread

import numpy as np
import soundcard as sc


@dataclass(frozen=True)
class AudioOutputDevice:
    id: str
    name: str
    channels: int
    is_default: bool = False


@dataclass(frozen=True)
class AudioChunk:
    samples: np.ndarray
    sample_rate: int

    @classmethod
    def from_wav(cls, path: str | Path) -> AudioChunk:
        source = Path(path)
        with wave.open(str(source), "rb") as wav_file:
            channels = wav_file.getnchannels()
            sample_width = wav_file.getsampwidth()
            sample_rate = wav_file.getframerate()
            frame_count = wav_file.getnframes()
            payload = wav_file.readframes(frame_count)

        if sample_width != 2:
            raise ValueError("Only 16-bit PCM wav files are supported")

        samples = np.frombuffer(payload, dtype=np.int16).astype(np.float32) / 32768.0
        if channels == 1:
            samples = samples.reshape(-1, 1)
        else:
            samples = samples.reshape(-1, channels)
        return cls(samples=samples, sample_rate=sample_rate)

    @property
    def channels(self) -> int:
        if self.samples.ndim == 1:
            return 1
        return int(self.samples.shape[1])

    @property
    def frames(self) -> int:
        return int(self.samples.shape[0])

    @property
    def duration_seconds(self) -> float:
        return self.frames / self.sample_rate

    @property
    def rms(self) -> float:
        if self.samples.size == 0:
            return 0.0
        return float(np.sqrt(np.mean(np.square(self.samples.astype(np.float64)))))

    def to_pcm16_bytes(self) -> bytes:
        clipped = np.clip(self.samples, -1.0, 1.0)
        pcm = (clipped * 32767).astype(np.int16)
        return pcm.tobytes()

    def to_wav_bytes(self) -> bytes:
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            self._write_wav(wav_file)
        return buffer.getvalue()

    def save_wav(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(target), "wb") as wav_file:
            self._write_wav(wav_file)
        return target

    def _write_wav(self, wav_file) -> None:
        wav_file.setnchannels(self.channels)
        wav_file.setsampwidth(2)
        wav_file.setframerate(self.sample_rate)
        wav_file.writeframes(self.to_pcm16_bytes())


class SystemAudioCapture:
    def __init__(self, sample_rate: int = 16000, channels: int = 1) -> None:
        if sample_rate <= 0:
            raise ValueError("sample_rate must be greater than 0")
        if channels <= 0:
            raise ValueError("channels must be greater than 0")
        self.sample_rate = sample_rate
        self.channels = channels

    def list_loopback_devices(self) -> list[AudioOutputDevice]:
        default_speaker = sc.default_speaker()
        default_id = getattr(default_speaker, "id", "")
        default_name = getattr(default_speaker, "name", "")

        devices: list[AudioOutputDevice] = []
        for microphone in sc.all_microphones(include_loopback=True):
            if not getattr(microphone, "isloopback", False):
                continue
            devices.append(
                AudioOutputDevice(
                    id=str(microphone.id),
                    name=str(microphone.name),
                    channels=int(microphone.channels),
                    is_default=microphone.id == default_id or microphone.name == default_name,
                )
            )
        return devices

    def get_default_loopback_device(self) -> AudioOutputDevice:
        devices = self.list_loopback_devices()
        for device in devices:
            if device.is_default:
                return device
        if devices:
            return devices[0]
        raise RuntimeError("未找到可用的 Windows 系统音频 loopback 设备")

    def record_seconds(self, duration_seconds: float, device_id: str | None = None) -> AudioChunk:
        if duration_seconds <= 0:
            raise ValueError("duration_seconds must be greater than 0")

        device = self._get_microphone(device_id)
        num_frames = int(self.sample_rate * duration_seconds)
        samples = device.record(
            numframes=num_frames,
            samplerate=self.sample_rate,
            channels=self.channels,
        )
        return AudioChunk(
            samples=np.asarray(samples, dtype=np.float32),
            sample_rate=self.sample_rate,
        )

    def stream_chunks(
        self,
        chunk_duration_seconds: float = 0.5,
        device_id: str | None = None,
        stop_event: Event | None = None,
    ) -> Iterator[AudioChunk]:
        if chunk_duration_seconds <= 0:
            raise ValueError("chunk_duration_seconds must be greater than 0")

        frames_per_chunk = int(self.sample_rate * chunk_duration_seconds)
        if frames_per_chunk <= 0:
            raise ValueError("chunk_duration_seconds is too small for the configured sample rate")

        device = self._get_microphone(device_id)
        with device.recorder(
            samplerate=self.sample_rate,
            channels=self.channels,
            blocksize=frames_per_chunk,
        ) as recorder:
            while stop_event is None or not stop_event.is_set():
                samples = recorder.record(numframes=frames_per_chunk)
                yield AudioChunk(
                    samples=np.asarray(samples, dtype=np.float32),
                    sample_rate=self.sample_rate,
                )

    def _get_microphone(self, device_id: str | None):
        if device_id:
            return sc.get_microphone(device_id, include_loopback=True)
        default_device = self.get_default_loopback_device()
        return sc.get_microphone(default_device.id, include_loopback=True)


class QueuedAudioCapture:
    def __init__(
        self,
        capture: SystemAudioCapture,
        *,
        chunk_duration_seconds: float = 0.16,
        device_id: str | None = None,
        max_chunks: int = 32,
    ) -> None:
        if chunk_duration_seconds <= 0:
            raise ValueError("chunk_duration_seconds must be greater than 0")
        if max_chunks <= 0:
            raise ValueError("max_chunks must be greater than 0")

        self.capture = capture
        self.chunk_duration_seconds = chunk_duration_seconds
        self.device_id = device_id
        self.max_chunks = max_chunks
        self._queue: queue.Queue[AudioChunk] = queue.Queue(maxsize=max_chunks)
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._lock = Lock()
        self._dropped_chunks = 0
        self._error: BaseException | None = None

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._error = None
            self._dropped_chunks = 0
            self._clear_queue()
            self._thread = Thread(
                target=self._run_capture_loop,
                name="system-audio-capture",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=max(1.0, self.chunk_duration_seconds * 4))

    def get_chunk(self, timeout_seconds: float = 0.25) -> AudioChunk | None:
        if self._error is not None:
            raise RuntimeError(f"系统音频采集线程已异常退出：{self._error}") from self._error

        try:
            return self._queue.get(timeout=timeout_seconds)
        except queue.Empty:
            if self._error is not None:
                raise RuntimeError(f"系统音频采集线程已异常退出：{self._error}") from self._error
            return None

    @property
    def dropped_chunks(self) -> int:
        return self._dropped_chunks

    @property
    def is_running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def _run_capture_loop(self) -> None:
        try:
            for chunk in self.capture.stream_chunks(
                chunk_duration_seconds=self.chunk_duration_seconds,
                device_id=self.device_id,
                stop_event=self._stop_event,
            ):
                self._put_latest(chunk)
        except BaseException as exc:
            self._error = exc
            self._stop_event.set()

    def _put_latest(self, chunk: AudioChunk) -> None:
        try:
            self._queue.put_nowait(chunk)
            return
        except queue.Full:
            pass

        try:
            self._queue.get_nowait()
            self._dropped_chunks += 1
        except queue.Empty:
            pass
        self._queue.put_nowait(chunk)

    def _clear_queue(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

