"""Reverse-Wordle-Solver: Lösung + Farbmatrix -> getippte Wörter."""

from .core import (
    GRAY,
    GREEN,
    UNKNOWN,
    WORD_LENGTH,
    YELLOW,
    PatternError,
    RowResult,
    Solver,
    WordPool,
    constraints,
    feedback,
    normalize_cells,
    normalize_pattern,
    parse_grid,
)

__all__ = [
    "GRAY",
    "GREEN",
    "UNKNOWN",
    "WORD_LENGTH",
    "YELLOW",
    "PatternError",
    "RowResult",
    "Solver",
    "WordPool",
    "constraints",
    "feedback",
    "normalize_cells",
    "normalize_pattern",
    "parse_grid",
]

__version__ = "1.0.0"
