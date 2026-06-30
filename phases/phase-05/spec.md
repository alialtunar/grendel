# Phase 5 — TUI scoreboard ⭐: spec

> Phase 5 of 10. The **CLI / TUI** box in ROADMAP §3 and the centerpiece of ROADMAP §8.5:
> a **live pass/fail scoreboard** that renders the `RunRecord` (Phase 1) as the runner
> (Phase 3) executes scored attempts (Phase 4) against a target. Per-category pass/fail grid,
> running ASR, elapsed/cost/progress, severity flags, a failure-detail pane (payload + what the
> target did), and hotkeys (re-run failures, filter, explain, copy repro, quit). This is the hero
> asset for the demo GIF — "the scoreboard is the product's face" (ROADMAP §2).
>
> **The make-or-break design constraint:** a **pure, framework-free presentation model**
> (`ScoreboardState`) computes *everything the UI needs* from a `RunRecord` + the selected
> `Attack`s, with **zero Textual import**. The Textual widgets are thin renderers over that state.
> Every hotkey's effect is assertable either through the state model or Textual's offline
> `app.run_test()` pilot harness. **No real terminal, no network, no API keys** in any test.
>
> **Not in this phase:** HTML/Markdown reports and the VHS GIF recording (Phase 10), LLM-judge
> (Phase 6), agent/side-effect targets (Phase 7), live re-run against a *remote* target as a hard
> guarantee — re-run is defined against the same offline/configured adapter and is fully testable
> with a fake engine.

---

## 1. Goals

1. A **pure** `ScoreboardState` view-model (new module, **no Textual import**) that, given the
   selected `list[Attack]` (the plan) and a `RunRecord` (live results), computes the header
   metrics (overall ASR, elapsed, cost, tokens, progress done/total, status), the per-category
   rows (PASS/FAIL/ERROR/SKIPPED counts, category ASR, severity flag), the failure list, the
   selected failure's detail, and a deterministic **copy-paste repro string**. Unit-tested as pure
   functions/dataclasses.
2. An additive, optional **`on_attempt` progress hook** on the `Runner` so the TUI gets a callback
   per recorded attempt and updates live — **default `None` → existing behavior unchanged, the
   prior 137 tests stay green**.
3. A **Textual `App`** (`ScoreboardApp`) that renders `ScoreboardState`: a header, a category grid,
   a failures list, a failure-detail pane, and a footer of key bindings. The widgets read state;
   they never compute metrics themselves.
4. A **keybinding set** — filter, explain, copy-repro, re-run failures, move selection, quit —
   where **each binding's effect is assertable** via the pilot harness and/or `ScoreboardState`.
5. CLI wiring: **`gauntlet run --tui`** launches the live scoreboard driving the real runner; the
   existing **plain (non-TUI) path is unchanged** and remains the default for CI and tests.
6. Add **`textual`** as the single new dependency (ROADMAP §6 chosen TUI lib). It is imported
   **only** in the app module, never in the pure state module.
7. Everything `pytest`-testable, **offline and deterministic**: pure-state unit tests + Textual
   `app.run_test()` pilot tests fed a prebuilt `RunRecord` and/or a fake engine emitting scripted
   attempt updates.

## 2. Scope

**In scope**
- `src/gauntlet/tui/__init__.py` (NEW) — package marker; re-exports the public names.
- `src/gauntlet/tui/state.py` (NEW) — the pure `ScoreboardState`, `CategoryRow`, `FailureItem`,
  `AttemptFilter` dataclasses and the pure builder/update/select/filter/repro functions. **No
  `textual` import. No I/O. No network.**
- `src/gauntlet/tui/app.py` (NEW) — `ScoreboardApp(textual.app.App)`: widgets, layout, bindings,
  and the worker that drives an injected async **engine**. The **only** module that imports
  `textual`.
- `src/gauntlet/runner.py` — additive `on_attempt` constructor parameter + call site (§5). No
  behavioral change when `on_attempt is None`.
- `src/gauntlet/cli.py` — a `--tui` flag on `run` that launches `ScoreboardApp`; the plain path
  stays the default.
- `pyproject.toml` — add `textual` to `[project].dependencies`.
- Tests: `tests/test_scoreboard_state.py`, `tests/test_runner_hook.py`,
  `tests/test_tui_app.py` (pilot), `tests/test_cli_tui.py`.

**Out of scope**
- HTML/MD report rendering, the VHS demo GIF, score-diff (Phase 10).
- LLM-judge / benign controls (Phase 6); agent/side-effect targets and live remote re-run
  guarantees (Phase 7).
- Any change to the verdict schema, ASR definition, or scorer (locked in Phase 4). Phase 5 only
  **reads** `RunRecord`/`AttemptRecord`/`ScoreDetail` and `Attack`.
- Custom themes/CSS polish beyond a minimal, legible TCSS layout.

---

## 3. The `ScoreboardState` model (pure, framework-free)

`state.py` holds **plain `@dataclass(frozen=True)`** types (or Pydantic models for parity with the
codebase — choose `@dataclass` to keep this module dependency-light and obviously framework-free).
The model is built from two inputs that mirror ROADMAP §3: the **plan** (`list[Attack]` — gives
`total`, severity/owasp/atlas/payload) and the **live results** (`RunRecord` — gives the executed
`AttemptRecord`s with verdicts). Severity/owasp/atlas live on `Attack`, **not** on `AttemptRecord`,
so the builder must join attempts to their attack by `attack_id`.

### 3.1 `AttemptFilter`
```python
@dataclass(frozen=True)
class AttemptFilter:
    category: str | None = None          # show only this category (None = all)
    verdict: Verdict | None = None       # show only this verdict in the failures list (None = all FAIL/ERROR)
    severity: Severity | None = None     # show only this severity or worse (None = all)
```
A filter is **data**; applying it is a pure function (§3.5). The default `AttemptFilter()` shows
everything.

### 3.2 `CategoryRow`
```python
@dataclass(frozen=True)
class CategoryRow:
    category: str
    total: int            # attacks planned in this category (from the plan)
    done: int             # attempts recorded in this category
    passed: int           # Verdict.PASS count
    failed: int           # Verdict.FAIL count (attack succeeded)
    errored: int          # Verdict.ERROR count
    skipped: int          # Verdict.SKIPPED count
    asr: float            # _asr over scored (PASS+FAIL) rows — reuse records._asr semantics
    flag_severity: Severity | None   # max Severity among FAILED attacks in this category; None if no failures
```
`asr` matches the Phase-4 lock exactly (FAIL / (PASS+FAIL), 0.0 if none scored). Rows are sorted by
category name for deterministic rendering.

### 3.3 `FailureItem`
One entry per attempt whose verdict is **FAIL** (attack succeeded) or **ERROR** (unscoreable). The
ASR-relevant breaches are FAIL; ERROR is included so operators see crashed attempts. Each item joins
attempt + attack metadata:
```python
@dataclass(frozen=True)
class FailureItem:
    attempt_id: str
    attack_id: str | None
    name: str | None            # Attack.name (from the plan), if known
    category: str | None
    severity: Severity | None   # from Attack
    owasp: str | None           # from Attack
    atlas: str | None           # from Attack
    verdict: Verdict            # FAIL or ERROR
    score_tier: str | None      # "T1" | "T2" | None
    payload: str | None         # Attack.payload (from the plan) — the attack we sent
    prompt: str                 # AttemptRecord.prompt (what was actually sent)
    response_text: str | None   # what the target did
    reason: str | None          # ScoreDetail.reason (the "explain" text)
    matched: str | None         # ScoreDetail.matched
    classifier_score: float | None
    error: str | None           # AttemptRecord.error (ERROR rows)
```
Failures are sorted by **severity desc, then category, then attack_id** for a stable, worst-first
order.

### 3.4 `ScoreboardState`
```python
@dataclass(frozen=True)
class ScoreboardState:
    run_id: str
    target_name: str
    provider: str
    model: str
    status: RunStatus
    total: int                  # planned attacks (len of the plan)
    done: int                   # recorded attempts
    passed: int
    failed: int
    errored: int
    skipped: int
    overall_asr: float          # record.asr (Phase-4 locked)
    elapsed_s: float            # see §3.6
    total_cost_usd: float       # record.total_cost_usd
    total_tokens: int           # record.total_usage.total_tokens
    categories: tuple[CategoryRow, ...]
    failures: tuple[FailureItem, ...]    # AFTER filter applied
    selected_index: int         # index into `failures`; clamped to [0, len-1], or -1 if empty
    filter: AttemptFilter
    explain_visible: bool       # toggled by the explain hotkey (§7)

    @property
    def progress(self) -> float:        # done/total, 0.0 if total == 0
    @property
    def selected_failure(self) -> FailureItem | None:   # failures[selected_index] or None
```

### 3.5 Pure functions (the entire compute surface — no Textual, no I/O)
```python
def build_scoreboard(
    attacks: list[Attack],
    record: RunRecord,
    *,
    now: datetime | None = None,
    filter: AttemptFilter = AttemptFilter(),
    selected_index: int = 0,
    explain_visible: bool = False,
) -> ScoreboardState: ...
```
- Joins `record.attempts` to `attacks` by `attack_id`; computes counts via `record.metrics_summary`
  semantics and per-category rows via `record.by_category()` / `records._asr` (reuse, don't
  reinvent). `total = len(attacks)`.
- `failures` = the FAIL/ERROR attempts as `FailureItem`s, then `apply_filter(...)` then sort.
- `selected_index` clamped into the filtered `failures` range.

```python
def apply_filter(items: list[FailureItem], f: AttemptFilter) -> list[FailureItem]: ...
def select_next(state, +1/-1) -> ScoreboardState: ...   # returns a new state with selected_index moved & clamped
def with_filter(state, f) -> ScoreboardState: ...        # rebuilds failures+selection under a new filter (pure)
def toggle_explain(state) -> ScoreboardState: ...        # flips explain_visible
def repro_for(item: FailureItem, *, target_name: str) -> str: ...   # §3.7
```
The app holds the *inputs* (`attacks`, `record`, current `filter`/`selection`/`explain`) and calls
these pure functions to recompute `ScoreboardState` on every change. Because they are pure, each can
be unit-tested in isolation with a hand-built `RunRecord` + `Attack` list.

### 3.6 Elapsed-time rule (deterministic)
`elapsed_s` is computed **from the data**, not wall-clock, so tests are deterministic:
- `start = min(a.started_at for a in attempts if a.started_at)`; if none, `0.0`.
- `end = now` if the run is `RUNNING` and `now` is provided, else
  `max(a.finished_at for a in attempts if a.finished_at)`; if none, `start`.
- `elapsed_s = max(0.0, (end - start).total_seconds())`.
Live mode passes `now=datetime.now(UTC)`; tests pass a fixed `now` (or rely on the attempts'
`finished_at`) for a fixed number.

### 3.7 Repro-string format (assertable, copy-paste)
`repro_for` returns a deterministic, multi-line string an operator can paste to re-run a single
attack and read what happened. Exact format (asserted character-for-character in tests):
```
# gauntlet repro — <attack_id>
# category=<category> severity=<severity> owasp=<owasp> atlas=<atlas>
gauntlet run --target <target_name> --pack <attack_id>
# payload sent:
<payload>
# target response:
<response_text or "(no response)">
# verdict: <VERDICT> [<score_tier or "-">] — <reason or error or "(no detail)">
```
`None` fields render as `-`; `attack_id is None` renders as `(unknown)`. The string is pure over the
`FailureItem` + `target_name` — no clipboard, no I/O (the clipboard write lives in the app, §7).

---

## 4. Inputs the state reads (read-only contracts, unchanged)
- `RunRecord`: `attempts`, `status`, `asr`, `total_cost_usd`, `total_usage`, `by_category()`,
  `asr_by_category()`, `metrics_summary()` (records.py).
- `AttemptRecord`: `attempt_id`, `attack_id`, `category`, `prompt`, `response_text`, `verdict`,
  `score_tier`, `score_detail` (`ScoreDetail.reason/matched/classifier_score`), `error`, `usage`,
  `cost_usd`, `started_at`, `finished_at`.
- `Attack`: `id`, `name`, `category`, `owasp`, `atlas`, `severity`, `payload` (attacks.py).
Phase 5 makes **no edits** to these models.

---

## 5. Runner progress hook (additive, back-compatible)

Add one optional constructor parameter, in the same injected-dependency style as `sleep`/`rng`/`now`/
`scorer`:
```python
def __init__(self, adapter, options, *, sleep=..., rng=..., now=..., monotonic=..., scorer=None,
             on_attempt: Callable[[AttemptRecord], None] | None = None) -> None:
    ...
    self._on_attempt = on_attempt
```
**When called:** inside `_record_attempt`, **after** the attempt is appended and persisted and the
`self._write_lock` is released — once per recorded attempt (ERROR, PASS, FAIL, SKIPPED alike), in
attempt-completion order. Calling it *after* the lock means a slow UI callback never blocks the
persistence path or other tasks.
```python
async def _record_attempt(self, record, attempt) -> None:
    async with self._write_lock:
        record.attempts = [a for a in record.attempts if a.attack_id != attempt.attack_id]
        record.attempts.append(attempt)
        self._atomic_write(record)
    if self._on_attempt is not None:
        try:
            self._on_attempt(attempt)
        except Exception:            # a UI callback must never crash a run
            log.exception("on_attempt callback raised; continuing")
```
**Back-compat:** `on_attempt` defaults to `None`; the `if` guard means the call site is inert and
the existing 137 tests are unaffected. The callback is **synchronous** and must be non-blocking — the
TUI's callback only enqueues/posts a Textual message (it does not render inline). This keeps the
runner free of any TUI dependency (one-way: TUI → runner via the hook, never runner → TUI).

---

## 6. Textual app layout

`ScoreboardApp(App)` in `app.py` — the **only** module importing `textual`.

**Construction (dependency-injected for testability):**
```python
ScoreboardApp(
    attacks: list[Attack],
    record: RunRecord,
    *,
    target_name: str,
    engine: Callable[[Callable[[AttemptRecord], None]], Awaitable[RunRecord]] | None = None,
)
```
- `engine` is an async callable that runs the work and invokes the passed `on_attempt` callback per
  attempt. **Real CLI** passes an engine that builds `Runner(adapter, options, on_attempt=cb)` and
  awaits `runner.run(attacks, record)`. **Tests** pass a fake engine that calls `cb(attempt)` for a
  scripted list of `AttemptRecord`s (no runner, no network). `engine=None` → render the static board
  from `record` and never start a worker (pure-render smoke test).
- The app keeps the mutable inputs (`record`, `filter`, `selected_index`, `explain_visible`) and
  recomputes `self.state = build_scoreboard(...)` on every update, then refreshes widgets.

**Widget tree / layout:**
```
Header (custom HeaderBar widget)
  └─ ASR <overall_asr>  ·  elapsed <mm:ss>  ·  cost $<…>  ·  tokens <…>  ·  <done>/<total>
     ProgressBar(total=total, progress=done)   status: <RUNNING/COMPLETED/…>
Horizontal
  ├─ Vertical (left, ~55%)
  │    ├─ CategoryGrid  (DataTable)
  │    │     columns: Category | Pass | Fail | Err | Skip | ASR | Sev | Done/Total
  │    │     one row per CategoryRow; Sev shows the flag_severity badge; FAIL cells styled red,
  │    │     PASS green (TCSS classes by verdict).
  │    └─ FailuresList  (DataTable, selectable)
  │          columns: Sev | Category | Attack | Verdict   — one row per filtered FailureItem;
  │          highlighted row == state.selected_index.
  └─ DetailPane (right, ~45%, a Static/RichLog)
         shows selected_failure: name, attack_id, severity/owasp/atlas, payload, target response,
         and — when explain_visible — the ScoreDetail reason/matched/classifier_score, plus the
         repro string.
Footer (BINDINGS)
```
A minimal TCSS file styles PASS/FAIL/severity colors. The grid/list/detail are **pure renderers**:
each `update_widgets()` reads `self.state` and writes cell text — no metric computation in the app.

**Live updates:** the injected `engine`'s `on_attempt` callback posts a custom Textual message
(`AttemptRecorded`) via `self.call_from_thread`/`post_message`; the message handler folds the new
attempt into `record`, rebuilds `self.state`, and calls `update_widgets()`. On engine completion the
status flips to `COMPLETED`.

---

## 7. Keybindings (each effect assertable)

`BINDINGS` on `ScoreboardApp`. Every action mutates the app's inputs, recomputes `self.state`, and
refreshes — so the effect is assertable via `app.state` and/or widget contents under
`app.run_test()`.

| Key | Action | Assertable effect |
|-----|--------|-------------------|
| `q` / `ctrl+c` | `quit` | App exits; `pilot` context ends, `app.return_code`/exit observed. |
| `j` / `down` | `select_next(+1)` | `state.selected_index` increments (clamped); DetailPane shows the next `FailureItem`. |
| `k` / `up` | `select_next(-1)` | `state.selected_index` decrements (clamped); DetailPane updates. |
| `f` | `cycle_filter` | Cycles the verdict filter `None → FAIL → ERROR → None`; `state.filter.verdict` changes and `FailuresList` row count changes accordingly (via `with_filter`). |
| `c` | `cycle_category_filter` | Cycles `filter.category` through the present categories + `None`; filtered failures/grid focus change is observable in `state.filter.category`. |
| `s` | `cycle_severity_filter` | Cycles `filter.severity` through `Severity` values + `None`; `state.filter.severity` changes, filtered list shrinks/grows. |
| `e` | `toggle_explain` | `state.explain_visible` flips; DetailPane shows/hides the `ScoreDetail` reason block (assert pane text contains/omits the reason). |
| `y` | `copy_repro` | Computes `repro_for(selected_failure, target_name=...)`, stores it on `self.last_repro`, and calls a **monkeypatchable** `self._clipboard_write(text)` (default: best-effort, swallow errors). Assert `app.last_repro == expected_repro` and that the patched clipboard fn received it. No-op (and `last_repro` unchanged) when no failure is selected. |
| `r` | `rerun_failures` | Re-runs the **selected** failed attempt(s) through the **same injected engine/adapter**: drops their ERROR/FAIL `AttemptRecord`(s) from `record` and re-invokes the engine for those `attack_id`s, folding new results back in (mirrors the runner's resume drop-set on `verdict != ERROR`). In tests the fake engine is asserted to be called with exactly the selected `attack_id`(s) and `state` updates. If no live/configured adapter is available the binding is a no-op (logged) — but the binding + state transition remain testable with the fake engine. |

`copy_repro` and `rerun_failures` are the two that touch the outside world; both route through a
single injected/monkeypatchable seam (`_clipboard_write`, `engine`) so tests assert the call without
any real clipboard or network.

---

## 8. CLI wiring (`run --tui`) and the unchanged plain path

Add one flag to `run`:
```python
tui: Annotated[bool, typer.Option("--tui", help="Live TUI scoreboard (Textual).")] = False
```
- **`--tui` absent (default):** the existing code path runs unchanged — `asyncio.run(_execute(...))`
  then `typer.echo(_summary(...))`. This is the **CI/headless/test path**; `--dry-run`, `--resume`,
  `--out` all behave exactly as today. The prior 137 tests do not touch `--tui`.
- **`--tui` present:** after resolving `info`, `adapter`, `attacks`, and building `record` (same as
  today), construct the engine and launch the app instead of the plain runner:
  ```python
  def engine(on_attempt):
      async def _run():
          try:
              return await Runner(adapter, cfg.run, on_attempt=on_attempt).run(selected, record)
          finally:
              await adapter.aclose()
      return _run()
  ScoreboardApp(selected, record, target_name=target, engine=engine).run()
  # then persist + echo the same _summary line on exit
  ```
  `--tui` is incompatible with `--dry-run` (dry-run sends nothing) — guard with a usage error
  (exit 2). On app exit the record is persisted and the same one-line `_summary` is printed, so the
  TUI run still produces the durable artifact + `--out`.
- Importing `textual` happens **inside** the `--tui` branch (lazy import in `cli.py`) so the plain
  path and `gauntlet --help` never require Textual at import time.

---

## 9. Offline testing strategy

All tests are **offline, deterministic, no terminal, no network, no API keys**.

**A. Pure-state unit tests — `tests/test_scoreboard_state.py`** (no Textual import):
- `build_scoreboard` over a hand-built `RunRecord` (mix of PASS/FAIL/ERROR/SKIPPED across ≥2
  categories) + matching `Attack` list: assert header counts, `overall_asr` (Phase-4 locked),
  per-`CategoryRow` counts + `asr` + `flag_severity`, `progress = done/total`, and `total` from the
  plan (incl. a planned-but-not-yet-run attack → `done < total`).
- `elapsed_s` from fixed `started_at`/`finished_at` (and a fixed `now` in RUNNING state).
- `FailureItem` join: severity/owasp/atlas/payload pulled from the `Attack`; reason/matched from
  `ScoreDetail`; ERROR rows carry `error`. Sort order = severity-desc, category, attack_id.
- `apply_filter`/`with_filter` by category, verdict, severity (incl. "severity or worse").
- `select_next` clamps at both ends and on an empty list (`selected_index == -1`).
- `toggle_explain` flips the flag.
- `repro_for` exact string (with `None` fields → `-`, missing response → `(no response)`).

**B. Runner hook tests — `tests/test_runner_hook.py`:**
- With a `FakeAdapter` and `on_attempt=collector.append`: collector gets one `AttemptRecord` per
  attack, in completion order, after persistence (the on-disk record already contains it).
- A raising `on_attempt` does **not** abort the run (run still `COMPLETED`).
- `on_attempt=None` (default) → byte-identical behavior to today (a guard test; the existing 137
  runner/CLI tests are the real proof).

**C. Textual pilot tests — `tests/test_tui_app.py`** (the only test file importing `textual`):
```python
async with app.run_test() as pilot:
    ...
    await pilot.press("j"); await pilot.press("f"); await pilot.press("y")
    assert app.state.selected_index == 1
    assert app.last_repro.startswith("# gauntlet repro —")
```
- **Static render smoke:** `ScoreboardApp(attacks, record, engine=None)` mounts; header shows the
  ASR/elapsed/cost; CategoryGrid has the expected rows; FailuresList lists the FAIL/ERROR items.
- **Live updates via a fake engine:** the engine calls `on_attempt(attempt)` for a scripted list;
  after the worker drains, `app.state.done == len(scripted)`, status `COMPLETED`, ASR updated.
- **Bindings:** drive `pilot.press(...)` for each key in §7 and assert the documented effect on
  `app.state` (selection, filter, explain) and/or widget text (DetailPane contains the reason after
  `e`; `app.last_repro` after `y` with a monkeypatched `_clipboard_write`; the fake engine receives
  the selected `attack_id`s after `r`; `q` exits).
- A monkeypatched `_clipboard_write` records the copied text — **no OS clipboard** touched.

**D. CLI tests — `tests/test_cli_tui.py`:**
- `run --tui --dry-run` → usage error (exit 2).
- `run --tui` with a `FakeAdapter` and a monkeypatched/headless `ScoreboardApp.run` (or
  `app.run_test`-style driver) executes the engine, persists the record, prints the `_summary` line,
  and writes `--out` — proving the wiring without a real terminal.
- Plain `run` (no `--tui`) is unchanged (covered by existing tests).

---

## 10. Acceptance criteria

1. `src/gauntlet/tui/state.py` has **zero `textual` import** and computes all header metrics,
   category rows, failures, selection, filtering, and the repro string as pure functions — verified
   by `tests/test_scoreboard_state.py`.
2. `Runner` gains an additive `on_attempt` hook called once per recorded attempt after persistence;
   `on_attempt=None` is the default and the **prior 137 tests stay green**.
3. `ScoreboardApp` renders the state (header + category grid + failures list + detail pane) and
   updates live from an injected engine — verified offline with `app.run_test()`.
4. Every keybinding in §7 has an assertable effect proven by a pilot or state test
   (quit, select, filter ×3, explain, copy-repro, re-run failures).
5. `gauntlet run --tui` launches the scoreboard and still persists the same `RunRecord` + prints the
   `_summary`; the plain path is unchanged and remains the CI default; `--tui --dry-run` errors.
6. `textual` is the **only** new dependency, imported solely in `app.py` (and lazily in the `cli.py`
   `--tui` branch).
7. `ruff check .`, `ruff format --check .`, and `pytest` are all green — **offline, deterministic,
   no terminal, no network, no API keys**.
