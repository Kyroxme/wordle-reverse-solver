"""Rauchtest: startet das echte TUI in einem Pseudo-Terminal."""

from __future__ import annotations

import os
import select
import subprocess
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

try:
    import fcntl
    import pty
    import struct
    import termios
except ImportError:  # pragma: no cover
    pty = None  # type: ignore[assignment]


@unittest.skipIf(pty is None, "pty nicht verfügbar")
class PtySmokeTest(unittest.TestCase):
    def test_full_flow(self) -> None:
        master, slave = pty.openpty()
        # Fenstergröße setzen, sonst rendert das TUI auf 0x0
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 100, 0, 0))
        env = dict(os.environ, TERM="xterm-256color")
        env.pop("NO_COLOR", None)
        proc = subprocess.Popen(
            [sys.executable, "reverse_wordle.py"],
            stdin=slave, stdout=slave, stderr=subprocess.PIPE,
            cwd=ROOT, env=env, close_fds=True,
        )
        os.close(slave)
        out = ""

        def pump(seconds: float = 0.4) -> str:
            nonlocal out
            end = time.time() + seconds
            chunk = ""
            while time.time() < end:
                ready, _, _ = select.select([master], [], [], 0.05)
                if not ready:
                    continue
                try:
                    data = os.read(master, 65536)
                except OSError:
                    break
                if not data:
                    break
                chunk += data.decode("utf-8", "replace")
            out += chunk
            return chunk

        def send(keys: str, wait: float = 0.25) -> None:
            os.write(master, keys.encode())
            pump(wait)

        try:
            pump(0.8)
            self.assertIn("REVERSE WORDLE", out)
            # Das TUI startet direkt in der Lösungseingabe.
            send("crane\r", 0.4)
            send("\t", 0.2)
            send("gyxxg", 0.6)
            self.assertIn("CAUSE", out)
            self.assertIn("Kandidaten", out)
            send("?", 0.4)
            self.assertIn("Hilfe", out)
            send("q", 0.3)
            send("q", 0.3)
            proc.wait(timeout=10)
            self.assertEqual(proc.returncode, 0, proc.stderr.read().decode("utf-8", "replace"))
        finally:
            if proc.poll() is None:
                proc.kill()
            if proc.stderr is not None:
                proc.stderr.close()
            os.close(master)


if __name__ == "__main__":
    unittest.main()
