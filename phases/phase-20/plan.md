# Phase 20 — implementation plan

Derived from `phases/phase-20/spec.md`. Two milestones, each ending in a checkpoint
(`ruff` clean + `pytest` green + `reviewer`/`tester` `STATUS: PASS`).

---

## Milestone 1 — Model picker: suggestions + type-your-own

**Intent:** the run flow offers models to pick, without a closed list.

**Steps**
1. **`providers.py` — data:** add `models: list[str] = []` to `ProviderPreset` (suggestions only).
   Populate for the hosted presets with a few current ids:
   - openai: `gpt-4o-mini`, `gpt-4o`, `o3-mini`
   - anthropic: `claude-opus-4-8`, `claude-sonnet-5`, `claude-haiku-4-5`
   - openrouter: `openai/gpt-4o-mini`, `anthropic/claude-3.5-sonnet`
   - ollama: `llama3.1`, `mistral`, `qwen2.5`
   `openai-compatible` stays empty. Keep `default_model` as-is. (Custom providers carry no models.)
2. **`cli.py` — `_preset_models(provider, cfg)`** helper: return `resolve_provider(...).models` or `[]`
   on `ConfigError`. Mirrors the existing `_preset_default_model` guard.
3. **`cli.py` — `_prompt_model(provider, cfg)`** becomes TTY-aware:
   - Non-TTY (tests/pipes): unchanged typed prompt (`typer.prompt`, default = preset default_model).
   - TTY + `questionary` + non-empty suggestions: `questionary.select("model", choices=[…models, ✎
     type another model…], default=<preset default_model if in models else None>)`; the ✎ sentinel →
     `questionary.text("model")` (free entry, any string).
   - TTY but no suggestions (e.g. openai-compatible / custom): fall through to the typed prompt.
   Return the stripped model string; an empty pick returns "" (caller already errors clearly).
4. **Wire `_menu_run` to `_prompt_model` (review pt 1):** replace `_menu_run`'s inline
   `typer.prompt("model (type it — no fixed list)", …)` (cli.py ~2080) with `_prompt_model(provider,
   cfg)`. Fold the "no fixed list" reassurance into `_prompt_model`'s typed-branch hint so it isn't
   lost.
5. **Tests** (`test_cli_run_flow.py`, new): `_preset_models` returns the openai suggestions and `[]`
   for an unknown provider; the non-TTY `_prompt_model` path still returns the typed model (drives the
   existing menu-run scripts). The questionary branch stays offline-untestable (documented), same
   convention as the rest of the menu.

**Checkpoint 1:** ruff clean + pytest green; `reviewer` + `tester` `STATUS: PASS`.

---

## Milestone 2 — Provider picker: no default + add-custom inline; explain packs/dry-run

**Intent:** the provider step is unbiased and extensible; every run prompt says what it is.

**Steps**
1. **`cli.py` — `_prompt_provider(cfg)`**: drop `default="openai"` (no preselected provider in the TTY
   picker). Append a `questionary.Separator()` + `questionary.Choice("+ add a custom agent (its own
   JSON API)", _ADD_CUSTOM)` where `_ADD_CUSTOM = "__add_custom__"` is a new module sentinel. On cancel
   return `None`. Delegate to `_prompt_provider_letter(cfg, allow_add_custom=True)` on the non-TTY path.
   **`_prompt_provider_letter(cfg, allow_add_custom: bool = False)` (review pts 2,3,7,8):** the shared
   helper stays default-preserving for its OTHER caller (`_targets_letter` ~1410 passes no flag → keeps
   `default = openai index`, no add-custom line). Only when `allow_add_custom` is True: print a
   `[0] add a custom agent (its own JSON API)` line and, BEFORE the permissive `return raw` fallback,
   add `if raw == "0": return _ADD_CUSTOM`. The numeric default stays (non-interactive pipes/tests need
   it); the "no preselect" change is TTY-only, matching the revised spec.
2. **`cli.py` — `_menu_run` ad-hoc branch**: after `provider = _prompt_provider(cfg)`:
   - `None` → return cfg (cancelled).
   - `_ADD_CUSTOM` → call new wrapper `_prompt_custom_agent(cfg)` which (a) prompts for a `name`
     (TTY-aware, matching the `_targets_letter` convention), (b) delegates to
     `_prompt_custom_agent_questionary/_letter(cfg, name)`, (c) returns `(new_cfg, name)`. **Success
     detection (review pts 4,5):** the delegate returns the SAME cfg on bad-JSON/ConfigError/declined
     confirm; treat `name and name in new_cfg.targets` as success → `run_cfg = new_cfg`, `target = name`
     (PERSISTS into the returned cfg). Otherwise `return cfg` (nothing added, mirror the existing
     `except ConfigError` returns). Skip the provider/model typed path in this branch.
   - otherwise (a hosted provider name) → `_prompt_model(provider, cfg)` (now the suggestion picker),
     throwaway target as today.
   Update `_menu_run`'s docstring (review pt 6): it no longer "always returns cfg UNCHANGED" — describe
   the two outcomes (throwaway ad-hoc/hosted vs. persisted add-custom agent).
3. **`cli.py` — explain packs/dry-run**: emit one hint line before each prompt in `_menu_run`:
   `typer.echo("  packs · which attack packs to fire (blank = all bundled)")` and
   `typer.echo("  dry-run · plan only, no network / no real API calls")`. Prompts themselves unchanged
   so existing input scripts keep working.
4. **Tests** (`test_cli_home.py` / `test_cli_run_flow.py`):
   - the ad-hoc run output now contains the packs + dry-run hint lines (assert substrings) — update
     any test that counts exact lines; the input scripts are unchanged (hints are echoes, not prompts).
   - `_prompt_provider_letter(cfg, allow_add_custom=True)` returns `_ADD_CUSTOM` for input `0`; called
     with the default (no flag) it does NOT (returns `"0"` as a name) — a small direct unit test of
     both, plus a guard that `_targets_letter`'s hosted-model add still works (regression).
   - the `_ADD_CUSTOM` wiring in `_menu_run` is exercised via the letter fallback: a menu-run script
     that picks `0`, enters a name + custom agent (base_url/path/body/text_path/model), then dry-runs →
     the returned cfg has the new custom provider+target and the plan runs "vs <name>".

**Checkpoint 2 (phase close):** full suite green + ruff clean; `reviewer` + `tester` `STATUS: PASS`;
append `phase 20: DONE …` to `PROGRESS.md`.

---

## Plan review — addressed
- (1) added M1 Step 4: `_menu_run` now calls `_prompt_model` (was inline dead-end).
- (2,3,7,8) `_prompt_provider_letter` parametrized `allow_add_custom` — shared `_targets_letter` caller
  unaffected; explicit `if raw == "0": return _ADD_CUSTOM` under the flag; `[0]` for letter-consistency;
  numeric default kept for non-interactive, no-preselect is TTY-only (spec narrowed to match).
- (4,5) `_prompt_custom_agent(cfg)` wrapper prompts `name`, returns `(cfg, name)`; `_menu_run` treats
  `name in new_cfg.targets` as success, else returns cfg unchanged.
- (6) `_menu_run` docstring updated to state the two outcomes.
- (9) TTY model picker pre-highlights the preset `default_model` when present in `models`.
- (10) sentinel/persist-vs-throwaway design confirmed sound — kept.

## Risks & mitigations
- **Hardcoded model list creeping in** → `models` is explicitly SUGGESTIONS; the ✎ escape + non-TTY
  typed path guarantee any model is reachable. Documented on the field + spec non-goal.
- **Existing menu-run scripts break** → hints are `typer.echo` (not prompts) and `_prompt_model`'s
  non-TTY branch is unchanged, so no extra input lines are consumed; only added-substring assertions.
- **`_ADD_CUSTOM` persisting vs ad-hoc not persisting** → intentional: a configured agent is saved,
  an ad-hoc hosted model stays throwaway. `_menu_run` returns the (possibly-updated) cfg either way.
- **questionary offline-untestable** → the letter fallback carries the same `_ADD_CUSTOM` branch and
  IS unit-tested; matches the project-wide menu-test convention.
