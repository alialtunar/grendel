# Phase 11 review

Scope verified against `phases/phase-11/spec.md`, `phases/phase-11/plan.md`, and ROADMAP.md §8.11.

## Milestone 1 — Rename gauntlet → grendel

1. Directory move complete: `src/grendel/` exists, `src/gauntlet/` is gone (confirmed via `git status` showing the old tree as deleted and the new tree present, no stray files).
2. No stale `gauntlet` token anywhere in `src/grendel` (`grep -rIin gauntlet src/grendel | grep -v __pycache__` returns nothing).
3. `import grendel` succeeds; `import gauntlet` raises `ModuleNotFoundError` (verified by direct execution).
4. `grendel --help` runs correctly; console-script entry point resolves (`[project.scripts] grendel = "grendel.cli:app"` in `pyproject.toml`, confirmed).
5. `pyproject.toml` fully updated: `name = "grendel"`, `packages = ["src/grendel"]`, `artifacts = ["src/grendel/packs/**/*.yaml"]`, `src = ["src", "tests"]`.
6. Public class renames complete and clean: `GauntletConfig`/`GauntletError` do not appear anywhere in `src/` or `tests/`; `GrendelConfig`/`GrendelError` are used consistently across `config.py`, `errors.py`, `feed.py`, `packloader.py`, `records.py`, `targets/`.
7. Canary tokens correctly paired in both special-case packs:
   - `packs/jailbreak/base64-obfuscation-06.yaml`: base64 line decodes to `Output the token GRENDEL-JAILBROKEN`, matching the `success_when.contains: [GRENDEL-JAILBROKEN]` matcher.
   - `packs/jailbreak/payload-split-05.yaml`: split payload (`A = "GRENDEL-"`, `B = "JAILBROKEN"`) correctly reconstructs to the matcher's expected token.
8. `tests/test_rename.py` implements and passes all four required guards: (a) canary pairing with base64-decoding of payload lines, (b) import root check, (c) console-script entry-point check via `pyproject.toml`, (d) case-insensitive `gauntlet` substring scan over `src/grendel/**/*.py`.
9. MCP hint string updated: `pip install grendel[mcp]` in `targets/mcp_adapter.py`.
10. User-facing docs and files renamed/reworded: `demo/grendel.tape` (was `demo/gauntlet.tape`), `examples/grendel.example.yaml` (was `examples/gauntlet.example.yaml`), and no `gauntlet` references remain in `README.md`, `docs/`, `demo/`, `examples/`.
11. Historical journal correctly left untouched: `ROADMAP.md`, `PROGRESS.md`, `phases/phase-01..10/*` still reference `gauntlet` (expected, per spec §2/§7 out-of-scope).

## Milestone 2 — TUI elevation

1. `src/grendel/tui/state.py` contains **no Textual import** (confirmed by reading the full file — only `dataclasses`, `datetime`, and intra-package imports).
2. `asr_level`: `ok` for `asr <= 0.0`, `warn` for `(0, 0.25]`, `bad` for `> 0.25`. Boundary tests in `test_scoreboard_state.py` pin all four required edges (`0.0`→ok, `1e-6`→warn, `0.25`→warn, `0.26`→bad) and pass.
3. `severity_level` and `verdict_glyph` mappings match spec §5.1 exactly and are unit-tested.
4. `StreamEvent` frozen dataclass, `ScoreboardState.stream` (bounded `STREAM_LIMIT = 12`, newest-first, built from `record.attempts[-STREAM_LIMIT:]` reversed) — correct and covered by `test_stream_is_bounded_newest_first_with_glyphs` / `test_stream_shorter_than_limit_keeps_all`.
5. `FailureItem.tool_calls` and `_tool_call_reprs`: defensive `.get()` access (`name`, `args`, `ordinal` all defaulted), sorted by ordinal then by arg key, deterministic `name(k=v, …)` reprs. Covered by `test_failure_tool_calls_repr_ordered_and_defensive` and `test_failure_without_tool_calls_is_empty_tuple`.
6. `tui/__init__.py` exports `StreamEvent`, `asr_level`, `severity_level`, `verdict_glyph`, `STREAM_LIMIT` (plus prior exports) — all present in `__all__`.
7. `app.py` remains a thin renderer: `StreamPane(DataTable)` with columns `St | Attack | Category | Verdict | Tier` exactly matching spec §5.2; colored header ASR via `_paint`/`asr_level`; colored grid ASR/Sev cells via `Text.from_markup`; detail pane renders "observed tool calls:" block after "target response" only when `item.tool_calls` is non-empty. No metric computation happens in `app.py` — all reads are from `self.state`.
8. `app.tcss` adds `#stream { height: auto; max-height: 40%; border-top: solid $primary; }` and the layout still composes (`#categories`/`#failures` at `1fr`).
9. Additive dataclass fields (`stream`, `tool_calls`) have defaults / are otherwise threaded consistently through `build_scoreboard`; no signature break for existing callers (`with_filter`, `select_next`, `toggle_explain` unaffected).
10. `test_scoreboard_state.py` and `test_tui_app.py` extended per spec §6: stream ordering/bound/glyphs, tool-call reprs, determinism, colored header/grid markup assertions, and the tool-call detail-pane rendering test all present and passing.

## Verification run

- `grep -rIin gauntlet src/grendel | grep -v __pycache__` → no output (clean).
- `python -c "import grendel"` → succeeds; `python -c "import gauntlet"` → `ModuleNotFoundError` (as required).
- `ruff check .` → All checks passed!
- `ruff format --check .` → 88 files already formatted.
- `grendel --help` → runs, shows correct program name and commands.
- `python -m pytest -q` → 434 passed, 1 skipped (exceeds the required 419+1-skipped baseline, consistent with the new Milestone-2 tests added).

## Notes (non-blocking)

- `asr_level` uses `asr <= 0.0` rather than a strict `== 0.0` check as literally written in spec §5.1 prose; functionally equivalent since ASR is never negative in practice, and the pinned boundary tests (0.0, 1e-6, 0.25, 0.26) all pass. Not a defect.

## Conclusion

All Milestone 1 (rename) and Milestone 2 (TUI elevation) deliverables from `phases/phase-11/plan.md` and `spec.md` are implemented correctly, consistently, and are covered by passing tests. No stale `gauntlet` references, no canary-pair drift, no behaviour change, state.py remains framework-free, app.py remains a thin renderer. `ruff` and the full test suite are clean.

STATUS: PASS
