import io
import tempfile
import time
import unittest
import wave
from contextlib import redirect_stdout
from pathlib import Path
from threading import Event
from unittest.mock import Mock, patch

import numpy as np

from app.audio.capture import AudioChunk, AudioOutputDevice, QueuedAudioCapture, SystemAudioCapture
from app.main import list_audio_devices, record_system_audio


class AudioChunkTest(unittest.TestCase):
    def test_chunk_exposes_duration_channels_and_rms(self) -> None:
        samples = np.array([[0.0], [0.5], [-0.5], [1.0]], dtype=np.float32)
        chunk = AudioChunk(samples=samples, sample_rate=2)

        self.assertEqual(chunk.channels, 1)
        self.assertEqual(chunk.frames, 4)
        self.assertEqual(chunk.duration_seconds, 2.0)
        self.assertGreater(chunk.rms, 0)

    def test_chunk_can_save_wav(self) -> None:
        samples = np.array([[0.0], [0.25], [-0.25], [1.0]], dtype=np.float32)
        chunk = AudioChunk(samples=samples, sample_rate=16000)

        with tempfile.TemporaryDirectory() as tmp_dir:
            path = chunk.save_wav(Path(tmp_dir) / "capture.wav")

            with wave.open(str(path), "rb") as wav_file:
                self.assertEqual(wav_file.getnchannels(), 1)
                self.assertEqual(wav_file.getsampwidth(), 2)
                self.assertEqual(wav_file.getframerate(), 16000)
                self.assertEqual(wav_file.getnframes(), 4)

    def test_chunk_can_roundtrip_wav_file(self) -> None:
        samples = np.array([[0.0], [0.25], [-0.25], [1.0]], dtype=np.float32)
        chunk = AudioChunk(samples=samples, sample_rate=16000)

        with tempfile.TemporaryDirectory() as tmp_dir:
            path = chunk.save_wav(Path(tmp_dir) / "capture.wav")
            restored = AudioChunk.from_wav(path)

        self.assertEqual(restored.sample_rate, 16000)
        self.assertEqual(restored.channels, 1)
        self.assertEqual(restored.frames, 4)
        np.testing.assert_allclose(restored.samples, samples, atol=1 / 32768)

    def test_chunk_can_export_wav_bytes(self) -> None:
        samples = np.array([[0.0], [0.25], [-0.25], [1.0]], dtype=np.float32)
        chunk = AudioChunk(samples=samples, sample_rate=16000)

        payload = chunk.to_wav_bytes()

        self.assertTrue(payload.startswith(b"RIFF"))
        self.assertIn(b"WAVE", payload[:16])


class AudioCliTest(unittest.TestCase):
    @patch("app.main.SystemAudioCapture")
    def test_list_audio_devices_prints_loopback_devices(self, capture_class: Mock) -> None:
        capture = capture_class.return_value
        capture.list_loopback_devices.return_value = [
            AudioOutputDevice(id="device-1", name="扬声器", channels=2, is_default=True)
        ]
        output = io.StringIO()

        with redirect_stdout(output):
            exit_code = list_audio_devices(sample_rate=16000, channels=1)

        self.assertEqual(exit_code, 0)
        self.assertIn("扬声器", output.getvalue())
        self.assertIn("默认", output.getvalue())

    @patch("app.main.SystemAudioCapture")
    def test_record_system_audio_saves_chunk(self, capture_class: Mock) -> None:
        samples = np.array([[0.0], [0.5]], dtype=np.float32)
        chunk = AudioChunk(samples=samples, sample_rate=16000)
        capture = capture_class.return_value
        capture.record_seconds.return_value = chunk

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "capture.wav"
            with redirect_stdout(io.StringIO()):
                exit_code = record_system_audio(
                    output_path=output_path,
                    duration_seconds=1.0,
                    sample_rate=16000,
                    channels=1,
                )

            self.assertEqual(exit_code, 0)
            self.assertTrue(output_path.exists())
            capture.record_seconds.assert_called_once_with(duration_seconds=1.0)


class SystemAudioCaptureStreamTest(unittest.TestCase):
    def test_stream_chunks_yields_until_stop_event(self) -> None:
        stop_event = Event()
        fake_device = Mock()
        fake_recorder = Mock()
        fake_recorder.__enter__ = Mock(return_value=fake_recorder)
        fake_recorder.__exit__ = Mock(return_value=False)

        def record(numframes: int):
            stop_event.set()
            return np.zeros((numframes, 1), dtype=np.float32)

        fake_recorder.record.side_effect = record
        fake_device.recorder.return_value = fake_recorder

        capture = SystemAudioCapture(sample_rate=16000, channels=1)
        with patch.object(capture, "_get_microphone", return_value=fake_device):
            chunks = list(capture.stream_chunks(chunk_duration_seconds=0.5, stop_event=stop_event))

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].frames, 8000)


class QueuedAudioCaptureTest(unittest.TestCase):
    def test_queued_capture_reads_chunks_from_background_thread(self) -> None:
        chunk = _test_chunk(0.25)
        capture = QueuedAudioCapture(
            _FakeStreamingCapture([chunk]),
            chunk_duration_seconds=0.16,
            max_chunks=4,
        )

        capture.start()
        received = capture.get_chunk(timeout_seconds=1.0)
        capture.stop()

        self.assertIsNotNone(received)
        self.assertEqual(received.frames, chunk.frames)

    def test_queued_capture_drops_old_chunks_when_queue_is_full(self) -> None:
        chunks = [_test_chunk(0.1), _test_chunk(0.2), _test_chunk(0.3)]
        capture = QueuedAudioCapture(
            _FakeStreamingCapture(chunks),
            chunk_duration_seconds=0.16,
            max_chunks=1,
        )

        capture.start()
        _wait_until_stopped(capture)
        received = capture.get_chunk(timeout_seconds=1.0)
        capture.stop()

        self.assertIsNotNone(received)
        self.assertAlmostEqual(float(received.samples[0, 0]), 0.3)
        self.assertEqual(capture.dropped_chunks, 2)


class _FakeStreamingCapture:
    def __init__(self, chunks: list[AudioChunk]) -> None:
        self.chunks = chunks

    def stream_chunks(self, **kwargs):  # noqa: ANN003
        stop_event = kwargs.get("stop_event")
        for chunk in self.chunks:
            if stop_event is not None and stop_event.is_set():
                break
            yield chunk


def _test_chunk(value: float) -> AudioChunk:
    samples = np.full((4, 1), value, dtype=np.float32)
    return AudioChunk(samples=samples, sample_rate=16000)


def _wait_until_stopped(capture: QueuedAudioCapture) -> None:
    deadline = time.monotonic() + 1.0
    while capture.is_running and time.monotonic() < deadline:
        time.sleep(0.01)


if __name__ == "__main__":
    unittest.main()
