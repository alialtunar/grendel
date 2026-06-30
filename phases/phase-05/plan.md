# Phase 5 — TUI scoreboard ⭐: implementation plan

> Build order is dependency-ordered: **pure state model** (no Textual) → **runner hook** (additive)
> → **Textual app skeleton** rendered from state → **keybindings** → **CLI `--tui` wiring**. The
> pure model lands first and standalone so the widgets and the CLI are thin renderers over an
> already-tested view-model. Every milestone ends in a **Checkpoint** with exact commands. The phase
> quality gate is `ruff check .` (zero findings), `ruff format --check .` (clean), and `pytest`
> (green, **offline, deterministic, no terminal, no network, no API keys**).
>
> New code reuses existing patterns: the `Verdict`/`RunStatus` enums and `RunRecord` derived helpers
> (`metrics_summary`, `by_category`, `asr_by_category`, `_asr`, `total_usage`, `total_cost_usd`) in
> `records.py`; the `Attack`/`Severity` models in `attacks.py`; the injected-dependency constructor
> style on `Runner` (`sleep`/`rng`/`now`/`scorer`) in `runner.py`; the Typer option/flag style in
> `cli.py`. **`textual` is the only new dependency** and is imported **only** in `tui/app.py` (and
> lazily in the `cli.py --tui` branch). The pure `tui/state.py` has **zero Textual import**. All
> changes to `runner.py`/`cli.py` are **additive** — the prior **137** tests stay green; any
> contract touch is called out explicitly (none expected — `on_attempt`/`--tui` both default off).

---

## Milestone 1 — `ScoreboardState` pure model + tests

**Build**
- `src/gauntlet/tui/__init__.py`: package marker; re-export the public state names.
- `src/gauntlet/tui/state.py` (NEW, **no `textual` import, no I/O**): the `@dataclass(frozen=True)`
  types `AttemptFilter`, `CategoryRow`, `FailureItem`, `ScoreboardState` (spec §3.1–§3.4) and the
  pure functions `build_scoreboard`, `apply_filter`, `with_filter`, `select_next`, `toggle_explain`,
  `repro_for` (spec §3.5). Reuse `records._asr`/`by_category()`/`metrics_summary()` — do **not**
  recompute ASR by hand. Join attempts → attacks by `attack_id` for severity/owasp/atlas/payload.
  Implement the deterministic `elapsed_s` rule (spec §3.6), the failure sort (severity-desc,
  category, attack_id), `progress`/`selected_failure` properties, and the exact `repro_for` format
  (spec §3.7).
  **[Review fixes]**
  - **#2 Severity ordering:** define a module-level `_SEVERITY_RANK = {LOW:0, MEDIUM:1, HIGH:2,
    CRITICAL:3}` in `state.py` (Severity enum has NO native ordering). The severity filter
    predicate is "this severity or worse": keep a failure iff `_SEVERITY_RANK[f.severity] >=
    _SEVERITY_RANK[filter.severity]`. The failure sort also uses this rank (desc).
  - **#5 `CategoryRow.total` from the PLAN, not executed attempts:** `total` per category is
    computed by grouping the **input `list[Attack]`** by `attack.category` — NOT from
    `record.by_category()` (which groups only executed attempts and would make `total == done`).
    Make this grouping an explicit step in `build_scoreboard`.
  - **#8 `rerun` acts on a single failure:** `selected_index` is one index → the re-run/explain
    target is exactly the one currently highlighted `FailureItem` (not all filtered).
- **[Fix #10]** `state.py` is imported in the M1 test (which runs BEFORE M3 installs textual), and
  the test asserts `assert "textual" not in sys.modules` after import — a machine-verifiable guard
  that the pure model never imports Textual.
- **[Fix #11]** extend `tests/fakes.py::make_attack` with keyword overrides for `severity`,
  `owasp`, `atlas` (currently hardcoded `high`/`LLM01`/`AML.T0051`) so FailureItem-join,
  `flag_severity`, and severity-filter tests can build attacks with differing values.
- `tests/test_scoreboard_state.py` (no Textual): spec §9.A — header counts + `overall_asr`;
  per-`CategoryRow` counts/`asr`/`flag_severity`; `total` from the plan with a not-yet-run attack
  (`done < total`, `progress < 1`); `elapsed_s` from fixed timestamps + fixed `now`; `FailureItem`
  join + sort order; `apply_filter`/`with_filter` by category/verdict/severity; `select_next`
  clamping incl. empty (`-1`); `toggle_explain`; `repro_for` exact string with `None`/missing-response
  rendering.

**Files**: `tui/__init__.py`, `tui/state.py`, `tests/test_scoreboard_state.py`.

**Checkpoint**
```
ruff check .
ruff format --check .
pytest tests/test_scoreboard_state.py -q
```
Passing: the view-model computes every UI value as pure functions, imports no Textual, and is fully
unit-tested. Prior 137 tests untouched (new module + new test only).

---

## Milestone 2 — Runner progress hook (additive)

**Build**
- `src/gauntlet/runner.py`: add `on_attempt: Callable[[AttemptRecord], None] | None = None` to
  `Runner.__init__` (keyword-only, alongside `scorer`), stored as `self._on_attempt`. In
  `_record_attempt`, **after** the `async with self._write_lock` block, call `self._on_attempt(attempt)`
  guarded by `if self._on_attempt is not None`, wrapped in `try/except Exception` that logs and
  continues (spec §5). No other changes; the ERROR/PASS/FAIL/SKIPPED paths and the resume skip-set
  are untouched.
- `tests/test_runner_hook.py`: spec §9.B — a `FakeAdapter` + `on_attempt=collector.append` collects
  one `AttemptRecord` per attack in completion order, and the persisted on-disk record already
  contains the attempt when the callback fires; a raising `on_attempt` leaves the run `COMPLETED`;
  `on_attempt=None` keeps behavior identical.

**Files**: `runner.py`, `tests/test_runner_hook.py`.

**Checkpoint**
```
ruff check .
ruff format --check .
pytest tests/test_runner_hook.py -q
pytest -q
```
Passing: the hook fires per attempt after persistence, never aborts a run, and is inert by default —
**the prior 137 tests stay green** (additive, default `None`).

---

## Milestone 3 — Textual app skeleton (header + grid + detail) + `run_test` smoke

**Build**
- `pyproject.toml`: add `textual>=0.80` to `[project].dependencies` (the single new dep; spec §1/§2).
- `src/gauntlet/tui/app.py` (NEW, the **only** module importing `textual`): `ScoreboardApp(App)`
  with the DI constructor `(attacks, record, *, target_name, engine=None)` (spec §6). Build
  `self.state = build_scoreboard(...)` from the inputs. Compose the widget tree: a `HeaderBar`
  (ASR/elapsed/cost/tokens/progress/status + `ProgressBar`), a `CategoryGrid` (`DataTable`), a
  `FailuresList` (`DataTable`, selectable), and a `DetailPane` (`Static`/`RichLog`), plus a minimal
  TCSS for PASS/FAIL/severity colors (spec §6). Implement `update_widgets()` as a **pure renderer**:
  it only reads `self.state` and writes cell/label text. Wire the live path:
  - **[Fix #3 — correct primitive]** the `on_attempt` callback (`self._post_attempt`) calls
    `self.post_message(AttemptRecorded(attempt))` **directly** — NOT `call_from_thread`. The
    engine runs as an async Textual worker on the SAME event-loop thread as the app, so
    `call_from_thread` would DEADLOCK (it blocks waiting for the loop it is running on).
    `post_message` is the correct, thread-safe primitive here.
  - **[Fix #4 — handler is a re-render trigger ONLY]** the `AttemptRecorded` handler must NOT
    re-insert/fold the attempt — the runner's `_record_attempt` already mutated the SAME
    `record.attempts` list object in place before the callback fired. The handler's only job is
    `self.state = build_scoreboard(self.attacks, self.record, ...)` then `update_widgets()`.
    Re-inserting would create duplicate attempts.
  - **[Fix #9 — worker API]** `on_mount`: if `engine is not None`, start an **async worker**
    (`@work(exclusive=False, thread=False)` or `run_worker(..., thread=False)`) that awaits
    `engine(self._post_attempt)` and flips status to `COMPLETED` on completion; if `engine is
    None`, render statically and start no worker.
- `tests/test_tui_app.py` (imports `textual`): spec §9.C **static + live smoke** only (bindings in
  M4) — `engine=None` static mount asserts header text + CategoryGrid rows + FailuresList items;
  a fake engine emitting a scripted attempt list drives `app.state.done`/status to completion.
  **[Fix #6 — deterministic worker drain]** the fake engine sets an `asyncio.Event` when it has
  emitted all scripted attempts; the pilot test `await`s that event (not a bare `pilot.pause()`)
  before asserting `app.state.done == len(scripted)`, so the live-update/binding tests are
  deterministic, never racy.

**Files**: `pyproject.toml`, `tui/app.py` (+ TCSS, e.g. `tui/app.tcss`), `tests/test_tui_app.py`.

**Checkpoint**
```
pip install -e ".[dev]"   # picks up textual
ruff check .
ruff format --check .
pytest tests/test_tui_app.py -q
pytest -q
```
Passing: the app mounts and renders the state offline via `app.run_test()`, live updates fold in from
a fake engine, and Textual is isolated to `app.py`. Prior 137 tests still green.

---

## Milestone 4 — Keybindings (filter / explain / copy-repro / rerun / quit) + pilot tests

**Build**
- `src/gauntlet/tui/app.py`: add `BINDINGS` and the action methods for spec §7 — `quit` (`q`/`ctrl+c`),
  `select_next(±1)` (`j`/`k`/arrows), `cycle_filter` (`f`, verdict `None→FAIL→ERROR→None`),
  `cycle_category_filter` (`c`), `cycle_severity_filter` (`s`), `toggle_explain` (`e`),
  `copy_repro` (`y`), `rerun_failures` (`r`). Each action mutates the app inputs, recomputes
  `self.state` via the M1 pure functions (`select_next`/`with_filter`/`toggle_explain`), and calls
  `update_widgets()`. `copy_repro` computes `repro_for(selected, target_name=...)`, stores
  `self.last_repro`, and calls the injected/monkeypatchable `self._clipboard_write(text)` (default
  best-effort, swallow errors); no-op when no failure is selected.
  **[Fix #1 + #8 — rerun via the runner's resume skip-set, single highlighted failure]**
  `rerun_failures` operates on exactly the ONE currently-highlighted `FailureItem` (not all
  filtered). The injected `engine` is callback-only (`Callable[[on_attempt_cb], Awaitable[
  RunRecord]]`) — it has NO attacks-subset parameter. So `r` does: (a) remove the highlighted
  attempt from `record.attempts` (under the same idea as the runner's resume drop-set), then
  (b) re-invoke the **same engine with its full original plan**; the Runner's resume logic
  (`done = {ids with verdict != ERROR}`) then re-runs exactly the dropped attack and skips the
  rest. Fold results in via the existing `AttemptRecorded` path. No-op (logged) when no engine is
  available. The fake engine in tests MUST simulate this skip-set (only emit for attack_ids not
  already present as non-ERROR in `record`) so the assertion is meaningful.
  DetailPane respects `explain_visible` (show/hide the `ScoreDetail` reason block + repro).
- `tests/test_tui_app.py`: spec §9.C **bindings** — under `app.run_test()`, drive `pilot.press(...)`
  for each key and assert the documented effect: `selected_index` after `j`/`k`; `filter.verdict`/
  `category`/`severity` + filtered row count after `f`/`c`/`s`; `explain_visible` + DetailPane text
  after `e`; `app.last_repro` (monkeypatched `_clipboard_write`) after `y`; the fake engine receives
  the selected `attack_id`(s) and state updates after `r`; `q` exits.

**Files**: `tui/app.py`, `tests/test_tui_app.py`.

**Checkpoint**
```
ruff check .
ruff format --check .
pytest tests/test_tui_app.py -q
pytest -q
```
Passing: every hotkey's effect is assertable offline via the pilot/state; copy-repro and rerun route
through monkeypatchable seams (no real clipboard, no network). Prior 137 tests still green.

---

## Milestone 5 — CLI `run --tui` wiring + integration

**Build**
- `src/gauntlet/cli.py`: add `tui: bool = typer.Option(False, "--tui", ...)` to `run`. When `--tui`:
  guard `--tui --dry-run` as a usage error (exit 2); build the `engine` closure that constructs
  `Runner(adapter, cfg.run, on_attempt=cb).run(selected, record)` (closing the adapter in `finally`);
  **lazily import** `ScoreboardApp` inside this branch and `ScoreboardApp(selected, record,
  target_name=target, engine=engine).run()`; on exit persist the record (same `run_path`/`--out`) and
  `typer.echo(_summary(...))` (spec §8). **[Fix #12]** cache `record_path = Runner(adapter,
  cfg.run).run_path(record)` BEFORE `.run()` (run_path only reads `output_dir`, so the adapter
  state is irrelevant, but compute it up front to avoid confusion). When `--tui` absent, the
  existing code path is byte-for-byte unchanged.
- `tests/test_cli_tui.py`: spec §9.D — `run --tui --dry-run` → exit 2; **[Fix #7 — one committed
  strategy]** replace `ScoreboardApp` with a thin **fake app class** (monkeypatch the name in
  `gauntlet.cli`) whose `.run()` does `asyncio.run(self.engine(lambda a: None))` synchronously —
  this exercises the REAL engine path (runner executes, record persists, adapter closes), so the
  test can assert the persisted `RunRecord` JSON, the `--out` file, and the echoed `_summary`. Do
  NOT monkeypatch `ScoreboardApp.run` to a no-op (that would skip the very things under test).
  Plain `run` covered by existing tests (unchanged).

**Files**: `cli.py`, `tests/test_cli_tui.py`.

**Checkpoint**
```
ruff check .
ruff format --check .
pytest -q
```
Passing: `gauntlet run --tui` launches the scoreboard, drives the real runner via the hook, persists
the same `RunRecord` + prints `_summary`, and errors on `--tui --dry-run`; the plain path is the
unchanged CI default. The **entire** suite is green offline — prior 137 tests plus the Phase-5 state,
hook, app, and CLI tests. Satisfies all acceptance criteria in spec §10.

---

## Plan review

1. **[BLOCKING] `rerun_failures` engine signature incompatible with partial re-runs.** Fixed (M4): engine stays callback-only; `r` drops the highlighted attempt from `record.attempts` then re-invokes the engine with the FULL plan — the runner's resume skip-set re-runs exactly that one. Fake engine simulates the skip-set.
2. **[BLOCKING] `Severity` has no ordering → "this severity or worse" filter unimplementable.** Fixed (M1): `_SEVERITY_RANK` dict in `state.py`; filter predicate `rank[f] >= rank[threshold]`.
3. **[BLOCKING] Live bridge used `call_from_thread` → deadlock (engine is on the app's own loop).** Fixed (M3): callback calls `self.post_message(AttemptRecorded(...))` directly; async worker `thread=False`.
4. **[BLOCKING] `AttemptRecorded` handler folding the attempt → duplicates (record is shared, already mutated in place).** Fixed (M3): handler only rebuilds `self.state` + `update_widgets()`, never re-inserts.
5. **`CategoryRow.total` can't come from `by_category()` (executed-only).** Fixed (M1): group the input `list[Attack]` by category for `total`.
6. **Pilot tests racy without worker drain.** Fixed (M3): fake engine sets an `asyncio.Event` on completion; tests await it before asserting.
7. **`test_cli_tui` monkeypatch strategy underspecified/contradictory.** Fixed (M5): committed to a thin fake app whose `.run()` runs the real engine synchronously, asserting persisted record + summary.
8. **`rerun` single-vs-all ambiguity.** Fixed (M1/M4): exactly the one highlighted `FailureItem`.
9. **Textual worker API unspecified.** Fixed (M3): async worker `thread=False` + `post_message`.
10. **No machine guard that `state.py` is Textual-free.** Fixed (M1): test asserts `"textual" not in sys.modules`.
11. **`make_attack` hardcodes severity/owasp/atlas.** Fixed (M1): add keyword overrides.
12. **`run_path` after adapter close in the TUI branch.** Fixed (M5): cache `record_path` up front.

**Resolution:** all four BLOCKING items (1–4) and the eight others (5–12) are folded into the
milestone build descriptions, test lists, and checkpoints above. Ready to implement.

STATUS: PASS
