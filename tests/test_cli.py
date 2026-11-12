"""Tests für die Kommandozeilen-Ausgabe."""

from __future__ import annotations

import io
import json
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from wordle.cli import main, split_rows  # noqa: E402


class SplitRowsTest(unittest.TestCase):
    def test_single(self) -> None:
        self.assertEqual(split_rows(["GYXXG"]), ["GYXXG"])

    def test_emoji_grid(self) -> None:
        grid = "🟩🟨⬛⬛🟩\n🟨⬛⬛⬛⬛\n"
        self.assertEqual(split_rows([grid]), ["GYXXG", "YXXXX"])

    def test_mixed_length_is_rejected(self) -> None:
        from wordle.core import PatternError

        with self.assertRaises(PatternError):
            split_rows(["GGG"])


class CliTest(unittest.TestCase):
    def run_main(self, argv: list[str]) -> tuple[int, str]:
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(argv)
        return code, buf.getvalue()

    def test_text_output(self) -> None:
        code, out = self.run_main(["-s", "crane", "-r", "GYXXG"])
        self.assertEqual(code, 0)
        self.assertIn("Lösung: CRANE", out)
        self.assertIn("Zeile 1  GYXXG", out)
        self.assertIn("CABLE", out)
        self.assertIn("Kandidaten", out)

    def test_json_output(self) -> None:
        code, out = self.run_main(["-s", "crane", "-r", "GYXXG", "XXXXX", "--json", "--pool", "all"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["solution"], "crane")
        self.assertTrue(data["in_answer_list"])
        self.assertEqual(len(data["rows"]), 2)
        self.assertEqual(data["rows"][0]["pattern"], "GYXXG")
        self.assertIn("CAUSE", [w.upper() for w in data["rows"][0]["words"]])
        self.assertGreaterEqual(data["rows"][1]["count"], data["rows"][0]["count"])
        self.assertIn("fest", data["rows"][0]["constraints"])

    def test_limit(self) -> None:
        code, out = self.run_main(["-s", "crane", "-r", "XXXXX", "-n", "5", "--pool", "all"])
        self.assertEqual(code, 0)
        self.assertIn("weitere", out)

    def test_bad_solution(self) -> None:
        code, out = self.run_main(["-s", "cran", "-r", "GYXXG"])
        self.assertEqual(code, 2)

    def test_info(self) -> None:
        code, out = self.run_main(["--info"])
        self.assertEqual(code, 0)
        self.assertIn("2309", out)
        self.assertIn("14855", out)

    def test_stdin_rows(self) -> None:
        proc = subprocess.run(
            [sys.executable, "reverse_wordle.py", "-s", "crane", "--json"],
            input="🟩🟨⬛⬛🟩\n🟨⬛⬛⬛⬛\n",
            capture_output=True, text=True, cwd=ROOT, timeout=120,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual([r["pattern"] for r in data["rows"]], ["GYXXG", "YXXXX"])

    def test_batch_mode_needs_no_termios(self) -> None:
        """Windows-Simulation: Batch-Ausgabe darf termios nie anfassen."""
        import sys as _sys
        from unittest import mock

        with mock.patch.dict(_sys.modules, {"termios": None, "tty": None}):
            code, out = self.run_main(["-s", "crane", "-r", "GYXXG"])
        self.assertEqual(code, 0)
        self.assertIn("CABLE", out)

    def test_tui_without_terminal_explains_itself(self) -> None:
        proc = subprocess.run(
            [sys.executable, "reverse_wordle.py"], input="", capture_output=True,
            text=True, cwd=ROOT, timeout=120,
        )
        self.assertEqual(proc.returncode, 2)
        self.assertIn("Keine Lösung", proc.stderr)


if __name__ == "__main__":
    unittest.main()
