# Phase 20 review

Scope: guided run flow — model suggestions (`ProviderPreset.models`), TTY-aware `_prompt_model`,
unbiased `_prompt_provider` + inline "+ add a custom agent", `_prompt_provider_letter`
(`allow_add_custom`), `_prompt_custom_agent` wrapper, `_menu_run` rewiring, packs/dry-run hint
lines, and `tests/test_cli_run_flow.py`.

## Verification performed
- Read `phases/phase-20/spec.md` and `phases/phase-20/plan.md` (incl. the 9-point "Plan review —
  addressed" section).
- Read `src/grendel/targets/providers.py` (`ProviderPreset.models`, `PRESETS` population).
- Read `src/grendel/cli.py`: `_preset_models` (1245), `_prompt_model` (1256), `_ADD_CUSTOM`
  sentinel (1285), `_prompt_provider_letter` (1288), `_prompt_provider` (1310),
  `_prompt_custom_agent_letter/_questionary/_prompt_custom_agent` (1370-1466), `_targets_letter`
  (1469, the *other* `_prompt_provider_letter` caller), `_menu_run` (2139).
- Read `tests/test_cli_run_flow.py` and the relevant scripts in `tests/test_cli_home.py`.
- Ran `python -m pytest -q` → **580 passed, 1 skipped** (matches plan expectation).
- Ran `python -m ruff check src tests` → **All checks passed**.

## Findings

1. **`providers.py` (models field)** — `ProviderPreset.models: list[str] = []` added; hosted
   presets populated exactly per plan step 1 (openai/anthropic/openrouter/ollama), openai-compatible
   left empty, `default_model` untouched. Matches plan. No issue.

2. **`_preset_models` / `_prompt_model`** — mirrors `_preset_default_model`'s `ConfigError` → `[]`
   guard. `_prompt_model` is TTY-aware: non-TTY unchanged typed prompt (default = preset
   `default_model`, hint text explicitly says "any model works" when no default — satisfies
   "no fixed list" reassurance, addressed point 1's fold-in). TTY + questionary + suggestions →
   `questionary.select` with a `✎ type another model…` escape routing to free `questionary.text`;
   TTY without suggestions falls through to the typed prompt (openai-compatible/custom case
   correctly has no `models`). Cancel (`sel is None`) returns `""`, consistent with "caller already
   errors clearly" per plan step 3. No issue.

3. **`_menu_run` now calls `_prompt_model`** (cli.py:2164) — confirms addressed point 1; the old
   inline dead-end prompt is gone.

4. **`_ADD_CUSTOM` sentinel + `_prompt_provider_letter(cfg, allow_add_custom=False)`** — default
   path (used by `_targets_letter` at cli.py:1484, no flag) preserves the numeric `openai`-indexed
   default and prints no `[0]` line; `allow_add_custom=True` path prints `[0] add a custom agent…`
   and returns `_ADD_CUSTOM` for raw `"0"` before the permissive `return raw` fallback. Verified by
   `test_provider_letter_add_custom_gated_by_flag` (asserts both branches) and confirmed by reading
   the code — the flag genuinely gates the sentinel, not just the printed line. Addressed points
   2/3/7/8 satisfied.

5. **`_prompt_provider(cfg) -> str | None`** — TTY path has no `default=` passed to
   `questionary.select` (no preselected provider, per spec capability 2); appends a `Separator()` +
   the add-custom `Choice`; cancel naturally returns `None` since `questionary.select(...).ask()`
   returns `None` on Ctrl-C/Esc. Non-TTY delegates to `_prompt_provider_letter(cfg,
   allow_add_custom=True)`. Matches plan step 1 of milestone 2.

6. **`_prompt_custom_agent(cfg)` wrapper** — TTY-aware name prompt (questionary if importable and
   stdin is a TTY, else `typer.prompt`), delegates to the letter/questionary custom-agent flows,
   and uses `name and name in new_cfg.targets` as the success signal, returning `(new_cfg, name)` on
   success and `(cfg, None)` otherwise (blank name, decline, or `ConfigError` inside the delegate,
   which itself returns the original `cfg` unchanged). This matches addressed points 4/5 exactly.
   Blank-name edge case: `name` is falsy → skips calling the delegate at all (`new_cfg = cfg`) and
   returns `(cfg, None)` — no wasted prompt, correct.

7. **`_menu_run` persist-vs-throwaway** (cli.py:2152-2171) — the `_ADD_CUSTOM` branch does
   `cfg, run_cfg, target = new_cfg, new_cfg, name` (persists into the returned `cfg`, the *outer*
   variable that eventually flows back to the home-menu loop and can be saved); the hosted ad-hoc
   branch keeps `run_cfg = cfg.with_cli_target(...)` as a throwaway copy that is never assigned back
   to `cfg`, and the function still `return cfg` at every exit path — the original session cfg,
   never `run_cfg`. This is the correct, intentional distinction and matches the docstring (updated,
   addressed point 6) and `test_run_flow_add_custom_agent_inline` /
   `test_home_menu_adhoc_run_does_not_leak_cli_target` (the latter pre-existing, still green).

8. **Packs/dry-run hint lines** (cli.py:2172, 2175) — plain `typer.echo`, not prompts; the actual
   `typer.prompt`/`typer.confirm` calls are unchanged, so existing input scripts (e.g.
   `test_cli_home.py:159,168,187,202,215`) still consume the same number of input lines. Confirmed
   by the full suite passing unmodified for those pre-existing scripts, and by
   `test_run_flow_explains_packs_and_dry_run` asserting the new substrings.

9. **Anti-hardcode (models as suggestions, not a closed list)** — verified: TTY path always offers
   `✎ type another model…` → free `questionary.text`; non-TTY path is a plain `typer.prompt` that
   accepts arbitrary text regardless of `models`; `openai-compatible`/custom providers correctly
   have `models=[]]` and fall through to the typed prompt on TTY too. No validation anywhere
   restricts the entered model to the suggestion list. Matches spec non-goal explicitly.

10. **No dead code / unused sentinel found.** `_TYPE_ANOTHER` and `_ADD_CUSTOM` are both consumed
    on both TTY and non-TTY paths. `_ADHOC` (pre-existing, from phase 19) and `_ADD_CUSTOM` are
    distinct sentinel strings (`"__adhoc__"` vs `"__add_custom__"`) — no collision risk if ever
    compared loosely.

11. **Regression check** — `_targets_letter`'s hosted-model add-target path (cli.py:1483-1493) still
    calls `_prompt_provider_letter(cfg)` (no flag) and `_prompt_model(provider, cfg)`; both are
    exercised by `test_home_menu_add_target` (test_cli_home.py:95) which remains green, confirming
    the shared-helper change didn't affect the non-run caller.

12. Full test suite: **580 passed, 1 skipped**, `ruff check src tests`: **All checks passed** — both
    match the plan's checkpoint expectations exactly.

No blocking issues found. All 9 plan-review points are implemented as described, the
persist-vs-throwaway distinction is correct, the model list is genuinely open-ended on every path,
and no regressions were found in the pre-existing menu-run/add-target/proxy tests.

- STATUS: PASS

---

# Post-phase-20 UX refinement review (menu Run: drop packs/dry-run prompts, single fire confirm, pause-before-redraw)

Scope: `_menu_run` in `src/grendel/cli.py` (2160-2231) simplified to always-all-packs +
always-real-run + one `fire N attack(s) vs <target> (...)?` confirm; new `_missing_run_key`
(2144-2157) and `_pause_menu` (2139-2141) helpers; `tests/test_cli_home.py` and
`tests/test_cli_run_flow.py` updated accordingly. The `grendel run` subcommand (with its own
`--pack`/`--dry-run` flags, lines ~375-477) is untouched.

## Verification performed
- Read `src/grendel/cli.py` around `_menu_run`, `_missing_run_key`, `_pause_menu`,
  `_home_letter`/`_home_questionary`/`_clear_and_logo`.
- Read `resolve_target_info`/`resolve_provider`/`PRESETS`/`build_cli_target_config`/
  `TargetConfig`/`with_cli_target` in `src/grendel/targets/__init__.py`,
  `src/grendel/targets/providers.py`, `src/grendel/config.py` to trace how
  `_missing_run_key` resolves an API-key env for both a configured target and the throwaway
  `_CLI_TARGET_NAME` run_cfg.
- Confirmed `click.termui.pause`'s actual source: it returns immediately when
  `not isatty(sys.stdin) or not isatty(sys.stdout)` — genuinely a no-op under `CliRunner`
  (non-TTY), so it cannot hang tests or consume scripted input lines.
- Grepped for leftover `dry-run`/`packs (comma`/`plan:` references in `cli.py` — none remain
  in the menu path; the `run` subcommand's own `--dry-run`/`plan:` (lines 375, 471-477) is a
  separate, unaffected code path.
- Read `tests/test_cli_home.py` (run-menu tests) and `tests/test_cli_run_flow.py` (no
  packs/dry-run-prompt test, add-custom-inline test) — scripts match the new single-confirm
  flow, no wasted lines.
- Ran `python -m pytest -q` → **580 passed, 1 skipped**.
- Ran `python -m ruff check src tests` → **All checks passed**.

## Findings

1. **`_pause_menu` no-op on non-TTY** — confirmed via `click.termui.pause` source: it checks
   `isatty(sys.stdin)`/`isatty(sys.stdout)` and returns immediately if either is false, before
   touching `echo`/`getchar`. Under `CliRunner` (pytest) both are non-TTY, so `_pause_menu()`
   is a true no-op — it cannot hang the suite or eat an extra scripted input line. No issue.

2. **`_missing_run_key` correctness** —
   - Configured target: `cfg.targets.get(target)` returns the real `TargetConfig`, so an
     explicit `api_key_env` override on that target is honored before falling back to
     `preset.api_key_env` (cli.py:2154). Correct.
   - Ad-hoc `_CLI_TARGET_NAME`: `build_cli_target_config(provider=..., model=...)` (cli.py:2187)
     never passes `api_key_env`, so `tc.api_key_env` is `None` and the check correctly falls
     back to the preset's env var (e.g. `OPENAI_API_KEY`). Correct.
   - Keyless providers: `ollama` has `requires_key=False` (derived from `api_style` not in
     `_AUTH_REQUIRING_STYLES`) → short-circuits to `None`. `custom` providers/targets go
     through the `type != "http"` branch of `resolve_target_info`, which returns
     `info["provider"] = target.type` (e.g. `"python"`/`"agent"`/`"mcp"`); the subsequent
     `resolve_provider(info["provider"], cfg)` then raises `ConfigError` (not a known
     provider/custom name), caught by `_missing_run_key`'s `except ConfigError: return None`.
     Correct, though incidental rather than by direct design — worth a one-line comment if this
     is ever refactored, but not a functional bug.
   - Minor pre-existing quirk (not introduced by this change, not blocking): the
     `openai-compatible` preset has `requires_key=True` (derived from `api_style="openai"`) but
     `api_key_env=None`; `_missing_run_key` computes `key_env = tc.api_key_env or
     preset.api_key_env` → `None`, and `if key_env and ...` short-circuits false, so no warning
     is ever shown for an `openai-compatible` target even if it truly needs a key entered via a
     header. This mirrors the existing `requires_key`/`api_key_env` split used elsewhere in the
     file (e.g. `describe_target`) and is out of scope for this refinement.

3. **No dead code / leftover references** — grep for `dry-run`, `packs (comma`, `plan:` in
   `cli.py` shows the only remaining hits are the `run` subcommand's own `--dry-run` flag/help
   text/`plan:` output (lines 375-477), which is a distinct, still-tested code path (subcommand
   dry-run tests are unaffected — full suite green). The menu path has none of these strings.
   `tests/test_cli_home.py:162` and `tests/test_cli_run_flow.py:48-49` explicitly assert their
   absence from menu output.

4. **Persist-vs-throwaway cfg behavior unaffected** — `_menu_run`'s `_ADD_CUSTOM` branch still
   persists into the returned `cfg` (`cfg, run_cfg, target = new_cfg, new_cfg, name`,
   cli.py:2183) while the hosted ad-hoc branch keeps `run_cfg` a throwaway
   (`cfg.with_cli_target(...)`, never reassigned to `cfg`) and every exit path still
   `return cfg`. This logic is untouched by the packs/dry-run/confirm simplification;
   `test_home_menu_adhoc_run_does_not_leak_cli_target` remains green.

5. **Edge cases** —
   - Empty catalog (`selected` empty): prints the guidance line, calls `_pause_menu()`, then
     `return cfg` — correct, and harmless under non-TTY tests (no-op pause).
   - Declining the confirm: prints `"  cancelled"` and returns `cfg` unchanged before any
     adapter/network call — verified by `test_home_menu_run_confirm_cancel` and
     `test_run_flow_no_packs_or_dry_run_prompt`.
   - Missing key: warning is echoed and the confirm's `default` flips to `False`
     (`default=not missing`) so an unattended Enter declines rather than firing a doomed run.
     Not covered by a dedicated automated test (no test sets an unset-key env + configured
     target and asserts the warning text/default-No behavior) — minor coverage gap, not
     blocking given the logic is simple and directly traceable through
     `resolve_target_info`/`resolve_provider`/`os.environ.get`, all of which are exercised
     elsewhere in the suite.

## Non-blocking suggestions
- Consider a small direct test for `_missing_run_key` (unset key on a configured http target →
  returns the env name; set key → `None`; non-http target → `None`) and/or a `_menu_run`
  end-to-end test asserting the `⚠ ... is not set` warning line and default-No confirm when the
  key env is unset. Not required to pass this review since the code path is simple and
  transitively covered by other tests of the same helpers.

Test/lint evidence: `python -m pytest -q` → 580 passed, 1 skipped; `python -m ruff check src
tests` → All checks passed.

- STATUS: PASS

---

# Post-phase-20 UX refinement review (menu Run: live per-attempt progress counter)

Scope: `on_attempt` param threaded through `_execute` (`src/grendel/cli.py:192-203`) into
`Runner(..., on_attempt=on_attempt)`; new `_run_progress(total)` helper
(`src/grendel/cli.py:2147-2161`); `_menu_run` wiring (`cli.py:2244-2252`); new tests in
`tests/test_cli_run_flow.py:76-103`. `Runner`'s `on_attempt` hook itself (`src/grendel/runner.py`)
pre-existed this change and was not modified.

## Verification performed
- Read `src/grendel/cli.py`: `_execute` (192), `_run_progress` (2147), `_menu_run` (2180-2257).
- Read `src/grendel/runner.py`: `Runner.__init__` (77-98), `_record_attempt` (134-148,
  persist-then-hook-outside-lock-with-try/except), `run` (337-371, `asyncio.gather` over
  per-attack tasks under a `Semaphore`).
- Read `src/grendel/records.py`: `Verdict` enum (14-19) and every `Verdict.FAIL`-as-success usage
  (`asr`, `metrics_summary`, `by_owasp`/`by_atlas`) to confirm FAIL = attack succeeded.
- Read `tests/test_cli_run_flow.py:76-114` (progress-counter tests + surrounding run-flow tests
  unaffected).
- Ran `python -m pytest -q` → **583 passed, 1 skipped**.
- Ran `python -m ruff check src tests` → **All checks passed**.

## Findings

1. **`on_attempt` threading is correct.** `_execute` forwards the callback unchanged into
   `Runner(...)`; the `run` subcommand's call site (cli.py:507-517) doesn't pass `on_attempt`
   (defaults to `None`), so the plain `grendel run` path is byte-identical to before — only the
   menu path (`_menu_run`) opts in. No regression to the subcommand path.

2. **A raising callback cannot crash a run.** `Runner._record_attempt` (runner.py:134-148) calls
   `self._on_attempt(attempt)` in a bare `try/except Exception: log.exception(...)` block, fired
   *after* `self._atomic_write(record)` and *outside* `self._write_lock`. This guard pre-existed
   (not part of this diff) but is exactly the safety net the new UI callback relies on. Confirmed
   by reading the code; the CLI's `cb` itself is simple (dict increment + `click.echo`) and
   unlikely to raise, but the guard covers it either way.

3. **Off-TTY / on-TTY gating is correct.** `_run_progress` returns `None` immediately when
   `not sys.stdout.isatty()` (cli.py:2151-2152), so pipes/CI/tests get no callback and no `\r`
   noise — confirmed by `test_run_progress_off_tty_is_none` and by the full suite passing clean
   (no stray `\r` in any captured output). The trailing `typer.echo("")` in `_menu_run`
   (cli.py:2251-2252) is correctly gated on `if on_attempt is not None:` — it only fires when a
   live line was actually written, so a non-TTY/off run doesn't print a spurious blank line.

4. **`attempt.verdict.name == "FAIL"` is the correct hit condition.** Cross-checked against
   `records.py`: `Verdict.FAIL` is used as "attack succeeded" everywhere in `RunRecord` (asr,
   `metrics_summary`'s `succeeded`/`defended` split, per-category/OWASP/ATLAS breakdowns).
   `Verdict.PASS` = defended, `ERROR`/`SKIPPED` are excluded from scoring. The progress callback's
   comment (`# FAIL = the attack got through`) and logic match this exactly, and match the final
   `_summary()` line's `succeeded=m['succeeded']` which is computed the same way.

5. **No regression to the existing menu/run flow.** `_execute`'s new keyword-only `on_attempt=None`
   parameter is additive and defaulted, so every other caller (the `run` subcommand) is unaffected.
   `_menu_run`'s persist-vs-throwaway cfg split, the single fire-confirm, `_missing_run_key`
   warning + default-No, and `_pause_menu()` before the summary are all untouched by this diff —
   confirmed by reading the surrounding lines (2213-2257) and by the full suite (including the
   pre-existing menu-run tests) passing unmodified.

6. **No concurrency hazard.** `Runner.run` (runner.py:337-368) drives per-attack tasks via
   `asyncio.gather` under a `Semaphore(self.options.concurrency)`, so multiple attempts *can* be
   in flight concurrently — but this is single-threaded cooperative asyncio, and the `cb` callback
   in `_run_progress` is fully synchronous (no `await` inside it), so `state["n"] += 1` /
   `state["hits"] += 1` cannot be interleaved by another task; each callback invocation runs to
   completion atomically before the event loop yields. No lock is needed and none is missing.

7. **Total count is correct.** `_menu_run` doesn't pass `controls=` to `_execute` (menu-run has no
   control items), so `total = len(selected)` (attacks only) exactly matches the number of
   `on_attempt` invocations the counter will see — the `n/total` display can't over/undercount.

8. **Tests are adequate for the new surface.** `test_run_progress_off_tty_is_none` and
   `test_run_progress_counts_attempts_and_hits` (using a minimal fake attempt with `.verdict.name`)
   directly exercise `_run_progress`'s both branches and the FAIL-counts-as-hit logic. The
   `_menu_run` wiring itself (`on_attempt = _run_progress(...)`, passed into `_execute`, and the
   gated trailing `echo("")`) is not separately covered by an end-to-end menu test, but since
   `_run_progress` returns `None` under the `CliRunner`'s non-TTY stdout, that code path is
   exercised (as a no-op) by every existing `_menu_run` test already in the suite — an explicit
   TTY-mode end-to-end assertion of the `\r attacking… n/total` line inside a full menu run would
   need a monkeypatched `isatty`, similar to the two direct unit tests; not required to pass this
   review since the direct unit tests already lock the callback's exact behavior and the wiring is
   two lines of trivial, directly-readable code.

## Non-blocking suggestions
- Optional: an end-to-end `_menu_run` test with `sys.stdout.isatty` monkeypatched True, asserting
  the final summary line follows a blank line (confirming the `typer.echo("")` gate fires in
  context, not just in isolation). Not required — the two direct `_run_progress` unit tests plus
  the trivial, directly-readable gating logic in `_menu_run` provide adequate confidence.

Test/lint evidence: `python -m pytest -q` → 583 passed, 1 skipped; `python -m ruff check src
tests` → All checks passed.

- STATUS: PASS
