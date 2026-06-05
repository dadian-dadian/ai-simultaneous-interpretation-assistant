import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

from app.asr import AsrResult
from app.audio.capture import AudioChunk
from app.main import main
from app.translate import TranslationResult


class MainEntryTest(unittest.TestCase):
    def test_version_flag_prints_version(self) -> None:
        output = io.StringIO()

        with redirect_stdout(output):
            exit_code = main(["--version"])

        self.assertEqual(exit_code, 0)
        self.assertIn("0.1.0", output.getvalue())

    def test_no_ui_mode_starts_without_desktop_dependency(self) -> None:
        exit_code = main(["--no-ui"])

        self.assertEqual(exit_code, 0)

    @patch("app.main.create_asr_client")
    def test_transcribe_audio_file_prints_asr_result(self, create_client: Mock) -> None:
        fake_client = create_client.return_value
        fake_client.transcribe.return_value = AsrResult(
            text="hello world",
            language="en",
            provider="mock",
            duration_seconds=1.0,
            is_mock=True,
        )
        audio = AudioChunk(samples=np.zeros((16000, 1), dtype=np.float32), sample_rate=16000)
        output = io.StringIO()

        with tempfile.TemporaryDirectory() as tmp_dir:
            wav_path = audio.save_wav(Path(tmp_dir) / "sample.wav")
            with redirect_stdout(output):
                exit_code = main(["--transcribe-audio", str(wav_path)])

        self.assertEqual(exit_code, 0)
        self.assertIn("ASR 提供方：mock", output.getvalue())
        self.assertIn("原文：hello world", output.getvalue())

    @patch("app.main.create_translator_client")
    def test_translate_text_prints_translation_result(self, create_translator: Mock) -> None:
        translator = create_translator.return_value
        translator.translate.return_value = TranslationResult(
            text="你好，世界",
            provider="openai-compatible",
            model="model-a",
            source_language="en",
            target_language="zh-CN",
        )
        output = io.StringIO()

        with redirect_stdout(output):
            exit_code = main(
                [
                    "--translate-text",
                    "hello world",
                    "--translation-api-key",
                    "translation-key",
                ]
            )

        self.assertEqual(exit_code, 0)
        self.assertIn("翻译提供方：openai-compatible", output.getvalue())
        self.assertIn("译文：你好，世界", output.getvalue())


if __name__ == "__main__":
    unittest.main()

