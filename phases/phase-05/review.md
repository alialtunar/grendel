# Phase 5 Review — TUI Scoreboard

## Files Inspected
- `src/gauntlet/tui/state.py`
- `src/gauntlet/tui/app.py`
- `src/gauntlet/tui/__init__.py`
- `src/gauntlet/tui/app.tcss`
- `src/gauntlet/runner.py`
- `src/gauntlet/cli.py`
- `tests/fakes.py`
- `tests/test_scoreboard_state.py`
- `tests/test_runner_hook.py`
- `tests/test_tui_app.py`
- `tests/test_cli_tui.py`

## Gate Results
- `ruff check .` — zero findings
- `ruff format --check .` — clean (46 files already formatted)
- `pytest -q` — **175 passed** (prior 137 + 38 new phase-5 tests)

---

## Findings

1. **Pure/Textual separation (Fix #10): PASS.** `state.py` contains zero `textual` imports. The subprocess-based machine guard in `test_state_imports_no_textual` asserts `"textual" not in sys.modules` in a fresh interpreter. Verified manually: `import gauntlet.tui.state` does not pull Textual into `sys.modules`. The `__init__.py` package marker re-exports only from `state.py`, never from `app.py`, so importing the package also stays Textual-free.

2. **Severity ordering (Fix #2): PASS.** `_SEVERITY_RANK = {LOW:0, MEDIUM:1, HIGH:2, CRITICAL:3}` is defined at module level in `state.py`. `apply_filter` uses `_rank(item.severity) >= _rank(filter.severity)` for the "this severity or worse" predicate. `_failure_sort_key` sorts by `-_rank(severity)` (descending). Tests assert the exact order (alpha/a1 critical, beta/b1 high, beta/b2 medium) and that severity filtering at `HIGH` correctly drops the MEDIUM failure.

3. **CategoryRow.total from the plan (Fix #5): PASS.** `build_scoreboard` computes `plan_by_cat` by iterating `attacks` (the input plan list) before touching `record.by_category()`. `CategoryRow.total` is set from `plan_by_cat.get(cat, 0)`, not from executed counts. `test_total_from_plan_with_unrun_attack` confirms `alpha.total == 3` and `alpha.done == 1` when only one of three planned attacks has run.

4. **on_attempt hook (Fix additive runner change): PASS.** Hook is keyword-only, defaults to `None`, stored as `self._on_attempt`. In `_record_attempt`, the callback fires AFTER the `async with self._write_lock` block (outside the lock), guarded by `if self._on_attempt is not None` and wrapped in `try/except Exception` that logs and continues. `test_hook_fires_per_attempt_after_persistence` verifies the on-disk JSON already contains the attempt when the callback fires. `test_raising_hook_does_not_abort_run` verifies a raising callback leaves the run `COMPLETED`. Prior 137 tests unaffected.

5. **Live bridge — post_message not call_from_thread (Fix #3): PASS.** `_post_attempt` calls `self.post_message(AttemptRecorded(attempt))` directly. The comment in both the docstring and the method explicitly explains why `call_from_thread` would deadlock (engine runs on the same event loop as the app).

6. **AttemptRecorded handler is a re-render trigger only (Fix #4): PASS.** `on_attempt_recorded` calls `self._rebuild()` (which re-runs `build_scoreboard` over the already-mutated `self.record`) and `update_widgets()`. It never appends to `record.attempts`. `FakeEngine` in the tests mutates `record.attempts` before calling `on_attempt`, mirroring the runner's actual behavior.

7. **Async worker thread=False (Fix #9): PASS.** `self.run_worker(self._run_engine(), exclusive=False)` passes a coroutine to `run_worker`. Verified against the Textual signature: `run_worker` defaults to `thread=False`, so a coroutine input creates an async worker on the app's own event loop. No blocking.

8. **Deterministic worker drain in pilot tests (Fix #6): PASS.** `FakeEngine` sets `self.done = asyncio.Event()` and calls `self.done.set()` after emitting all scripted attempts. Live-update tests do `await asyncio.wait_for(engine.done.wait(), timeout=5)` before asserting `app.state.done`. No bare `pilot.pause()` used for live synchronization.

9. **Rerun operates on exactly the highlighted single failure (Fix #1/#8): PASS.** `action_rerun_failures` reads `self.state.selected_failure` (the one highlighted item), returns early if `None`, drops only that `attack_id` from `record.attempts`, then re-invokes `_run_engine()` with the full original plan. The runner's resume skip-set re-runs only the dropped attack. `test_rerun_key_reinvokes_engine_for_selected` asserts `engine.emitted == ["alpha/a1"]` exactly.

10. **copy_repro via monkeypatchable _clipboard_write: PASS.** `action_copy_repro` calls `self._clipboard_write(text)` which is a method on the instance (not a module function), making it trivially monkeypatchable. `test_copy_repro_key` patches it as `app._clipboard_write = lambda text: captured.append(text)` and asserts both `app.last_repro` is set and the captured text matches.

11. **--tui --dry-run exit 2 (Fix plan adherence): PASS.** `cli.py` checks `if tui and dry_run:` before any network/adapter work and calls `raise typer.Exit(code=2)`. `test_tui_dry_run_exits_2` asserts `result.exit_code == 2` and `"incompatible" in result.output`.

12. **CLI --tui fake app strategy (Fix #7): PASS.** `test_cli_tui.py` defines `FakeApp` whose `.run()` calls `asyncio.run(self.engine(lambda attempt: None))`. This exercises the real `Runner` (adapter sends, record persists, adapter closes in `finally`). The test asserts `adapter.closed is True`, `len(adapter.requests) == 2`, and the persisted JSON has `status == COMPLETED` with both attacks as `PASS`. This is not a no-op monkeypatch.

13. **record_path cached before .run() (Fix #12): PASS.** `record_path = Runner(adapter, cfg.run).run_path(record)` is computed before the `engine(...)` call in the TUI branch. `run_path` only reads `options.output_dir` so the ephemeral Runner is harmless.

14. **Lazy Textual import in cli.py: PASS.** `from .tui.app import ScoreboardApp` is inside the `if tui:` branch of the `run()` function. The import happens at call time, so the monkeypatch in `test_cli_tui.py` (`monkeypatch.setattr(appmod, "ScoreboardApp", FakeApp)`) correctly intercepts the lazy `from .tui.app import ScoreboardApp` because `from X import Y` resolves to `sys.modules['X'].Y` at execution time.

15. **fakes.py make_attack extended (Fix #11): PASS.** `make_attack` now accepts `severity`, `owasp`, `atlas` keyword overrides (defaulting to `"high"`, `"LLM01"`, `"AML.T0051"`). Tests use these overrides to build the critical/high/medium/low attacks needed for `FailureItem` join, `flag_severity`, and severity-filter assertions.

16. **Edge cases:**
    - Zero attacks: `state.progress` guards with `if self.total else 0.0`. `ProgressBar.update(total=state.total or None, ...)` passes `None` when total is 0 (Textual handles this).
    - Empty failures: `_clamp_index` returns `-1` when `n <= 0`. `selected_failure` property guards with `0 <= self.selected_index`. All keybindings tested against empty failures in `test_keys_do_not_crash_on_empty_failures`.
    - `_elapsed_s` with no started_at timestamps: returns 0.0 (tested in `test_elapsed_zero_when_no_starts`).

17. **No issues with `_rebuild` vs `_adopt` separation:** `_rebuild` is used for live record mutations (preserves view inputs `_filter`/`_selected_index`/`_explain_visible`). `_adopt` is used for pure state transitions (updates all three view inputs from the new state). Both patterns call `update_widgets()`.

18. **Minor observation (non-blocking):** `action_rerun_failures` drops attempts by `attack_id` (all attempts for that attack), not by `attempt_id` (the specific attempt). This is intentional — the runner's resume skip-set also works by `attack_id`. Since the runner deduplicates by `attack_id` in `_record_attempt`, there is at most one attempt per attack at any time. No bug here.

STATUS: PASS
