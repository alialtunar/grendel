# Review: run-target picker UX follow-up (`_prompt_run_target`, `_menu_run`)

Scope: post-phase-19 follow-up UX change in `src/grendel/cli.py` (`_ADHOC` sentinel,
`_run_target_label`, `_prompt_run_target`, updated `_menu_run`) and matching test updates in
`tests/test_cli_home.py`. No phase folder/spec exists for this change (it's a small follow-up on
top of an already-DONE phase 19 / "ALL PHASES COMPLETE"); reviewed against the described intent
and against the existing project conventions in phase 18/19 (never leak ad-hoc target, cancel
returns cfg unchanged, offline-testable via the numbered fallback).

## Findings

1. **Control flow is correct.** `_menu_run` (`src/grendel/cli.py:2027-2049`): `sel = _prompt_run_target(cfg)`;
   `sel is None` → return `cfg` unchanged (cancel, matches doc comment); `sel != _ADHOC` → uses the
   configured target directly against the real session `cfg` (no throwaway needed, correct since
   nothing new is synthesized); `sel == _ADHOC` → falls through to the pre-existing ad-hoc
   provider+model flow, still built on a throwaway `run_cfg = cfg.with_cli_target(...)`, so the
   "never leaks into the saved config" invariant from phase 18 is preserved. Verified by
   `test_home_menu_adhoc_run_does_not_leak_cli_target` (still passes).

2. **`_prompt_run_target` (`cli.py:1989-2024`) is sound.**
   - No configured targets → returns `_ADHOC` immediately, skipping the picker entirely (matches
     the documented "no empty picker" behavior and the ad-hoc-only prior tests).
   - TTY path: builds `questionary.Choice` list of configured targets + a separator + an ad-hoc
     choice; `.ask()` naturally returns `None` on Ctrl-C/ESC, which flows straight into the
     already-handled `sel is None` cancel branch — no extra handling needed.
   - `ImportError` on `questionary` inside the TTY branch falls through to the numbered fallback
     rather than crashing — reasonable defensive behavior, matches the project's pattern of
     optional-dependency guards elsewhere (e.g. `mcp`).
   - Numbered fallback (also the test/non-TTY path): validates digit range before indexing
     (`1 <= int(raw) <= len(names)`), accepts a typed target name directly as an escape hatch, and
     otherwise echoes "unknown choice" and returns `None` (cancel) rather than crashing or looping
     unexpectedly — consistent with other letter-menu "unknown option" handling in `_home_letter`.

3. **`_run_target_label` (`cli.py:1980-1986`) can't crash the picker.** Wraps
   `resolve_target_info` in `try/except ConfigError`, falling back to the bare target name — so a
   target referencing a deleted/misconfigured provider still renders in the list instead of
   blowing up the menu.

4. **Ad-hoc path unaffected.** For a fresh/empty config, `_prompt_run_target` returns `_ADHOC`
   with zero extra prompts, so the prompt sequence `blank(provider)/model/blank(packs)/dry-run` is
   byte-identical to the old flow. `test_home_menu_run_dry_run`,
   `test_home_menu_run_full_writes_record`, `test_home_menu_run_applies_config_scoring`, and
   `test_home_menu_adhoc_run_does_not_leak_cli_target` all still pass unmodified in behavior.

5. **New test `test_home_menu_run_picks_configured_target`** (`tests/test_cli_home.py:193-206`)
   correctly exercises the numbered-picker path end to end: writes a `gpt` target into
   `grendel.yaml`, drives the script `"x\n1\n\ny\nq\n"`, and asserts both the picker prompt text
   and that the run actually targeted `gpt` (`"vs gpt" in result.output`), not an ad-hoc model —
   a real regression guard, not just a smoke test.

6. **No dead code / no leftover free-text target-name prompt.** Grepped `cli.py` for the old
   "target name (blank" prompt text — not found; the old free-text entry point is fully replaced,
   consistent with the stated intent.

7. Verified independently: `python -m pytest -q` → 575 passed, 1 skipped;
   `python -m ruff check src/grendel/cli.py tests/test_cli_home.py` → all checks passed;
   `python -m pytest tests/test_cli_home.py -q` → 18 passed.

No blocking issues found. This is a small, self-contained, well-tested UX improvement that
preserves all documented invariants (ad-hoc-target-never-leaks, cancel-returns-cfg-unchanged,
offline-testable non-TTY fallback).

- STATUS: PASS

---

# Review: provider picker (arrow-key) + menu explanations follow-up

Scope: further post-phase-19 UX follow-up in `src/grendel/cli.py`:
1. New `_prompt_provider(cfg)` (arrow-key `questionary.select` on a TTY over hosted providers,
   numbered `_prompt_provider_letter` fallback otherwise); `_menu_run`'s ad-hoc path now calls it,
   and the model-prompt label changed to "model (type it — no fixed list)".
2. Short purpose annotations added to `_settings_letter`/`_settings_questionary` (run/judge/proxy)
   and `_judge_label`, plus a one-line judge explainer echoed before the enable prompt in
   `_edit_judge_letter`/`_edit_judge_q`.

No phase folder/spec exists for this change; reviewed against project conventions (never leak
ad-hoc target, TTY/non-TTY parity via numbered fallback, prompt-sequence stability for existing
tests).

## Findings

1. **`_prompt_provider` (`cli.py:1270-1287`) is sound.**
   - Non-TTY (`sys.stdin.isatty()` False — the path `CliRunner`/tests take) falls straight to
     `_prompt_provider_letter(cfg)`, byte-identical to the old direct call — no regression to the
     numbered fallback used by tests. Confirmed: full suite still 575 passed/1 skipped.
   - TTY path wraps the `questionary` import in `try/except ImportError: pass` (no `else` needed
     structurally — falls through to the final `return _prompt_provider_letter(cfg)` after `pass`),
     consistent with the optional-dependency guard pattern used elsewhere (e.g. `mcp`).
   - `questionary.select(...).ask()` returning `None` (Ctrl-C/ESC) degrades to `"openai"` via
     `return sel or "openai"` — always returns a non-empty string, never `None`, so the caller in
     `_menu_run` (`build_cli_target_config(provider=provider, ...)`) can't be handed a falsy
     provider. `"openai"` is a real member of `_known_providers(cfg)` (excluded set is only
     `openai-compatible`), so the returned default is always a valid, resolvable provider name.
   - Both the TTY and fallback branches exclude `openai-compatible` for the same reason as the
     pre-existing `_prompt_provider_letter` (hosted-model pick can't dead-end on a missing
     `base_url`) — consistent, no drift between the two pickers' provider sets.

2. **Ad-hoc run path still synthesizes a throwaway cfg — no leak.** `_menu_run` (`cli.py:2076-2089`)
   unchanged in this respect: `run_cfg = cfg.with_cli_target(_CLI_TARGET_NAME, tc)` is still a
   fresh object assigned to the local `run_cfg`, never assigned back to the session `cfg`; the
   function still returns the original `cfg` at every exit path. The only change is the *source* of
   `provider` (now `_prompt_provider(cfg)` instead of `_prompt_provider_letter(cfg)`), which does
   not touch the leak-safety invariant. `test_home_menu_adhoc_run_does_not_leak_cli_target` still
   passes.

3. **New echo lines don't break existing prompt sequences.**
   - `_settings_letter`/`_settings_questionary` (`cli.py:1821-1862`): the annotations are appended
     to the same `typer.echo`/`questionary.Choice` label strings (not new prompts), and the
     r/j/p/b menu loop and `typer.prompt("settings", ...)` / `questionary.select(...)` calls are
     unchanged — still accepts r/j/p/b and loops correctly on unknown input.
   - `_edit_judge_letter`/`_edit_judge_q` (`cli.py:1772-1807`): the new `typer.echo(...)` explainer
     lines are pure output (no `typer.prompt`/`questionary.*` call), inserted *before* the existing
     `confirm(enable)` → `prompt/text(target)` sequence, which is otherwise byte-identical in order
     and default handling. `typer.echo` output is not consumed by `CliRunner`'s scripted input, so
     no input-line is skipped/misaligned; only `result.output` grows, which the assertions in
     `test_cli_home.py` for these paths use substring checks, not full-string equality — verified
     by the passing suite.
   - `_judge_label` (`cli.py:1671-1676`): the `[8:]` slice used in `_config_prompt_loop`
     (`cli.py:1734`) to strip the leading "judge   " column still works — the label's prefix is
     still exactly `"judge   · "` (5-letter word + 3 spaces = 8 chars) before the now-longer
     descriptive text; slicing off the first 8 chars still yields the intended `"· ..."` suffix
     with no off-by-one truncation of real content.

4. **No cross-menu inconsistency.** The `_settings_letter` proxy line ("engine speed & limits
   (concurrency, tokens, timeout)") and `_settings_questionary` run line ("concurrency, tokens")
   differ slightly (timeout mentioned only in the letter variant) — cosmetic only, not a functional
   or blocking issue, but noted for a future polish pass if the two menus are meant to stay in
   lockstep.

5. Verified independently: `python -m pytest -q` → 575 passed, 1 skipped;
   `python -m ruff check src/grendel/cli.py` → all checks passed.

No blocking issues found. The provider picker correctly degrades TTY→arrow-key,
non-TTY→numbered-fallback with an always-valid returned provider name, the ad-hoc throwaway-cfg
leak-safety invariant is untouched, and the new explanatory echo lines are pure output that don't
perturb any existing prompt/confirm sequence or test assertions.

- STATUS: PASS
