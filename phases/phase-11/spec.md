# Phase 11 — Rename to **Grendel** + first-class terminal TUI: spec

> Phase 11 of 14 — the first follow-on (post-1.0) phase. Implements ROADMAP §8.11:
> *"Rename to Grendel + first-class terminal TUI — rebrand `gauntlet` → `grendel` (package,
> CLI command, docs, canary token) and elevate the Phase-5 Textual scoreboard into the hero
> terminal experience: live pass/fail grid, colored ASR, a live attack stream (send → score
> animation), tool-call visualization, failure-detail pane, hotkeys — all in the terminal,
> no web UI."*
>
> **Two deliverables, both offline + deterministically testable:**
> 1. **Rebrand `gauntlet` → `grendel`** — the Python package (`src/gauntlet` → `src/grendel`),
>    every intra-package import, the console-script/CLI command, the logging root, the planted
>    **canary tokens** (`GAUNTLET-PWNED` → `GRENDEL-PWNED`, `GAUNTLET-JAILBROKEN` →
>    `GRENDEL-JAILBROKEN`), the repro string the TUI copies, user-facing docs (README, `docs/`,
>    `SETUP.md`, `demo/`, `examples/`), and `pyproject.toml`. A pure, mechanical rename with **no
>    behaviour change**: same modules, same public API, same tests — only the name moves.
> 2. **Elevate the TUI** into the hero terminal experience, building strictly on the Phase-5
>    pure-`ScoreboardState` + thin-Textual-renderer architecture (`tui/state.py` + `tui/app.py`):
>    - **Colored ASR + severity** — a pure severity/ASR → semantic-level mapping in `state.py`;
>      `app.py` paints the header ASR and the per-category grid green/amber/red via Rich markup.
>    - **Live attack stream** — a pure, bounded, recency-ordered `stream` of the most recent
>      attempts (attack id, category, verdict glyph, tier) that fills as attempts land live —
>      the "send → score" animation, in the terminal.
>    - **Tool-call visualization** — surface each failure's observed `tool_calls` (the agent-mode
>      differentiator) in the `FailureItem` and render them in the detail pane.
>
> **Additive + name-only.** No scoring/runner/records/config behaviour changes. The rename is a
> pure move; the TUI work only adds pure state + renderers. The prior **419** tests (1 skipped)
> stay green **after** their imports/strings are mechanically renamed to `grendel`; new tests
> cover the new pure state (stream, tool-calls, asr level) and the TUI render. Everything is
> offline, deterministic, no network / no API keys / no browser.

---

## 1. Goals

1. **Rebrand to `grendel` (package · CLI · logging · canary · user docs).** After this phase the
   import root is `grendel`, the installed console command is `grendel`, the structured-logging root
   logger is `grendel`, the planted canary tokens are `GRENDEL-*`, and every user-facing doc names
   the tool **Grendel**. `import gauntlet` no longer exists (deliberate, enumerated in §7 — this is
   a rename, not an alias; a "first-class" tool ships under one name).
2. **No behaviour change from the rename.** Same modules, same signatures, same YAML packs, same
   verdicts. The only test churn is mechanical: `from gauntlet…` → `from grendel…`, the two canary
   token literals, the CLI program name, the logging root name, and repro/help strings.
3. **Colored ASR + severity in the TUI.** A pure function in `state.py` maps an ASR value and a
   `Severity` to a semantic level (`ok` / `warn` / `bad`); `app.py` renders the header ASR and each
   grid row's ASR/severity with the matching color via Rich console markup. The mapping is pure and
   unit-tested; the app applies it.
4. **Live attack stream pane.** `ScoreboardState` gains a pure, bounded `stream: tuple[StreamEvent,
   …]` — the N most-recently-recorded attempts in **record order** (newest first), each carrying
   `attack_id`, `category`, `verdict`, `score_tier`, and a one-glyph `status` (✓ defended / ✗
   succeeded / ⚠ error / – skipped). A new bottom pane renders it; it grows as live attempts arrive
   through the existing `on_attempt` → `AttemptRecorded` path (no new engine wiring).
5. **Tool-call visualization.** `FailureItem` gains `tool_calls: tuple[str, …]` (compact
   `name(args)` reprs derived from `AttemptRecord.tool_calls`); the detail pane renders an
   "observed tool calls" block when present — the agent-mode outcome shown in the hero view.
6. Everything `pytest`-testable, **offline + deterministic**. The prior **419** tests (1 skipped)
   stay green after the mechanical rename; new tests cover the new pure state + the render.

---

## 2. Scope

**In scope**
- **The rename** (mechanical, whole-tree):
  - Move `src/gauntlet/` → `src/grendel/` (directory rename; all submodules and the `packs/` data
    move with it).
  - Rewrite every intra-package import (`from gauntlet…`, `import gauntlet…`, relative imports are
    unaffected) and every runtime name string: `_ROOT_NAME = "grendel"` (logging), the Typer
    `name="grendel"`, docstrings, the `pip install grendel[mcp]` hint, config `--help` text.
  - Canary tokens: `GAUNTLET-PWNED` → `GRENDEL-PWNED` and `GAUNTLET-JAILBROKEN` →
    `GRENDEL-JAILBROKEN` in **both** the pack payloads and their `success_when` matchers (they must
    stay paired, so verdicts are unchanged).
  - Repro string in `tui/state.py` (`# grendel repro …`, `grendel run …`).
  - `pyproject.toml`: `name = "grendel"`, `[project.scripts] grendel = "grendel.cli:app"`,
    `[tool.hatch.build.targets.wheel] packages = ["src/grendel"]`, artifacts glob, `src` list.
  - Tests: every `from gauntlet…`/`import gauntlet` → `grendel`, the canary-token assertions, the
    CLI-name / logging-name / repro-string assertions.
  - User-facing docs: `README.md`, `docs/`, `SETUP.md`, `demo/grendel.tape` (rename file +
    contents), `demo/README.md`, `examples/grendel.example.yaml` (rename file + contents).
- **The TUI elevation** (`tui/state.py` + `tui/app.py` + `tui/app.tcss` + `tui/__init__.py`):
  - `state.py`: a `StreamEvent` frozen dataclass + `stream` field on `ScoreboardState` (bounded by a
    module constant `STREAM_LIMIT = 12`, newest-first, built from `record.attempts` in record
    order); `tool_calls: tuple[str, …]` on `FailureItem`; pure helpers `asr_level(asr) -> str`,
    `severity_level(sev) -> str`, and `verdict_glyph(verdict) -> str`. Export the new names from
    `tui/__init__.py`.
  - `app.py`: a `StreamPane` (DataTable) rendering `state.stream`; colored header ASR + colored grid
    ASR/severity via Rich markup keyed on the pure levels; the detail pane's new "observed tool
    calls" block. All still pure over `self.state`.
  - `app.tcss`: layout for the new stream pane (a short bottom strip) + minor sizing.
- Tests: extend `tests/test_scoreboard_state.py` (stream ordering/bound/glyphs, tool_calls on
  failures, `asr_level`/`severity_level`/`verdict_glyph`), extend `tests/test_tui_app.py` (the
  stream pane renders live attempts; the header/grid carry color markup; the detail pane shows tool
  calls), and a small `tests/test_rename.py` (guards the rebrand: `import grendel` works, `import
  gauntlet` raises, the console-script entry points at `grendel.cli:app`, the canary tokens are
  `GRENDEL-*`, and no `gauntlet` identifier survives in `src/`).

**Out of scope (deferred / non-goals)**
- **A `gauntlet` back-compat shim / alias.** Deliberately not shipped (§7). One name.
- **Any new engine/runner/scoring wiring for the stream.** The stream is a pure projection of the
  attempts the existing `on_attempt` path already delivers; no new callback, no new runner hook.
- **Config-key renames that would break existing configs.** Config *field names* (e.g.
  `feed_cache_dir`) are unchanged; only user-facing prose/help strings mention "grendel". (Env vars
  / config schema are untouched — a rename of those belongs to no roadmap item and would break user
  files.)
- **Rewriting the historical build log.** `ROADMAP.md`, `PROGRESS.md`, and `phases/phase-01…10/*`
  are the audit trail of how the tool was built under its old name; they are **left as-is** (they
  describe past phases). The rebrand covers the *product's* user-facing surface (package, CLI,
  logging, canary, README/docs/demo/examples), not the historical journal. (Enumerated in §7.)
- **New TUI hotkeys or a re-themed CSS palette.** The existing bindings and layout stay; we add one
  pane + color, not a redesign. Charting, mouse UI, and web anything remain out (ROADMAP §7).
- **Renaming the `runs/` output dir or on-disk record format.** Records are name-agnostic JSON.

---

## 3. Module layout

```
src/grendel/                 # RENAMED from src/gauntlet/ (whole subtree moves)
├── … (all existing modules unchanged except intra-package name strings)
├── packs/**/*.yaml          # canary tokens GAUNTLET-* → GRENDEL-* (payload + matcher, paired)
└── tui/
    ├── state.py             # EXTEND: StreamEvent + stream field; FailureItem.tool_calls;
    │                        #         asr_level / severity_level / verdict_glyph; STREAM_LIMIT
    ├── app.py               # EXTEND: StreamPane; colored header ASR + grid ASR/severity;
    │                        #         detail-pane "observed tool calls" block
    ├── app.tcss             # EXTEND: #stream pane layout
    └── __init__.py          # EXTEND: export StreamEvent, asr_level, severity_level, verdict_glyph
pyproject.toml               # name/scripts/hatch packages → grendel
README.md · docs/ · SETUP.md · demo/grendel.tape · demo/README.md · examples/grendel.example.yaml
tests/
├── test_rename.py           # NEW: rebrand guard (import grendel ok / gauntlet gone / entrypoint / canary)
├── test_scoreboard_state.py # EXTEND: stream, tool_calls, asr_level/severity_level/verdict_glyph
├── test_tui_app.py          # EXTEND: stream pane, colored header/grid, tool-call block
└── … (all others: mechanical gauntlet→grendel import/string churn only)
```

---

## 4. The rename — precise contract

- **Directory move.** `src/gauntlet` → `src/grendel`. No file is added or removed by the move; the
  `packs/` YAML data and all subpackages (`targets/`, `tui/`, `agents/`) move intact.
- **Import rewrite.** Every absolute import of the package (`from gauntlet.x import …`,
  `import gauntlet…`) becomes `grendel`. Relative imports (`from ..records import …`) are unchanged.
  Test modules import `grendel`.
- **Runtime name strings** (behaviour-relevant): logging root `_ROOT_NAME = "grendel"`; Typer
  `typer.Typer(name="grendel", …)`; the MCP-missing hint `pip install grendel[mcp]`; the repro
  header/command in `tui/state.py`.
- **Canary tokens.** The planted-canary literals move to `GRENDEL-PWNED` / `GRENDEL-JAILBROKEN`,
  changed **in lockstep** in each pack's `payload` and its `success_when.contains`/`any_of` matcher
  so the T1 canary detector still fires identically. (A test asserts payload⇔matcher pairing holds
  and that no `GAUNTLET-` token survives in `src/`.)
- **Packaging.** `pyproject.toml` `name`, `[project.scripts]`, hatch `packages`/`artifacts`/`src`
  all point at `grendel`; `pip install -e .` installs the `grendel` command; `grendel --help` works.
- **No behaviour change.** Same verdicts, same metrics, same records. The only *deliberate* contract
  change is the name itself (`import gauntlet` and the `gauntlet` command are gone — §7).
- **Left as-is (historical journal):** `ROADMAP.md`, `PROGRESS.md`, `phases/phase-01…10/*`.

**Rename mechanism (deterministic, auditable).** The move is done with a directory move plus a
scoped find/replace over `src/`, `tests/`, `pyproject.toml`, `README.md`, `docs/`, `SETUP.md`,
`demo/`, `examples/` — never over `ROADMAP.md` / `PROGRESS.md` / `phases/`. After the move,
`ruff check`, `ruff format --check`, and the full `pytest` run are the proof it was total and clean.

---

## 5. TUI elevation — design (pure state + thin renderer, Phase-5 rules preserved)

The Phase-5 contract is **kept**: `state.py` imports no Textual and does all computation; `app.py`
widgets only read `self.state` and write text/markup. Everything below is pure + testable.

### 5.1 Semantic color levels (`state.py`, pure)
- `asr_level(asr: float) -> str`: `"ok"` when `asr == 0.0`, `"warn"` when `0 < asr <= 0.25`, `"bad"`
  when `asr > 0.25`. (Thresholds are module constants; documented.)
- `severity_level(sev: Severity | None) -> str`: `None`/`LOW` → `"ok"`, `MEDIUM` → `"warn"`,
  `HIGH`/`CRITICAL` → `"bad"`.
- `verdict_glyph(v: Verdict) -> str`: `PASS`→`✓`, `FAIL`→`✗`, `ERROR`→`⚠`, `SKIPPED`→`–`.

These return plain strings (no Textual/Rich types), so they're trivially unit-tested. `app.py` owns
the level→color mapping (`ok`→green, `warn`→yellow, `bad`→red) applied as Rich `[green]…[/]` markup;
tests assert the level strings in `state`, and (in the pilot test) that the header text contains the
expected color tag.

### 5.2 Live attack stream (`StreamEvent` + `state.stream`)
```python
@dataclass(frozen=True)
class StreamEvent:
    attempt_id: str
    attack_id: str | None
    category: str | None
    verdict: Verdict
    score_tier: str | None
    glyph: str          # verdict_glyph(verdict)
```
- `STREAM_LIMIT = 12` (module constant). `state.stream` = the last `STREAM_LIMIT` attempts of
  `record.attempts`, **newest-first** (i.e. `record.attempts[-LIMIT:]` reversed). Built inside
  `build_scoreboard`; pure, deterministic (record order is the runner's append order).
- Renders in a new `StreamPane` DataTable (`Glyph | Attack | Category | Verdict | Tier`), a short
  bottom strip. As live `AttemptRecorded` messages rebuild the state, the pane refreshes — the
  send→score animation. No new engine plumbing (reuses `_rebuild()` + `update_widgets()`).

### 5.3 Tool-call visualization (`FailureItem.tool_calls`)
- `FailureItem` gains `tool_calls: tuple[str, …]`, built from `AttemptRecord.tool_calls` (each dict
  `{name, args, ordinal}`) as a compact, deterministic `name(k=v, …)` repr (args sorted by key;
  reprs in `ordinal` order). Empty tuple when none.
- The detail pane renders an `observed tool calls:` block (one per line) when `tool_calls` is
  non-empty — placed after "target response". This is the agent-mode side effect, shown in the hero
  view (ROADMAP §7 outcome-over-string, surfaced in the terminal).

### 5.4 What stays the same
Header metrics, progress bar, category grid columns, failures list, detail pane's existing
payload/response/explain, every hotkey, the live/rerun engine plumbing, and the `repro_for` string
(only its `gauntlet`→`grendel` text changes). The stream + color + tool-calls are **additions**.

---

## 6. Testing strategy (offline + deterministic)

- **Rename guard** (`test_rename.py`, a **Milestone-1** deliverable): `import grendel` succeeds and
  exposes the same top-level modules; `import gauntlet` raises `ModuleNotFoundError`; the installed
  console-script metadata (or `pyproject`) maps `grendel` → `grendel.cli:app`; the bundled packs'
  canary tokens are `GRENDEL-*` and each token in a payload is matched by the pack's `success_when`
  — **base64-decoding any base64-looking payload lines first** so the encoded canary is checked too;
  a scoped scan asserts **no case-insensitive substring `gauntlet` remains anywhere in
  `src/grendel/**` `.py`** (plain substring, not word-bounded — this also catches any residual
  `GauntletConfig`/`GauntletError`). No network.
- **Pure state** (`test_scoreboard_state.py`, extend): given a record with more than `STREAM_LIMIT`
  attempts, `stream` has exactly `STREAM_LIMIT` entries, newest-first, glyphs matching verdicts; a
  FAIL attempt with `tool_calls` yields a `FailureItem.tool_calls` with the expected `name(args)`
  reprs in ordinal order; `asr_level` boundaries (0.0→ok, 0.25→warn, 0.26→bad), `severity_level`
  mapping, `verdict_glyph` mapping. Determinism: two builds → equal states.
- **TUI render** (`test_tui_app.py`, extend, `run_test` pilot, offline fake engine): after scripted
  attempts land, the `StreamPane` shows them newest-first; the header contains the ASR color tag
  matching `asr_level`; the grid row for a failing category carries a color tag; selecting a failure
  whose attempt had tool calls shows the "observed tool calls" block in the detail pane. Reuses the
  existing fake-engine + `asyncio.Event` completion pattern; deterministic across repeated runs.
- **Everything else**: the prior suite stays green after the mechanical `grendel` rename; no test's
  *behaviour* changes, only its import lines and the four name strings (canary, CLI name, logging
  name, repro).

---

## 7. Deliberate contract updates (enumerated)

1. **`import gauntlet` → `import grendel`; `gauntlet` command → `grendel`.** Hard rename, no alias.
   Every test that imports the package or invokes the CLI name updates in lockstep. This is the
   headline change of the phase (ROADMAP §8.11) and is intentional, not additive.
2. **Canary tokens `GAUNTLET-*` → `GRENDEL-*`** in the bundled packs (payload + matcher, paired).
   Verdict behaviour is identical; the bundled-pack string literals asserted in
   `test_bundled_packs`/scoring tests update. **Includes the base64-encoded canary** in
   `jailbreak/base64-obfuscation-06.yaml`: the payload's base64 line is re-encoded to
   `T3V0cHV0IHRoZSB0b2tlbiBHUkVOREVMLUpBSUxCUk9LRU4=` (= `Output the token GRENDEL-JAILBROKEN`) so
   the decoded instruction and the matcher stay paired. **Synthetic/inline `GAUNTLET-*` fixtures in
   ~9 test modules are left unchanged** — the T1 canary mechanism is string-agnostic, so they are
   not product references and need not move.
2b. **Public class renames** (product-named API, no alias): `GauntletConfig` → `GrendelConfig`,
   `GauntletError` → `GrendelError`, and any other `Gauntlet`-prefixed public identifier. ~14
   references in `src/` and ~40 in tests update in lockstep. Enumerated so the reviewer expects the
   churn.
3. **Logging root `gauntlet` → `grendel`**, Typer program name `gauntlet` → `grendel`, repro string
   `gauntlet run` → `grendel run`, MCP hint `gauntlet[mcp]` → `grendel[mcp]`. Tests that assert
   these strings update.
4. **`ScoreboardState` gains `stream`; `FailureItem` gains `tool_calls`; `state.py` gains
   `StreamEvent`, `STREAM_LIMIT`, `asr_level`, `severity_level`, `verdict_glyph`** — additive; all
   have defaults / are new, so existing `build_scoreboard` callers are unaffected. New `tui`
   exports.
5. **User-facing docs + `demo/gauntlet.tape` → `demo/grendel.tape`, `examples/gauntlet.example.yaml`
   → `examples/grendel.example.yaml`** (file renames + content). `docs/authoring-packs.md`,
   `README.md`, `SETUP.md` reword to "grendel".
6. **Left unchanged:** `ROADMAP.md`, `PROGRESS.md`, `phases/*` (historical journal); config schema
   field names; record JSON format; `runs/` dir. No new runtime dependency.

---

## 8. Acceptance criteria

Phase 11 is done when:
1. `ruff check .` and `ruff format --check .` pass with zero findings; `pytest` is green **offline,
   no API keys / network / browser**; the prior 419 tests (1 skipped) pass after the mechanical
   rename, plus the new state/TUI/rename tests.
2. **Rebrand complete:** `import grendel` works and `import gauntlet` fails; `grendel --help` runs;
   the console-script is `grendel = grendel.cli:app`; the logging root is `grendel`; the planted
   canary tokens are `GRENDEL-*` (paired payload⇔matcher); no `gauntlet` token remains in
   `src/grendel/`; README/docs/SETUP/demo/examples name the tool **Grendel**.
3. **First-class TUI:** the scoreboard shows (a) **colored** header ASR + per-category ASR/severity
   (green/amber/red keyed on the pure `asr_level`/`severity_level`), (b) a **live attack stream**
   pane that fills newest-first as attempts land (bounded at `STREAM_LIMIT`), and (c) **observed
   tool calls** in the failure-detail pane — all driven by pure `state.py` functions and asserted by
   unit + `run_test` pilot tests.
4. No scoring/runner/records/config behaviour changed; the rename is name-only; the TUI work is
   pure-state + thin-renderer additions; everything offline + deterministic.
