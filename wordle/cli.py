"""Kommandozeile: Batch-Ausgabe für Skripte und Start des TUI."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

from .core import WORD_LENGTH, PatternError, Solver, normalize_cells
from .tui import POOL_LABEL, TARGET_SOLUTION, App, run

EPILOG = """\
Beispiele:
  python3 reverse_wordle.py                          # TUI starten
  python3 reverse_wordle.py -s crane -r GYXXG YXGYG  # zwei Zeilen auswerten
  python3 reverse_wordle.py -s crane -r "🟩🟨⬛⬛🟩" --pool all
  printf '🟩🟨⬛⬛🟩\\n🟨🟨⬛⬛⬛\\n' | python3 reverse_wordle.py -s crane
"""


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="reverse_wordle",
        description=(
            "Reverse Wordle: aus der bekannten Lösung und der Farbmatrix "
            "die tatsächlich getippten Wörter rekonstruieren."
        ),
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("-s", "--solution", help="die korrekte Lösung (5 Buchstaben)")
    p.add_argument(
        "-r", "--rows", nargs="+", metavar="MUSTER",
        help="Farbmuster je Zeile, z. B. GYXXG oder 🟩🟨⬛⬛🟩 (auch mehrere Zeilen am Stück)",
    )
    p.add_argument(
        "--pool", choices=("answers", "all"), default="answers",
        help="answers = offizielle Lösungsliste (Standard), all = alle erlaubten Tipps",
    )
    p.add_argument("-n", "--limit", type=int, default=60, help="max. Kandidaten pro Zeile (Standard 60)")
    p.add_argument("--json", action="store_true", help="Ausgabe als JSON")
    p.add_argument("--no-color", action="store_true", help="Farben im TUI abschalten")
    p.add_argument("--info", action="store_true", help="nur Wortlisten-Info zeigen")
    return p


def split_rows(raw: Iterable[str]) -> list[str]:
    """Fasst beliebig eingegebene Muster zu 5-Zellen-Blöcken zusammen."""
    cells = "".join(normalize_cells(part) for part in raw)
    if not cells:
        return []
    if len(cells) % WORD_LENGTH:
        raise PatternError(
            f"{len(cells)} Farbzellen – das passt nicht in {WORD_LENGTH}er-Blöcke"
        )
    return [cells[i:i + WORD_LENGTH] for i in range(0, len(cells), WORD_LENGTH)]


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    solver = Solver()

    if args.info:
        print(f"Offizielle Lösungen : {len(solver.answer_words):>6} Wörter  (data/answers.txt)")
        print(f"Erlaubte Tipps      : {len(solver.all_words):>6} Wörter  (data/allowed_guesses.txt)")
        return 0

    if not args.solution:
        if not sys.stdin.isatty():
            print("Keine Lösung angegeben. Nutze -s/--solution.", file=sys.stderr)
            return 2
        app = App(solver, pool=args.pool)
        if args.rows:
            try:
                for i, pat in enumerate(split_rows(args.rows)[:len(app.rows)]):
                    app.rows[i] = pat
            except PatternError as exc:
                print(f"Muster ungültig: {exc}", file=sys.stderr)
                return 2
            app.recompute()
        else:
            app.begin_input(TARGET_SOLUTION)   # direkt loslegen
        return run(app, color=not args.no_color)

    solution = args.solution.strip().lower()
    if len(solution) != WORD_LENGTH or not solution.isalpha():
        print(f"Lösung muss genau {WORD_LENGTH} Buchstaben haben: {args.solution!r}", file=sys.stderr)
        return 2

    raw = list(args.rows or [])
    if not raw and not sys.stdin.isatty():
        raw = [line for line in sys.stdin.read().splitlines() if line.strip()]
    if not raw:
        print("Keine Farbmuster angegeben (--rows oder STDIN).", file=sys.stderr)
        return 2

    try:
        patterns = split_rows(raw)
    except PatternError as exc:
        print(f"Muster ungültig: {exc}", file=sys.stderr)
        return 2

    results = solver.solve(solution, patterns, args.pool)
    if args.json:
        print(json.dumps(
            {
                "solution": solution,
                "in_answer_list": solution in solver.answer_set,
                "pool": args.pool,
                "rows": [
                    {
                        "row": i + 1,
                        "pattern": r.pattern,
                        "count": r.count,
                        "answer_count": len(r.answer_words),
                        "tested": r.tested,
                        "ms": round(r.ms, 3),
                        "words": list(r.words),
                        "constraints": solver.explain(solution, r.pattern).describe(),
                    }
                    for i, r in enumerate(results)
                ],
            },
            ensure_ascii=False,
            indent=2,
        ))
        return 0

    print(f"Lösung: {solution.upper()}"
          + ("" if solution in solver.answer_set else "   (nicht in der offiziellen Lösungsliste)"))
    print(f"Wortliste: {POOL_LABEL[args.pool]} ({len(solver.pool(args.pool))} Wörter)")
    print()
    for res in results:
        i = res.row
        extra = f" · {len(res.answer_words)} Antworten" if args.pool == "all" else ""
        timing = "aus Cache" if res.cached else f"{res.ms:.1f} ms"
        print(f"Zeile {i + 1}  {res.pattern}  →  {res.count} Kandidaten{extra}   ({timing})")
        print(f"         {solver.explain(solution, res.pattern).describe()}")
        if not res.words:
            print("         Kein Wort passt – Muster prüfen oder Lösung überprüfen.")
        else:
            shown = res.words[: max(0, args.limit)]
            print("         " + "  ".join(w.upper() for w in shown))
            if len(res.words) > len(shown):
                print(f"         … und {len(res.words) - len(shown)} weitere (-n erhöhen)")
        print()
    return 0
