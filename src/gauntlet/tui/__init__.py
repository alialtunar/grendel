"""The gauntlet TUI scoreboard package.

The pure presentation model (``state``) is dependency-light and imports no Textual; the
Textual app (``app``) is imported lazily by callers so importing this package never
requires Textual.
"""

from __future__ import annotations

from .state import (
    AttemptFilter,
    CategoryRow,
    FailureItem,
    ScoreboardState,
    apply_filter,
    build_scoreboard,
    repro_for,
    select_next,
    toggle_explain,
    with_filter,
)

__all__ = [
    "AttemptFilter",
    "CategoryRow",
    "FailureItem",
    "ScoreboardState",
    "apply_filter",
    "build_scoreboard",
    "repro_for",
    "select_next",
    "toggle_explain",
    "with_filter",
]
