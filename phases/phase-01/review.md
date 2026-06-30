# Phase 1 Review

Reviewer: Claude (independent). Diff base: `git diff HEAD~1 HEAD`. Tests verified live.

---

## Verified gates

- `ruff check .` — clean (confirmed)
- `ruff format --check .` — 18 files already formatted (confirmed)
- `pytest -q` — 41/41 passed, offline, no API keys (confirmed)

---

## Findings

### 1. Collision validator — correct and load-time (plan Fix #1, spec §10 #5)

`GauntletConfig._check_provider_collisions_and_targets` is a `model_validator(mode="after")`. It fires inside `GauntletConfig.model_validate(raw)` which is called by `load_config()`. `PRESETS` is imported lazily inside the validator to avoid the import cycle with `targets.providers`. The test `test_custom_provider_preset_collision_raises` writes a YAML with `providers.openai` and asserts `ConfigError` from `load_config()` — not from a later command call. Implementation matches the plan's intent.

The defensive backstop in `resolve_provider()` is present and tested (`test_collision_backstop_raises` mutates `cfg.providers` after construction to bypass the load-time check, then asserts the backstop fires).

### 2. Dry-run boundary — enforced correctly (plan Fix #2, spec §10 #7)

`build_target(dry_run=True)` passes `api_key=None`, `client=None`, `owns_client=False` to `HTTPTargetAdapter`. No `os.environ` read, no `httpx.AsyncClient` construction. `resolve_target_info()` calls only `resolve_provider()` and `_resolve_base_url()` — no env access. `send()` on a dry-run adapter raises `AdapterError("has no HTTP client (built with dry_run=True)")` rather than silently returning nothing. `test_run_dry_run_offline` deletes `OPENAI_API_KEY` and asserts exit code 0 with provider/model in output.

### 3. RunRecord round-trip and no-secret-leak (plan Fixes #4, #9, spec §8, §10 #6)

`to_json()` delegates to `model_dump_json()` (ISO-8601 UTC datetimes). `from_json()` delegates to `model_validate_json()`. `test_roundtrip_equal` asserts equality after a round-trip with two `AttemptRecord`s containing datetime fields.

`make_run_record()` uses `config.model_dump(mode="json")` which serialises `api_key_env` string names but never resolves env vars. `test_config_snapshot_no_secret` sets `OPENAI_API_KEY=sk-test` and asserts `"sk-test" not in json.dumps(record.config_snapshot)`. `test_full_offline_flow` also asserts the written JSON file contains no `sk-dummy`.

`asr` formula: `len(FAILs) / len(attempts)` if attempts else `0.0` (no `is_control` filter — correctly deferred to Phase 6). Test covers empty list, mixed verdicts (0.5), and the 2-category grouping case.

### 4. Three api_styles — all implemented and tested offline (spec §7)

- **openai**: `POST {base_url}/chat/completions`, `Authorization: Bearer <key>`, parses `choices[0].message.content`, `usage.prompt_tokens/completion_tokens`.
- **anthropic**: `POST {base_url}/messages`, `x-api-key: <key>` + `anthropic-version: 2023-06-01`, parses `content[0].text`, `usage.input_tokens/output_tokens`.
- **ollama**: `POST {base_url}/api/chat`, no auth, `stream: false`, `options.{temperature,num_predict}`, parses `message.content`, `prompt_eval_count/eval_count`.

All three are driven through `httpx.MockTransport` in `test_http_adapter.py`. Non-2xx and missing-key paths are also covered without network access.

### 5. Client ownership (plan Fix #8)

`build_target()` sets `owns_client = (client is None)` and passes it to the adapter. `aclose()` only closes the client when `owns_client` is True. `test_owns_created_client_closes` asserts `adapter._owns_client is True` when no client is injected. The integration test passes an external client, uses `async with build_target(...)`, then calls `await client.aclose()` explicitly — no leak.

### 6. CLI state passing — no module globals (plan Fix #7)

`main()` callback calls `ctx.ensure_object(dict)` and stores `ctx.obj["config"]`. Each command reads `ctx.obj` via `_resolve_config()`. `CliRunner` tests reuse the process without cross-contamination.

### 7. Minor observations (non-blocking)

**7a. `anthropic-version` header applied twice, harmlessly.** The `anthropic` preset declares `default_headers={"anthropic-version": "2023-06-01"}`. `HTTPTargetAdapter.__init__` copies these into `self.extra_headers`. `_build_request()` then also calls `headers.setdefault("anthropic-version", "2023-06-01")`, which is a no-op because the key is already present. The redundant `setdefault` could be removed, but it causes no incorrect behaviour.

**7b. `configure_logging` clears and reinstalls the handler on every call** rather than skipping if already configured with the same args. The test `test_idempotent_single_handler` verifies exactly 1 handler after two calls with identical args, which passes. The plan's "safe to call twice" requirement is satisfied.

**7c. `run` command without `--dry-run` creates and immediately closes a real `AsyncClient`.** No requests are sent in Phase 1 (the "no attack packs" stub path), so the client is wasted. This is correct Phase 1 stub behaviour; the close happens before any output, so there is no resource leak.

**7d. No test exercises `gauntlet run --target <name>` *without* `--dry-run` when a key is absent.** In that path, `build_target()` resolves `api_key=None` (env var unset), creates the adapter, and the CLI closes it without ever calling `send()`. No `ProviderError` is raised at Phase 1. This is by design (Phase 1 sends nothing), but worth noting for Phase 3 when `send()` is actually called.

---

STATUS: PASS
