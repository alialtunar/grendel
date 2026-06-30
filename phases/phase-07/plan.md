# Phase 7 — Agent mode (sandbox + Python/MCP adapters + T4 side-effect scoring): implementation plan

> Build order is dependency-ordered and **agent-last for scoring impact**, so the prior **226**
> tests stay green at every checkpoint: (1) the instrumented sandbox + `ToolCall` + the
> additive `AdapterResponse.tool_calls` + runner flow (data only, **no scoring change**);
> (2) the Python-callable + agent-sandbox adapters + the deterministic demo weak agent
> (offline, no scoring change); (3) the **safe** side-effect grammar parser + evaluator (pure,
> offline, no `eval`); (4) wire the T4 side-effect scorer into `score_async` + the
> not-applicable behavior; (5) the bundled `tool-abuse` pack + config target-type extensions +
> `build_target` dispatch + end-to-end integration; (6, optional) the MCP adapter interface
> behind a lazy guarded import. Every milestone ends in a **Checkpoint** with exact commands.
> Quality gate: `ruff check .` (zero findings), `ruff format --check .` (clean), `pytest`
> (green, **offline, no API keys, no network, no `mcp` package, no real side effects**). New
> code reuses existing patterns: Pydantic v2 `ConfigDict(extra="forbid")`, the
> `TargetAdapter`/`AdapterResponse` contract, the `FakeAdapter`/`StubClassifier` test-double
> style, the `Scorer`/`Runner` injected-dependency style, the packloader license-gate +
> coherence checks, and the `ScoreDetail`/`Verdict` models. **No new *required* deps** (`mcp`
> is an optional/lazy extra). Everything additive; the single contract refinement
> (`side-effect` is no longer always SKIPPED in `score_async` — it scores PASS/FAIL when an
> **agent** target supplies observed `tool_calls`) is **inert** for every existing plain-LLM
> test (no existing test uses an agent target / sets `response.tool_calls`) — noted explicitly
> where it occurs.

---

## Milestone 1 — Instrumented sandbox + `ToolCall` + `AdapterResponse.tool_calls` + runner flow (data only)

**Build**
- `src/gauntlet/sandbox.py` (NEW): `ToolCall` (pydantic, `name`/`args`/`ordinal`,
  `extra="forbid"`); `ToolRegistry` (`register`, `call` → records a `ToolCall` and runs the
  optional **fake** `fn`, `calls`, `count`, `called`, `snapshot()`); `ToolContext` (the object
  handed to the agent — exposes registered tools as bound callables **and** `call(name,
  **kwargs)`, both routed through `ToolRegistry.call`). **No real side effects**: a no-`fn`
  tool is a pure recorder; a registered `fn` is a fake. A fresh registry is built per send.
  **[Fix #4 — bound-callable mechanism + reserved names]** `ToolContext` dispatches tool access
  via `__getattr__` (so the agent writes `tools.send_email(to=..., body=...)`). The names
  `register`, `call`, `calls`, `count`, `called`, `snapshot` (and any real attribute) are
  RESERVED — `register()` raises `ValueError` if a tool is registered under a reserved name.
  Test the reserved-name rejection and that `__getattr__` routes through `ToolRegistry.call`.
  **[Fix #9 — JSON-serializable args]** `ToolRegistry.call` validates that kwargs are
  JSON-serializable at record time (`json.dumps(args)` in a try/except → raise a clear
  `ValueError`), consistent with `ToolCall.args` being JSON-serializable; this keeps the
  `called_with` evaluator (which does `json.dumps(args)`) from ever hitting a `TypeError`.
- `src/gauntlet/targets/base.py`: add **additive** `AdapterResponse.tool_calls: list[dict] |
  None = None`. Tri-state contract (spec §4): `None` = adapter does not observe tools; `[]` =
  agent observed zero; list = observed calls. Existing `AdapterResponse` constructions default
  to `None` → unchanged.
- `src/gauntlet/runner.py`: in `_run_attempt`'s successful-send branch, set
  `tool_calls=response.tool_calls or []` on the built `AttemptRecord` (the reserved field).
  **Inert** for every current adapter (all return `tool_calls=None` → `[]`, the existing
  default). No scoring change in this milestone.
  **[Fix #7 — preserve the not-applicable signal]** because `response.tool_calls or []`
  collapses `None` (adapter doesn't observe tools) and `[]` (agent observed zero) to `[]` in the
  persisted record, add an additive `AttemptRecord.tool_observed: bool = False`, set to
  `response.tool_calls is not None`, so report/TUI/score-diff (Phase 10) can still distinguish
  "side-effect not applicable" from "applicable, no calls". Additive default False → inert.
- `tests/test_sandbox.py`: `call` records `ToolCall`s in order (`ordinal` 0,1,2…);
  `count`/`called` correct for called/never-called tools; `snapshot()` shape
  `[{name,args,ordinal}, ...]`; a registered fake runs but performs **no real side effect**
  (e.g. assert no file created); fresh-registry isolation.
- `tests/test_runner_*`: add one additive case (or extend an existing runner test) asserting
  `AttemptRecord.tool_calls == []` for a plain `FakeAdapter` send (proves the flow is inert).

**Files**: `sandbox.py`, `targets/base.py`, `runner.py`, `tests/test_sandbox.py`, an additive
runner-test case.

**Checkpoint**
```
ruff check .
ruff format --check .
pytest -q   # FULL suite — base.py + runner.py touch shared paths; confirm the 226 prior tests stay green
```
Passing: the sandbox records tool calls with no side effects, `AdapterResponse.tool_calls` is
additive (default `None`), and the runner flows it into `AttemptRecord.tool_calls` inertly.
No scoring change yet; prior 226 tests green.

---

## Milestone 2 — Python-callable + agent-sandbox adapters + the demo weak agent (offline)

**Build**
- `src/gauntlet/agents/__init__.py` (NEW): `load_callable("module:attr")` — a tiny, safe
  importlib helper (`importlib.import_module` + `getattr`), raising `ConfigError` on a malformed
  spec / missing module / missing attribute / non-callable. **No arbitrary code beyond
  importing the named module** (the user opts in via config).
- `src/gauntlet/agents/demo.py` (NEW): `weak_agent(request: AdapterRequest, tools:
  ToolContext) -> str` — **[Fix #12]** registers fake `send_email(to, body)` /
  `delete_file(path)` recorders **per-call inside the callable body** (the `ToolContext` is fresh
  per `send`; module-level registration would reference a stale context), then **naively scans
  `request.prompt`** for instruction-shaped text and calls the matching fake tool with the
  attacker-supplied argument. **Deterministic** (same prompt → same calls), offline, no real side
  effect. This is the ROADMAP §9 deliberately-weak demo agent the agent pack reproducibly defeats.
- `src/gauntlet/targets/python_adapter.py` (NEW):
  - `PythonCallableAdapter` (`type: python`): wraps `fn(request) -> str | mapping`; `send`
    awaits a coroutine fn or calls a sync fn; returns `AdapterResponse(text=..., raw=...,
    provider="python", model=<entrypoint>, tool_calls=None)`. **No tool observation.**
  - `AgentSandboxAdapter` (`type: agent`): wraps `fn(request, tools) -> str`; per `send` builds
    a fresh `ToolRegistry`/`ToolContext`, invokes the agent, returns `AdapterResponse(text=...,
    provider="agent", model=<entrypoint>, tool_calls=registry.snapshot())` (a list).
    **[Fix #5 — async agent callables]** `send` uses `inspect.iscoroutinefunction(fn)` and
    `await`s a coroutine agent, calls a sync agent directly (mirror `PythonCallableAdapter`).
    Test BOTH a sync and an async agent callable (a coroutine agent must not yield a coroutine
    object as `text`).
- `tests/test_python_adapter.py`: `PythonCallableAdapter` over a str-returning callable →
  `tool_calls is None`; over an async callable too; `AgentSandboxAdapter` over `weak_agent` —
  an injected "send … to evil@x" payload → a recorded `send_email` call in `tool_calls`
  snapshot; a benign prompt → `tool_calls == []`; `load_callable` error cases (bad spec /
  missing attr / not callable).

**Files**: `agents/__init__.py`, `agents/demo.py`, `targets/python_adapter.py`,
`tests/test_python_adapter.py`.

**Checkpoint**
```
ruff check .
ruff format --check .
pytest tests/test_python_adapter.py tests/test_sandbox.py -q
pytest -q   # [Fix #14] also run the FULL suite to catch any import/name-collision regression early
```
Passing: both new adapters work offline; the demo weak agent deterministically records fake
tool calls; `load_callable` is safe and validated. No `build_target`/scoring wiring yet; prior
226 tests untouched.

---

## Milestone 3 — Safe side-effect assertion grammar (parser + evaluator), pure & offline

**Build**
- `src/gauntlet/sideeffect.py` (NEW): the restricted-grammar parser + evaluator (spec §6) —
  **NO `eval`/`exec`/`compile`**. A tiny tokenizer + matcher producing an `Assertion` value
  object; `parse_assertion(expr) -> Assertion`; `evaluate(expr, calls) -> bool` over a
  `list[ToolCall] | list[dict]`. Supported forms: `<tool>.called [== true|false]`,
  `<tool>.count <cmp> INT`, `<tool>.called_with('<substr>')[== true|false]`, and the
  `tool.calls['<name>'] <cmp> INT` alias. `called_with` = case-insensitive substring over
  `json.dumps(args, sort_keys=True)`; unknown tool ⇒ `count==0`/`called==false` (not an error).
  Anything outside the grammar raises `AssertionSyntaxError(ValueError)` naming the offending
  token.
- `tests/test_sideeffect_eval.py`: the full §6.2 matrix (each form + each comparator,
  `called_with` hit/miss, bracket alias, unknown-tool ⇒ false); the **safety set** —
  `os.system('x')`, `a and b`, arithmetic, bare ident, `send_email.count >= 'x'`,
  wrong-arity / unknown function → `AssertionSyntaxError`; an explicit assertion that the module
  source contains no `eval(`/`exec(` (cheap safety guard).

**Files**: `sideeffect.py`, `tests/test_sideeffect_eval.py`.

**Checkpoint**
```
ruff check .
ruff format --check .
pytest tests/test_sideeffect_eval.py -q
```
Passing: the evaluator parses and evaluates the full grammar over observed `ToolCall`s, rejects
everything outside it, and uses no `eval`. Pure/offline; prior 226 tests untouched (nothing
imports `sideeffect` yet).

---

## Milestone 4 — T4 side-effect scorer wired into `score_async` + not-applicable behavior

**Build**
- `src/gauntlet/scoring.py`:
  - Add `score_side_effect(check: SideEffectCheck, tool_calls) -> ScoreResult` (spec §7):
    `tool_calls is None` → `SKIPPED`, tier `None`, reason `not-applicable: side-effect check
    requires an agent target`; assertion **true** → `FAIL`/`T4` (attack succeeded — bad side
    effect happened); **false** → `PASS`/`T4`; `AssertionSyntaxError` → `ERROR`/`T4` with the
    message. `ScoreDetail(tier="T4", reason=..., matched=<tool/expr>)`.
  - **Sync `score()` is NOT modified** for side-effect — it keeps returning `SKIPPED` (the
    Phase-2..6 placeholder), so every test calling `score()` directly on a side-effect attack
    stays green.
  - **`score_async`**: for `check.type == "side-effect"`, return
    `score_side_effect(check, response.tool_calls if response is not None else None)`. This is
    **independent of the judge** (T4 is free/always-on). **[Fix #1 — CRITICAL position]** this
    side-effect branch MUST be placed **BEFORE** the `if not self._judge_enabled(): return base`
    early-return. The current `score_async` body is `base = self.score(...); if not
    self._judge_enabled(): return base; ...`; since `score()` returns SKIPPED for side-effect and
    the judge is OFF by default, inserting T4 inside the judge-enabled branch would silently
    yield SKIPPED for every agent target. Structure: compute `base = self.score(...)`; **if
    `check.type == "side-effect"`: return `score_side_effect(check, response.tool_calls...)`**;
    THEN the `if not self._judge_enabled(): return base` guard; THEN the judge/T3 logic.
    **[Inert refinement]** previously `score_async` returned the SKIPPED base for side-effect; now
    it evaluates T4 **only when an agent supplied `response.tool_calls` (not `None`)**. For every
    existing test (plain-LLM `FakeAdapter`, `tool_calls` defaults to `None`) the result is still
    SKIPPED → inert. Add a test asserting T4 fires for an agent response **with the judge
    DISABLED** (the default) — proving the position fix.
- `tests/test_scoring_t4.py`: `tool_calls=None` → SKIPPED/not-applicable; satisfied → FAIL/T4;
  unsatisfied → PASS/T4; bad assertion → ERROR/T4; `score_async` on a side-effect attack with an
  agent-style `AdapterResponse(tool_calls=[...])` evaluates T4, while sync `score()` on the same
  attack still returns SKIPPED; a plain-LLM response (`tool_calls=None`) via `score_async` stays
  SKIPPED (the inert-refinement proof).

**Files**: `scoring.py`, `tests/test_scoring_t4.py`.

**Checkpoint**
```
ruff check .
ruff format --check .
pytest tests/test_scoring_t4.py tests/test_scoring_t1.py tests/test_scoring_t2.py tests/test_scoring_t3.py -q
```
Then full suite:
```
pytest -q
```
Passing: T4 scores side-effect outcomes (FAIL/PASS/ERROR) for agent targets and stays
SKIPPED/not-applicable for plain-LLM targets; sync `score()` unchanged; the contract refinement
is inert. Prior 226 tests green.

---

## Milestone 5 — Bundled `tool-abuse` pack + config target-type extensions + `build_target` dispatch + integration

**Build**
- `src/gauntlet/config.py` (spec §10): extend `TargetConfig.type` to
  `Literal["http", "python", "agent", "mcp"]` (default `"http"`); make `provider`/`model`
  optional; add `entrypoint: str | None` and an `mcp: McpConfig | None` (+ `McpConfig`).
  **[Fix #2 — scope provider/collision checks]** in the `GauntletConfig` model-validator inner
  loop, add `if target.type != "http": continue` BEFORE the `provider not in known` /
  base_url / collision checks (otherwise `None not in known` is True → spurious ConfigError for
  python/agent/mcp targets). **[Fix #6 — re-require http fields]** since `provider`/`model` are
  now Optional at the field level (schema no longer protects), add a scoped check that raises
  `ConfigError` naming the target when `type == "http"` and `provider` or `model` is `None`
  (else `model=None` would propagate to `RunRecord.model: str` and blow up at record-build time
  instead of load time). For `python`/`agent` require `entrypoint` (else `ConfigError`); for
  `mcp` require an `mcp` block with `command` or `url`. Existing `http` configs validate
  identically (inert).
- `src/gauntlet/targets/__init__.py`: widen `build_target` return type to `TargetAdapter`
  (**[Fix #11]** grep callers for any `HTTPTargetAdapter`-specific attribute access after
  `build_target` and adjust — expected none); dispatch by `type` — `http` → `HTTPTargetAdapter`
  (unchanged); `python` → `PythonCallableAdapter(load_callable(entrypoint))`; `agent` →
  `AgentSandboxAdapter(load_callable(entrypoint))`; `mcp` → `MCPTargetAdapter` (M6; until then a
  clear `ConfigError`/`AdapterError` placeholder). `dry_run=True` builds the shell without
  invoking the callable / connecting. **[Fix #10]** update `resolve_target_info` ATOMICALLY with
  the `TargetConfig` change: for non-http types do NOT call `resolve_provider` (it would fail on
  `provider=None`); return synthetic `provider`/`model`/`base_url`/`api_style="n/a"` so the CLI
  `--dry-run` output (`info['api_style']`) works. Test dry-run with a non-http (agent) target.
- `src/gauntlet/packs/tool-abuse/*.yaml` (NEW data): 4–6 side-effect attacks (spec §9.2),
  `category: tool-abuse`, `success_when.type: side-effect`, clean Apache/MIT licenses,
  coherent ids/paths. **[Fix #3 — enumerate ALL four breaking `test_bundled_packs.py` tests]**
  (not just "count"): `test_loads_exactly_twelve` (`len == 12`), `test_category_counts`
  (`{"prompt-injection":6,"jailbreak":6}`), `test_list_packs_twelve_rows_license_ok` (`len ==
  12`), AND `test_all_fields_well_formed` which asserts `a.success_when.type == "string"` — the
  tool-abuse attacks are `side-effect`, so this one breaks for a NON-count reason. Update all
  four as deliberate additive contract changes (new totals + relax the type assertion to the
  per-category expectation). license/coherence gating already accept side-effect checks (schema
  shipped in Phase 2).
- **[Fix #8 — loader-side assertion validation: COMMITTED decision = HARD ERROR]** `load_packs`
  parses each `SideEffectCheck.assert_` via `parse_assertion` and raises `PackError` naming the
  file on a malformed assertion (fail fast). This is NON-breaking for string/classifier/judge
  packs (they have no `assert_`). Add a temp-fixture test: a side-effect pack with a malformed
  assert → `PackError`; the bundled tool-abuse packs all parse clean.
- `tests/test_pack_tool_abuse.py`: `load_packs()` includes the `tool-abuse` attacks (license +
  coherence pass); a `Runner` + `AgentSandboxAdapter(weak_agent)` + default `Scorer` over the
  pack → side-effect attacks score `FAIL`/`T4` with populated `AttemptRecord.tool_calls`; the
  **same** pack against a plain `FakeAdapter` (`tool_calls=None`) → all `SKIPPED`. Add an
  additive config test for the new target types (python/agent build + entrypoint-required
  validation).

**Files**: `config.py`, `targets/__init__.py`, `packs/tool-abuse/*.yaml`,
`tests/test_pack_tool_abuse.py`, additive cases in `tests/test_config.py` /
`tests/test_packloader.py` (count refinement).

**Checkpoint**
```
ruff check .
ruff format --check .
pytest -q
```
Passing: the **entire** suite is green offline (no keys/network/`mcp`/real side effects) — the
prior 226 tests plus the new Phase-7 tests; `build_target` constructs python/agent targets, the
`tool-abuse` pack reproducibly scores **FAIL/T4** against the demo agent and **SKIPPED** against
a plain LLM, and config extensions are additive. Satisfies spec §13 items 1–7.

---

## Milestone 6 (optional) — MCP target adapter interface behind a lazy guarded import

**Build**
- `src/gauntlet/targets/mcp_adapter.py` (NEW): `MCPTargetAdapter(TargetAdapter)` with an
  **injectable client seam** (`client=<fake>` for tests; `None` → build the real client from
  `McpConfig`). **Lazy guarded import**: no module-level `import mcp`; the real `mcp` import
  fires only inside connect/send, raising `AdapterError("MCP target requires the optional 'mcp'
  package; pip install gauntlet[mcp]")` on `ImportError`. `send` maps request → MCP tool
  interaction and returns `AdapterResponse(text=..., tool_calls=<observed MCP calls>)` so
  side-effect checks score MCP targets the same way.
- `src/gauntlet/targets/__init__.py`: replace the M5 `mcp` placeholder with the real dispatch
  (still lazy — construction stays offline; the `mcp` import only fires on connect/send).
- Declare `mcp` as an **optional extra** (`gauntlet[mcp]`) in packaging metadata — never a core
  dep (spec §11).
- `tests/test_mcp_adapter.py`: `MCPTargetAdapter` with a **fake injected client** → `send`
  returns text + observed `tool_calls` (offline, no `mcp`); the real (non-injected) path raises
  the guarded `AdapterError` when `mcp` is absent; `import gauntlet` / `import
  gauntlet.targets` does **not** import `mcp` (`assert "mcp" not in sys.modules`).
  **[Fix #13]** mark the "raises AdapterError when mcp absent" test with
  `@pytest.mark.skipif(importlib.util.find_spec("mcp") is not None, reason="mcp installed")` so
  if a future CI installs `mcp` the guard test is explicitly skipped (not silently passing while
  the no-mcp path goes unexercised).

**Files**: `targets/mcp_adapter.py`, `targets/__init__.py`, packaging extra,
`tests/test_mcp_adapter.py`.

**Checkpoint**
```
ruff check .
ruff format --check .
pytest -q   # passes with `mcp` NOT installed
```
Passing: the MCP adapter is an interface behind a lazy guarded import, interface-tested with a
fake client; `import gauntlet` never imports `mcp`; the real path fails clearly when `mcp` is
absent; the full suite is green without the `mcp` package. Satisfies spec §13 items 8–9.

> **Note on M6 optionality.** If M6 is deferred, M5 leaves `type: mcp` as a clear
> `ConfigError`/`AdapterError` ("MCP target not yet available") and Phase 7 still meets its core
> goal (Python-callable + agent sandbox + T4 side-effect scoring). M6 (and the MCP attack
> surface) can land with Phase 8.

---

## Plan review

1. **[BLOCKING] `score_async` early-return swallows T4 for default (judge-off) deployments.** Fixed (M4): the side-effect → `score_side_effect` return is placed BEFORE the `if not self._judge_enabled(): return base` guard; T4 is judge-independent. Test proves T4 fires with judge disabled.
2. **[BLOCKING] Config validator breaks for non-http targets when `provider=None`.** Fixed (M5): `if target.type != "http": continue` before provider/collision checks.
3. **[BLOCKING] Four `test_bundled_packs.py` tests break, not just counts.** Fixed (M5): enumerated all four incl. `test_all_fields_well_formed`'s `success_when.type == "string"` assertion.
4. **[BLOCKING] `ToolContext` bound-callable mechanism + reserved names unspecified.** Fixed (M1): `__getattr__` dispatch; reserved names (register/call/calls/count/called/snapshot) rejected in `register()`.
5. **Async agent callable support unspecified.** Fixed (M2): `inspect.iscoroutinefunction` + await in `AgentSandboxAdapter`; both sync/async tested.
6. **`model` optional removes http schema protection.** Fixed (M5): scoped ConfigError when type==http and provider/model None.
7. **`tool_calls or []` loses the not-applicable signal.** Fixed (M1): additive `AttemptRecord.tool_observed: bool = False`.
8. **Loader-side assertion validation undecided.** Fixed (M5): COMMITTED to hard error — `load_packs` parses each `assert_`, PackError on malformed; non-breaking for non-side-effect packs.
9. **`called_with` json.dumps on non-serializable args.** Fixed (M1): `ToolRegistry.call` enforces JSON-serializable kwargs at record time.
10. **`resolve_target_info` + dry-run gap for non-http.** Fixed (M5): updated atomically; non-http returns api_style "n/a" without resolve_provider; dry-run tested with agent target.
11. **`build_target` return-type widening.** Fixed (M5): widen to TargetAdapter + grep callers.
12. **Demo agent registration timing.** Fixed (M2): per-call registration inside the callable body (fresh ToolContext per send).
13. **MCP guard test silently skipped if mcp installed.** Fixed (M6): explicit `skipif(find_spec("mcp"))`.
14. **M2 checkpoint didn't run full suite.** Fixed (M2): added `pytest -q`.

**Resolution:** all four BLOCKING items (1–4) and the ten others (5–14) are folded into the
milestone build descriptions, test lists, and checkpoints above. Ready to implement.

STATUS: PASS
</content>
