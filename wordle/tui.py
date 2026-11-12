"""Einfaches Terminal-UI für den Reverse-Solver.

Aufbau: ``App`` hält den Zustand und verarbeitet Tasten (pur, testbar),
``render()`` erzeugt daraus reine Textzeilen. Der I/O-Loop am Ende ist der
einzige Teil, der ein echtes Terminal braucht.
"""

from __future__ import annotations

import os
import re
import select
import shutil
import sys
from dataclasses import dataclass, field

from .core import (
    GRAY,
    GREEN,
    UNKNOWN,
    YELLOW,
    PatternError,
    RowResult,
    Solver,
    normalize_cells,
)

ROWS = 6
CELLS = 5

#: Tastenkürzel -> Zellzustand
COLOR_KEYS = {
    "g": GREEN, "G": GREEN, "2": GREEN,
    "y": YELLOW, "Y": YELLOW, "1": YELLOW,
    "x": GRAY, "X": GRAY, "0": GRAY, "b": GRAY, "B": GRAY, "-": GRAY,
    " ": UNKNOWN, "?": UNKNOWN, ".": UNKNOWN,
}

POOL_LABEL = {
    "answers": "offizielle Lösungen",
    "all": "alle erlaubten Tipps",
}

#: Ziel einer Eingabezeile
TARGET_SOLUTION = "solution"
TARGET_ROW = "row"


# --------------------------------------------------------------------------
# ANSI-Helfer
# --------------------------------------------------------------------------

_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
RESET = "\x1b[0m"
BOLD = "\x1b[1m"

#: Hintergrund, Vordergrund und Ersatzzeichen pro Zellzustand (256 Farben)
TILE_COLORS = {
    GREEN: ("48;5;35", "38;5;232", "G"),
    YELLOW: ("48;5;220", "38;5;232", "Y"),
    GRAY: ("48;5;240", "38;5;255", "X"),
    UNKNOWN: ("48;5;236", "38;5;245", " "),
}


def vlen(text: str) -> int:
    """Sichtbare Länge ohne ANSI-Sequenzen."""
    return len(_ANSI.sub("", text))


def clip(text: str, width: int) -> str:
    """Kürzt auf ``width`` sichtbare Zeichen, ANSI bleibt heil."""
    out: list[str] = []
    visible = 0
    i = 0
    while i < len(text):
        if text[i] == "\x1b":
            m = _ANSI.match(text, i)
            if m:
                out.append(m.group(0))
                i = m.end()
                continue
        if visible >= width:
            if "\x1b" in text:
                out.append(RESET)
            break
        out.append(text[i])
        visible += 1
        i += 1
    return "".join(out)


def pad(text: str, width: int) -> str:
    """Füllt rechts auf ``width`` sichtbare Zeichen auf."""
    return text + " " * max(0, width - vlen(text))


def two(left: str, right: str, width: int) -> str:
    """Links/Rechts-Ausrichtung auf einer Zeile."""
    space = width - vlen(left) - vlen(right)
    if space < 1:
        return left + " " + clip(right, max(0, width - vlen(left) - 1))
    return left + " " * space + right


def tile(mark: str, color: bool, cursor: bool = False) -> str:
    """Eine Zelle als farbiger Block (ohne Farbe als ASCII-Klammer)."""
    bg, fg, glyph = TILE_COLORS.get(mark, TILE_COLORS[UNKNOWN])
    if not color:
        return f">{glyph}<" if cursor else f"[{glyph}]"
    text = f" {glyph} "
    if cursor:
        text = f"\x1b[1;4m{text}"
    return f"\x1b[{bg};{fg}m{text}{RESET}"


# --------------------------------------------------------------------------
# Zustand
# --------------------------------------------------------------------------

@dataclass
class App:
    """Kompletter UI-Zustand plus Tastenverarbeitung."""

    solver: Solver
    solution: str = ""
    rows: list[str] = field(default_factory=lambda: [UNKNOWN * CELLS for _ in range(ROWS)])
    focus: int = -1                 # -1 = Lösungszeile, sonst 0..5
    col: int = 0
    pool: str = "answers"
    help: bool = False
    status: str = ""
    scroll: int = 0
    results: dict[int, RowResult] = field(default_factory=dict)
    target: str | None = None       # aktive Eingabezeile
    buffer: str = ""
    start_row: int = 0              # ab welcher Zeile ein Muster landet
    debug: bool = False             # Tasten-Diagnose in der Statuszeile

    def __post_init__(self) -> None:
        self.recompute()

    # -- Zustand ---------------------------------------------------------

    @property
    def typing(self) -> bool:
        return self.target is not None

    def view_row(self) -> int | None:
        """Zeile, deren Kandidaten gerade angezeigt werden."""
        if self.focus >= 0:
            return self.focus
        for i in range(len(self.rows) - 1, -1, -1):
            if self.rows[i] != UNKNOWN * CELLS:
                return i
        return None

    def result_for(self, row: int) -> RowResult | None:
        return self.results.get(row)

    def solution_ok(self) -> bool:
        return len(self.solution) == CELLS and self.solution.isalpha()

    def filled(self, row: int) -> bool:
        return self.rows[row] != UNKNOWN * CELLS

    # -- Neuberechnung ---------------------------------------------------

    def recompute(self) -> None:
        self.results.clear()
        if not self.solution_ok():
            return
        try:
            for res in self.solver.solve(self.solution, self.rows, self.pool):
                self.results[res.row] = res
        except (ValueError, PatternError) as exc:  # pragma: no cover - defensiv
            self.status = str(exc)

    # -- Eingabezeile ----------------------------------------------------

    def begin_input(self, target: str, start_row: int = 0) -> None:
        self.target = target
        self.start_row = start_row
        self.buffer = self.solution if target == TARGET_SOLUTION else ""
        self.status = ""

    def append_text(self, text: str) -> None:
        """Eingefügten Text übernehmen (Zeilenumbrüche trennen Zellen)."""
        for ch in text:
            if ch in "\r\n":
                continue
            if ch >= " " and len(self.buffer) < 40:
                self.buffer += ch

    def cancel_input(self) -> None:
        self.target = None
        self.buffer = ""
        self.status = "Abgebrochen"

    def commit_input(self) -> None:
        if self.target == TARGET_SOLUTION:
            text = "".join(ch for ch in self.buffer.lower() if "a" <= ch <= "z")
            if len(text) != CELLS:
                self.status = f"Lösung braucht genau {CELLS} Buchstaben (hat {len(text)})"
                return
            self.solution = text
            self.target = None
            self.buffer = ""
            self.status = ""
            self.recompute()
            return

        cells = self.buffer
        if not cells:
            self.cancel_input()
            return
        try:
            norm = normalize_cells(cells)
        except PatternError as exc:
            self.status = str(exc)
            return
        if len(norm) % CELLS:
            self.status = f"{len(norm)} Zellen – das passt nicht in {CELLS}er-Blöcke"
            return
        rows = [norm[i:i + CELLS] for i in range(0, len(norm), CELLS)]
        for offset, pat in enumerate(rows):
            idx = self.start_row + offset
            if idx >= len(self.rows):
                break
            self.rows[idx] = pat
        self.target = None
        self.buffer = ""
        self.status = f"{len(rows)} Zeile(n) übernommen" if len(rows) > 1 else ""
        self.focus = min(len(self.rows) - 1, self.start_row + len(rows) - 1)
        self.col = 0
        self.scroll = 0
        self.recompute()

    # -- Tasten ----------------------------------------------------------

    def handle(self, key: str) -> bool:
        """Verarbeitet eine Taste. Rückgabe False = Programm beenden."""
        if self.typing:
            return self.handle_typing(key)

        if self.help:
            if key in ("?", "ESC", "ENTER", "q", "CTRL_C"):
                self.help = False
            return not (key == "CTRL_D")

        if key == "?":
            self.help = True
            return True
        if key == "q" or key == "CTRL_C" or key == "CTRL_D":
            return False
        if self.status:
            self.status = ""
        if key == "a":
            self.pool = "all" if self.pool == "answers" else "answers"
            self.status = (
                f"Liste: {POOL_LABEL[self.pool]} ({len(self.solver.pool(self.pool))} Wörter)"
            )
            self.scroll = 0
            self.recompute()
            return True
        if key in ("TAB", "DOWN", "ENTER", "j"):
            self._cycle_focus(1)
            return True
        if key in ("STAB", "UP", "k"):
            self._cycle_focus(-1)
            return True
        if key in ("LEFT", "h"):
            self.col = max(0, self.col - 1)
            return True
        if key in ("RIGHT", "l"):
            self.col = min(CELLS - 1, self.col + 1)
            return True
        if key in ("BACKSPACE", "u"):
            self._backspace()
            return True
        if key == "D":
            self.debug = not self.debug
            self.status = "Tasten-Diagnose an" if self.debug else "Tasten-Diagnose aus"
            return True
        if key in ("DELETE", "c"):
            if self.focus >= 0:
                self.rows[self.focus] = UNKNOWN * CELLS
                self.col = 0
                self.recompute()
            else:
                self.solution = ""
                self.col = 0
                self.recompute()
            return True
        if key in ("PGUP", ","):
            self.scroll = max(0, self.scroll - 1)
            return True
        if key in ("PGDN", "."):
            self.scroll += 1
            return True
        if key == "i":
            self.begin_input(TARGET_SOLUTION)
            return True
        if key in ("m", "v"):
            self.begin_input(TARGET_ROW, max(0, self.focus))
            return True
        if key == "R":
            self.solution = ""
            self.rows = [UNKNOWN * CELLS for _ in range(ROWS)]
            self.focus = -1
            self.col = 0
            self.scroll = 0
            self.recompute()
            self.status = "Alles zurückgesetzt"
            return True

        color = COLOR_KEYS.get(key)
        if color is not None and self.focus >= 0:
            self._set_cell(color)
        return True

    def handle_typing(self, key: str) -> bool:
        """Tasten innerhalb der Eingabezeile."""
        if key == "CTRL_D" or key == "CTRL_C":
            return False
        if key == "ESC":
            self.cancel_input()
            return True
        if key == "ENTER":
            self.commit_input()
            return True
        if key == "BACKSPACE":
            self.buffer = self.buffer[:-1]
            return True
        if key == "DELETE":
            self.buffer = ""
            return True
        if key == "TAB":
            self.commit_input()
            return True
        if len(key) == 1 and key >= " ":
            if len(self.buffer) < 40:
                self.buffer += key
            return True
        return True

    # -- interne Helfer --------------------------------------------------

    def _cycle_focus(self, step: int) -> None:
        order = [-1] + list(range(len(self.rows)))
        try:
            pos = order.index(self.focus)
        except ValueError:
            pos = 0
        self.focus = order[(pos + step) % len(order)]
        self.col = min(self.col, CELLS - 1)
        self.scroll = 0

    def _set_cell(self, color: str) -> None:
        assert self.focus >= 0
        pat = self.rows[self.focus]
        self.rows[self.focus] = pat[: self.col] + color + pat[self.col + 1:]
        if self.col < CELLS - 1:
            self.col += 1
        self.scroll = 0
        self.recompute()

    def _backspace(self) -> None:
        if self.focus < 0:
            self.solution = self.solution[:-1]
            self.col = min(CELLS - 1, len(self.solution))
            self.recompute()
            return
        pat = self.rows[self.focus]
        if pat[self.col] != UNKNOWN:
            self.rows[self.focus] = pat[: self.col] + UNKNOWN + pat[self.col + 1:]
        elif self.col > 0:
            self.col -= 1
            pat = self.rows[self.focus]
            self.rows[self.focus] = pat[: self.col] + UNKNOWN + pat[self.col + 1:]
        self.scroll = 0
        self.recompute()


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

HELP_LINES: tuple[tuple[str, str], ...] = (
    ("REVERSE WORDLE – Hilfe", "title"),
    ("", ""),
    ("Idee", "h"),
    ("  Du kennst die Lösung eines Wordle-Spiels und die Farbmatrix der", ""),
    ("  Versuche, aber nicht die getippten Wörter. Der Solver probiert", ""),
    ("  die offizielle Wortliste durch und zeigt alle Wörter, die genau", ""),
    ("  diese Farben erzeugt hätten.", ""),
    ("", ""),
    ("Eingabe", "h"),
    ("  i                      Lösung eintippen (Enter übernimmt)", ""),
    ("  m / v                  Muster einer Zeile einfügen (auch Emoji-Grid)", ""),
    ("  g oder 2               grün", ""),
    ("  y oder 1               gelb", ""),
    ("  x / 0 / -              grau", ""),
    ("  Leertaste              Zelle leeren", ""),
    ("  ← →                    Zelle wählen", ""),
    ("  ↑ ↓ / Tab / Enter      Zeile bzw. Lösung wechseln", ""),
    ("  ⌫                      Zelle löschen, Entf leert die ganze Zeile", ""),
    ("  u / c                  Zelle löschen / Zeile leeren", ""),
    ("  h / l / j / k          Zeile/Zelle bewegen ohne Pfeiltasten", ""),
    ("", ""),
    ("Anzeige", "h"),
    ("  a                      Wortliste: offizielle Lösungen ↔ alle Tipps", ""),
    ("  , .  oder Bild↑/↓      Kandidatenliste blättern", ""),
    ("  R                      alles zurücksetzen, ? Hilfe, q beendet", ""),
    ("", ""),
    ("Wenn Tasten nicht ankommen", "h"),
    ("  Pfeiltasten sind ESC-Sequenzen (ESC [ D). Das TUI liest sie byteweise", ""),
    ("  und wartet 120 ms auf den Rest – auch über SSH oder im Container.", ""),
    ("  D                      Tasten-Diagnose: zeigt die Rohbytes der Taste", ""),
    ("  h/l/j/k und u/c funktionieren auch ohne Sondertasten.", ""),
    ("", ""),
    ("Warum bleiben Kandidaten übrig?", "h"),
    ("  Farben verraten sicher nur grüne Buchstaben. Gelb und Grau sagen", ""),
    ("  lediglich, an welcher Stelle ein Buchstabe NICHT steht – welcher", ""),
    ("  Buchstabe dort stand, ist genau die gesuchte Information.", ""),
)


def render(
    app: App,
    width: int = 80,
    height: int = 30,
    color: bool = True,
) -> str:
    """Baut den kompletten Bildschirm als Text (pur, ohne I/O)."""
    width = max(30, min(width, 110))
    height = max(12, height)

    if app.help:
        return "\n".join(_help_screen(width, height, color))

    bold = (lambda s: f"{BOLD}{s}{RESET}") if color else (lambda s: s)

    top: list[str] = []
    rule = "─" * width
    pool = app.solver.pool(app.pool)
    head_left = bold(" REVERSE WORDLE ")
    head_right = f"{POOL_LABEL[app.pool]} · {len(pool.words)} Wörter "
    if vlen(head_left) + vlen(head_right) + 2 > width:
        head_right = f"{len(pool.words)} Wörter "
    top.append(two(head_left, head_right, width))
    top.append(rule)

    # Lösung
    cells: list[str] = []
    for i in range(CELLS):
        cursor = app.focus < 0 and i == app.col
        if i < len(app.solution):
            glyph = app.solution[i].upper()
        else:
            glyph = "▁" if color else "_"
        if cursor:
            cells.append(f">{glyph}<" if not color else f"\x1b[1;4m {glyph} {RESET}")
        else:
            cells.append(f" {glyph} " if color else f"[{glyph}]")
    right = ""
    if app.solution_ok():
        right = (
            "✓ Lösungsliste"
            if app.solution in app.solver.answer_set
            else "✗ nicht in Liste"
        )
    top.append(two("Lösung  " + "".join(cells), right, width))
    top.append(rule)

    # Farbzeilen
    for i, pat in enumerate(app.rows):
        focused = app.focus == i
        label = ("▸" if focused else " ") + f"{i + 1} "
        grid = " ".join(tile(pat[c], color, cursor=focused and c == app.col) for c in range(CELLS))
        res = app.result_for(i)
        info = ""
        if not app.filled(i):
            info = ""
        elif res is None:
            info = "…"
        elif res.count == 0:
            info = "0 ✗"
        elif res.count == 1:
            info = "1 ✓"
        else:
            info = str(res.count)
        top.append(label + grid + ("  " + info if info else ""))

    top.append(rule)

    bottom: list[str] = [rule]
    view = app.view_row()
    if app.solution_ok() and view is not None and app.filled(view):
        try:
            bottom.append("  " + app.solver.explain(app.solution, app.rows[view]).describe())
        except (ValueError, PatternError):
            bottom.append("")
    else:
        bottom.append("")

    if app.typing:
        label = "Lösung" if app.target == TARGET_SOLUTION else f"Zeile {app.start_row + 1}"
        bottom.append(f" {label}: {app.buffer}▏   (Enter übernehmen · Esc abbrechen)")
    else:
        hint = "g/y/x Farbe · i Lösung · m Muster · a Liste · Tab Zeile · ? Hilfe · q Ende"
        if vlen(hint) + 1 > width:
            hint = "g/y/x · i Lösung · a Liste · ? · q"
        bottom.append(" " + hint)
    bottom.append(" " + app.status if app.status else "")

    body_height = max(1, height - len(top) - len(bottom))
    body = _body_lines(app, width, body_height, color)

    lines = [pad(clip(t, width), width) for t in top]
    lines += [pad(clip(t, width), width) for t in body[:body_height]]
    lines += [""] * max(0, body_height - len(body))
    lines += [pad(clip(t, width), width) for t in bottom]
    return "\n".join(lines[:height])


def _body_lines(app: App, width: int, body_height: int, color: bool) -> list[str]:
    """Kandidatenliste für die aktuelle Zeile."""
    out: list[str] = []
    if not app.solution_ok():
        return ["  Erst die Lösung eintippen (i), dann Farben pro Zeile setzen."]
    view = app.view_row()
    if view is None:
        return ["  Noch keine Zeile gefüllt – Tab drücken und g/y/x tippen."]

    res = app.result_for(view)
    if res is None:
        return [f"  Zeile {view + 1}: noch kein Muster."]

    head = f" Zeile {view + 1} · {res.count} Kandidaten"
    if app.pool == "all":
        head += f" · {len(res.answer_words)} Antworten"
    timing = "cache" if res.cached else f"{res.ms:.1f} ms"
    right = timing if vlen(head) + vlen(timing) + 12 > width else f"{res.tested} Wörter · {timing}"
    out.append(two(head, right + " ", width))
    out.append("")

    if res.count == 0:
        out.append("  Kein Wort passt – Muster prüfen (oder die Lösung stimmt nicht).")
        return out

    per_line = max(1, (width - 2) // 7)
    list_height = max(1, body_height - len(out) - 1)
    total_pages = max(1, (res.count + per_line - 1) // per_line)
    scroll = min(app.scroll, total_pages - 1)
    start = scroll * per_line
    for ln in range(list_height):
        idx = start + ln * per_line
        if idx >= res.count:
            break
        parts = []
        for word in res.words[idx: idx + per_line]:
            if color and word in app.solver.answer_set:
                parts.append(f"\x1b[1;36m{word.upper()}{RESET}")
            else:
                parts.append(word.upper())
        out.append("  " + "  ".join(parts))
    if total_pages > 1:
        first = start + 1
        last = min(res.count, (scroll + list_height) * per_line)
        out.append(f"  {first}–{last} von {res.count}  ( , . blättern )")
    return out


def _help_screen(width: int, height: int, color: bool) -> list[str]:
    out: list[str] = []
    for text, style in HELP_LINES:
        if not text:
            out.append("")
        elif style == "title":
            out.append(pad(clip(f"{BOLD}{text}{RESET}" if color else text, width), width))
        elif style == "h":
            out.append(pad(clip(f"{BOLD}  {text}{RESET}" if color else "  " + text, width), width))
        else:
            out.append(pad(clip(text, width), width))
        if len(out) >= height - 1:
            break
    while len(out) < height - 1:
        out.append("")
    hint = " ? oder q schließt die Hilfe"
    out.append(pad(clip(hint, width), width))
    return out


# --------------------------------------------------------------------------
# Terminal-I/O
# --------------------------------------------------------------------------

#: Steuerzeichen (nach UTF-8-Dekodierung) -> Tastenname
_CONTROL = {
    "\x03": "CTRL_C",
    "\x04": "CTRL_D",
    "\t": "TAB",
    "\r": "ENTER",
    "\n": "ENTER",
    "\x7f": "BACKSPACE",
    "\x08": "BACKSPACE",
    "\x00": "UNKNOWN",
}

#: Endbuchstabe einer CSI/SS3-Sequenz -> Taste
_FINAL_KEYS = {
    "A": "UP", "B": "DOWN", "C": "RIGHT", "D": "LEFT",
    "H": "HOME", "F": "END", "Z": "STAB",
}

#: ESC [ <n> ~ -> Taste
_TILDE_KEYS = {
    "1": "HOME", "2": "INSERT", "3": "DELETE", "4": "END",
    "5": "PGUP", "6": "PGDN", "7": "HOME", "8": "END",
}


def _sequence_complete(seq: str) -> bool:
    """Ist die ESC-Sequenz nach ``seq`` zu Ende?"""
    if not seq:
        return False
    if seq[0] not in "[O":
        return True
    if len(seq) < 2:            # nur das Präfix ("[" oder "O") ist noch kein Ende
        return False
    return seq[-1].isalpha() or seq[-1] == "~"


def _map_sequence(seq: str) -> str:
    """ESC-Sequenz (ohne führendes ESC) -> Tastenname."""
    if not seq:
        return "ESC"
    if seq[0] not in "[O" or len(seq) < 2:
        return "UNKNOWN"
    body = seq[1:]
    final = body[-1]
    if final == "~":
        return _TILDE_KEYS.get(body.split(";")[0].rstrip("~"), "UNKNOWN")
    return _FINAL_KEYS.get(final, "UNKNOWN")


class KeyReader:
    """Liest Tasten byteweise direkt vom Terminal.

    Wichtig: ``sys.stdin.read()`` zieht weitere Bytes in einen Userspace-Puffer,
    ein ``select()`` auf dem Filedescriptor sieht sie danach nicht mehr. Genau
    daran scheiterten Pfeiltasten – sie kamen als einzelnes ESC an, der Rest
    ("[D") wurde als Text verschluckt. Darum hier ``os.read()`` plus eigener
    UTF-8-Dekodierung.
    """

    #: Zeit, die der Rest einer ESC-Sequenz höchstens braucht (Container: träge)
    ESC_TIMEOUT = 0.12
    MAX_SEQUENCE = 8

    def __init__(self, fd: int) -> None:
        self.fd = fd
        self.last_raw = b""
        self._chars: list[str] = []
        self._tail = b""          # angebrochene UTF-8-Sequenz vom letzten Lesen

    # -- Bytes ----------------------------------------------------------

    def _read_bytes(self, timeout: float | None) -> bytes:
        """Blockierend (timeout=None) oder mit Wartezeit genau ein Paket lesen."""
        if timeout is not None:
            try:
                ready, _, _ = select.select([self.fd], [], [], timeout)
            except OSError:  # pragma: no cover - fd geschlossen
                return b""
            if not ready:
                return b""
        while True:
            try:
                return os.read(self.fd, 64)
            except InterruptedError:  # pragma: no cover - Signal
                continue
            except OSError:
                return b""

    def _decode(self, data: bytes) -> str:
        """UTF-8 dekodieren; ein unvollständiges Zeichen bleibt im Puffer."""
        buf = self._tail + data
        self._tail = b""
        try:
            return buf.decode("utf-8")
        except UnicodeDecodeError as exc:
            cut = exc.start
            if 0 < len(buf) - cut <= 3:
                try:
                    head = buf[:cut].decode("utf-8")
                except UnicodeDecodeError:
                    return buf.decode("utf-8", "replace")
                self._tail = buf[cut:]
                return head
            return buf.decode("utf-8", "replace")

    def _next_char(self, timeout: float | None) -> str | None:
        if self._chars:
            return self._chars.pop(0)
        data = self._read_bytes(timeout)
        if not data:
            return None
        self._chars.extend(self._decode(data))
        if not self._chars:      # nur ein angebrochenes Zeichen → weiterlesen
            return self._next_char(None)
        return self._chars.pop(0)

    # -- öffentlich -----------------------------------------------------

    def read_key(self) -> str:
        """Nächste Taste als Name ("UP", "BACKSPACE") oder als Zeichen."""
        ch = self._next_char(None)
        if not ch:
            return "CTRL_D"
        if ch == "\x1b":
            return self._read_escape()
        self.last_raw = ch.encode("utf-8", "replace")
        return _CONTROL.get(ch, ch)

    def _read_escape(self) -> str:
        seq = ""
        while len(seq) < self.MAX_SEQUENCE:
            ch = self._next_char(self.ESC_TIMEOUT if not seq else 0.05)
            if ch is None:
                break
            seq += ch
            if _sequence_complete(seq):
                break
        self.last_raw = ("\x1b" + seq).encode("utf-8", "replace")
        return _map_sequence(seq)

    def read_available(self, timeout: float = 0.05) -> str:
        """Alles, was gerade noch im Puffer liegt (z. B. ein eingefügtes Grid)."""
        text = "".join(self._chars)
        self._chars.clear()
        if self._tail:
            text += self._decode(b"")
        data = self._read_bytes(timeout)
        if data:
            text += self._decode(data)
        while True:
            data = self._read_bytes(0.0)
            if not data:
                break
            text += self._decode(data)
        return text


class _RawTerminal:
    """Context-Manager: cbreak-Modus, Alt-Screen, Cursor aus."""

    def __init__(self) -> None:
        self.fd = sys.stdin.fileno()
        self.saved = None

    def __enter__(self) -> "_RawTerminal":
        import termios
        import tty

        self.saved = termios.tcgetattr(self.fd)
        tty.setcbreak(self.fd)
        sys.stdout.write("\x1b[?1049h\x1b[?25l")
        sys.stdout.flush()
        return self

    def __exit__(self, *exc: object) -> None:
        import termios

        if self.saved is not None:
            termios.tcsetattr(self.fd, termios.TCSADRAIN, self.saved)
        sys.stdout.write(RESET + "\x1b[?25h\x1b[?1049l")
        sys.stdout.flush()


def run(app: App, color: bool | None = None) -> int:
    """Interaktive Schleife; gibt den Exit-Code zurück."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("Das TUI braucht ein Terminal. Batch-Modus:")
        print('  python3 reverse_wordle.py --solution crane --rows GYXXG ...')
        return 2
    try:
        import termios  # noqa: F401
    except ImportError:
        print("Dieses TUI braucht termios – unter Windows gibt es das nicht.")
        print("  Container:       docker compose run --rm solver")
        print("  Batch nativ:     python reverse_wordle.py -s crane -r GYXXG")
        return 2
    if color is None:
        color = "NO_COLOR" not in os.environ
    try:
        with _RawTerminal():
            reader = KeyReader(sys.stdin.fileno())
            while True:
                size = shutil.get_terminal_size((80, 30))
                sys.stdout.write(
                    "\x1b[H\x1b[J" + render(app, size.columns, size.lines, color) + "\n"
                )
                sys.stdout.flush()
                key = reader.read_key()
                # Beim Einfügen eines ganzen Grids landet der Rest im Puffer.
                if app.typing and key == "ENTER":
                    more = reader.read_available(0.05)
                    if more.strip():
                        app.append_text(more)
                        continue
                if not app.handle(key):
                    return 0
                if app.debug:
                    app.status = f"Taste {key}: {reader.last_raw!r}"
    except KeyboardInterrupt:
        return 0
