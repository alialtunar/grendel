# Phase 21 review

Scope: `src/grendel/targets/model_list.py`, `src/grendel/live.py`, `src/grendel/cli.py`
(`_resolve_model_choices`, `_prompt_model`, `_menu_run`), `src/grendel/targets/providers.py`,
`pyproject.toml`, `tests/test_model_list.py`, `tests/test_live_dashboard.py`.

## Findings

1. **M1 — `fetch_models` (src/grendel/targets/model_list.py:18-53).** Conditional auth headers
   confirmed: `Authorization`/`x-api-key` are only set `if api_key:` (lines 30-35); ollama gets no
   auth header; a missing key still issues the request and a 401/403 degrades to `[]` via the
   blanket `except Exception` (line 52). `custom` / no `base_url` short-circuits before any request
   (line 23). `anthropic` merges `preset.default_headers` (carries `anthropic-version`) with
   `x-api-key` (line 29). De-dup with order preserved via the `val not in out` check (line 49).
   Matches plan step M1.1 exactly.

2. **Plan-review point (1) conditional headers** — verified, no `None` ever passed as a header
   value; `tests/test_model_list.py::test_openai_missing_key_sends_no_auth_and_401_gives_empty` and
   `test_anthropic_missing_key_no_header_and_403_gives_empty` assert this directly (headers absent,
   `[]` returned, no `TypeError`).

3. **Plan-review point (2) live ASR excludes controls** — `live.py:38-41` only bumps `hits`/
   `defended` `and not control`; `records.py:102` (`_asr`) does the same exclusion (`not a.is_control`
   over `PASS`/`FAIL`). Formulas are algebraically identical (`hits/(hits+defended)`, 0 when
   unscored). `test_controls_excluded_from_asr` locks this in.

4. **Plan-review point (3) total==0 guard** — `LiveAttackRun.__init__` guards
   `self.total = max(int(total), 1)` (live.py:26); `_render` re-guards with `max(self.total, 1)`
   (redundant but harmless, defense-in-depth as the plan intended). In practice `_menu_run` never
   calls `make_live_run` with 0 anyway (the `if not selected:` early-return at cli.py:2239-2242
   precedes it), so this is belt-and-suspenders as designed. `test_total_zero_guard_no_zero_division`
   confirms no `ZeroDivisionError`.

5. **Plan-review point (4) anthropic missing-key test** — present
   (`test_anthropic_missing_key_no_header_and_403_gives_empty`), asserts no `x-api-key` header and
   `[]` on 403.

6. **Plan-review point (5) thread-safety comment** — `live.py:48-50` states state mutation +
   `_render()` happen together on the calling (asyncio-loop) thread before the internally-locked
   `Live.update()`, and that rich's background refresh thread never itself calls `_render()`. This
   matches rich's actual implementation (`Live.update()`/`Live.refresh()` take `self._lock`; the
   auto-refresh thread redraws the already-set `self.renderable`, it does not invoke the renderable
   factory). Correct and consistent with how `on_attempt` is invoked by `runner.py:144-148` (single
   asyncio-loop thread, not a real OS thread pool).

7. **Never raises / never blocks tests+pipes.** `fetch_models` only wraps genuine failure modes and
   is exercised offline via `httpx.MockTransport` in tests. It is only reachable from
   `_prompt_model` inside `if sys.stdin.isatty():` (cli.py:1284), so CliRunner-driven tests (non-TTY
   stdin) never reach it — confirmed no direct `fetch_models`/`_resolve_model_choices` calls in
   `tests/test_cli_run_flow.py`. `make_live_run` gates on `sys.stdout.isatty()` first (live.py:110)
   before even trying `import rich`, so it is `None` in the whole test suite and in `_menu_run`'s
   off-TTY branch, which is byte-identical to the pre-existing `_run_progress` fallback (cli.py:
   2275-2284, unchanged).

8. **Dashboard cannot crash or hang a real run.** `on_attempt` wraps its entire body in
   `try/except Exception: pass` (live.py:33-54) in addition to `Runner`'s own
   `except Exception: log.exception(...)` guard around the callback (runner.py:144-148) — two
   independent safety nets. `Console(legacy_windows=False)` (live.py:94) avoids the win32-API path
   that crashes on a cp1254 console; the ASCII-degrade glyph table (live.py:14-19, driven by
   `stream_supports_unicode`) is a second line of defense, and `install_console_fallback()`
   (banner.py:49-62, called at cli.py:133 before any menu code runs) is a third — even a genuinely
   unencodable character written to `sys.stdout` degrades to `?`/ASCII instead of raising. This is a
   solid three-layer defense against the Windows cp1254 crash the user hit previously.

9. **providers.py static fallback lists** — openai (10 ids), anthropic (7 ids), ollama (6 ids) all
   satisfy the `len >= 5` test assertion; openrouter has 7 popular namespaced ids (no length
   assertion required by the plan, consistent with "a handful"). `openai-compatible` correctly
   stays empty (`base_url=None`, no `models=`), so `_resolve_model_choices` returns `([], "model")`
   for it and `_prompt_model` falls through to the typed prompt — matches the "type-your-own always
   works" non-goal.

10. **Full suite green.** `python -m pytest -q` → 598 passed, 1 skipped (matches expectation).
    `python -m ruff check src tests` → all checks passed.

## Minor, non-blocking nits

- `cli.py:1272` (`_resolve_model_choices`) does `static = list(preset.models)` inline instead of
  reusing the existing `_preset_models(provider, cfg)` helper (cli.py:1248), which does the same
  thing plus its own `ConfigError` handling (moot here since `preset` is already resolved). Not a
  bug — `_preset_models` is still exercised directly by `tests/test_cli_run_flow.py` — just a small
  duplication opportunity for a future pass.
- `live.py` re-derives `max(self.total, 1)` inside `_render` even though `__init__` already
  normalizes `self.total` to `>= 1`; harmless double-guard, not worth flagging as a defect given the
  plan explicitly called for the guard "so the bar math can't ZeroDivisionError if the class is
  reused with total == 0 elsewhere."

No blocking issues found. All 5 "Plan review — addressed" points are implemented and covered by
tests exactly as specified; M1 and M2 both match spec.md's goals (live-fetch-with-static-fallback
model picker, rich dashboard degrading cleanly off-TTY/no-rich); no network leakage into non-TTY
paths; no crash/hang risk introduced into the dashboard.

STATUS: PASS
