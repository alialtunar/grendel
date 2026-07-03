# Phase 23 (post-review bug-fix pass) — review

Scope: independent review of 6 targeted bug fixes applied to
`src/grendel/cli.py`, `src/grendel/live.py`, `src/grendel/targets/model_list.py`
after the phase 20-23 code review. Note: the repo has an in-progress, uncommitted
package rename (`gauntlet` -> `grendel`, `src/grendel/` is untracked in git status);
this review only covers the 6 listed fixes, not the rename itself.

## Findings

1. **Model-picker cancel (cli.py:2192-2194, `_menu_run`)** — Correct.
   `if not model: return cfg` was added right after `model = _prompt_model(provider, cfg)`,
   mirroring the existing `if provider is None: return cfg` convention. Confirmed
   `build_cli_target_config` (config.py:303-317) only treats `model=None` as "not given";
   an empty string `""` would previously have been accepted and built a live target,
   so the guard closes a real billable-junk-run gap.
   Checked `_prompt_model` (cli.py:1244-1270): the only way it returns `""` is an explicit
   Esc/cancel on the questionary picker or a blank `typer.prompt` answer when there is no
   preset default (`default` falsy). When a real preset default exists, `typer.prompt(...,
   default=default)` returns that default on Enter, never `""` — so the fix cannot swallow a
   legitimate empty-default selection; there's no such thing as a legitimate "" model in this
   codebase. Test `test_run_flow_empty_model_cancels_run` (tests/test_cli_run_flow.py:107-115)
   exercises exactly this path and asserts the run never reaches the fire-confirm.

2. **`_layout` short-terminal overflow (live.py:23-37, 150-152)** — Correct.
   `_CHROME=6`, `_LOGO_LINES_U=7`, `_LOGO_LINES_A=6`. Verified against the actual banner art
   (banner.py:65-80): unicode `_LOGO` has 6 block-art rows, ascii `_LOGO_ASCII` has 5 — each
   plus a 1-row spacer appended in `live.py:_render` (rows.append(Text(""))) after the logo,
   giving 7 and 6 respectively, exactly matching the constants.
   `show_logo = width >= _MIN_LOGO_WIDTH and height >= _CHROME + logo_h + 3` and
   `visible = max(1, height - _CHROME - logo_part)`.
   - At the exact boundary `height == _CHROME + logo_h + 3`: show_logo is True (>=), so
     `visible = height - _CHROME - logo_h = 3`, and total rendered = logo_h + _CHROME + visible
     == height exactly — fits.
   - Just below the boundary: show_logo drops to False, logo_part=0,
     `visible = max(1, height - _CHROME)`. For any `height >= _CHROME` this fits within height.
   - Only for a pathological `height < _CHROME` (terminal under 6 rows tall) does the `max(1, …)`
     floor push the panel (chrome=6 + visible=1 = 7) past `height`. This is a pre-existing
     structural limit — `_CHROME` (borders/header/footer) is a hard minimum for any layout, and
     `__enter__` falls back to 24x80 on any console-size read error, so this floor case is not
     reachable via the normal code path. Not a regression from this fix (which strictly improves
     the prior floor-of-3 behavior) — noted as a pre-existing informational edge case, not blocking.
   - `__enter__` (live.py:150-152) now passes `unicode=self.unicode` — confirmed `self.unicode`
     is set in `__init__` (live.py:46) and used consistently elsewhere (`_render`, `_panel`).
   - `test_layout_fits_terminal_height` (tests/test_live_dashboard.py:107-119) covers the wide,
     narrow, short, and ascii cases; all pass.

3. **`_list_run_records` perf (cli.py:2261-2287)** — Correct.
   Field names/values used (`target_name`, `provider`, `model`, `status`, `attempts`,
   `is_control`, `verdict` in `("pass","fail")`) match `RunRecord`/`AttemptRecord` (records.py:
   14-18 `Verdict` enum values are exactly `"pass"/"fail"/"error"/"skipped"`; 122-132 field
   names; `to_json` at 254-255 is a plain `model_dump_json()`, so enums serialize to their
   `.value` strings — `raw.get("status")` yields the plain string, used only for display).
   ASR computation (`hits/len(scored)` over non-control pass/fail attempts) matches
   `records._asr`. The whole per-file block is wrapped in a bare `except Exception`
   (cli.py:2284) so any `KeyError`/`TypeError`/`AttributeError`/`JSONDecodeError` on a partial
   or malformed record falls back to `p.name` as the label — cannot crash the listing.

4. **`_run_progress` control exclusion (cli.py:2141-2146)** — Correct.
   `if attempt.verdict.name == "FAIL" and not getattr(attempt, "is_control", False)` matches
   `records._asr`'s exclusion of controls and `LiveAttackRun`'s own hit-counting logic
   (live.py:58-59: `if name == "FAIL" and not control`). Same semantics, consistent across the
   TTY dashboard and the non-rich progress line.

5. **`fetch_models` timeout (model_list.py:36-43)** — Correct.
   `c.get(url, headers=headers, timeout=timeout)` passes the timeout explicitly on the call,
   so an injected `client` (which may have no default timeout, as in tests) still degrades
   gracefully instead of hanging. `owns`/`finally: c.close()` logic is unaffected and correct.

6. No other callers of `_layout`, `_list_run_records`, or `_run_progress` exist in
   `src/grendel/` — each has exactly one call site (verified via grep), so none of the fixes
   have blast radius beyond their own call site.

## Verification performed
- Read all 5 touched functions plus their call sites and the data models they depend on
  (`config.build_cli_target_config`, `records.RunRecord`/`AttemptRecord`/`Verdict`,
  `banner._LOGO`/`_LOGO_ASCII`).
- `python -m pytest -q` → 605 passed, 1 skipped.
- `python -m ruff check src tests` → all checks passed.
- Confirmed targeted regression tests exist and cover each fix:
  `test_run_flow_empty_model_cancels_run`, `test_layout_fits_terminal_height`,
  `_run_progress` control-exclusion test (tests/test_cli_run_flow.py:~95-104),
  and `test_model_list.py` timeout coverage.

## Non-blocking observations
- Item 2's pathological `height < _CHROME` case can still overflow by construction; this is a
  structural floor rather than a bug introduced by the fix, and is unreachable via the normal
  `console.size` path (exceptions fall back to 24x80). No action required.

STATUS: PASS
