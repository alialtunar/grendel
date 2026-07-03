# Phase 19 — implementation plan

Derived from `phases/phase-19/spec.md`. Three milestones, each ending in a checkpoint
(`ruff` clean + `pytest` green + `reviewer`/`tester` `STATUS: PASS`).

---

## Milestone 1 — Configurable `custom` adapter

**Intent:** an agent's request/response shape lives in config, not code; a 4th `api_style: custom`
connects to any POST/JSON API. No change to the openai/anthropic/ollama paths.

**Steps**
1. **`config.py` — schema:**
   - New `CustomRequestSpec(BaseModel, extra="forbid")`: `path: str = ""`, `body: dict` (JSON
     template, `{prompt}`/`{system}`/`{model}`/`{api_key}` placeholders), `headers: dict[str,str] = {}`.
   - New `CustomResponseSpec(BaseModel, extra="forbid")`: `text_path: str`.
   - `CustomProviderConfig`: extend `api_style` Literal with `"custom"`; add
     `request: CustomRequestSpec | None = None`, `response: CustomResponseSpec | None = None`;
     `@model_validator(after)`: when `api_style == "custom"`, both `request` and `response` are
     required (else `ConfigError`); when not custom, they must be absent (else `ConfigError`).
2. **`providers.py` — carry the spec (as plain dicts, no config import):**
   - `ProviderPreset`: extend `api_style` Literal with `"custom"`; add `request: dict | None = None`,
     `response: dict | None = None`. `custom` stays OUT of `_AUTH_REQUIRING_STYLES` (key only if an
     explicit `requires_key`/header sets it).
   - `resolve_provider`: for a custom-style custom provider, pass
     `request=custom.request.model_dump() if custom.request else None` (same for response).
3. **`http_adapter.py` — the custom branch:**
   - Module helpers: `_subst(value, mapping)` recursively replaces `{prompt}/{system}/{model}/{api_key}`
     in string leaves ONLY (dict/list walked; other types untouched; unknown `{...}` left as-is);
     `_dotted_get(data, path)` walks dict keys + numeric list indices, raising `AdapterError` on a
     missing/non-navigable path.
   - `_build_request` `custom` branch: `req = self.preset.request or {}`; `url =
     f"{self.base_url}{req.get('path','')}"`; `mapping = {prompt, system or "", model, api_key or ""}`;
     `body = _subst(req.get("body", {}), mapping)`; `headers = {**extra_headers, **_subst(req.get(
     "headers", {}), mapping)}`. (No API key auto-added — user puts it in the template header.)
   - `_parse_response` `custom` branch: `path = (self.preset.response or {}).get("text_path")`;
     if missing → `AdapterError`; `text = _dotted_get(data, path)`; coerce to str; return
     `AdapterResponse(text=…, raw=data, model=self.model, provider=self.preset.name, latency_ms=…)`.
   - `send`: unchanged (requires_key gate already data-driven; custom.requires_key defaults False).
4. **`cli.py` — `describe_target` custom-aware:** when `info["api_style"] == "custom"`, show
   `POST {base}{request.path}  ·  {text_path note}` instead of the API_PATHS suffix (which is
   openai/anthropic/ollama only). Read path from the resolved preset.
5. **Tests** (`test_custom_adapter.py`):
   - config: `api_style=custom` without `request`/`response` → `ConfigError`; with both → OK; a
     non-custom style carrying `request` → `ConfigError`.
   - `resolve_provider` copies request/response dicts onto the preset; `requires_key` False.
   - adapter build_request: `_subst` fills `{prompt}`/`{system}`, leaves a stray `{foo}` untouched;
     nested body dict substituted; header templated.
   - adapter parse: `_dotted_get` reads `reply` and `choices.0.message.content`; missing path →
     `AdapterError`.
   - end-to-end via `httpx.MockTransport`: a target on a custom provider sends the templated body to
     the templated path and scores the mapped `text_path` response (offline).

**Checkpoint 1:** ruff clean + pytest green (prior + new); `reviewer` + `tester` `STATUS: PASS`.

---

## Milestone 2 — Menu: 2 top options + proxy out of add-target

**Intent:** the add-target menu asks *what* you test (model vs agent), not *how grendel connects*;
proxy leaves this menu (kept as `grendel proxy`, reframed for indirect injection).

**Steps**
1. **`cli.py` letter + questionary add-target:** top choice becomes **[1] a model** (hosted
   provider+model, unchanged) · **[2] an agent (its own API)**. Remove the proxy option from BOTH
   shells. `_echo_proxy_hint` is retitled and moved to the proxy command's help/next-line, not the
   add-target flow (kept as a helper; referenced from `grendel proxy` output).
2. **Agent sub-choice** (both shells): **[a] OpenAI-compatible chat URL** (existing `url` path →
   provider `openai-compatible` + base_url + model) · **[b] custom JSON API** → prompt base_url,
   request path, body template (JSON string parsed to dict; bad JSON → error+retry), `text_path`;
   build a `CustomProviderConfig(api_style="custom", …)` under a provider name derived from the
   target name (`<name>` if free) and a `TargetConfig(type=http, provider=<name>, model)`. New pure
   helper `_add_custom_agent(cfg, name, base_url, path, body, text_path, model)` returns the new cfg
   (adds provider + target, revalidated); collisions raise `ConfigError`.
3. **Tests** (`test_cli_home.py`): update the existing `test_home_menu_add_target_and_save` script
   for the new option order (intent `1` still = hosted model); new
   `test_home_menu_add_custom_agent` (letter path): choose model→agent→custom, enter base_url/path/
   body/text_path, confirm, save → the saved YAML has a `providers.<name>` with `api_style: custom`
   and a target referencing it.

**Checkpoint 2:** ruff clean + pytest green; `reviewer` + `tester` `STATUS: PASS`.

---

## Milestone 3 — Finalize (architecture review + bug hunt + docs)

**Intent:** the whole tool is consistent, hardcode-free, documented, and proven against a real
bespoke-JSON agent.

**Steps**
1. **Architecture consistency sweep** (reviewer-driven): the four `api_style`s appear consistently
   in `_build_request`/`_parse_response`/`ProviderPreset`/`CustomProviderConfig`; `describe_target`,
   `run`, `proxy`, and the menu all resolve providers/scorer the same way; no dead branch, no double
   source of truth. Record findings in `review.md`.
2. **Hardcode scan:** grep for residual `"openai"`/`gpt-`/URL literals in branch conditions; confirm
   all are data (PRESETS/API_PATHS) or examples. Fix any genuine special-case.
3. **Bug hunt + fixes:** placeholder collision (stray `{}` in agent body), wrong/missing `text_path`,
   custom provider with no base_url, empty body — each has a test asserting a clear error, not a
   crash.
4. **Docs:** README "test an agent" section = custom adapter primary + openai-compatible + proxy(=
   indirect) note; `docs/authoring-packs.md` untouched unless a doc-test needs it; keep additive.
5. **Live end-to-end (manual, recorded in PROGRESS):** a tiny bespoke-JSON echo agent (stdlib
   `http.server`, `POST /chat {"message"}→{"reply"}`) + a `grendel.yaml` custom provider →
   `grendel run --target … --pack jailbreak --dry-run` then a real run → `grendel report`.

**Checkpoint 3 (phase close):** full suite green + ruff clean + `grendel doctor` healthy; `reviewer`
+ `tester` `STATUS: PASS`; append `phase 19: DONE …` + `ALL PHASES COMPLETE` to `PROGRESS.md`.

---

## Plan review — addressed
- (1,2) `_add_custom_agent` MUST pre-check `name not in cfg.providers` (distinct from the PRESETS
  collision the validator checks) and raise `ConfigError`; `_remove_target` MUST also delete
  `cfg.providers[name]` when the removed target's `provider == name` and no other target references
  it. Tests: re-add-after-remove, provider-name-already-used.
- (3) `describe_target` custom branch calls `resolve_provider(info["provider"], preview)` to read
  `preset.request["path"]` / `preset.response["text_path"]` (done in M1).
- (4) the questionary shell is offline-untestable (needs a TTY) per the project-wide convention
  (see test_cli_home.py docstring); instead the shared pure helper `_add_custom_agent` — which BOTH
  shells call — is unit-tested directly (collision + remove/re-add), plus the letter-shell flow test.
- (5) M3 bug-hunt: unresolved `{api_key}` in a header template → substitutes to `""` (`"Bearer "`),
  a non-crashing malformed header; covered as intentional by `test_custom_round_trip`.

## Risks & mitigations
- **Placeholder collision** (real `{prompt}` text inside the agent body) → `_subst` replaces only the
  four known keys, leaves other braces verbatim; test covers a stray `{foo}`.
- **Cross-module type coupling** (ProviderPreset needing config types) → preset carries request/
  response as plain **dicts**, so providers.py keeps zero runtime config import (no cycle).
- **`text_path` typo / missing field** → `_dotted_get` raises `AdapterError` with the path, not a
  KeyError/crash; tested.
- **Menu test breakage** → existing add-target tests updated for the new order (not deleted); the
  custom path adds a new test.
- **Finalize scope creep** → M3 is consistency + bug + docs only; no new feature.
