import io
import unittest
from contextlib import redirect_stdout

from app.main import main


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


if __name__ == "__main__":
    unittest.main()

