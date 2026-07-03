# Phase 25 review — in-app results browser

Scope reviewed: `src/grendel/report_card.py` (`render_attempt`, `_BADGE`, `_clip`), `src/grendel/cli.py`
(`_attempts_by_outcome`, `_show_attempt`, `_pick_attempt`, `_menu_results`, and the `_menu_run`/
`_menu_reports` wiring), `src/grendel/records.py` (`AttemptRecord`/`ScoreDetail` fields), and the new/
updated tests in `tests/test_report_card.py` and `tests/test_cli_home.py`.

## Findings

1. **Off-TTY control flow (plan-review point 1) — verified correct.** Traced every updated script in
   `tests/test_cli_home.py` token-by-token against the actual prompt call sites:
   - `test_home_menu_run_full_writes_record` / `test_home_menu_run_applies_config_scoring`
     (`"x\n\ngpt-4o-mini\ny\n\ns\n"`): `_prompt_run_target` returns `_ADHOC` with **zero** input consumed
     when `cfg.targets` is empty (`cli.py:2130-2131`), so the blank line after `x` is the provider prompt
     default, `gpt-4o-mini` is the model, `y` fires, the next blank line is consumed by
     `_menu_results`'s filter prompt (`typer.prompt("results filter", default="b")`, `cli.py:2260`) which
     returns immediately on unrecognised/blank input (`cli.py:2262-2263`), and `s` is the outer
     save-and-quit. Six tokens, six prompts — exact match.
   - `test_home_menu_adhoc_run_does_not_leak_cli_target`: same pattern doubled, one blank per run.
   - `test_home_menu_reports_lists_and_renders` (`"r\n1\n\nq\n"`) and
     `test_home_menu_results_browser_drills_into_a_hit` (`"r\n1\nh\n1\nb\nq\n"`): traced through
     `_menu_reports` → `_reports_letter_pick` → `_menu_results` → `_pick_attempt`; token counts match
     exactly (verified `_reports_letter_pick`, `cli.py:2461-2472`, consumes exactly one line).
   - Confirmed the two decline-path tests (`test_home_menu_run_confirm_cancel`,
     `test_home_menu_run_picks_configured_target`) correctly do **not** need a browser-exit token, since
     `typer.confirm(...)` returning False takes the `return cfg` branch (`cli.py:2386-2388`) before
     `_menu_results` is ever reached — and `test_home_menu_reports_empty` returns before `_menu_results`
     too (empty records list). No run-/report-firing test was missed; full suite (`618 passed, 1
     skipped`) and `ruff check src tests` (clean) confirm this empirically, not just by inspection.

2. **Unknown-input safety — verified.** Both the filter prompt (`cli.py:2258-2263`) and the numbered
   attempt picker (`_pick_attempt`, `cli.py:2292-2300`) map any unrecognised/blank value straight to
   `return`/back with no re-prompt loop — matches the existing `_reports_letter_pick` convention, so a
   stray scripted line can never drain stdin into an `Abort`.

3. **`_menu_run`/`_menu_reports` still `return cfg`** (`cli.py:2429`, `cli.py:2512`); `_menu_results`'s
   return value is discarded at both call sites (`cli.py:2428`, `cli.py:2511`). Home loop keeps a valid
   `GrendelConfig` throughout.

4. **cp1254 safety — verified via test + code inspection.** `_BADGE` (`report_card.py:16-21`) supplies
   ascii pairs for all four verdicts including SKIPPED (`". skipped"`, no bare `·`); `_clip`'s truncation
   marker is `" (truncated)"` in ascii mode vs `"… (truncated)"` in unicode (`report_card.py:152-156`).
   `test_render_attempt_ascii_is_cp1254_safe` asserts none of `█ ░ ✗ ✓ ⚠ → … 🐺 ·` leak in ascii mode, and
   it passes. (Note: `_pick_attempt`'s off-TTY "+N more" line unconditionally uses `"…"`, `cli.py:2296` —
   pre-existing codebase convention, e.g. `cli.py:2056`, not gated on `unicode`/cp1254-detection; not
   introduced by this phase and consistent with existing style, so not flagged as blocking.)

5. **Missing-field guards — verified.** No `response_text` → falls back to `attempt.error or "(no
   response)"` (`report_card.py:169`); no `score_detail` or empty `reason` → the whole "why" section is
   omitted (`report_card.py:172`); `attack_id is None` → sort key uses `a.attack_id or ""`
   (`cli.py:2193`) and the title uses `attempt.attack_id or '(no id)'` (`report_card.py:180`); empty
   buckets print `"(none)"` (`cli.py:2266`).

6. **`errors` bucket correctness — verified.** `_attempts_by_outcome`'s `errors` bucket is non-control
   `Verdict.ERROR` (`cli.py:2192,2196`), which matches exactly the card's `metrics_summary()["errored"]`
   definition (`records.py:219,239`: `attacks = [a for a in self.attempts if not a.is_control]`, then
   `sum(1 for a in attacks if a.verdict == Verdict.ERROR)`). No re-parsing/re-loading: `_menu_results`
   operates on the already-loaded in-memory `record`/`rec` object passed in from the caller — no extra
   catalog or file I/O.

7. **No dead code found.** `_pause_menu` is still called from `_menu_results` (`cli.py:2271`) and
   elsewhere; no unused imports (ruff clean); `render_attempt`'s fallback badge tuple
   (`_BADGE.get(..., ("· ?", ". ?", "dim"))`, `report_card.py:148-150`) is defensive for a
   theoretically-impossible fifth `Verdict` value — harmless, matches the existing defensive style used
   elsewhere in the file (e.g. `hits[:5]` "?" fallback for missing attack_id).

## Verification run

- `python -m pytest -q` → `618 passed, 1 skipped` (matches expected count).
- `python -m ruff check src tests` → `All checks passed!`

No blocking issues found. All 8 plan-review points are independently confirmed against the actual code
(not just re-stated from the plan), and the full test suite / lint pass green.

STATUS: PASS
