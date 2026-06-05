import io
import tempfile
import unittest
import wave
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

from app.audio.capture import AudioChunk, AudioOutputDevice
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


if __name__ == "__main__":
    unittest.main()
