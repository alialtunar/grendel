# Phase 5 Test Report

**Date:** 2026-06-30

## Test Runs

The full suite was run **three times** to check for flakiness. All runs passed with identical results.

| Run | Result | Duration |
|-----|--------|----------|
| 1   | 175 passed | 9.23s |
| 2   | 175 passed | 9.52s |
| 3   | 175 passed | 11.80s |

No flakes detected. All TUI/async worker tests were deterministic across all runs.

## Lint & Format

- `ruff check .` — All checks passed (clean)
- `ruff format --check .` — 46 files already formatted (clean)

## Phase-5 Specific Tests (38 tests)

All 38 new Phase-5 tests passed in all runs:

### test_scoreboard_state.py (14 tests)
- `test_state_imports_no_textual` — PASSED (state.py confirmed to have no textual import)
- `test_header_counts_and_overall_asr` — PASSED
- `test_category_rows_counts_asr_and_flag` — PASSED
- `test_total_from_plan_with_unrun_attack` — PASSED
- `test_elapsed_from_timestamps` — PASSED
- `test_elapsed_running_uses_now` — PASSED
- `test_elapsed_zero_when_no_starts` — PASSED
- `test_failure_join_and_sort_order` — PASSED
- `test_filter_by_category_verdict_severity` — PASSED
- `test_select_next_clamps_both_ends` — PASSED
- `test_select_next_empty_is_minus_one` — PASSED
- `test_toggle_explain` — PASSED
- `test_repro_for_exact_string` — PASSED
- `test_repro_for_none_and_missing_response` — PASSED

### test_runner_hook.py (3 tests)
- `test_hook_fires_per_attempt_after_persistence` — PASSED
- `test_raising_hook_does_not_abort_run` — PASSED
- `test_default_none_is_inert` — PASSED

### test_tui_app.py (19 tests)
All Textual pilot tests passed deterministically:
- `test_static_render_smoke` — PASSED
- `test_live_updates_via_fake_engine` — PASSED
- `test_select_keys_move_and_clamp` — PASSED
- `test_verdict_filter_key` — PASSED
- `test_category_filter_key` — PASSED
- `test_severity_filter_key` — PASSED
- `test_explain_key_toggles_detail` — PASSED
- `test_copy_repro_key` — PASSED
- `test_copy_repro_noop_when_no_failure` — PASSED
- `test_rerun_key_reinvokes_engine_for_selected` — PASSED
- `test_quit_key_exits` — PASSED
- `test_keys_do_not_crash_on_empty_failures[j/k/f/c/s/e/y/r]` (8 parametrized) — PASSED

### test_cli_tui.py (2 tests)
- `test_tui_dry_run_exits_2` — PASSED
- `test_tui_runs_engine_persists_and_summarizes` — PASSED

## Confirmations

- `state.py` has no textual import: CONFIRMED
- Runner `on_attempt` hook tests: all 3 PASSED
- TUI pilot tests (live update + all keybindings): all 19 PASSED deterministically
- `--tui` CLI tests: both PASSED

STATUS: PASS
