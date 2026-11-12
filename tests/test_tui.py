"""Tests für Zustandslogik und Rendering des TUI (ohne echtes Terminal)."""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wordle.core import UNKNOWN, Solver  # noqa: E402
from wordle.tui import (  # noqa: E402
    TARGET_ROW,
    TARGET_SOLUTION,
    App,
    render,
    vlen,
)


class AppTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.solver = Solver()

    def new_app(self) -> App:
        return App(self.solver)

    def type_solution(self, app: App, word: str) -> None:
        app.handle("i")
        for ch in word:
            app.handle_typing(ch)
        app.handle_typing("ENTER")

    def fill_row(self, app: App, pattern: str) -> None:
        app.handle("TAB")          # von der Lösung in Zeile 1
        for ch in pattern:
            app.handle(ch.lower())

    # -- Eingabe ---------------------------------------------------------

    def test_solution_input(self) -> None:
        app = self.new_app()
        self.assertFalse(app.solution_ok())
        self.assertEqual(app.results, {})
        self.type_solution(app, "crane")
        self.assertEqual(app.solution, "crane")
        self.assertTrue(app.solution_ok())
        self.assertFalse(app.typing)

    def test_solution_input_ignores_junk(self) -> None:
        app = self.new_app()
        app.handle("i")
        for ch in "cr1ane!":
            app.handle_typing(ch)
        app.handle_typing("ENTER")
        self.assertEqual(app.solution, "crane")

    def test_solution_too_short_keeps_old_value(self) -> None:
        app = self.new_app()
        self.type_solution(app, "crane")
        app.handle("i")
        app.handle_typing("BACKSPACE")
        app.handle_typing("ENTER")
        self.assertEqual(app.solution, "crane")
        self.assertIn("genau 5 Buchstaben", app.status)

    def test_typing_q_does_not_quit(self) -> None:
        app = self.new_app()
        app.handle("i")
        self.assertTrue(app.handle_typing("q"))
        self.assertIn("q", app.buffer)

    def test_escape_cancels_input(self) -> None:
        app = self.new_app()
        app.handle("i")
        app.handle_typing("c")
        self.assertEqual(app.handle_typing("ESC"), True)
        self.assertFalse(app.typing)
        self.assertEqual(app.solution, "")

    def test_rows_by_keys(self) -> None:
        app = self.new_app()
        self.type_solution(app, "crane")
        self.fill_row(app, "gyxxg")
        self.assertEqual(app.rows[0], "GYXXG")
        res = app.result_for(0)
        self.assertIsNotNone(res)
        self.assertEqual(res.count, 4)                 # CABLE CACHE CASTE CAUSE
        self.assertEqual(app.focus, 0)

    def test_backspace_and_delete(self) -> None:
        app = self.new_app()
        self.type_solution(app, "crane")
        self.fill_row(app, "gyxxg")
        app.handle("BACKSPACE")                        # letzte Zelle leeren
        self.assertEqual(app.rows[0], "GYXX?")
        app.handle("DELETE")                           # ganze Zeile leeren
        self.assertEqual(app.rows[0], UNKNOWN * 5)
        self.assertIsNone(app.result_for(0))

    def test_focus_cycle(self) -> None:
        app = self.new_app()
        seen = [app.focus]
        for _ in range(7):
            app.handle("TAB")
            seen.append(app.focus)
        self.assertEqual(seen, [-1, 0, 1, 2, 3, 4, 5, -1])

    def test_pool_toggle_changes_results(self) -> None:
        app = self.new_app()
        self.type_solution(app, "crane")
        self.fill_row(app, "gyxxg")
        small = app.result_for(0).count
        app.handle("a")
        self.assertEqual(app.pool, "all")
        big = app.result_for(0).count
        self.assertGreater(big, small)
        self.assertEqual(app.results[0].pool_name, "all")
        app.handle("a")
        self.assertEqual(app.pool, "answers")

    def test_multiline_paste(self) -> None:
        app = self.new_app()
        self.type_solution(app, "crane")
        app.begin_input(TARGET_ROW, 0)
        app.append_text("🟩🟨⬛⬛🟩\n🟨⬛⬛⬛⬛\n")
        app.commit_input()
        self.assertEqual(app.rows[0], "GYXXG")
        self.assertEqual(app.rows[1], "YXXXX")
        self.assertFalse(app.typing)
        self.assertIn(1, app.results)

    def test_paste_not_multiple_of_five(self) -> None:
        app = self.new_app()
        app.begin_input(TARGET_ROW, 0)
        app.append_text("GGG")
        app.commit_input()
        self.assertIn("Blöcke", app.status)
        self.assertEqual(app.rows[0], UNKNOWN * 5)

    def test_reset(self) -> None:
        app = self.new_app()
        self.type_solution(app, "crane")
        self.fill_row(app, "gyxxg")
        app.handle("R")
        self.assertEqual(app.solution, "")
        self.assertEqual(app.focus, -1)
        self.assertEqual(app.results, {})

    def test_quit_keys(self) -> None:
        app = self.new_app()
        self.assertFalse(app.handle("q"))
        app2 = self.new_app()
        self.assertFalse(app2.handle("CTRL_C"))


class RenderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.solver = Solver()

    def app(self) -> App:
        app = App(self.solver)
        app.handle("i")
        for ch in "crane":
            app.handle_typing(ch)
        app.handle_typing("ENTER")
        app.handle("TAB")
        for ch in "gyxxg":
            app.handle(ch)
        return app

    def test_layout_widths(self) -> None:
        app = self.app()
        for width in (30, 40, 60, 80, 120):
            text = render(app, width, 30, color=True)
            lines = text.splitlines()
            self.assertEqual(len(lines), 30)
            for line in lines:
                self.assertLessEqual(vlen(line), width, f"zu breit bei {width}: {line!r}")

    def test_plain_mode_has_no_ansi(self) -> None:
        app = self.app()
        text = render(app, 50, 24, color=False)
        self.assertNotIn("\x1b", text)
        self.assertIn("[G]", text)
        self.assertIn("[Y]", text)

    def test_contains_solution_and_candidates(self) -> None:
        app = self.app()
        text = render(app, 60, 30, color=False)
        sol_line = next(line for line in text.splitlines() if line.startswith("Lösung"))
        self.assertEqual(re.findall(r"\[([A-Z])\]", sol_line), list("CRANE"))
        self.assertIn("CAUSE", text)
        self.assertIn("Zeile 1", text)
        self.assertIn("4 Kandidaten", text)

    def test_scrolling(self) -> None:
        app = App(self.solver, solution="crane")
        app.rows[0] = "XXXXX"
        app.focus = 0
        app.recompute()
        self.assertGreater(app.result_for(0).count, 40)
        first = render(app, 50, 20, color=False)
        app.handle(".")
        second = render(app, 50, 20, color=False)
        self.assertNotEqual(first, second)

    def test_help_screen(self) -> None:
        app = self.app()
        app.handle("?")
        text = render(app, 50, 20, color=False)
        self.assertIn("Hilfe", text)
        self.assertEqual(len(text.splitlines()), 20)
        app.handle("?")
        self.assertNotIn("Hilfe", render(app, 50, 20, color=False))

    def test_small_terminal(self) -> None:
        app = self.app()
        text = render(app, 30, 14, color=True)
        self.assertEqual(len(text.splitlines()), 14)


if __name__ == "__main__":
    unittest.main()
