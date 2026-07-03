# Phase 12 Review

Scope checked against `phases/phase-12/spec.md` + `plan.md` + ROADMAP §8.12. Files inspected:
`src/grendel/config.py`, `src/grendel/cli.py`, `tests/test_config.py`, `tests/test_cli_flag_target.py`,
`tests/test_cli_proxy.py`, `tests/test_cli_run.py`, `phases/phase-12/test-report.md`.

## Re-verification (second pass)

Both previously-reported issues have been fixed and are independently confirmed:

1. **`list --pack-dir` (was BLOCKING) — FIXED.** `list_()` in `src/grendel/cli.py` (lines 490-506)
   now takes a repeatable `pack_dir: list[Path] | None` option and appends it to
   `cfg.catalog.pack_dirs` before the `list_packs(config=cfg)` call, mirroring `run`. Verified live:
   `grendel list --help` now shows `--pack-dir`, and
   `tests/test_cli_flag_target.py::test_list_pack_dir_loads_user_pack` (builds a tmp
   `prompt-injection/userpack-01.yaml` and asserts it appears in `list --packs --pack-dir DIR`)
   passes.
2. **`--header`/`--api-key-env` alone (was a minor nit) — FIXED.** The `http` group-detection
   condition in `_cli_target` (`cli.py` lines 195-201) now includes `api_key_env is not None` and
   `bool(header)`. Verified live: `run --api-key-env FOO --dry-run` now exits 2 with "--provider and
   --model must be given together for an HTTP target" (the specific message) instead of the generic
   "specify a target" message.

Full suite re-run: `ruff check .` clean, `ruff format --check .` clean (90 files), `pytest`: 465
passed, 1 skipped (434 baseline + 1 new test since the prior pass at 464).

## Findings from first pass (all resolved, kept for record)

- ~~BLOCKING: `list` command missing `--pack-dir`~~ — fixed, see above.
- ~~Minor: `--header`/`--api-key-env` alone fell through to the generic error message~~ — fixed, see
  above.

## Verified as correct (unchanged from first pass)

- `with_cli_target` uses the exact plan snippet (`model_dump(mode="python")` + `model_validate`),
  re-runs `_check_provider_collisions_and_targets`, preserves `Path` fields, and lets `ConfigError`
  propagate unwrapped (confirmed by `tests/test_config.py`). `ConfigError` extends `Exception`
  directly, so pydantic-core does not wrap it — matches the plan's stated guarantee.
- `_cli_target`'s exactly-one-source logic (http/python/agent/mcp groups, `--target` XOR flags, http
  provider+model-together, mcp exactly-one-of-three, `--header k=v` parsing) is complete; every
  violation path exits 2.
- Insertion order in `run` matches the pinned plan: `--tui`+`--dry-run` check, then `--fail-under`
  range check, then the `_cli_target` block, then `resolve_target_info`/`build_target`.
- `--output-dir` vs `--resume` precedence (resume wins) is correct and tested
  (`test_output_dir_ignored_when_resuming`).
- `run --pack-dir` and (now) `list --pack-dir` both correctly append to `cfg.catalog.pack_dirs`
  before catalog loading.
- `proxy` command: merges `--host`/`--port`/`--route` over `cfg.proxy`, validates port range/route
  path/unknown provider (all exit 2), last-route-wins on duplicate path, deterministic sorted output
  with `(none)` for empty routes, states "serving starts in Phase 13", binds no socket.
- `ProxyConfig` model matches spec exactly; no `PRESETS` import in `config.py`.
- No runner/scoring/records/adapter behavior changes; `--config` + named `--target` paths untouched.

## Result

No outstanding blocking issues. Phase 12 deliverables (ad-hoc flag targets, output/pack dirs on
`run` and `list`, `ProxyConfig` + `proxy` preview command) match spec and plan, are covered by
passing tests, and lint/format are clean.

STATUS: PASS
