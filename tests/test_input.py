"""Tests der Eingabeschicht: Pfeiltasten, Backspace, UTF-8, Einfügen.

Der Kern: ``sys.stdin.read()`` puffert Bytes im Userspace, ``select()`` sieht
sie danach nicht mehr. Diese Tests lesen darum über einen echten Pty-FD.
"""

from __future__ import annotations

import os
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    import pty
    import tty

    from wordle.tui import KeyReader, _CONTROL
except ImportError:  # pragma: no cover - exotische Plattform
    pty = None  # type: ignore[assignment]


@unittest.skipIf(pty is None, "pty nicht verfügbar")
class KeyReaderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.master, self.slave = pty.openpty()
        tty.setcbreak(self.slave)
        self.reader = KeyReader(self.slave)

    def tearDown(self) -> None:
        for fd in (self.master, self.slave):
            try:
                os.close(fd)
            except OSError:
                pass

    def send(self, data: bytes) -> None:
        os.write(self.master, data)

    def test_arrow_keys(self) -> None:
        cases = [
            (b"\x1b[A", "UP"), (b"\x1b[B", "DOWN"),
            (b"\x1b[C", "RIGHT"), (b"\x1b[D", "LEFT"),
            (b"\x1bOA", "UP"), (b"\x1bOD", "LEFT"),          # Applikationsmodus
            (b"\x1b[1;5D", "LEFT"),                          # mit Modifier
            (b"\x1b[Z", "STAB"),
        ]
        for seq, name in cases:
            with self.subTest(seq=seq):
                self.send(seq)
                self.assertEqual(self.reader.read_key(), name)

    def test_special_keys(self) -> None:
        cases = [
            (b"\x1b[3~", "DELETE"), (b"\x1b[5~", "PGUP"), (b"\x1b[6~", "PGDN"),
            (b"\x7f", "BACKSPACE"), (b"\x08", "BACKSPACE"),
            (b"\t", "TAB"), (b"\r", "ENTER"),
            (b"g", "g"), (b"2", "2"),
        ]
        for seq, name in cases:
            with self.subTest(seq=seq):
                self.send(seq)
                self.assertEqual(self.reader.read_key(), name)

    def test_control_mapping(self) -> None:
        """Ctrl-C kommt im echten TUI als SIGINT an, die Abbildung bleibt trotzdem."""
        self.assertEqual(_CONTROL["\x03"], "CTRL_C")
        self.assertEqual(_CONTROL["\x04"], "CTRL_D")

    def test_lone_escape_is_not_swallowed(self) -> None:
        self.send(b"\x1b")
        started = time.perf_counter()
        self.assertEqual(self.reader.read_key(), "ESC")
        self.assertLess(time.perf_counter() - started, 1.0)

    def test_escape_sequence_across_writes(self) -> None:
        """Träges Terminal/Container: ESC und Rest kommen getrennt an."""
        self.send(b"\x1b")
        time.sleep(0.03)
        self.send(b"[D")
        self.assertEqual(self.reader.read_key(), "LEFT")

    def test_buffered_chars_are_not_lost(self) -> None:
        self.send(b"abc")
        self.assertEqual([self.reader.read_key() for _ in range(3)], ["a", "b", "c"])

    def test_utf8_character(self) -> None:
        self.send("🟩".encode())
        self.assertEqual(self.reader.read_key(), "🟩")

    def test_utf8_split_across_writes(self) -> None:
        data = "🟨".encode()
        self.send(data[:2])
        time.sleep(0.03)
        self.send(data[2:])
        self.assertEqual(self.reader.read_key(), "🟨")

    def test_paste(self) -> None:
        self.send("🟩🟨⬛⬛🟩".encode())
        self.assertEqual(self.reader.read_available(0.1), "🟩🟨⬛⬛🟩")

    def test_unknown_sequence_is_ignored(self) -> None:
        self.send(b"\x1b[99~")
        self.assertEqual(self.reader.read_key(), "UNKNOWN")


class FallbackKeysTest(unittest.TestCase):
    """Ohne Sondertasten muss das TUI weiter bedienbar sein."""

    @classmethod
    def setUpClass(cls) -> None:
        from wordle.core import Solver

        cls.solver = Solver()

    def app(self):
        from wordle.tui import App

        app = App(self.solver, solution="crane")
        app.focus = 0
        return app

    def test_hjkl_move(self) -> None:
        app = self.app()
        app.handle("l")
        self.assertEqual(app.col, 1)
        app.handle("l")
        self.assertEqual(app.col, 2)
        app.handle("h")
        self.assertEqual(app.col, 1)
        app.handle("j")
        self.assertEqual(app.focus, 1)
        app.handle("k")
        self.assertEqual(app.focus, 0)

    def test_u_and_c(self) -> None:
        app = self.app()
        for ch in "gyxxg":
            app.handle(ch)
        self.assertEqual(app.rows[0], "GYXXG")
        app.handle("u")                      # entspricht Backspace
        self.assertEqual(app.rows[0], "GYXX?")
        app.handle("c")                      # entspricht Entf
        self.assertEqual(app.rows[0], "?????")

    def test_debug_toggle(self) -> None:
        app = self.app()
        self.assertFalse(app.debug)
        app.handle("D")
        self.assertTrue(app.debug)
        app.handle("D")
        self.assertFalse(app.debug)


if __name__ == "__main__":
    unittest.main()
