"""Kernlogik: Wordle-Feedback und Rückwärts-Suche nach getippten Wörtern.

Wichtig für das Verständnis der Suche: Aus einem Farbmuster kennt man nur die
*grünen* Buchstaben. Bei Gelb und Grau ist der getippte Buchstabe unbekannt –
das ist ja genau die gesuchte Information. Ein Kandidat ist deshalb jedes Wort,
dessen vollständiges Feedback an den bekannten Stellen zum Muster passt.

Das Modul ist frei von Ein-/Ausgabe, damit es sich testen lässt.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

WORD_LENGTH = 5
GREEN = "G"
YELLOW = "Y"
GRAY = "X"
UNKNOWN = "?"

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
ANSWERS_FILE = DATA_DIR / "answers.txt"
GUESSES_FILE = DATA_DIR / "allowed_guesses.txt"

#: Alle Musterzeichen, die als "keine Information" gelten dürfen.
_EMPTY_PATTERN = set(UNKNOWN)


# --------------------------------------------------------------------------
# Muster normalisieren
# --------------------------------------------------------------------------

#: Erlaubte Schreibweisen pro Zelle. Mehrbuchstabiges wird unten zuerst geprüft.
_SYMBOLS = {
    "g": GREEN, "G": GREEN, "2": GREEN, "🟩": GREEN,
    "y": YELLOW, "Y": YELLOW, "1": YELLOW, "🟨": YELLOW,
    "x": GRAY, "X": GRAY, "0": GRAY, "-": GRAY, "b": GRAY, "B": GRAY,
    "⬛": GRAY, "⬜": GRAY, "🟫": GRAY, "⬤": GRAY,
    "?": UNKNOWN, ".": UNKNOWN, "_": UNKNOWN,
}

#: Wörter, die als ganzes Zellenmuster vorkommen dürfen (deutsche Eingabe).
_WORDS = (("grau", GRAY), ("gelb", YELLOW), ("gruen", GREEN), ("grün", GREEN))

#: Zeichen, die beim Einfügen aus einem Emoji-Grid stören (Leerzeichen trennen).
_STRIP = "\ufe0f\ufe0e\u200d\u200b\t\r\n "


class PatternError(ValueError):
    """Ungültiges Farbmuster."""


def normalize_cells(raw: str) -> str:
    """Wandelt beliebige Schreibweisen in eine Folge von G/Y/X/?-Zeichen.

    Anders als :func:`normalize_pattern` ist die Länge hier offen – praktisch
    für eingefügte Emoji-Grids mit mehreren Zeilen.
    """
    text = raw
    for ch in _STRIP:
        text = text.replace(ch, "")
    out: list[str] = []
    i = 0
    while i < len(text):
        for word, sym in _WORDS:
            if text[i:i + len(word)].lower() == word:
                out.append(sym)
                i += len(word)
                break
        else:
            ch = text[i]
            sym = _SYMBOLS.get(ch)
            if sym is None:
                raise PatternError(
                    f"Unbekanntes Zeichen {ch!r}: erlaubt sind G/g/2 (grün), "
                    f"Y/y/1 (gelb), X/x/0/- (grau), ?/. (unbekannt) sowie 🟩🟨⬛"
                )
            out.append(sym)
            i += 1
    return "".join(out)


def normalize_pattern(raw: str) -> str:
    """Wandelt beliebige Schreibweisen in einen 5-stelligen G/Y/X/?-String.

    Akzeptiert z. B. ``"GGXYG"``, ``"g g x y g"``, ``"22010"`` oder
    ``"🟩🟩⬛🟨🟩"``.

    >>> normalize_pattern("ggxyg")
    'GGXYG'
    >>> normalize_pattern("🟩🟨⬛⬛🟩")
    'GYXXG'
    """
    result = normalize_cells(raw)
    if len(result) != WORD_LENGTH:
        raise PatternError(
            f"Muster muss {WORD_LENGTH} Zellen haben, hat aber {len(result)}: {raw!r}"
        )
    return result


def parse_grid(lines: Iterable[str]) -> list[str]:
    """Parst mehrere Musterzeilen; leere Zeilen werden übersprungen."""
    return [normalize_pattern(line) for line in lines if line.strip()]


# --------------------------------------------------------------------------
# Feedback
# --------------------------------------------------------------------------

def feedback(guess: str, solution: str) -> str:
    """Wordle-Feedback von ``guess`` gegenüber ``solution`` als G/Y/X-String.

    Offizielle Regel: erst alle grünen Treffer, danach gelbe Treffer aus den
    *übrigen* Lösungsbuchstaben, von links nach rechts vergeben.

    >>> feedback("bobby", "abbey")
    'YXGXG'
    >>> feedback("crane", "crane")
    'GGGGG'
    >>> feedback("babes", "abbey")
    'YYGGX'
    """
    if len(guess) != WORD_LENGTH or len(solution) != WORD_LENGTH:
        raise ValueError("Nur 5-Buchstaben-Wörter werden unterstützt")
    guess = guess.lower()
    solution = solution.lower()

    marks = [GRAY] * WORD_LENGTH
    remaining: dict[str, int] = {}
    for i in range(WORD_LENGTH):
        if guess[i] == solution[i]:
            marks[i] = GREEN
        else:
            remaining[solution[i]] = remaining.get(solution[i], 0) + 1
    for i in range(WORD_LENGTH):
        if marks[i] == GREEN:
            continue
        ch = guess[i]
        left = remaining.get(ch, 0)
        if left:
            remaining[ch] = left - 1
            marks[i] = YELLOW
    return "".join(marks)


def matches_partial(marks: str, pattern: str) -> bool:
    """True, wenn ``marks`` das (evtl. unvollständige) Muster erfüllt."""
    return all(p == UNKNOWN or p == m for p, m in zip(pattern, marks))


# --------------------------------------------------------------------------
# Wortlisten
# --------------------------------------------------------------------------

def _read_words(path: Path) -> tuple[str, ...]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:  # pragma: no cover - nur bei kaputtem Repo
        raise FileNotFoundError(
            f"Wortliste fehlt: {path}\n"
            f"Lade sie neu mit:  python3 tools/fetch_official_lists.py"
        ) from exc
    words: list[str] = []
    for line in text.splitlines():
        w = line.strip().lower()
        if not w or w.startswith("#"):
            continue
        if len(w) != WORD_LENGTH or not w.isalpha():
            raise ValueError(f"Ungültiges Wort in {path.name}: {w!r}")
        words.append(w)
    if not words:
        raise ValueError(f"Leere Wortliste: {path}")
    return tuple(words)


class WordPool:
    """Sortierte, eindeutige Wortliste."""

    __slots__ = ("name", "words")

    def __init__(self, name: str, words: Iterable[str]) -> None:
        self.name = name
        self.words = tuple(sorted(dict.fromkeys(w.lower() for w in words)))

    def __len__(self) -> int:
        return len(self.words)


# --------------------------------------------------------------------------
# Suche
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class RowResult:
    """Ergebnis für eine Zeile: welche Wörter passen zum gesehenen Muster?"""

    row: int
    pattern: str
    words: tuple[str, ...]
    answer_words: tuple[str, ...]
    pool_name: str
    tested: int
    ms: float
    cached: bool = False

    @property
    def count(self) -> int:
        return len(self.words)


@dataclass(frozen=True)
class Constraints:
    """Was ein Muster über das getippte Wort verrät – mehr gibt die Farbe nicht her."""

    anchors: tuple[tuple[int, str], ...]          # grün: Position + Buchstabe
    blocked: tuple[tuple[int, str], ...]          # gelb/grau: Position + verbotener Buchstabe
    yellow_positions: tuple[int, ...]
    gray_positions: tuple[int, ...]

    def describe(self) -> str:
        parts: list[str] = []
        if self.anchors:
            parts.append("fest: " + ", ".join(f"{i + 1}={c.upper()}" for i, c in self.anchors))
        yellows = [(i, c) for i, c in self.blocked if i in self.yellow_positions]
        grays = [(i, c) for i, c in self.blocked if i in self.gray_positions]
        if yellows:
            parts.append(
                "gelb: " + ", ".join(f"{i + 1}≠{c.upper()}" for i, c in yellows)
                + " (Buchstabe kommt sonst in der Lösung vor)"
            )
        if grays:
            parts.append("grau: " + ", ".join(f"{i + 1}≠{c.upper()}" for i, c in grays))
        return " · ".join(parts) if parts else "noch keine Einschränkung"


def constraints(solution: str, pattern: str) -> Constraints:
    """Leitet aus Lösung + Muster ab, was sicher über das getippte Wort gilt."""
    sol = solution.strip().lower()
    if len(sol) != WORD_LENGTH or not sol.isalpha():
        raise ValueError(f"Lösung muss ein 5-Buchstaben-Wort sein: {solution!r}")
    pat = normalize_pattern(pattern)

    anchors: list[tuple[int, str]] = []
    blocked: list[tuple[int, str]] = []
    yellows: list[int] = []
    grays: list[int] = []
    for i, p in enumerate(pat):
        if p == GREEN:
            anchors.append((i, sol[i]))
        elif p == UNKNOWN:
            continue
        else:
            blocked.append((i, sol[i]))
            if p == YELLOW:
                yellows.append(i)
            else:
                grays.append(i)
    return Constraints(
        anchors=tuple(anchors),
        blocked=tuple(blocked),
        yellow_positions=tuple(yellows),
        gray_positions=tuple(grays),
    )


class Solver:
    """Rückwärts-Suche: Lösung + Farbmuster -> mögliche getippte Wörter."""

    #: Anzeigename -> Datei
    POOLS = {"answers": ANSWERS_FILE, "all": GUESSES_FILE}

    def __init__(self, data_dir: Path | None = None) -> None:
        base = Path(data_dir) if data_dir else DATA_DIR
        self.answer_words = _read_words(base / ANSWERS_FILE.name)
        all_words = _read_words(base / GUESSES_FILE.name)
        # Jede Lösung muss auch ein erlaubter Tipp sein.
        self.all_words = tuple(sorted(set(all_words) | set(self.answer_words)))
        self.answer_set = frozenset(self.answer_words)
        self.pools = {
            "answers": WordPool("answers", self.answer_words),
            "all": WordPool("all", self.all_words),
        }
        self._cache: dict[tuple[str, str, str], RowResult] = {}

    # -- öffentliche API ---------------------------------------------------

    def pool(self, name: str = "answers") -> WordPool:
        try:
            return self.pools[name]
        except KeyError:
            raise KeyError(
                f"Unbekannte Wortliste {name!r}, erlaubt: {sorted(self.pools)}"
            ) from None

    def candidates(self, solution: str, pattern: str, pool: str = "answers") -> RowResult:
        """Alle Wörter aus ``pool``, die gegen ``solution`` genau ``pattern`` ergeben."""
        sol = solution.strip().lower()
        if len(sol) != WORD_LENGTH or not sol.isalpha():
            raise ValueError(f"Lösung muss ein 5-Buchstaben-Wort sein: {solution!r}")
        pat = normalize_pattern(pattern)
        key = (pool, sol, pat)
        hit = self._cache.get(key)
        if hit is not None:
            return RowResult(
                row=hit.row, pattern=hit.pattern, words=hit.words,
                answer_words=hit.answer_words, pool_name=hit.pool_name,
                tested=hit.tested, ms=hit.ms, cached=True,
            )

        word_pool = self.pool(pool)
        t0 = time.perf_counter()
        words = self._filter(word_pool, sol, pat)
        words.sort(key=lambda w: (w not in self.answer_set, w))
        elapsed = (time.perf_counter() - t0) * 1000.0
        result = RowResult(
            row=-1,
            pattern=pat,
            words=tuple(words),
            answer_words=tuple(w for w in words if w in self.answer_set),
            pool_name=pool,
            tested=len(word_pool),
            ms=elapsed,
        )
        self._cache[key] = result
        return result

    def solve(
        self,
        solution: str,
        patterns: Sequence[str],
        pool: str = "answers",
    ) -> list[RowResult]:
        """Kandidaten für alle Zeilen in einem Rutsch."""
        out: list[RowResult] = []
        for i, pat in enumerate(patterns):
            try:
                norm = normalize_pattern(pat)
            except PatternError:
                continue
            if set(norm) <= _EMPTY_PATTERN:
                continue
            res = self.candidates(solution, norm, pool)
            out.append(
                RowResult(
                    row=i, pattern=res.pattern, words=res.words,
                    answer_words=res.answer_words, pool_name=res.pool_name,
                    tested=res.tested, ms=res.ms, cached=res.cached,
                )
            )
        return out

    def explain(self, solution: str, pattern: str) -> Constraints:
        return constraints(solution, pattern)

    # -- interne Vorfilterung ---------------------------------------------

    def _filter(self, pool: WordPool, sol: str, pat: str) -> list[str]:
        """Positionsfilter, dann exaktes Feedback – in einem Durchlauf."""
        words = pool.words
        sol_idx = [ord(c) - 97 for c in sol]

        eq = [""] * WORD_LENGTH      # grün: Buchstabe an dieser Stelle Pflicht
        neq = [""] * WORD_LENGTH     # gelb/grau: dieser Lösungsbuchstabe verboten
        for i, p in enumerate(pat):
            if p == GREEN:
                eq[i] = sol[i]
            elif p != UNKNOWN:
                neq[i] = sol[i]

        # Nicht-grüne Stellen bilden den Vorrat, aus dem Gelb vergeben wird.
        slots = [i for i in range(WORD_LENGTH) if pat[i] != GREEN]
        complete = UNKNOWN not in pat
        need = [0] * 26

        a, b, c, d, e = eq
        na, nb, nc, nd, ne = neq
        has_eq = bool(a or b or c or d or e)
        has_neq = bool(na or nb or nc or nd or ne)

        hits: list[str] = []
        for word in words:
            w0, w1, w2, w3, w4 = word[0], word[1], word[2], word[3], word[4]
            if has_eq and (
                (a and w0 != a) or (b and w1 != b) or (c and w2 != c)
                or (d and w3 != d) or (e and w4 != e)
            ):
                continue
            if has_neq and (
                (w0 == na) or (w1 == nb) or (w2 == nc) or (w3 == nd) or (w4 == ne)
            ):
                continue

            if not complete:
                if matches_partial(feedback(word, sol), pat):
                    hits.append(word)
                continue

            for i in slots:
                need[sol_idx[i]] += 1
            ok = True
            for i in slots:
                n = need[ord(word[i]) - 97]
                if n:
                    need[ord(word[i]) - 97] = n - 1
                    if pat[i] != YELLOW:
                        ok = False
                        break
                elif pat[i] != GRAY:
                    ok = False
                    break
            for i in slots:  # Vorrat für das nächste Wort zurücksetzen
                need[sol_idx[i]] = 0
            if ok:
                hits.append(word)
        return hits
