import unittest

import numpy as np

from app.audio.buffer import AudioRingBuffer
from app.audio.capture import AudioChunk


class AudioRingBufferTest(unittest.TestCase):
    def test_buffer_keeps_recent_samples_only(self) -> None:
        buffer = AudioRingBuffer(max_duration_seconds=1.0, sample_rate=4)

        buffer.append(
            AudioChunk(samples=np.array([[1.0], [2.0]], dtype=np.float32), sample_rate=4)
        )
        buffer.append(
            AudioChunk(
                samples=np.array([[3.0], [4.0], [5.0]], dtype=np.float32),
                sample_rate=4,
            )
        )

        recent = buffer.recent()

        self.assertEqual(recent.frames, 4)
        np.testing.assert_allclose(recent.samples[:, 0], np.array([2.0, 3.0, 4.0, 5.0]))

    def test_recent_duration_can_be_limited(self) -> None:
        buffer = AudioRingBuffer(max_duration_seconds=2.0, sample_rate=4)
        buffer.append(
            AudioChunk(samples=np.arange(8, dtype=np.float32).reshape(-1, 1), sample_rate=4)
        )

        recent = buffer.recent(duration_seconds=0.5)

        np.testing.assert_allclose(recent.samples[:, 0], np.array([6.0, 7.0]))


if __name__ == "__main__":
    unittest.main()

