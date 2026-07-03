# Phase 12 — Everything configurable from the terminal: spec

> Phase 12 of 14. Implements ROADMAP §8.12: *"Everything configurable from the terminal — run the
> whole tool with **no config file**: select/connect a target from flags
> (`--model`/`--agent`/`--python`/`--mcp-*`), and set proxy host/port/routes, output dirs, and
> import dirs from the CLI. Config files become optional."*
>
> **Three deliverables, all offline + deterministically testable:**
> 1. **Ad-hoc target from flags** on `grendel run` — build and connect a target entirely from CLI
>    options, with **no `--config` and no `--target`** required: an HTTP/LLM target from
>    `--provider`/`--model` (`--base-url`/`--api-key-env`/`--header` for OpenAI-compatible/custom),
>    a Python-callable target from `--python module:attr`, an agent-sandbox target from
>    `--agent module:attr`, and an MCP target from `--mcp-command`/`--mcp-url`/`--mcp-fake-client`/
>    `--mcp-tool`. Exactly one target *source* must be given (a named `--target`, or one flag group);
>    the flags synthesize a `TargetConfig`, inject it under a synthetic name, and **reuse the entire
>    existing `resolve_target_info` / `build_target` path** — no adapter logic is duplicated.
> 2. **Output + import dirs from the CLI** — `run` gains `--output-dir DIR` (overrides
>    `run.output_dir`, where records are written) and `--pack-dir DIR` (repeatable; appends user pack
>    directories to the catalog); `list` also gains `--pack-dir`. So the record location and the
>    attack catalog are fully CLI-driven.
> 3. **Proxy configurable from the terminal** — a new `ProxyConfig` (host/port/routes) on
>    `GrendelConfig` and a new `grendel proxy` command that merges `--host`/`--port`/`--route` over
>    any config and **prints the resolved, validated proxy configuration**. *Serving is Phase 13* —
>    this phase makes the proxy **configurable and previewable** from the terminal (the config surface
>    ROADMAP §12 asks for); the actual OpenAI-compatible server lands in Phase 13, consuming exactly
>    this `ProxyConfig`.
>
> **Additive + default-safe.** `--config` stays supported and behaves exactly as before; a named
> `--target` from a config file still works unchanged. No scoring/runner/records/target-adapter
> behaviour changes — only the CLI surface + two small additive config models (`ProxyConfig`, and
> nothing else changes on existing models). The prior **434** tests (1 skipped) stay green; new tests
> cover the flag-target synthesis, the dir flags, the `proxy` command, and the exactly-one-source
> validation. Everything offline, no network / no API keys.

---

## 1. Goals

1. **Run with no config file.** `grendel run` no longer *requires* `--config` or a configured
   `--target`. A target can be fully specified by flags; with no flags and no `--target` it is a
   usage error (exit 2) naming the four ways to specify one.
2. **All four target types from flags**, mapping 1:1 to the existing `TargetConfig.type`:
   - **http:** `--provider NAME --model MODEL` (+ optional `--base-url`, `--api-key-env`,
     `--header k=v` repeatable). Reuses the provider presets + custom-provider validation.
   - **python:** `--python module:attr` → `type=python`, `entrypoint=module:attr`.
   - **agent:** `--agent module:attr` → `type=agent`, `entrypoint=module:attr`.
   - **mcp:** `--mcp-command "cmd arg…"` **or** `--mcp-url URL` **or** `--mcp-fake-client module:attr`
     (+ optional `--mcp-tool`) → `type=mcp` with the matching `McpConfig`.
3. **Exactly-one-target-source.** The user gives **either** `--target NAME` (a config-defined target)
   **or** exactly one flag group (http / python / agent / mcp). Zero sources, or more than one, →
   exit 2 with a clear message. The synthesized target is validated by the **same** `GrendelConfig`
   cross-checks (unknown provider, missing base_url for openai-compatible, etc.).
4. **Output + import dirs from flags.** `run --output-dir DIR` overrides `run.output_dir`;
   `run --pack-dir DIR` (repeatable) and `list --pack-dir DIR` append to `catalog.pack_dirs` (so the
   catalog is CLI-driven, config-free). Relative paths resolve against the process cwd.
5. **Proxy config from the terminal.** `ProxyConfig{host, port, routes}` on `GrendelConfig`
   (defaults: `127.0.0.1:8100`, routes empty). `grendel proxy [--host H] [--port P]
   [--route PATH=PROVIDER …] [--config C]` merges flags over config, validates (port range, route
   PATH starts `/`, PROVIDER is a known preset or custom provider), and prints the resolved config.
   **No server yet** — a one-line note says serving arrives in Phase 13.
6. Everything `pytest`-testable, **offline + deterministic**. Prior 434 tests (1 skipped) stay green;
   new tests cover §1–5. No network, no API keys, no real side effects.

---

## 2. Scope

**In scope**
- `src/grendel/config.py` (EXTEND): add `ProxyConfig` (host: str = "127.0.0.1", port: int in
  [1,65535] = 8100, routes: dict[str, str] = {} mapping a URL path prefix → provider name) and a
  `proxy: ProxyConfig = ProxyConfig()` field on `GrendelConfig`. Add a public method
  `GrendelConfig.with_cli_target(name, target) -> GrendelConfig` that returns a **revalidated** copy
  with the synthesized target added (so the existing cross-field validation runs on it). No change to
  any existing model's fields/semantics.
- `src/grendel/cli.py` (EXTEND):
  - A `_cli_target(...) -> tuple[str, GrendelConfig] | None` helper that reads the target flags,
    enforces exactly-one-source, synthesizes a `TargetConfig`, and returns the injected target name
    + the augmented config (or `None` when only `--target` is used). Usage errors → exit 2.
  - `run` gains: `--provider`, `--model`, `--base-url`, `--api-key-env`, `--header` (repeatable
    `k=v`), `--python`, `--agent`, `--mcp-command`, `--mcp-url`, `--mcp-fake-client`, `--mcp-tool`,
    `--output-dir`, `--pack-dir` (repeatable). `--target` becomes **optional**.
  - `list` gains `--pack-dir` (repeatable).
  - new `proxy` command (§5).
- Tests: `tests/test_cli_flag_target.py` (NEW — each target type from flags with no config;
  exactly-one-source errors), extend `tests/test_cli_run.py` (`--output-dir`/`--pack-dir`),
  `tests/test_config.py` (`ProxyConfig` defaults/validation, `with_cli_target` revalidation),
  `tests/test_cli_proxy.py` (NEW — the `proxy` command merge/validate/print).

**Out of scope (deferred / non-goals)**
- **The proxy *server*.** No socket, no request forwarding, no OpenAI-compatible endpoint — that is
  Phase 13, which will make `grendel proxy` actually serve using this `ProxyConfig`. Phase 12 only
  makes it *configurable + previewable*.
- **Renaming/removing existing config keys or `--target`.** `--config` and named `--target` keep
  working identically. Config files are made *optional*, not deprecated.
- **A global interactive config wizard / TUI settings screen.** CLI flags only.
- **New provider presets or adapter behaviour.** The flag path builds the *same* adapters via the
  *same* factory; no new target semantics.
- **Env-var-based target selection** beyond the existing `--api-key-env` (which just names the env
  var holding the key, as today). No new magic env vars.

---

## 3. Ad-hoc target from flags — design

### 3.1 The flag groups (mutually exclusive; exactly one, unless `--target`)
| Group | Flags | Synthesized `TargetConfig` |
|-------|-------|----------------------------|
| http | `--provider`, `--model` (req. together), `--base-url?`, `--api-key-env?`, `--header k=v*` | `type=http, provider, model, base_url?, api_key_env?, extra_headers` |
| python | `--python module:attr` | `type=python, entrypoint` |
| agent | `--agent module:attr` | `type=agent, entrypoint` |
| mcp | one of `--mcp-command`/`--mcp-url`/`--mcp-fake-client` (+ `--mcp-tool?`) | `type=mcp, mcp=McpConfig(...)` |

A "group is present" iff any of its flags is set. Rules (all → exit 2 with a specific message):
- `--target` given **and** any target flag given → error ("use --target OR the target flags, not both").
- No `--target` and **zero** groups present → error (list the four ways).
- More than one group present → error ("choose exactly one of --provider/--model, --python,
  --agent, --mcp-*").
- http group: `--provider` and `--model` must be given together (one without the other → error).
- mcp group: exactly one of `--mcp-command`/`--mcp-url`/`--mcp-fake-client` (zero is not the group;
  two → error). `--mcp-command` is split on whitespace into argv.
- `--header` values must be `key=value` (no `=` → error).

### 3.2 Synthesis + validation (reuse, don't duplicate)
The helper builds a `TargetConfig` (its own field validators run) and calls
`cfg.with_cli_target(_CLI_TARGET_NAME, target)`, which returns a **revalidated** `GrendelConfig`
copy (via `model_validate` over the mutated `targets` map) so the existing
`_check_provider_collisions_and_targets` cross-checks fire — unknown provider, missing base_url for
`openai-compatible`, missing entrypoint, missing mcp block. `_CLI_TARGET_NAME = "cli"` (documented;
collides only if the user *also* named a config target `cli`, in which case the flag form errors).
The run then proceeds exactly as today with `target = "cli"`: `resolve_target_info("cli", cfg)` /
`build_target("cli", cfg, …)` need **no change**.

### 3.3 Dry-run + all paths
Because synthesis happens before target resolution, `--dry-run`, `--tui`, `--resume`, `--judge`, and
`--fail-under` all work unchanged with a flag target (the synthesized target info prints in the
dry-run plan, records store its provider/model, etc.).

---

## 4. Output + import dirs — design

- `run --output-dir DIR`: if set, `cfg.run.output_dir = DIR` (before the record path is computed).
  `--out FILE` (existing, an explicit record file) still takes precedence for the written artifact;
  `--output-dir` sets the *default* directory the runner writes into. Both may be used.
- `run --pack-dir DIR` / `list --pack-dir DIR` (repeatable): each appended to
  `cfg.catalog.pack_dirs` (USER source) before `_load_attacks` / `list_packs`. Non-existent dir →
  the loader's existing behaviour (surfaced as a pack error, exit 2) — no new error path.
- Relative paths resolve against cwd (no config-file anchor exists on the CLI path).

---

## 5. `grendel proxy` — terminal-configurable proxy (preview; serving in Phase 13)

```
grendel proxy [--host H] [--port P] [--route PATH=PROVIDER ...] [--config C]
```
- Starts from `cfg.proxy` (defaults `127.0.0.1:8100`, no routes). `--host`/`--port` override;
  each `--route PATH=PROVIDER` adds/overrides a route (PATH must start with `/`; PROVIDER must be a
  known preset or a configured custom provider — else exit 2). A `--route` without `=` → exit 2.
- Validates the merged `ProxyConfig` (port in [1,65535]; routes well-formed) and **prints** the
  resolved configuration deterministically:
  ```
  proxy config:
    host: 127.0.0.1
    port: 8100
    routes:
      /openai -> openai
      /anthropic -> anthropic
  (serving starts in Phase 13; this previews the resolved configuration)
  ```
  Empty routes prints `routes: (none)`.
- Exit 0 on a valid config; exit 2 on any validation error. No network, no socket bound.

`ProxyConfig` validation (in `config.py`): `port` field-constrained to `[1, 65535]`; a
`routes` validator requires every key to start with `/` and be non-empty (provider-known-ness is
checked at the CLI, where `PRESETS` + `cfg.providers` are available, mirroring target validation).

---

## 6. Deliberate contract updates (enumerated)

1. **`grendel run --target` becomes optional** (was required). Existing invocations with `--target`
   are unchanged; omitting it is now valid **iff** a target-flag group is given. New usage errors
   (exit 2) for zero/many sources.
2. **`run` gains** `--provider/--model/--base-url/--api-key-env/--header/--python/--agent/
   --mcp-command/--mcp-url/--mcp-fake-client/--mcp-tool/--output-dir/--pack-dir`; **`list` gains**
   `--pack-dir`. All additive/optional; unset → today's behaviour.
3. **`GrendelConfig` gains `proxy: ProxyConfig`** (new model) and a `with_cli_target` method. Additive
   — default `ProxyConfig()` changes nothing for existing configs; unknown-key strictness preserved.
4. **New `grendel proxy` command** — purely additive; previews config, does not serve (Phase 13).
5. No runner/scoring/records/adapter behaviour change; `--config` + named `--target` keep working.
   No new runtime dependency.

---

## 7. Testing strategy (offline + deterministic)

- **Flag targets** (`test_cli_flag_target.py`): with **no `--config`**, patch `_load_attacks` +
  `build_target` (as existing run tests do) and:
  - `run --provider openai --model gpt-4o-mini` (dry-run) → plan prints, provider/model come from
    flags; a full run with a `FakeAdapter` writes a record whose `provider`/`model` match.
  - `run --python pkg.mod:fn` / `--agent pkg.mod:fn` → dry-run prints `provider=python|agent`,
    `model=<entrypoint>` (via the existing `resolve_target_info` non-http branch), no network.
  - `run --mcp-fake-client tests_mod:factory` (offline seam) → dry-run resolves an mcp target.
  - Exactly-one-source: no source → exit 2; `--target x` + `--model y` → exit 2; `--provider` w/o
    `--model` → exit 2; two groups → exit 2; `--header nope` (no `=`) → exit 2; unknown `--provider`
    → exit 2 (via the reused cross-check).
- **Dirs** (`test_cli_run.py` extend): `run --output-dir DIR …` writes the record under DIR;
  `run --pack-dir DIR` and `list --pack-dir DIR` cause a pack in DIR to be loaded (build a tiny
  valid pack in `tmp_path`).
- **ProxyConfig** (`test_config.py` extend): defaults (`127.0.0.1`, `8100`, `{}`); port out of range
  → `ConfigError`/validation; a route key not starting `/` → error; `with_cli_target` returns a
  revalidated config (an unknown provider in the synthesized target raises `ConfigError`).
- **proxy command** (`test_cli_proxy.py`): default print (no config → `127.0.0.1:8100`,
  `routes: (none)`); `--host/--port/--route /openai=openai` merges + prints sorted routes; bad port
  → exit 2; `--route noleadingslash=openai` → exit 2; `--route /x=unknownprov` → exit 2; `--route x`
  (no `=`) → exit 2. Deterministic output asserted as substrings.
- **No behaviour drift:** the prior 434 tests (1 skipped) stay green; only the additive §6 updates.

---

## 8. Acceptance criteria

Phase 12 is done when:
1. `ruff check .` + `ruff format --check .` clean; `pytest` green **offline, no keys/network**; the
   prior 434 tests (1 skipped) pass plus the new flag-target/dir/proxy/config tests.
2. **No-config run:** `grendel run --provider … --model …` (and the `--python`/`--agent`/`--mcp-*`
   forms) run the full pipeline with **no `--config` and no configured `--target`**, reusing the
   existing target factory unchanged; exactly-one-source is enforced with clear exit-2 errors.
3. **Dirs from CLI:** `run --output-dir` sets the record directory and `run/list --pack-dir` drive
   the catalog, both without a config file.
4. **Proxy configurable:** `ProxyConfig` on `GrendelConfig` + `grendel proxy` merges `--host/--port/
   --route` over config, validates, and prints the resolved configuration; serving is explicitly
   deferred to Phase 13. Everything offline + deterministic.
5. `--config` and named `--target` keep working identically; no runner/scoring/adapter behaviour
   changed; the additions are the enumerated §6 items only.
