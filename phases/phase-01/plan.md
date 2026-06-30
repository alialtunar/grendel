# Phase 1 — Foundation: implementation plan

> Build order is dependency-ordered: scaffolding + config → logging + records →
> adapters → CLI wiring → integration. Every milestone ends in a **Checkpoint** with
> exact commands. The quality gate for the whole phase is `ruff check .` (zero findings)
> and `pytest` (green, offline, no API keys). Target: Python 3.11+, src-layout package
> `gauntlet`. Dependencies are pinned minimal: `typer`, `pydantic>=2`, `httpx`,
> `pyyaml`; dev: `ruff`, `pytest`, `pytest-asyncio`.

---

## Milestone 1 — Project scaffolding + config

**Build**
- `pyproject.toml`: project metadata, `requires-python = ">=3.11"`, runtime deps
  (`typer`, `pydantic>=2`, `httpx`, `pyyaml`), optional `dev` extra
  (`ruff`, `pytest`, `pytest-asyncio`), `[project.scripts] gauntlet = "gauntlet.cli:app"`,
  src-layout build config, and `[tool.ruff]` + `[tool.pytest.ini_options]`
  (`asyncio_mode = "auto"`). Pin `pytest-asyncio>=0.21,<1`. Configure
  `[tool.ruff.format]` and add `ruff format --check .` to every checkpoint.
- `src/gauntlet/__init__.py` with `__version__`.
- `src/gauntlet/errors.py`: `GauntletError` base + `ConfigError`, `AdapterError`,
  `ProviderError`.
- `src/gauntlet/config.py`: `GauntletConfig`, `LogConfig`, `RunOptions`, `TargetConfig`,
  `CustomProviderConfig` (all `extra="forbid"`), and `load_config(path) -> GauntletConfig`
  that reads YAML and applies validation rules from spec §4. Validation failures raise
  `ConfigError` naming the field/target.
  **[Fix #1 — load-time collision check]** Add a `model_validator(mode="after")` on
  `GauntletConfig` that rejects any `providers` key colliding with a `PRESETS` name,
  raising `ConfigError` naming the offending key — so the error surfaces at
  `load_config()` time (spec §10 #5), not lazily at command time. (`config.py` imports
  the preset *names* only to avoid a heavy import cycle.)
- A sample `examples/gauntlet.example.yaml` (one openai target, one openai-compatible
  target, one custom provider) for tests and docs.
- `tests/conftest.py` (tmp-path config fixture) and `tests/test_config.py`.

**Files**: `pyproject.toml`, `src/gauntlet/{__init__,errors,config}.py`,
`examples/gauntlet.example.yaml`, `tests/conftest.py`, `tests/test_config.py`.

**Checkpoint**
```
pip install -e ".[dev]"
ruff check .
pytest tests/test_config.py -q
```
Passing looks like: install succeeds; ruff clean; tests prove (a) the example YAML
loads into a `GauntletConfig`, (b) defaults are applied, (c) `openai-compatible` without
`base_url` raises `ConfigError`, (d) an unknown `provider` raises `ConfigError`, (e) an
unknown YAML key is rejected.

---

## Milestone 2 — Logging + RunRecord

**Build**
- `src/gauntlet/logging_setup.py`: `configure_logging(level, fmt)` installing a stdlib
  handler — a JSON formatter for `fmt="json"`, a concise human formatter for `"text"`;
  idempotent (safe to call twice). `get_logger(name)` helper.
- `src/gauntlet/records.py`: `Verdict`, `RunStatus`, `TokenUsage`, `AttemptRecord`,
  `RunRecord` per spec §8, with `to_json`/`from_json`, `total_attempts`, `asr`, and
  `by_category()`. `make_run_record(...)` constructor helper that fills `run_id`,
  `created_at`, and a sanitized `config_snapshot` (env-var names only, no secret values).
  **[Fix #3] `by_category()` returns `dict[str, list[AttemptRecord]]`** (attempts grouped
  by `category`; `None` category grouped under key `"uncategorized"`). The M2 test asserts
  a 3-attempt / 2-category list yields a dict with the correct keyed subsets.
  **[Fix #4] Phase-1 `asr` formula:** `len([a for a in attempts if a.verdict ==
  Verdict.FAIL]) / len(attempts)` if attempts else `0.0`; the non-control filter is
  deferred to Phase 6 when `is_control` is added.
  **[Fix #9] `config_snapshot` is built by `config.model_dump(mode="json")`** with no
  env-var resolution. The test sets `OPENAI_API_KEY=sk-test` and asserts that `sk-test`
  does not appear anywhere in `json.dumps(record.config_snapshot)`.
- `tests/test_logging.py`, `tests/test_records.py`.

**Files**: `src/gauntlet/{logging_setup,records}.py`,
`tests/test_logging.py`, `tests/test_records.py`.

**Checkpoint**
```
ruff check .
pytest tests/test_logging.py tests/test_records.py -q
```
Passing looks like: logging test asserts JSON lines parse and the level filter works;
records test asserts `RunRecord.from_json(rec.to_json()) == rec`, `asr == 0.0` for empty
attempts and computes correctly for a mixed list, and `config_snapshot` contains no
secret values.

---

## Milestone 3 — TargetAdapter interface + HTTP adapter + providers

**Build**
- `src/gauntlet/targets/base.py`: `AdapterRequest`, `AdapterResponse`, `TargetAdapter`
  ABC with async `send`, `aclose`, and async-context-manager support (spec §6).
- `src/gauntlet/targets/providers.py`: `ProviderPreset` model + `PRESETS` table (spec §5)
  + `resolve_provider(name, config)` that returns a preset or a custom provider, raising
  `ConfigError` on collisions/unknown names.
- `src/gauntlet/targets/http_adapter.py`: `HTTPTargetAdapter` with request shaping +
  response parsing for `openai`, `anthropic`, `ollama` styles; injectable
  `httpx.AsyncClient`; `ProviderError` on missing key, `AdapterError` on non-2xx
  (spec §7).
- `src/gauntlet/targets/__init__.py`: `build_target(name, config, client=None, dry_run=False)`
  factory that resolves provider + key (from `os.environ[api_key_env]`) and returns a wired
  `HTTPTargetAdapter`. **[Fix #2 — dry-run boundary]** when `dry_run=True` it skips BOTH
  env-var key resolution and `httpx.AsyncClient` construction (so `run --dry-run` works
  offline with no keys, spec §10 #7); also expose `resolve_target_info(name, config) ->
  dict` (provider/model/base_url/api_style) used by `run --dry-run` and `list`.
  **[Fix #8 — client ownership]** when `client=None` the returned adapter owns the client
  it creates; callers must `async with adapter:` or `await adapter.aclose()`. Tests must
  close the adapter before the loop tears down.
  **[Fix #1 — collision]** the load-time collision check lives in `config.py` (M1); the
  duplicate check in `resolve_provider` is a defensive backstop only.
- `tests/test_providers.py`, `tests/test_http_adapter.py` using
  `httpx.MockTransport` handlers that return canned OpenAI/Anthropic/Ollama JSON — **no
  network, no keys** (set dummy env vars inside the test).

**Files**: `src/gauntlet/targets/{__init__,base,providers,http_adapter}.py`,
`tests/test_providers.py`, `tests/test_http_adapter.py`.

**Checkpoint**
```
ruff check .
pytest tests/test_providers.py tests/test_http_adapter.py -q
```
Passing looks like: providers test asserts the five presets resolve, custom-provider
lookup works, and a name collision raises `ConfigError`; adapter test drives all three
`api_style`s through `MockTransport`, asserting `AdapterResponse.text`/usage/finish_reason
extraction, that a non-2xx raises `AdapterError`, and that a missing required key raises
`ProviderError` — all with no real network.

---

## Milestone 4 — CLI wiring

**Build**
- `src/gauntlet/cli.py`: Typer `app` with a global callback (`--config/-c`,
  `--log-level`, `--log-format`) that loads config + configures logging into the Typer
  context. Commands `run`, `list`, `report` per spec §9 — stubs that parse, dispatch,
  log a structured summary, and exit. `run` calls `build_target(..., dry_run=...)` and
  prints the resolved provider/model/base_url, then the Phase-2 "no packs yet" notice.
  `report` loads a `RunRecord` and prints a summary. Map `ConfigError` → exit code 2.
  **[Fix #7 — state passing]** the global callback uses `ctx.ensure_object(dict)` and
  stores `ctx.obj["config"]`; each command takes `ctx: typer.Context` and reads `ctx.obj`
  (no module-level globals — `CliRunner` reuses the process across invocations).
- `tests/test_cli.py` using `typer.testing.CliRunner`.

**Files**: `src/gauntlet/cli.py`, `tests/test_cli.py`.

**Checkpoint**
```
ruff check .
pytest tests/test_cli.py -q
gauntlet --help
gauntlet list --providers -c examples/gauntlet.example.yaml
```
Passing looks like: CLI tests assert `--help` for all commands, `list --providers` prints
the five presets plus the custom one, `run --target <name> --dry-run` reports the resolved
provider/model with no network call, an invalid config yields exit code 2, and `report`
on a written `RunRecord` JSON prints its summary.

---

## Milestone 5 — Integration test + phase gate

**Build**
- `tests/test_integration.py`: an end-to-end offline flow — load the example config,
  build a target backed by a `MockTransport`, send one `AdapterRequest`, fold the
  response into an `AttemptRecord`, assemble a `RunRecord`, write it to disk, then run
  `gauntlet report --run <file>` via `CliRunner` and assert the summary. Proves every
  Phase-1 piece composes without touching the network.
- Final cleanup pass: docstrings, ensure `ruff` clean across the tree, confirm
  `asyncio_mode = "auto"` so async tests need no decorators.

**Files**: `tests/test_integration.py` (+ any small fixes surfaced).

**Checkpoint**
```
ruff check .
pytest -q
```
Passing looks like: the **entire** suite is green offline with no API keys set, ruff
reports zero findings, and the integration test demonstrates config → adapter →
AttemptRecord → RunRecord → `gauntlet report` end to end. This satisfies all acceptance
criteria in spec §10.
```

---

## Plan review

1. **[BLOCKING] Custom-provider collision check is misplaced — it must live in `load_config()`, not `resolve_provider()`.** A config with a collision would otherwise pass `load_config()` silently and only error at command time, violating spec §10 #5. Fix: a `model_validator(mode="after")` on `GauntletConfig` cross-checks `providers` keys against `PRESETS`.
2. **[BLOCKING] `--dry-run` vs `build_target()` key-resolution boundary undefined**, making acceptance criterion 7 untestable offline. Fix: `build_target(..., dry_run=True)` skips key resolution AND client construction; `resolve_target_info()` returns provider/model/base_url without reading env vars.
3. **[BLOCKING] `by_category()` return type undefined.** Fix: lock to `dict[str, list[AttemptRecord]]`, `None` → `"uncategorized"`; M2 test asserts the keyed subsets.
4. **`asr` Phase-1 semantics** — no `is_control` field yet. Fix: Phase-1 formula = FAIL fraction over all attempts; control filter deferred to Phase 6.
5. **`pytest-asyncio` unpinned.** Fix: pin `>=0.21,<1` in the dev extra.
6. **`ruff format --check .` absent from checkpoints.** Fix: add to every checkpoint + configure `[tool.ruff.format]`.
7. **Typer state-passing pattern unnamed** (risk of module globals breaking `CliRunner`). Fix: `ctx.ensure_object(dict)` + `ctx.obj["config"]`.
8. **`build_target()` client ownership unstated** (leaked `AsyncClient` → `ResourceWarning`). Fix: adapter owns its created client; tests close it.
9. **`make_run_record()` sanitization unspecified.** Fix: `config.model_dump(mode="json")`; test asserts no secret value leaks into `config_snapshot`.

**Resolution (applied to milestones above before implementation):** all three BLOCKING
items (1, 2, 3) and the six non-blocking items (4–9) have been folded into the relevant
milestone build descriptions and checkpoints above. Plan is ready to implement.

STATUS: PASS
