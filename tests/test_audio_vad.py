import unittest

import numpy as np

from app.audio.capture import AudioChunk
from app.audio.vad import (
    SILERO_FRAME_SIZE,
    SileroOnnxVad,
    SileroVadSegmenter,
    VadEventType,
    default_silero_model_path,
)


class FakeVad:
    sample_rate = 16000

    def __init__(self, probabilities: list[float]) -> None:
        self.probabilities = probabilities

    def reset(self) -> None:
        pass

    def predict(self, frame: np.ndarray):
        probability = self.probabilities.pop(0)
        return type(
            "Result",
            (),
            {
                "speech_probability": probability,
                "is_speech": probability >= 0.5,
            },
        )()


class SileroOnnxVadTest(unittest.TestCase):
    def test_model_file_exists(self) -> None:
        self.assertTrue(default_silero_model_path().exists())

    def test_silence_frame_has_low_speech_probability(self) -> None:
        vad = SileroOnnxVad()

        result = vad.predict(np.zeros((SILERO_FRAME_SIZE,), dtype=np.float32))

        self.assertFalse(result.is_speech)
        self.assertLess(result.speech_probability, 0.1)


class SileroVadSegmenterTest(unittest.TestCase):
    def test_segmenter_emits_start_and_end_events(self) -> None:
        vad = FakeVad([0.9, 0.8, 0.1, 0.1])
        segmenter = SileroVadSegmenter(
            vad=vad,  # type: ignore[arg-type]
            min_silence_ms=64,
            speech_pad_ms=0,
        )
        samples = np.ones((SILERO_FRAME_SIZE * 4, 1), dtype=np.float32)
        chunk = AudioChunk(samples=samples, sample_rate=16000)

        events = segmenter.accept_chunk(chunk)

        self.assertEqual(events[0].type, VadEventType.SPEECH_START)
        self.assertEqual(events[-1].type, VadEventType.SPEECH_END)
        self.assertIsNotNone(events[-1].segment)
        assert events[-1].segment is not None
        self.assertGreater(events[-1].segment.duration_seconds, 0)

    def test_flush_ends_active_segment(self) -> None:
        vad = FakeVad([0.9])
        segmenter = SileroVadSegmenter(vad=vad, speech_pad_ms=0)  # type: ignore[arg-type]
        chunk = AudioChunk(
            samples=np.ones((SILERO_FRAME_SIZE, 1), dtype=np.float32),
            sample_rate=16000,
        )

        segmenter.accept_chunk(chunk)
        events = segmenter.flush()

        self.assertEqual(events[0].type, VadEventType.SPEECH_END)


if __name__ == "__main__":
    unittest.main()

