#!/usr/bin/env python3
"""Reverse Wordle Solver – Einstiegspunkt.

    python3 reverse_wordle.py                 # TUI
    python3 reverse_wordle.py --help          # Batch-Modus
"""

from __future__ import annotations

import sys

from wordle.cli import main

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
