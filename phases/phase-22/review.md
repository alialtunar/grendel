# Phase 22 review — branded live dashboard (`src/grendel/live.py`)

Scope: presentation-only redesign of `LiveAttackRun._render`/`__enter__` and new `_layout` helper.
Reviewed `src/grendel/live.py`, `src/grendel/banner.py`, `src/grendel/cli.py` (`_menu_run` wiring),
`tests/test_live_dashboard.py`. Full repo history for `src/grendel/` is untracked in this working
tree (mid-rename from `gauntlet`), so no clean `git diff` exists for phase 22 alone — reviewed the
files directly against `phases/phase-22/spec.md` and `plan.md` instead.

## Findings

1. **All 7 "Plan review — addressed" points are implemented as described** (`src/grendel/live.py`):
   - (1) logo `Text(..., no_wrap=True, overflow="crop")` at line 110-113, gated by
     `_show_logo = width >= _MIN_LOGO_WIDTH` (66) in `_layout` (line 31).
   - (2)(3) `_layout(height, width)` (lines 28-34) computes `visible = max(3, height - _CHROME -
     logo_part)` where `_CHROME = 6` and `logo_part = _LOGO_LINES(7) if show_logo else 0` — a real
     total-height budget, not just a floor, matching the documented arithmetic. Constants carry
     comments (lines 22-25).
   - (4) exact label `f"{self.n}/{self.total} sent"` at line 96; asserted verbatim in tests
     (`test_live_dashboard.py:76,86`).
   - (5) ascii separator uses `Text("-" * self._width, ...)` (line 124) where `self._width` is the
     panel inner width set from `_layout`'s `max(20, width - 4)` (line 34) in `__enter__` (line 147).
   - (6) `ProgressBar` is constructed only inside `if self.unicode:` (lines 82-88); the ascii branch
     builds a manual `#`/`-` `Text` bar (lines 89-91) — single gate is `self.unicode`
     (`stream_supports_unicode`), not rich's own detection.
   - (7) `test_render_at_80_cols_still_shows_core` (test file line 82-86) covers width=80.

2. **cp1254 crash-safety preserved.** `test_ascii_degrade_uses_no_fancy_glyphs_or_box` asserts none
   of `█ ░ ✗ ✓ ⚠ · ─ │ ━` appear when `unicode=False`; `box.ASCII` used for the panel (line 166),
   `Rule` (unicode chars) only built in the `u` branch (line 124), glyphs degrade via `_GLYPH` (lines
   15-20) and the stat-row `hit_m/def_m/err_m` triple (line 107). `legacy_windows=False` kept in
   `__enter__` (line 142), `render_logo(unicode=u)` passed through. Confirmed by running the test
   suite — passes.

3. **`_render` cannot raise on the live path.** `on_attempt` wraps the whole call (including
   `_render()`) in `try/except Exception: pass` (lines 51-72), and `_render` itself only does
   pure-Python string/rich-object construction with guarded state (`total = max(total, 1)` in
   `__init__`, so no division by zero in either the `ProgressBar` or manual bar). Verified with
   `test_total_zero_guard_no_zero_division`.

4. **Off-TTY / no-rich path unchanged.** `make_live_run` still None-gates on `sys.stdout.isatty()`
   and a `rich` import (lines 173-185); `cli.py:2264-2284` `_menu_run` fallback to the plain
   `_run_progress` counter is intact and untouched. `on_attempt`/`_asr` still exclude `is_control`
   (lines 56-58), unchanged from phase 21.

5. **Minor, non-blocking cosmetic inaccuracy:** `_LOGO_LINES = 7` (6 wordmark rows + 1 blank) is used
   in `_layout` regardless of `unicode` mode, but the ASCII wordmark (`banner._LOGO_ASCII`) is only 5
   lines, not 6 — confirmed by running `render_logo(unicode=False)` → 5 lines vs. `unicode=True` → 6
   lines. In ASCII mode the actual rendered logo+blank is 6 lines, so `_layout`'s budget of 7
   over-reserves by one row. This is conservative (never overflows the terminal, just yields one
   fewer stream row than optimal in ASCII mode) and does not violate the "whole panel fits" invariant
   asserted by `test_layout_fits_terminal_height`, since that test only exercises the unicode-logo
   case. Not a functional bug; worth a one-line fix or comment if picked up in a later polish pass,
   but does not block this phase.
6. `_panel` helper is straightforward and correct; `box.ROUNDED`/`box.ASCII` selection, `border_style`,
   and title selection (`"🐺 live attack run"` only reachable when `stream_supports_unicode` already
   verified `🐺` is encodable) are consistent. No dead code found; `_visible` default of 12 without
   `__enter__` is tested (`LiveAttackRun.__init__` line 46, matches spec step 1(b)/plan step 4's
   "headless" test — present in `test_render_has_logo_panel_target_sent_and_recent` since it never
   calls `__enter__`).

## Verification run
- `python -m pytest -q` → 601 passed, 1 skipped.
- `python -m ruff check src tests` → All checks passed.
- `python -m pytest -q tests/test_live_dashboard.py -v` → 9 passed (counter/ASR, controls-exclusion,
  zero-total guard, logo+panel+sent+recent render, 80-col render, logo-dropped, ascii-degrade,
  `_layout` height-fit).

No blocking issues found.

STATUS: PASS
