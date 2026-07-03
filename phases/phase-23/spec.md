# Phase 23 — view run reports from the home menu

## Problem (user feedback)
After a menu run finishes, `_pause_menu()` waits for Enter and then the home loop's `_clear_and_logo`
wipes the screen — so the run summary AND the `next: grendel report --run <path>` hint are gone before
the user can act on them ("entere bastım raporu göremedim"). The home menu has no way to view a report,
and the user no longer knows the run-id/path to pass to `grendel report`.

## Goal
Add a home-menu entry to **view a past run's report inline**:
- List recent run records from `cfg.run.output_dir` (newest first) with a one-line label
  (target, attempts, ASR, status) — the just-finished run is at the top.
- Pick one (arrow-key on a TTY, numbered fallback off-TTY), render a plain-text report on screen, show
  the `grendel report --run <path> --format md/html` hint for the full/exportable version, and
  `_pause_menu()` so it stays until the user presses Enter.

## Non-goals
- No change to the `report` subcommand's behavior/output (reuse its text rendering via a shared pure
  function; substrings the tests assert must stay identical).
- No new report format, no rich rendering here — plain text (crash-safe on cp1254 like the rest).
- No change to the run flow, scoring, or record format.

## Decisions
- Extract the `report` command's inline text body into `reports.render_text(record)` (single source),
  used by BOTH the command and the new menu viewer.

## Dev strategy
Established phase workflow: plan → plan-reviewer → implement → reviewer → tester → gates (ruff clean +
pytest green + STATUS: PASS) → append to PROGRESS.md.
