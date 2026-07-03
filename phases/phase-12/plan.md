# Phase 12 — implementation plan

Derived from `phases/phase-12/spec.md`. Two milestones, each ending in a verifiable checkpoint
(`ruff` clean + `pytest` green + `reviewer`/`tester` `STATUS: PASS`). Milestone 1 is the config-model
+ flag-target engine (the headline: run with no config file); Milestone 2 is the dir flags + the
`proxy` command. **No runner/scoring/records/adapter behaviour changes.**

---

## Milestone 1 — Ad-hoc target from flags (run with no config file)

**Intent:** let `grendel run` build any of the four target types from CLI flags, with no `--config`
and no configured `--target`, reusing the existing `resolve_target_info`/`build_target` factory.

**Steps**
1. **`config.py` — `with_cli_target`** (exact implementation, verified — no either/or):
   ```python
   def with_cli_target(self, name: str, target: TargetConfig) -> GrendelConfig:
       if name in self.targets:
           raise ConfigError(f"target {name!r} already exists in config; rename or omit --target")
       data = self.model_dump(mode="python")
       data["targets"] = {**data["targets"], name: target.model_dump(mode="python")}
       return GrendelConfig.model_validate(data)
   ```
   `mode="python"` keeps `Path` fields (`run.output_dir`, `catalog.pack_dirs/feed_cache_dir/
   staged_dir`) as `Path`, and `model_validate` re-runs `_check_provider_collisions_and_targets` on
   the merged map. **Confirmed** (empirically + by inspection): `ConfigError` does not subclass
   `ValueError`/`TypeError`/`AssertionError`, so pydantic-core does NOT wrap it into a
   `ValidationError` from the `mode="after"` validator — it propagates raw through `model_validate`
   (same guarantee `load_config`'s `except ConfigError: raise` already relies on). A unit test asserts
   (a) an unknown-provider synthesized target raises `ConfigError` (not `ValidationError`), (b) a
   `catalog.pack_dirs` Path survives unchanged, and (c) a duplicate name raises `ConfigError`.
2. **`cli.py` — `_cli_target` helper.** Signature takes all the target flags; returns
   `tuple[str, GrendelConfig]` (the injected name + augmented cfg) or `None` when only `--target` is
   used. Logic per spec §3.1:
   - Detect which groups are present (http/python/agent/mcp) and whether `--target` was passed.
   - Enforce exactly-one-source and the per-group rules; every violation →
     `typer.echo(msg, err=True); raise typer.Exit(2)`.
   - Build the `TargetConfig` for the present group (parse `--header k=v` into `extra_headers`,
     `--mcp-command` split on whitespace into argv), then
     `return _CLI_TARGET_NAME, cfg.with_cli_target(_CLI_TARGET_NAME, target)` inside a
     `try/except ConfigError → exit 2`.
3. **`cli.py` — wire into `run`.** Make `--target` `Optional[str] = None`. Add the new options
   (§2). **Insertion order (pinned):** place the `_cli_target` block **after** the existing
   `--tui`+`--dry-run` incompatibility check and the `--fail-under` range check (cli.py ~lines
   200-205), **immediately before** the existing `resolve_target_info`/`build_target` try block — so
   usage-error precedence is: tui/dry-run, then fail-under, then target-source, then target
   resolution. Snippet:
   ```
   flag_target = _cli_target(target=target, provider=provider, model=model, ...)
   if flag_target is not None:
       target, cfg = flag_target
   elif target is None:
       echo("specify a target: --target NAME, or --provider/--model, --python, --agent, --mcp-*")
       raise typer.Exit(2)
   ```
   Everything downstream (`resolve_target_info(target, cfg)`, `build_target`, dry-run print, record
   build) is unchanged.
4. **Tests** (`test_cli_flag_target.py`): each target type from flags with **no `--config`**
   (dry-run + a `FakeAdapter` full run for http), and every exactly-one-source / per-group error →
   exit 2. Reuse `_patch_packs`/`_patch_target` monkeypatch pattern from `test_cli_run.py`; for the
   python/agent/mcp dry-run cases, `resolve_target_info` must run on the synthesized target (do NOT
   patch it) so the non-http info branch is exercised. Use an offline `--mcp-fake-client` factory
   defined in the test module.

**Checkpoint 1:**
- `ruff check .` + `ruff format --check .` clean.
- `grendel run --provider openai --model gpt-4o-mini --dry-run` (no `-c`) prints a plan with
  provider=openai model=gpt-4o-mini; `--python`/`--agent`/`--mcp-fake-client` dry-runs resolve;
  a full `FakeAdapter` run writes a record with the flag provider/model.
- Exactly-one-source errors all exit 2.
- `pytest` green: prior 434 (1 skipped) + new flag-target tests. Named `--target` + `--config` still
  work (existing run tests unchanged).
- `reviewer` + `tester` → `STATUS: PASS`.

---

## Milestone 2 — Output/import dirs from flags + `grendel proxy` (config previewable)

**Intent:** finish "everything configurable from the terminal": record dir + catalog dirs from
flags, and a `ProxyConfig` + `proxy` command that previews the resolved proxy configuration.

**Steps**
1. **`config.py` — `ProxyConfig`.** New model (`extra="forbid"`): `host: str = "127.0.0.1"`,
   `port: int = Field(8100, ge=1, le=65535)`, `routes: dict[str, str] = {}`; a `routes` field
   validator requiring each key to be non-empty and start with `/`. Add
   `proxy: ProxyConfig = ProxyConfig()` to `GrendelConfig`. (Provider-known-ness of a route target
   is validated at the CLI, not here, so `config.py` needs no `PRESETS` import.)
2. **`cli.py` — dir flags on `run`/`list`.**
   - `run --output-dir DIR`: `if output_dir is not None: cfg.run.output_dir = output_dir`, applied
     right after config resolution / `_cli_target`. **Precedence vs `--resume` (pinned): `--resume`
     wins** — the existing resume branch sets `cfg.run.output_dir = resume.parent` and must run
     *after* the `--output-dir` assignment (so resuming into a fixed record's directory is
     unaffected by a stray `--output-dir`). A test asserts resume+output-dir lands the record in
     `resume.parent`, not the `--output-dir`.
   - `run --pack-dir DIR*` and `list --pack-dir DIR*`: `cfg.catalog.pack_dirs = [*cfg.catalog.
     pack_dirs, *pack_dir]` before `_load_attacks(cfg)` / `list_packs(config=cfg)`.
   (Mutating the resolved cfg in place is fine — it is per-invocation.)
3. **`cli.py` — `proxy` command** (§5): merge `--host`/`--port`/`--route PATH=PROVIDER` over
   `cfg.proxy`; parse each `--route` as `PATH=PROVIDER` (no `=` → exit 2); validate PATH starts `/`
   and PROVIDER ∈ `PRESETS | cfg.providers` (else exit 2); build the merged `ProxyConfig` (its
   validators run; port range → exit 2 via `ConfigError`), then print the deterministic block
   (routes sorted by path; `(none)` when empty) + the "serving starts in Phase 13" note. Exit 0.
4. **Tests:** `test_config.py` (ProxyConfig defaults/validation; `with_cli_target` revalidation +
   duplicate-name + Path-survival + ConfigError-not-wrapped), `test_cli_run.py` (`--output-dir`
   writes under DIR; `--output-dir`+`--resume` → record in `resume.parent`; `--pack-dir` loads a tmp
   pack; `list --pack-dir`), `test_cli_proxy.py` (default/merge/print; duplicate `--route /x=…`
   twice → last-wins; the four exit-2 error cases: no `=`, non-`/` path, unknown provider, bad port).
   Also a flag-target test for the judge-collision case: a config whose `judge.target == "cli"` plus
   a flag-target group → exit 2 (the `with_cli_target` name-collision guard).

**Checkpoint 2 (phase close):**
- `ruff check .` + `ruff format --check .` clean.
- `run --output-dir`/`--pack-dir` and `list --pack-dir` work with **no config**; `grendel proxy`
  merges + prints + validates (exit 2 on bad port/route/provider), and states serving is Phase 13.
- `pytest` green: 434 prior (1 skipped) + all new tests; deterministic; offline.
- `reviewer` + `tester` → `STATUS: PASS`; `review.md` + `test-report.md` end in `STATUS: PASS`.

---

## Risks & mitigations
- **`with_cli_target` round-trip loses/rewrites nested model data (Paths, McpConfig).** Mitigate:
  use the exact Step-1 snippet (`data = self.model_dump(mode="python")`; overwrite `data["targets"]`
  with the merged dict; `model_validate(data)`) — `mode="python"` preserves `Path`/nested models;
  a test asserts a `catalog.pack_dirs` Path survives `with_cli_target` unchanged.
- **Flag combinatorics get confusing → wrong exit codes.** Mitigate: a single `_cli_target` helper
  with an explicit present-groups list and a table-driven set of checks; a test per error branch.
- **`--output-dir` vs `--out` precedence ambiguity.** Mitigate: `--out` (explicit file) wins for the
  written artifact; `--output-dir` sets the runner's default dir. Documented in `--help` + a test
  asserting a record lands under `--output-dir` when `--out` is absent.
- **Proxy provider-validation needs PRESETS (import cycle risk).** Mitigate: do it in the CLI
  (already imports `PRESETS`), not in `config.py` — mirrors how target provider checks are split.
- **Scope creep into the Phase-13 server.** Mitigate: `proxy` only prints; a test asserts no socket
  is bound (it returns immediately) and the "Phase 13" note is present.
