# Phase 15 review — control-center TUI

Scope checked: `src/grendel/tui/app.py` (scoreboard mixin refactor), `src/grendel/tui/doctor.py`
(new), `src/grendel/tui/control.py` (new), `src/grendel/config.py` (`build_cli_target_config`,
`save_config`), `src/grendel/cli.py` (`_cli_target` wrapper, new `tui` command), and the new/extended
tests (`test_tui_app.py` unchanged, `test_tui_doctor.py`, `test_config_save.py`, `test_tui_control.py`).

## Findings

1. **`run --tui` / `test_tui_app.py` untouched — verified.** `tests/test_tui_app.py` is byte-identical
   in intent to the pre-phase-11..14 suite and passes standalone (22/22). The `_ScoreboardUI` mixin is
   composed into `ScoreboardApp(_ScoreboardUI, App)` which still composes widgets on its own default
   screen, so `app.query_one`, `app.state`, `app.record` (both plain instance attributes on the mixin,
   not forwarding properties — correct, since `ScoreboardApp` *is* the `_ScoreboardUI` instance),
   `app._clipboard_write`, and `app.last_repro` all resolve exactly as before. `BINDINGS` is set on the
   concrete class from a module-level list (`_SCOREBOARD_BINDINGS`), matching the documented Textual
   constraint (bindings aren't picked up from a plain mixin). No regression found.

2. **`ScoreboardScreen` reuse for the control center is correct and isolated.** `ScoreboardScreen(_ScoreboardUI,
   Screen)` composes the same widgets on a `Screen`; its `escape` binding pops back to the menu. Note
   `last_repro`/`state`/`record` live on the *Screen* instance in this path (not forwarded to
   `ControlApp`), which is fine — nothing in `test_tui_control.py` or the spec requires the control
   app to expose them, and `_clipboard_write` correctly still calls `self.app.copy_to_clipboard`
   (Screen's `self.app` resolves to the owning `ControlApp`).

3. **`build_cli_target_config` extraction is behaviour-preserving.** All five usage-error branches
   (`--target`+flags, >1 group, unpaired provider/model, malformed `--header`, >1 mcp source) raise
   `ConfigError` from the pure helper and are exercised in `test_config_save.py`
   (`test_build_cli_target_usage_errors`, parametrized). `cli._cli_target` wraps it, translating
   `ConfigError` → `_die` (`typer.Exit(2)`), preserving the exit-2 contract; the full CLI suite
   (`test_cli_flag_target.py` et al.) is green. Good separation: the TUI's `RunSetupScreen` reuses the
   same pure helper and catches `ConfigError` inline instead of exiting.

4. **`save_config` round-trips correctly**, including the harder "never-loaded, default-path, relative
   `pack_dir`" case (`test_never_loaded_default_path_save_with_relative_pack_dir`), asserting the saved
   relative path resolves to an absolute path anchored at the file's directory after reload. Both
   round-trip tests pass.

5. **`doctor_report` never leaks secret values.** Confirmed by inspection (`env.get(name)` only
   converted to a `bool`) and by the dedicated test injecting a fake API-key value and asserting it
   never appears in any rendered section. Presence-only Env-keys section is correct.

6. **Control screens are thin drivers, wrapping existing engines, matching the spec:**
   - `RunSetupScreen.action_start` builds the same `Runner(adapter, cfg.run, on_attempt=...)` engine
     closure as `cli.run --tui`, and pushes `ScoreboardScreen` — exercised with a fake engine/adapter in
     `test_run_setup_launches_scoreboard`.
   - `PacksScreen` uses `list_packs`/`corpus.import_corpus` unchanged; import test against the bundled
     garak fixture asserts `imported 5`.
   - `ProxyScreen.action_serve` builds a real `ProxySession` + calls `proxy.make_server` then starts
     `httpd.serve_forever` on a background thread, `action_stop` calls `proxy.stop_server` (which itself
     closes the session's httpx client on its own loop — verified in `proxy.py`, no client leak in the
     real path). The pilot test monkeypatches `proxy.make_server`/`stop_server` — no real socket bind in
     the suite, matching the offline-testing requirement.
   - Minor, non-blocking deviation from the plan's wording: `ProxyScreen.action_serve` starts the serve
     thread with a raw `threading.Thread(..., daemon=True)` rather than a Textual `self.run_worker(...,
     thread=True)` call. Plan/spec explicitly said "in a Textual worker thread." Functionally
     equivalent here (daemon thread, never blocks the UI loop, monkeypatched in tests), but it bypasses
     Textual's worker lifecycle/cancellation (no entry in `app.workers`, can't be cancelled via
     `Screen.workers.cancel_all()` on screen pop, no worker-state message). Not a correctness bug given
     current usage, but worth aligning with the plan's stated mechanism if this screen sees more work.

7. **No behaviour change to scoring/records/runner/proxy/catalog/config-schema.** `grendel` with no
   args still exits 2 with the usage/help panel (verified via `CliRunner`). No new runtime dependency
   (Textual only).

8. **Full gate:** `pytest` → 532 passed, 1 skipped (exact expected count). `ruff check .` clean. `ruff
   format --check .` clean (101 files already formatted).

9. **Housekeeping (non-blocking):** a stray `out.txt` debug artifact (CLI error output from manual
   testing) sits untracked at the repo root; not part of the phase-15 deliverable, safe to delete
   before commit but not a code-review blocker. `PROGRESS.md` has not yet been appended with the
   phase-15 line — expected, since that update is the closing chore commit that follows this review.

## Verdict

No blocking defects found. The scoreboard refactor is behaviour-preserving (confirmed by running
`test_tui_app.py` in isolation and the full suite), the pure extractions
(`build_cli_target_config`/`save_config`/`doctor_report`) match the plan's contracts and are covered by
tests including the harder edge cases (five usage errors, default-path relative-pack-dir round-trip,
no-secret-leak), and every new screen is a thin, offline-testable driver over an existing engine with
no real network/socket/serve-loop in the suite.

STATUS: PASS
