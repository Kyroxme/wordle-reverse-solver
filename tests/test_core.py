"""Tests für Kernlogik und Wortlisten."""

from __future__ import annotations

import random
import sys
import time
import unittest
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wordle.core import (  # noqa: E402
    GRAY,
    GREEN,
    UNKNOWN,
    YELLOW,
    PatternError,
    Solver,
    constraints,
    feedback,
    matches_partial,
    normalize_cells,
    normalize_pattern,
)


def ref_feedback(guess: str, solution: str) -> str:
    """Unabhängige Referenzimplementierung (Counter, zwei Durchläufe)."""
    pool = Counter(solution)
    marks: list[str | None] = [None] * 5
    for i, (g, s) in enumerate(zip(guess, solution)):
        if g == s:
            marks[i] = GREEN
            pool[g] -= 1
    for i, (g, s) in enumerate(zip(guess, solution)):
        if marks[i] is not None:
            continue
        if pool[g] > 0:
            marks[i] = YELLOW
            pool[g] -= 1
        else:
            marks[i] = GRAY
    return "".join(marks)  # type: ignore[arg-type]


class FeedbackTest(unittest.TestCase):
    def test_basic(self) -> None:
        self.assertEqual(feedback("crane", "crane"), "GGGGG")
        self.assertEqual(feedback("crane", "abbey"), "XXYXY")
        self.assertEqual(feedback("crane", "zzzzz"), "XXXXX")
        self.assertEqual(feedback("bobby", "abbey"), "YXGXG")
        self.assertEqual(feedback("babes", "abbey"), "YYGGX")

    def test_green_counts_once(self) -> None:
        # Beide b der Lösung sitzen an Position 2 und 3 -> doppelt grün.
        self.assertEqual(feedback("bbbbb", "abbey"), "XGGXX")
        self.assertEqual(feedback("eerie", "eerie"), "GGGGG")

    def test_matches_reference_random(self) -> None:
        solver = Solver()
        rng = random.Random(1234)
        for _ in range(400):
            guess = rng.choice(solver.all_words)
            sol = rng.choice(solver.answer_words)
            self.assertEqual(feedback(guess, sol), ref_feedback(guess, sol))

    def test_count_invariant(self) -> None:
        """G+Y pro Buchstabe muss min(Anzahl im Tipp, Anzahl in Lösung) sein."""
        solver = Solver()
        rng = random.Random(99)
        for _ in range(200):
            guess = rng.choice(solver.all_words)
            sol = rng.choice(solver.answer_words)
            marks = feedback(guess, sol)
            self.assertEqual(len(marks), 5)
            for letter in set(guess) | set(sol):
                marked = sum(1 for m, g in zip(marks, guess) if g == letter and m != GRAY)
                self.assertEqual(marked, min(guess.count(letter), sol.count(letter)))

    def test_bad_input(self) -> None:
        with self.assertRaises(ValueError):
            feedback("cran", "crane")


class NormalizeTest(unittest.TestCase):
    def test_variants(self) -> None:
        self.assertEqual(normalize_pattern("GGXYG"), "GGXYG")
        self.assertEqual(normalize_pattern("ggxyg"), "GGXYG")
        self.assertEqual(normalize_pattern("2 2 1 0 2"), "GGYXG")
        self.assertEqual(normalize_pattern("🟩🟩🟨⬛🟩"), "GGYXG")
        self.assertEqual(normalize_pattern("🟩🟩🟨⬛🟩\ufe0f"), "GGYXG")
        self.assertEqual(normalize_pattern("??.??"), "?????")
        self.assertEqual(normalize_pattern("grün grün gelb grau grün"), "GGYXG")

    def test_multi_row(self) -> None:
        self.assertEqual(normalize_cells("🟩🟨⬛⬛🟩\n🟨⬛⬛⬛⬛"), "GYXXGYXXXX")
        self.assertEqual(len(normalize_cells("g" * 30)), 30)

    def test_errors(self) -> None:
        with self.assertRaises(PatternError):
            normalize_pattern("GGG")
        with self.assertRaises(PatternError):
            normalize_pattern("GGGGGG")
        with self.assertRaises(PatternError):
            normalize_pattern("GGGQ")


class ConstraintsTest(unittest.TestCase):
    def test_describe(self) -> None:
        c = constraints("crane", "GYXXG")
        self.assertEqual(c.anchors, ((0, "c"), (4, "e")))
        text = c.describe()
        self.assertIn("fest: 1=C", text)
        self.assertIn("gelb: 2≠R", text)
        self.assertIn("grau: 3≠A", text)

    def test_empty(self) -> None:
        self.assertEqual(constraints("crane", "?????").describe(), "noch keine Einschränkung")


class SolverTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.solver = Solver()

    def brute(self, solution: str, pattern: str, words) -> set[str]:
        return {w for w in words if matches_partial(feedback(w, solution), pattern)}

    def test_data_lists(self) -> None:
        s = self.solver
        self.assertEqual(len(s.answer_words), 2309)
        self.assertEqual(len(s.all_words), 14855)
        self.assertTrue(set(s.answer_words) <= set(s.all_words))
        self.assertEqual(len(set(s.answer_words)), len(s.answer_words))
        for w in s.all_words[:50] + s.answer_words[:50]:
            self.assertEqual(len(w), 5)
            self.assertTrue(w.isalpha() and w.islower())

    def test_guess_is_always_a_candidate(self) -> None:
        s = self.solver
        rng = random.Random(7)
        for _ in range(60):
            sol = rng.choice(s.answer_words)
            guess = rng.choice(s.all_words)
            res = s.candidates(sol, feedback(guess, sol), "all")
            self.assertIn(guess, res.words)

    def test_matches_brute_force(self) -> None:
        s = self.solver
        rng = random.Random(4242)
        for _ in range(40):
            sol = rng.choice(s.answer_words)
            guess = rng.choice(s.all_words)
            pat = feedback(guess, sol)
            res = s.candidates(sol, pat, "all")
            self.assertEqual(set(res.words), self.brute(sol, pat, s.all_words))

    def test_partial_pattern(self) -> None:
        s = self.solver
        pat = "GG???"
        res = s.candidates("crane", pat, "answers")
        self.assertEqual(set(res.words), self.brute("crane", pat, s.answer_words))

    def test_answer_pool_is_subset(self) -> None:
        s = self.solver
        pat = feedback("slate", "crane")
        small = s.candidates("crane", pat, "answers")
        big = s.candidates("crane", pat, "all")
        self.assertTrue(set(small.words) <= set(big.words))
        self.assertEqual(small.answer_words, small.words)
        for word in small.words:
            self.assertEqual(feedback(word, "crane"), pat)

    def test_impossible_pattern(self) -> None:
        res = self.solver.candidates("crane", "GGGGG", "all")
        self.assertEqual(res.words, ("crane",))

    def test_cache(self) -> None:
        s = self.solver
        pat = feedback("zymic", "abbey")
        first = s.candidates("abbey", pat, "answers")
        second = s.candidates("abbey", pat, "answers")
        self.assertFalse(first.cached)
        self.assertTrue(second.cached)
        self.assertEqual(first.words, second.words)

    def test_bad_solution(self) -> None:
        with self.assertRaises(ValueError):
            self.solver.candidates("toolong", "GGGGG")

    def test_performance(self) -> None:
        s = self.solver
        guesses = ("slate", "pious", "adieu", "soare", "tears", "abbey")
        t0 = time.perf_counter()
        for g in guesses:
            s.candidates("crane", feedback(g, "crane"), "all")
        elapsed = time.perf_counter() - t0
        self.assertLess(elapsed, 2.0, f"6 Zeilen brauchten {elapsed:.2f}s")


class RowSolverTest(unittest.TestCase):
    def test_solve_skips_empty_rows(self) -> None:
        s = Solver()
        rows = ["?????", "GGGGG", "?????"]
        out = s.solve("crane", rows, "answers")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].row, 1)


if __name__ == "__main__":
    unittest.main()
