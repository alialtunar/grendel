# Phase 26 review — first-run WELCOME orientation block

Scope reviewed: `src/grendel/banner.py` (`render_welcome`), `src/grendel/cli.py`
(`_home_letter`, `_home_questionary`), `tests/test_cli_home.py`.

## Findings

1. **Consistent placement, correctly gated (spec point 1).** Both `_home_letter` (cli.py:2521-2526)
   and `_home_questionary` (cli.py:2573-2579) print `render_welcome(...)` + a blank line right after
   `_clear_and_logo`, before `config_header`, and only `if not cfg.targets`. Order is identical in both
   shells (logo -> welcome -> header/options). Verified with tests
   `test_home_menu_welcome_shown_when_no_targets` and `test_home_menu_welcome_hidden_once_a_target_exists`
   (test_cli_home.py:75-89), both passing.

2. **cp1254 safety confirmed.** `render_welcome` (banner.py:123-143) only varies the em-dash on the
   `unicode` flag (`dash = "—" if unicode else "-"`); it never emits `·` or `🐺` in either branch, so
   the ascii path is trivially safe. `test_render_welcome_orients_the_newcomer` (test_cli_home.py:62-72)
   asserts none of `—`, `·`, `🐺` leak into the `unicode=False` output. Output also still flows through
   the existing `install_console_fallback` at the stdout boundary as an additional safety net.

3. **No regressions.** Full suite: 621 passed, 1 skipped. `ruff check src tests`: all checks passed.
   The banner path (`render_banner`, `COMMANDS` drift-guard, `test_first_run_walkthrough`) is untouched
   — confirmed by reading `render_banner` (banner.py:155-182, no diff from welcome work) and
   `test_first_run_walkthrough` (test_cli_walkthrough.py:24-31), which exercises the non-TTY banner
   path (`GRENDEL_NO_AUTOCONFIG=1`, no `GRENDEL_FORCE_MENU`) and is independent of the menu-only welcome
   change. Existing empty-config menu tests (packs listing, doctor entry, etc.) still pass because they
   assert substrings, not exact/absent output, per the plan's risk mitigation.

4. **Copy accuracy across both shells (plan point 7).** `render_welcome`'s three steps reference menu
   ITEM NAMES — `(targets)`, `(run)`, and a "doctor" tip — with no bracket-key hints. This reads
   correctly in the letter shell (`[t] targets`, cli.py:2527) and the questionary shell
   (`targets · ...`, `run · ...`, `doctor · ...`, cli.py:2581-2590), where bracket keys don't exist.

5. **`color=sys.stdout.isatty()` used correctly (not stdin), no dead code.** Both shells call
   `render_welcome(color=sys.stdout.isatty(), unicode=unicode)` (cli.py:2524, 2576), matching the
   existing `_clear_and_logo` convention. The local `import sys` in each function is used for this call
   (not unused/dead). The `lambda` stylers in `render_welcome` (`b`, `g`, `dim`) are all referenced in
   the returned lines — no unused locals. Ruff confirms no lint violations (e.g. no F401/F841).

## Minor observations (non-blocking)
- `render_welcome`'s `unicode` parameter only toggles the dash character; this is intentional per the
  plan (no other unicode-only glyphs are used in the block), and the unit test explicitly covers this
  narrow surface — acceptable given the reduced glyph set was a deliberate simplification vs. the
  original spec (which considered a 🐺 title and `·` bullets that were dropped to avoid duplicating
  ascii-degrade logic). No action needed.

## Verification run
- `python -m pytest -q` → 621 passed, 1 skipped.
- `python -m ruff check src tests` → All checks passed.

STATUS: PASS
