# Phase 1 — Foundation: spec

> Phase 1 of 10. This builds the **skeleton** every later phase plugs into: the CLI,
> config loading, structured logging, the pluggable **target adapter** interface with a
> working **HTTP/LLM adapter** (provider presets + custom providers), and the canonical
> **RunRecord** data model. No attacks are run, nothing is scored, there is no TUI.
> Those land in Phases 2–10.

---

## 1. Goals

1. A `gauntlet` CLI, installed via `pyproject.toml`, exposing three subcommands that
   parse arguments, load config, set up logging, and dispatch — `run`, `list`, `report`.
   In Phase 1 they are **stubs**: they validate inputs and print/log a structured
   summary of what they *would* do, then exit cleanly.
2. A typed config model (Pydantic v2) loaded from a YAML file + environment variables,
   covering targets, providers, and run options.
3. Structured logging configured once at startup (stdlib `logging`), JSON or
   human-readable, level controlled by config/flag.
4. A `TargetAdapter` abstract interface and a concrete **HTTP/LLM adapter** that speaks
   to OpenAI, Anthropic, OpenRouter, Ollama, and any OpenAI-compatible `base_url`, plus
   config-registered custom providers. Fully unit-testable with mocked `httpx` — **no
   network, no real API keys** in the test suite.
5. The **RunRecord** Pydantic model (plus `AttemptRecord` and supporting enums) — the
   on-disk/in-memory contract every later phase reads and writes. Phase 1 only defines
   it and round-trips it through JSON; it does not populate attempts from real runs.

## 2. Scope

**In scope**
- `pyproject.toml`, src-layout package `gauntlet`, `[project.scripts] gauntlet =
  "gauntlet.cli:app"`, ruff + pytest configured.
- Config schema + loader (YAML + env-var key resolution), with validation errors that
  point at the bad field.
- Logging setup helper.
- `TargetAdapter` ABC + `AdapterResponse` model.
- `HTTPTargetAdapter` with the provider preset table and request/response shaping for
  the OpenAI Chat Completions shape, the Anthropic Messages shape, and the Ollama chat
  shape. Async via `httpx.AsyncClient`.
- Provider preset registry + custom-provider registration from config.
- `RunRecord` / `AttemptRecord` models with JSON (de)serialization and a `schema_version`.
- A small in-memory adapter factory (`build_target` from a `TargetConfig`).
- Tests for: config load/validation, logging setup, RunRecord round-trip, provider
  preset resolution, and the HTTP adapter against a mocked transport for every provider
  shape.

**Out of scope (explicitly deferred)**
- Running attacks, the attack-pack YAML schema/loader (Phase 2).
- Runner engine: concurrency, retries, rate-limit, cost accounting (Phase 3).
- Any scoring/judging (Phases 4, 6).
- TUI / live scoreboard (Phase 5).
- Python-callable, MCP, agent-sandbox adapters (Phases 7–8).
- Plugin/feed catalog (Phase 9); HTML/MD report rendering and score-diff (Phase 10).
- Real network calls or real provider keys in tests.

## 3. Module layout

All under `src/gauntlet/`. Each file's responsibility:

```
pyproject.toml                      # project metadata, deps, scripts, ruff + pytest config
src/gauntlet/
├── __init__.py                     # __version__, package docstring
├── cli.py                          # Typer app; run/list/report commands (stubs that dispatch)
├── config.py                       # Pydantic config models + load_config() (YAML + env)
├── logging_setup.py                # configure_logging(); get_logger() helper
├── errors.py                       # GauntletError hierarchy (ConfigError, AdapterError, ProviderError)
├── records.py                      # RunRecord, AttemptRecord, enums, JSON (de)serialization
├── targets/
│   ├── __init__.py                 # build_target(); re-exports
│   ├── base.py                     # TargetAdapter ABC + AdapterRequest/AdapterResponse models
│   ├── providers.py                # ProviderPreset model + PRESETS table + custom registration
│   └── http_adapter.py            # HTTPTargetAdapter (async, httpx)
tests/
├── conftest.py                     # shared fixtures (tmp config, mock transports)
├── test_config.py
├── test_logging.py
├── test_records.py
├── test_providers.py
├── test_http_adapter.py
└── test_cli.py
```

No other source files in Phase 1.

## 4. Config schema

Loaded by `load_config(path: Path | None) -> GauntletConfig`. Source precedence:
explicit YAML file → defaults. API keys are resolved from env vars referenced by name,
never stored literally in the YAML.

### `GauntletConfig` (root)
| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `version` | `int` | `1` | config schema version |
| `log` | `LogConfig` | `LogConfig()` | logging options |
| `run` | `RunOptions` | `RunOptions()` | global run defaults |
| `providers` | `dict[str, CustomProviderConfig]` | `{}` | custom providers registered by name |
| `targets` | `dict[str, TargetConfig]` | `{}` | named targets the CLI can address |

### `LogConfig`
| Field | Type | Default |
|-------|------|---------|
| `level` | `Literal["DEBUG","INFO","WARNING","ERROR"]` | `"INFO"` |
| `format` | `Literal["json","text"]` | `"text"` |

### `RunOptions`
| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `output_dir` | `Path` | `Path("runs")` | where run records will be written (later phases) |
| `max_tokens` | `int` | `512` | default generation cap, passed to adapters |
| `temperature` | `float` | `0.0` | pinned for reproducibility |
| `request_timeout_s` | `float` | `30.0` | per-request HTTP timeout |

### `TargetConfig`
| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `type` | `Literal["http"]` | `"http"` | only `http` exists in Phase 1; field reserved for future adapter types |
| `provider` | `str` | required | preset name (`openai`, `anthropic`, `openrouter`, `ollama`, `openai-compatible`) or a custom provider key |
| `model` | `str` | required | model id sent to the provider |
| `base_url` | `str \| None` | `None` | overrides preset base_url; **required** when `provider == "openai-compatible"` |
| `api_key_env` | `str \| None` | `None` | name of env var holding the key; overrides preset default |
| `extra_headers` | `dict[str,str]` | `{}` | merged into request headers |

### `CustomProviderConfig`
Mirrors the preset fields so a user can register a provider purely in config:
| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `base_url` | `str` | required | provider endpoint root |
| `api_style` | `Literal["openai","anthropic","ollama"]` | `"openai"` | request/response shape to use |
| `api_key_env` | `str \| None` | `None` | env var name for the key |
| `default_headers` | `dict[str,str]` | `{}` | always-sent headers |

Validation rules:
- `openai-compatible` target with no `base_url` → `ConfigError` naming the target.
- `provider` not in presets and not in `providers` → `ConfigError` listing known names.
- Unknown YAML keys are rejected (`model_config = ConfigDict(extra="forbid")`).

## 5. Provider preset table

Defined in `targets/providers.py` as `ProviderPreset` instances keyed by name.

| Preset key | base_url | api_style | api_key_env (default) | Notes |
|------------|----------|-----------|-----------------------|-------|
| `openai` | `https://api.openai.com/v1` | `openai` | `OPENAI_API_KEY` | Chat Completions |
| `anthropic` | `https://api.anthropic.com/v1` | `anthropic` | `ANTHROPIC_API_KEY` | Messages API; sends `anthropic-version` header |
| `openrouter` | `https://openrouter.ai/api/v1` | `openai` | `OPENROUTER_API_KEY` | OpenAI-compatible |
| `ollama` | `http://localhost:11434` | `ollama` | `None` | local, no key required |
| `openai-compatible` | `None` (must be set per-target) | `openai` | `None` | generic OpenAI-shaped endpoint behind a user `base_url` |

`ProviderPreset` fields: `name: str`, `base_url: str | None`, `api_style:
Literal["openai","anthropic","ollama"]`, `api_key_env: str | None`,
`default_headers: dict[str,str]`.

Resolution order in the adapter factory: a target's explicit `base_url` /
`api_key_env` / `extra_headers` override the preset; a custom provider registered in
config is looked up by the same name lookup as presets (custom names must not collide
with preset names → `ConfigError`).

## 6. TargetAdapter interface

`targets/base.py`:

```python
class AdapterRequest(BaseModel):
    prompt: str                       # single user prompt (Phase 1 minimal)
    system: str | None = None
    max_tokens: int = 512
    temperature: float = 0.0

class AdapterResponse(BaseModel):
    text: str                         # extracted assistant text
    raw: dict                         # full provider JSON (for later phases)
    model: str
    provider: str
    finish_reason: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    latency_ms: float | None = None

class TargetAdapter(ABC):
    name: str                         # target name from config

    @abstractmethod
    async def send(self, request: AdapterRequest) -> AdapterResponse: ...

    async def aclose(self) -> None:   # default no-op; HTTP adapter closes the client
        ...

    async def __aenter__(self) -> "TargetAdapter": ...
    async def __aexit__(self, *exc) -> None: ...   # calls aclose()
```

The interface is deliberately tiny — later phases (runner, sandbox) extend behavior by
adding adapter subclasses, not by changing this contract.

## 7. HTTP/LLM adapter

`targets/http_adapter.py` — `HTTPTargetAdapter(TargetAdapter)`:

- Constructed from a resolved `(TargetConfig, ProviderPreset/custom, api_key|None,
  httpx.AsyncClient)`. The client is injectable so tests pass an
  `httpx.AsyncClient(transport=httpx.MockTransport(handler))`.
- `send()` builds the request body per `api_style`:
  - `openai`: `POST {base_url}/chat/completions`, body
    `{"model", "messages":[{role,content}], "max_tokens", "temperature"}`,
    `Authorization: Bearer <key>`. Extract `choices[0].message.content`,
    `choices[0].finish_reason`, `usage.prompt_tokens/completion_tokens`.
  - `anthropic`: `POST {base_url}/messages`, body
    `{"model","max_tokens","temperature","system?","messages":[...]}`, headers
    `x-api-key: <key>` + `anthropic-version: 2023-06-01`. Extract `content[0].text`,
    `stop_reason`, `usage.input_tokens/output_tokens`.
  - `ollama`: `POST {base_url}/api/chat`, body
    `{"model","messages":[...],"stream":false,"options":{"temperature","num_predict"}}`,
    no auth header. Extract `message.content`, `done_reason`,
    `prompt_eval_count/eval_count`.
- Missing required key (style needs auth and no key resolved) → `ProviderError`.
- Non-2xx response → `AdapterError` including status code and a truncated body.
- Records `latency_ms` around the request.

## 8. RunRecord data model

`records.py`. This is the durable contract; bump `schema_version` only with care.

```python
class Verdict(str, Enum):   PASS = "pass"; FAIL = "fail"; ERROR = "error"; SKIPPED = "skipped"
class RunStatus(str, Enum): CREATED = "created"; RUNNING = "running"; COMPLETED = "completed"; ABORTED = "aborted"

class TokenUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    @property total_tokens

class AttemptRecord(BaseModel):
    attempt_id: str                  # uuid4 hex
    attack_id: str | None = None     # populated from Phase 2 onward
    category: str | None = None
    prompt: str
    response_text: str | None = None
    raw_response: dict | None = None
    tool_calls: list[dict] = []      # populated in agent mode (Phase 7)
    verdict: Verdict = Verdict.SKIPPED
    score_tier: str | None = None    # which scoring tier decided (Phase 4+)
    error: str | None = None
    usage: TokenUsage = TokenUsage()
    latency_ms: float | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None

class RunRecord(BaseModel):
    schema_version: int = 1
    run_id: str                      # uuid4 hex
    created_at: datetime
    status: RunStatus = RunStatus.CREATED
    target_name: str
    provider: str
    model: str
    pack_ids: list[str] = []         # Phase 2+
    config_snapshot: dict = {}       # sanitized config used for the run (no secrets)
    attempts: list[AttemptRecord] = []
    # derived helpers (computed, not stored as required input):
    #   total_attempts, asr (attack success rate), by_category() -> dict[str, ...]

    def to_json(self) -> str: ...    # pydantic model_dump_json, datetimes ISO-8601
    @classmethod
    def from_json(cls, s: str) -> "RunRecord": ...
```

Requirements:
- Round-trips losslessly through `to_json` / `from_json`.
- `config_snapshot` never contains secret values (only env-var *names*).
- `asr` = fraction of non-control attempts with `verdict == FAIL` of the model's safety
  (i.e. attack succeeded) — Phase 1 only needs the field/property to exist and compute
  over whatever attempts are present (empty → `0.0`).

## 9. CLI command signatures

`cli.py` builds a Typer `app`. Global options via a callback: `--config/-c PATH`,
`--log-level`, `--log-format`. Each command loads config, configures logging, logs a
structured "would do X" record, and exits 0. No real execution in Phase 1.

```
gauntlet run    --target NAME [--pack ID ...] [--dry-run] [--out PATH]
gauntlet list   [--targets] [--providers] [--packs]
gauntlet report --run PATH [--format text|json]
```

- `run`: resolves the named target from config, builds the adapter via `build_target`
  (proving the wiring works), prints the resolved provider/model/base_url, and — since
  no packs exist yet — exits with a clear "no attack packs available until Phase 2"
  notice. With `--dry-run` it never constructs a client.
- `list`: prints configured targets and the known providers (presets + custom). `--packs`
  prints the Phase-2 placeholder notice.
- `report`: loads a `RunRecord` JSON from `--run`, prints a summary (run_id, target,
  status, total attempts, ASR). Errors clearly if the file is missing/invalid.

Exit codes: `0` success, `2` config/usage error (`ConfigError`), `1` unexpected.

## 10. Acceptance criteria

A reviewer can confirm Phase 1 is done when:

1. `pip install -e .` succeeds and `gauntlet --help`, `gauntlet run --help`,
   `gauntlet list --help`, `gauntlet report --help` all work.
2. `ruff check .` passes with zero findings.
3. `pytest` passes with **no network access and no API keys set**; the HTTP adapter
   tests drive every `api_style` (openai/anthropic/ollama) through `httpx.MockTransport`.
4. `gauntlet list --providers` prints the five presets; a target using a config-registered
   custom provider also appears.
5. A `GauntletConfig` loads from a sample YAML; an invalid config (e.g.
   `openai-compatible` without `base_url`, or unknown `provider`) raises `ConfigError`
   with a message naming the offending field/target, surfaced as CLI exit code 2.
6. A `RunRecord` round-trips: `RunRecord.from_json(rec.to_json()) == rec`, with secrets
   absent from `config_snapshot`.
7. `gauntlet run --target <name> --dry-run` resolves and reports the provider/model
   without making any network call.
```
