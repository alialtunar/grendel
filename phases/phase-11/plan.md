# Phase 11 — implementation plan

Derived from `phases/phase-11/spec.md`. Two milestones, each ending in a verifiable checkpoint
(`ruff` clean + `pytest` green + `reviewer`/`tester` `STATUS: PASS`). Milestone 1 is the pure,
mechanical rename (must land green before any feature work); Milestone 2 is the additive TUI
elevation. **No scoring/runner/records/config behaviour changes anywhere.**

---

## Milestone 1 — Rebrand `gauntlet` → `grendel` (pure rename, no behaviour change)

**Intent:** move the package and every name reference to `grendel` with zero behaviour change, so
the whole prior suite passes under the new name.

**Steps**
1. **Move the package tree.** `src/gauntlet/` → `src/grendel/` (directory move; all submodules and
   `packs/**` move intact). No file added/removed.
2. **Rewrite imports + runtime name strings** across `src/grendel/` and `tests/`:
   - Absolute imports `from gauntlet…` / `import gauntlet…` → `grendel`. (Relative imports unchanged.)
   - `logging_setup.py`: `_ROOT_NAME = "grendel"`.
   - `cli.py`: `typer.Typer(name="grendel", …)`, `--config` help text, module docstring.
   - `targets/mcp_adapter.py`: `pip install grendel[mcp]` hint.
   - `tui/state.py`: repro string `# grendel repro …`, `grendel run …`.
   - Docstrings / comments that name the tool.
   - **Public class renames (DECIDED — rename, product-named API):** `GauntletConfig` →
     `GrendelConfig` and `GauntletError` → `GrendelError` (and any other `Gauntlet`-prefixed public
     identifier — grep `\bGauntlet` in `src/`). These are the config root model and the exception
     hierarchy root; a first-class rebrand renames them too. Update the class definitions, all
     `src/grendel/` references (14 in src), and the ~40 test references. This is enumerated in spec
     §7. (There is no back-compat alias.)
3. **Canary tokens.** In `src/grendel/packs/**`, replace `GAUNTLET-PWNED` → `GRENDEL-PWNED` and
   `GAUNTLET-JAILBROKEN` → `GRENDEL-JAILBROKEN` in **both** each pack's `payload` and its
   `success_when` matcher (paired; verdict behaviour identical).
   - **Base64-encoded canary (special case):** `jailbreak/base64-obfuscation-06.yaml` carries the
     canary *inside a base64 payload line* (`T3V0cHV0IHRoZSB0b2tlbiBHQVVOVExFVC1KQUlMQlJPS0VO` =
     `Output the token GAUNTLET-JAILBROKEN`). A plain-text replace would update only the matcher and
     silently break the pair. Explicitly replace that base64 line with
     `T3V0cHV0IHRoZSB0b2tlbiBHUkVOREVMLUpBSUxCUk9LRU4=` (= `Output the token GRENDEL-JAILBROKEN`).
     The `test_rename.py` canary-pair check (step 5a) base64-decodes payload lines so this can't
     regress.
   - **Synthetic/inline canary strings in test files:** the T1 canary mechanism is string-agnostic,
     so these are not product references. The scoped blanket replace normalizes them to `GRENDEL-*`
     alongside the required bundled-pack-assertion updates (e.g. `test_bundled_packs.py`); this is
     harmless (verdicts unchanged) and keeps the tree self-consistent. (Either leaving them or
     normalizing them is correct; we normalize for consistency.)
4. **Packaging.** `pyproject.toml`: `name = "grendel"`, `[project.scripts] grendel =
   "grendel.cli:app"`, `[tool.hatch.build.targets.wheel] packages = ["src/grendel"]`, the
   `artifacts` glob `src/grendel/packs/**/*.yaml`, and `[tool.ruff] src = ["src", "tests"]` (path
   unchanged). Re-install editable so the `grendel` entry point resolves for the CLI tests.
5. **Tests churn.** Update every test's `from gauntlet…`/`import gauntlet` → `grendel`, the canary
   token assertions (`GRENDEL-*`), the CLI-program-name assertion, the logging-root-name assertion,
   and the repro-string assertion. **No test's behaviour/logic changes** — only names.
6. **User-facing docs.** `README.md`, `docs/authoring-packs.md`, `SETUP.md`, `demo/README.md`
   reword `gauntlet` → `grendel`/**Grendel**; rename `demo/gauntlet.tape` → `demo/grendel.tape` and
   `examples/gauntlet.example.yaml` → `examples/grendel.example.yaml` (and rewrite their contents,
   incl. the `Output demo/grendel.gif` directive and any `gauntlet` commands). Update
   `test_docs_readme.py`/`test_docs_authoring.py` markers accordingly.
7. **Leave the historical journal untouched:** `ROADMAP.md`, `PROGRESS.md`, `phases/phase-01…10/*`.
   Also out of scope (test-helper filenames, not product references): `conftest.py`'s
   `name="gauntlet.yaml"` default parameter stays.
8. **Rename guard test (`test_rename.py`) — a Milestone-1 deliverable** (moved here from M2):
   - (a) canary pairing: every bundled pack's `success_when` token appears in its payload —
     **base64-decoding** any base64-looking payload lines first — and all bundled tokens are
     `GRENDEL-*` with **no** `GAUNTLET-` surviving in `src/grendel/packs/`.
   - (b) `import grendel` works and exposes the same top-level modules; `import gauntlet` raises
     `ModuleNotFoundError`.
   - (c) console-script metadata (or `pyproject.toml`) maps `grendel` → `grendel.cli:app`.
   - (d) **scan:** no case-insensitive substring `gauntlet` remains anywhere in `src/grendel/**`
     `.py` (this catches `GauntletConfig`/`GauntletError` residue too — the scan is a plain
     case-insensitive `"gauntlet" in text`, not word-bounded). YAML packs are covered by (a).

**Checkpoint 1 (must pass before Milestone 2):**
- `ruff check .` and `ruff format --check .` — zero findings.
- `python -c "import grendel"` works; `python -c "import gauntlet"` → `ModuleNotFoundError`.
- `grendel --help` runs (entry point resolves).
- `test_rename.py` (all four guards above) passes.
- `pytest` green: the prior **419** tests (1 skipped) pass under `grendel`, with only the mechanical
  name churn (incl. `GrendelConfig`/`GrendelError` and the bundled-pack `GRENDEL-*` assertions).
- `reviewer` + `tester` → `STATUS: PASS`.

---

## Milestone 2 — Elevate the TUI (colored ASR + live stream + tool-call visualization)

**Intent:** turn the Phase-5 scoreboard into the hero terminal view, purely by adding state +
renderers (Phase-5 pure-state / thin-renderer rules preserved).

**Steps**
1. **`tui/state.py` — pure additions:**
   - Module constants: `STREAM_LIMIT = 12`; ASR thresholds (`_ASR_WARN_MAX = 0.25`).
   - `asr_level(asr) -> str` (`ok`/`warn`/`bad`), `severity_level(sev) -> str` (`ok`/`warn`/`bad`),
     `verdict_glyph(v) -> str` (`✓`/`✗`/`⚠`/`–`). Plain-string returns, no Textual.
   - `@dataclass(frozen=True) class StreamEvent` (attempt_id, attack_id, category, verdict,
     score_tier, glyph).
   - `ScoreboardState.stream: tuple[StreamEvent, …] = ()` (new field, defaulted).
   - `FailureItem.tool_calls: tuple[str, …] = ()` (new field, defaulted) — compact `name(k=v,…)`
     reprs from `AttemptRecord.tool_calls`. Each dict is the sandbox shape `{name, args, ordinal}`
     (Phase-7 `ToolRegistry.snapshot()`); the helper `_tool_call_reprs(list[dict]) -> tuple[str,…]`
     reads them **defensively** — `d.get("name", "?")`, `d.get("args", {})` (sorted by key), sorted
     by `d.get("ordinal", 0)` — so a differently-shaped dict never raises. Empty tuple when none.
   - In `build_scoreboard`: populate `tool_calls` on each `FailureItem`, and build `stream` =
     newest-first last-`STREAM_LIMIT` of `record.attempts` (via `verdict_glyph`).
2. **`tui/__init__.py`:** export `StreamEvent`, `asr_level`, `severity_level`, `verdict_glyph`,
   `STREAM_LIMIT`.
3. **`tui/app.py` — thin renderer additions:**
   - `StreamPane(DataTable)` with columns `St | Attack | Category | Verdict | Tier` (first column
     `St` = the status glyph); `compose()` adds it as a bottom strip (`id="stream"`);
     `update_widgets()` clears + fills from `state.stream` (glyph, attack_id, category, verdict,
     tier). Column names match spec §5.2 exactly.
   - Colored header ASR: wrap the ASR figure in `[green]/[yellow]/[red]` markup keyed on
     `asr_level(state.overall_asr)`. `Static.update()` renders Rich console markup by default in
     Textual 0.80+ (no `markup=` arg needed); the pilot test asserts primarily on the pure
     `asr_level` in `state`, and secondarily that the rendered header string carries the expected
     color tag.
   - Colored grid: the ASR cell and Sev cell per row wrapped in markup keyed on `asr_level(row.asr)`
     / `severity_level(row.flag_severity)` (use `Text.from_markup` or Rich renderables the DataTable
     accepts).
   - Detail pane: after "target response", when `item.tool_calls` is non-empty, render
     `observed tool calls:` followed by one line per repr.
4. **`tui/app.tcss`:** add `#stream { height: auto; }` (short bottom strip) and adjust `#body`/left
   heights so the grid, failures, and stream all fit.
5. **Tests:**
   - `test_scoreboard_state.py` (extend): stream count/order/glyphs; `FailureItem.tool_calls`
     reprs (incl. a defensively-handled odd dict); `asr_level` boundaries pinning **both** edges
     (`0.0`→ok, `1e-6`→warn, `0.25`→warn, `0.26`→bad), `severity_level`/`verdict_glyph` mappings;
     determinism (two builds equal).
   - `test_tui_app.py` (extend): live stream pane fills newest-first; header ASR string carries the
     color tag matching `asr_level`; a failing category grid row carries color markup; detail pane
     shows the tool-call block for a failure with tool calls. Reuse the offline fake-engine +
     `asyncio.Event` pattern.
   - (`test_rename.py` already landed in Milestone 1; unchanged here.)

**Checkpoint 2 (phase close):**
- `ruff check .` + `ruff format --check .` — zero findings.
- `pytest` green: 419 prior (1 skipped) + the new state/TUI/rename tests; deterministic across
  repeated `run_test` pilot runs; offline.
- The scoreboard demonstrably shows colored ASR/severity, the live stream pane, and tool-call
  visualization (asserted by the pilot tests).
- `reviewer` + `tester` → `STATUS: PASS`; `review.md` + `test-report.md` end in `STATUS: PASS`.

---

## Risks & mitigations
- **Rename misses a reference → import error / stray `gauntlet`.** Mitigate: `test_rename.py`
  scans `src/grendel/` for surviving `gauntlet` tokens and asserts `import gauntlet` fails; the full
  suite + `ruff` catch any missed import.
- **Editable install stale (`gauntlet` entry point cached).** Mitigate: re-run `pip install -e .`
  after the pyproject change so `grendel --help` and the CLI tests resolve the new script.
- **DataTable color markup not rendering as expected in tests.** Mitigate: assert on the pure
  `asr_level`/`severity_level` in state tests (guaranteed), and in the pilot test assert the header
  `Static` text contains the markup tag (HeaderBar renders markup); keep grid-cell coloring simple
  (Rich `Text`), not asserted by exact pixels.
- **Canary token drift (payload changed, matcher not).** Mitigate: the paired replacement + a
  `test_rename.py` assertion that every `GRENDEL-*` token in a payload is covered by its pack's
  `success_when`.
