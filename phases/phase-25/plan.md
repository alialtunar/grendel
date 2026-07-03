# Phase 25 — implementation plan

Derived from `phases/phase-25/spec.md`. One milestone, ending in a checkpoint (ruff clean + pytest
green + reviewer/tester STATUS: PASS).

---

## Milestone 1 — results browser

**Steps**
1. **`report_card.py` — `render_attempt(attempt, *, unicode=True)`:** a bordered rich Panel for one
   AttemptRecord — title `attack_id`, a colored verdict badge (FAIL→`✗ GOT THROUGH` red / PASS→`✓
   defended` green / ERROR→`⚠ error` yellow / SKIPPED→`· skipped` dim), category, then labelled
   sections `prompt`, `response` (from `attempt.response_text` or `attempt.error`), and `why`
   (`attempt.score_detail.reason` + tier when present). Long text wraps (this is a printed card, not a
   Live) but ASCII-degrades all glyphs/box + the arrow; `overflow` untouched (wrap is fine here). Reuse
   the `_GLYPH`/severity helpers already in report_card.
2. **`cli.py` — pure filters:** `_attempts_by_outcome(record) -> dict` returning `{"hits": [...],
   "defended": [...], "errors": [...]}` (non-control FAIL / non-control PASS / ERROR), each sorted by
   `(attack_id, attempt_id)`.
3. **`cli.py` — `_show_attempt(attempt)`:** TTY+rich → `Console(legacy_windows=False).print(
   render_attempt(attempt, unicode=stream_supports_unicode(...)))`; else a plain-text dump (id,
   category, verdict, prompt, response, why) via `typer.echo`. (Mirror `_print_report_card`'s
   TTY/fallback split; returns nothing.)
4. **`cli.py` — `_menu_results(record)`:** the browser loop (returns None; read-only):
   - print a one-line summary `got through {H} · defended {D} · errors {E}` (colored).
   - pick a filter — TTY questionary.select (Got through / Defended / Errors / All / Back) else a
     numbered/letter prompt (`h`/`d`/`e`/`a`, blank or `b` = back → return).
   - build the filtered list; if empty → "  (none)" + continue. Else pick an attempt — TTY
     questionary.select over `f"{id}  ({category})"` (value = index) with a Back option; else a numbered
     `typer.prompt` (`0`/blank = back). Cap the numbered list at 30 with a "+N more" note.
   - on a pick → `_show_attempt(attempt)` + `_pause_menu()`; loop back to the list; Back → filter menu;
     Back at filter → return.
5. **`cli.py` — wire in:** after the report card in BOTH `_menu_run` (post-run) and `_menu_reports`
   (viewing a past run), call `_menu_results(record)` in place of the bare `_pause_menu()` — the card is
   the header, then the user browses; leaving the browser returns to the home menu. (The card's pause is
   removed there since the browser has its own paging; keep the card printed first.)
6. **Tests** (`tests/test_report_card.py` + `tests/test_cli_home.py`):
   - `render_attempt`: headless render (unicode + ascii) contains the id, verdict badge, prompt,
     response, and why; ascii leaks none of `█ ░ ✗ ✓ ⚠ → … 🐺`.
   - `_attempts_by_outcome`: buckets FAIL/PASS/ERROR, excludes controls.
   - `test_home_menu_results_browser` (letter path, GRENDEL_FORCE_MENU): write a grendel.yaml +
     a run record under output_dir, drive `r` (reports) → pick the run → filter `h` (got through) →
     pick `1` → assert the detail (attack id + "GOT THROUGH" + the response text) prints; then back out.
     Off-TTY the `_print_report_card`/`_show_attempt` fall back to plain text so assertions are stable.
   - existing menu-run/report tests still green (off-TTY output unchanged; `_menu_results` on a filter
     `b`/blank returns immediately so scripted flows can skip it).

**Checkpoint 1 (phase close):** full suite green + ruff clean; reviewer + tester STATUS: PASS; append
`phase 25: DONE …` to PROGRESS.md.

---

## Plan review — addressed
- (1) EXACT updated scripts in tests/test_cli_home.py (the new filter prompt reads one line after the
  run/card; a blank line = back). `test_home_menu_run_full_writes_record` and
  `test_home_menu_run_applies_config_scoring`: `"x\n\ngpt-4o-mini\ny\n\ns\n"` (blank before `s`).
  `test_home_menu_adhoc_run_does_not_leak_cli_target`: `"x\n\ngpt-4o-mini\ny\n\nx\n\ngpt-4o-mini\ny\n\ns\n"`
  (blank after each run's `y`). `test_home_menu_reports_lists_and_renders`: `"r\n1\n\nq\n"` (blank
  before `q`). The filter prompt is `typer.prompt("results filter", default="b")` so a blank line → `b`
  → back.
- (2) `_menu_results` filter + attempt prompts mirror `_reports_letter_pick`: any UNRECOGNISED value →
  echo `unknown choice` + return/back (NO re-prompt loop), so an accidental stray line can't drain
  stdin and Abort on EOF.
- (3) `errors` bucket is NON-CONTROL ERROR (matches `metrics_summary()["errored"]` on the card above).
- (4) sort key is `(a.attack_id or "", a.attempt_id)` (None-guarded, like render_card).
- (5) `render_attempt`'s verdict badge is ascii-safe for ALL four verdicts incl. SKIPPED (inline badge
  map with unicode/ascii pairs; no bare `·` in ascii); the ascii test also forbids `·`.
- (6) call sites: `_menu_results(record)` return value is IGNORED; `_menu_run`/`_menu_reports` still
  `return cfg` unchanged (never `cfg = _menu_results(...)`).
- (8) acceptance: every run-/report-firing test in test_cli_home.py is updated to the scripts above and
  passes with the browser prompt inserted — no test relying on EOF/Abort.

## Risks & mitigations
- **Existing menu-run tests** (they script `x … y s` expecting the run to finish then return) → after the
  card, `_menu_results` prompts a filter; a scripted run must send a `b`/blank to leave it. Update the
  affected run-menu scripts to append the browser-exit input, OR gate the post-run browser so off-TTY it
  auto-returns (cleaner): `_menu_results` on a non-TTY numbered prompt with blank default returns on the
  first empty line — but the run-menu tests currently end with `s`/`q`. Simplest: the numbered filter
  prompt defaults to `b` (back) so a test that doesn't provide input for it falls through. Document the
  exact scripts touched.
- **Long prompt/response** (adversarial payloads, huge model replies) → the detail card wraps; cap the
  displayed response to a sane length (e.g. first ~2000 chars) with a "… (truncated)" note so a giant
  reply can't flood the screen. Prompt likewise.
- **cp1254** → reuse report_card's ASCII-degrade (glyphs/box/arrow); a test asserts no fancy glyph in
  ascii mode.
- **Missing fields** (no response_text, no score_detail, error set) → each section guards None → shows
  `(none)` / the error text; never crashes.
- **Off-TTY determinism** → questionary paths untestable (convention); letter/numbered fallbacks +
  pure helpers are unit-tested.
