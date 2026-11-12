#!/usr/bin/env python3
"""Lädt die offiziellen Wordle-Wortlisten von der NYT-Website neu.

Die Listen stecken im JS-Bundle der Wordle-Seite: ein sortiertes Array mit
allen erlaubten Tipps, direkt gefolgt von den offiziellen Lösungswörtern in
ihrer Rätsel-Reihenfolge. Das Skript schneidet beide Teile am Übergang
zwischen dem letzten Ratewort und dem ersten Lösungswort ("cigar").

Aufruf:  python3 tools/fetch_official_lists.py [--data-dir DIR]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

PAGE = "https://www.nytimes.com/games/wordle/index.html"
ANSWER_ANCHOR = "cigar"          # erstes Wort der offiziellen Lösungsliste
WORD_ARRAY = re.compile(r'\[(?:"[a-z]{5}",?)+\]')


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (reverse-wordle-solver)"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8", "replace")


def find_bundle() -> str:
    """Sucht das JS-Bundle, das die Wortlisten enthält."""
    page = fetch(PAGE)
    assets = sorted(set(re.findall(r"games-assets/v2/[A-Za-z0-9._-]+\.js", page)))
    if not assets:
        raise SystemExit("Keine JS-Assets auf der Wordle-Seite gefunden.")
    for asset in assets:
        url = "https://www.nytimes.com/" + asset
        try:
            text = fetch(url)
        except OSError as exc:
            print(f"  übersprungen ({exc}): {asset}", file=sys.stderr)
            continue
        if f'"{ANSWER_ANCHOR}"' in text:
            print(f"Wortlisten gefunden in {asset}")
            return text
    raise SystemExit("Kein Bundle mit den Wortlisten gefunden.")


def split_lists(bundle: str) -> tuple[list[str], list[str]]:
    arrays = [json.loads(m.group(0)) for m in WORD_ARRAY.finditer(bundle)]
    arrays = [a for a in arrays if ANSWER_ANCHOR in a]
    if not arrays:
        raise SystemExit("Wortlisten-Array nicht gefunden.")
    words = max(arrays, key=len)
    cut = words.index(ANSWER_ANCHOR)
    guesses, answers = words[:cut], words[cut:]
    if len(set(guesses) & set(answers)):
        raise SystemExit("Überlappung zwischen Rate- und Lösungsliste – Format geändert?")
    if not all(len(w) == 5 and w.isalpha() for w in guesses + answers):
        raise SystemExit("Unerwartete Wörter in der Liste – Format geändert?")
    return guesses, answers


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default=str(Path(__file__).resolve().parents[1] / "data"))
    args = parser.parse_args()

    guesses, answers = split_lists(find_bundle())
    data_dir = Path(args.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "answers.txt").write_text("\n".join(answers) + "\n", encoding="utf-8")
    (data_dir / "allowed_guesses.txt").write_text(
        "\n".join(sorted(set(guesses) | set(answers))) + "\n", encoding="utf-8"
    )
    print(f"{len(answers)} Lösungen  -> {data_dir / 'answers.txt'}")
    print(f"{len(set(guesses) | set(answers))} erlaubte Tipps -> {data_dir / 'allowed_guesses.txt'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
