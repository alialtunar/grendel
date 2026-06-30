# Phase 3 — Runner engine: implementation plan

> Build order is dependency-ordered: runner config + request building + fake-adapter harness +
> persistence → concurrency + rate-limit + timeout → retries/backoff (seedable) + error
> taxonomy → token/cost accounting + resume → CLI `run` wiring + integration. Every milestone
> ends in a **Checkpoint** with exact commands. The phase quality gate is `ruff check .` (zero
> findings), `ruff format --check .` (clean), and `pytest` (green, **offline, no API keys**).
> New code reuses existing patterns: Pydantic v2 `ConfigDict(extra="forbid")` (`config.py`),
> the `GauntletError` hierarchy (`errors.py`), the `TargetAdapter` contract (`targets/base.py`),
> and the `RunRecord`/`make_run_record` data model (`records.py`). **No new third-party deps** —
> only stdlib `asyncio`/`random`/`time`/`os`; `httpx` is already present. All `records.py`
> changes are **additive** so the Phase-1 (41) and Phase-2 (38) suites stay green. The runner
> imports **no scorer** — verdicts are `SKIPPED`/`ERROR` only (scoring is Phase 4).

---

## Milestone 1 — Runner config + request building + fake-adapter harness + persistence

**Build**
- `src/gauntlet/config.py`: add the six `RunOptions` fields per spec §4 (`concurrency` `ge=1`
  =4, `rps` `gt=0|None` =None, `max_retries` `ge=0` =3, `retry_base_delay_s` `ge=0` =0.5,
  `retry_max_delay_s` `ge=0` =30.0, `retry_seed` `int|None` =None). All defaulted →
  `config_snapshot` and existing configs still validate.
- `src/gauntlet/records.py`: add `AttemptRecord.cost_usd: float | None = None` (additive, no
  `schema_version` bump).
- `tests/fakes.py`: `FakeAdapter(TargetAdapter)` — canned `AdapterResponse`, records received
  `AdapterRequest`s; constructor knobs for `text`, token counts, `model`, `provider`, and a
  per-call failure script (used in M3). Plus a recording `sleep` and a manual `monotonic`
  clock helper.
- `src/gauntlet/runner.py` (first slice): `Runner.__init__` (with injected `sleep`/`rng`/`now`/
  `monotonic`), `run_path()`, `_build_request(attack)` (payload→prompt, max_tokens/temperature
  from options — spec §5), atomic `_write_record(record)` (temp file + `os.replace`, guarded by
  an `asyncio.Lock`, `output_dir` created), and a **sequential** `run()` that executes attacks
  (sorted by id), folds each success into an `AttemptRecord` (`verdict=SKIPPED`, response_text,
  raw_response, usage, latency, timestamps), sets `RunStatus.RUNNING`→`COMPLETED`, and persists
  at start/after each/at end. (Concurrency/rate-limit/timeout/retries come in M2–M3.)
- `tests/test_runner_basic.py`: single + multi attack happy path against `FakeAdapter`; assert
  request building (prompt == payload, pinned max_tokens/temperature), `verdict==SKIPPED`,
  usage copied, deterministic id ordering, and that `output_dir/<run_id>.json` exists and
  round-trips via `RunRecord.from_json`.

**Files**: `config.py`, `records.py`, `runner.py`, `tests/fakes.py`, `tests/test_runner_basic.py`.

**Checkpoint**
```
ruff check .
ruff format --check .
pytest tests/test_runner_basic.py -q
```
Passing: ruff + format clean; the runner builds correct requests, records `SKIPPED` attempts,
and persists a valid, reloadable `RunRecord` — all offline (spec §13 #2, and the persistence
half of #7).

---

## Milestone 2 — Concurrency + rate-limit + timeout

**Build**
- `src/gauntlet/runner.py`: replace the sequential loop with a scheduled one —
  `asyncio.Semaphore(options.concurrency)` shared across attempts, all remaining attacks
  launched as tasks and `await asyncio.gather`-ed. Add the global min-interval **rate-limit
  gate** (`asyncio.Lock` + `last_dispatch`, interval `1/rps`, `rps=None` → no-op) using the
  injected `monotonic`/`sleep`, run once per attempt before the send. Wrap each send in
  `asyncio.wait_for(adapter.send(req), options.request_timeout_s)`; a `TimeoutError` surfaces
  here (its retry handling lands in M3 — for now, with `max_retries=0`, a timeout records
  `Verdict.ERROR`). Keep per-attempt persistence under the write-lock.
  **[Review fixes]** #4: each task body has a catch-all `except Exception` → record
  `Verdict.ERROR` (NOT just `TimeoutError`) so M2's runner is already crash-safe before M3
  adds the full taxonomy. #10: `asyncio.gather(*tasks)` runs with default
  `return_exceptions=False`; the per-task handler converts every `Exception` to ERROR but
  must **re-raise `CancelledError`** (do not catch it) so it propagates to the ABORTED path.
  #8: the rate-limit gate is taken **outside/before** the concurrency semaphore (acquire
  rate slot → acquire semaphore → send), so a task does not burn a concurrency slot while
  sleeping the rate interval. Note this ordering explicitly in the code.
- `tests/test_runner_concurrency.py`: a barrier `FakeAdapter` proving max in-flight == 
  `concurrency` (e.g. 2 with 6 attacks); rate-limit spacing asserted against the fake clock
  (timestamps ≥ `1/rps`; `rps=None` → no spacing); a timeout `FakeAdapter` with `max_retries=0`
  → that attempt is `Verdict.ERROR` and the run still completes.

**Files**: `runner.py`, `tests/test_runner_concurrency.py`.

**Checkpoint**
```
ruff check .
ruff format --check .
pytest tests/test_runner_concurrency.py -q
```
Passing: concurrency is bounded by the semaphore, rate-limit spacing holds on the fake clock,
per-request timeout fires, and a timed-out attempt is recorded (not crashed) — spec §13 #3, #4,
and the timeout path of #5.

---

## Milestone 3 — Retries / backoff (seedable) + error taxonomy

**Build**
- `src/gauntlet/errors.py`: `AdapterError.__init__(self, message, *, status_code=None)` storing
  `self.status_code` (additive — `AdapterError("msg")` still works). **[Fix #6]** the override
  MUST call `super().__init__(message)` so `str(exc)` stays the human-readable message
  (used for `AttemptRecord.error=str(exc)`); add a test asserting `str(AdapterError("x"))=="x"`.
- `src/gauntlet/targets/http_adapter.py`: the non-2xx raise passes
  `status_code=resp.status_code` (one-line change; no behavior change for callers).
- `src/gauntlet/runner.py`: wrap each send in the retry loop — up to `1 + max_retries` tries;
  `_is_transient(exc)` per spec §7 table (`asyncio.TimeoutError`, `httpx.TimeoutException`,
  `httpx.TransportError`, `AdapterError` with `status_code==429` or `5xx`); full-jitter backoff
  `delay = rng.uniform(0, min(retry_max_delay_s, retry_base_delay_s * 2**i))` via the injected
  `rng`/`sleep`. Non-transient or exhausted-transient → `AttemptRecord` `verdict=ERROR`,
  `error=str(exc)`, timestamps set; the run continues. Propagate `CancelledError`/
  `KeyboardInterrupt` → `RunStatus.ABORTED` + final persist.
- `tests/test_runner_retries.py`: transient fails K<max then succeeds (assert success +
  recorded sleep sequence exactly, via seeded `Random`); transient exhausted → `ERROR`;
  429/5xx `AdapterError` → retried; non-transient (`AdapterError` status `None`/`404`,
  `ProviderError`, `ValueError`) → `ERROR` with **zero** sleeps; a run with one failing attack
  still ends `COMPLETED`.

**Files**: `errors.py`, `targets/http_adapter.py`, `runner.py`, `tests/test_runner_retries.py`.

**Checkpoint**
```
ruff check .
ruff format --check .
pytest tests/test_runner_retries.py -q
```
Passing: transient errors retry with deterministic seeded backoff, non-transient errors record
`ERROR` without retry, exhaustion records `ERROR`, and the run never crashes — spec §13 #5.

---

## Milestone 4 — Token/cost accounting + RunRecord persistence + resume

**Build**
- `src/gauntlet/pricing.py`: `PRICES` table (illustrative placeholders, a few openai/anthropic
  models) + `estimate_cost(provider, model, usage) -> tuple[float, bool]`; unknown → `(0.0,
  False)`.
- `src/gauntlet/records.py`: **[Fix #5]** add `TokenUsage.__add__` (returns a new
  `TokenUsage` summing prompt/completion) so `sum(...)` works; then add
  `RunRecord.total_usage` and `RunRecord.total_cost_usd` **properties** (sum over attempts,
  treating `cost_usd=None` as 0; mirrors the existing `asr` property — derived, not
  serialized).
- `src/gauntlet/runner.py`: on each success, copy response tokens into `AttemptRecord.usage`
  (missing → 0) and set `cost_usd` from `estimate_cost(record.provider, record.model, usage)`
  (debug-log a one-line note when unknown). **[Fix #9]** on `ERROR` attempts leave
  `cost_usd = None` (no response → no tokens; never store `0.0`). Implement the **resume
  skip-set**: at `run()` start build `done = {a.attack_id for a in record.attempts if
  a.verdict != Verdict.ERROR}`; schedule only attacks whose `id not in done`. **[Fix #1]**
  before appending a re-tried `ERROR` attempt's new record, **remove all existing
  `AttemptRecord`s with that `attack_id`** from `record.attempts` (no duplicate ids ever);
  do the remove+append under the write-lock so concurrent completions can't race.
- `tests/test_runner_cost_resume.py`: `total_usage` == sum; priced model → `cost_usd>0`,
  unlisted → `0.0`; `estimate_cost` unknown → `(0.0, False)`; build a partial record (some
  `SKIPPED`, one `ERROR`, some attacks missing), feed it back into `run()` with the same attack
  list → executed skipped, `ERROR`+missing run, ends `COMPLETED`, file valid JSON throughout.

**Files**: `pricing.py`, `records.py`, `runner.py`, `tests/test_runner_cost_resume.py`.

**Checkpoint**
```
ruff check .
ruff format --check .
pytest tests/test_runner_cost_resume.py -q
```
Passing: token/cost aggregation is correct (known + unknown models), and resume skips executed
attempts while re-running `ERROR`/missing ones — spec §13 #6, #7.

---

## Milestone 5 — CLI `run` wiring + integration

**Build**
- `src/gauntlet/cli.py`: replace the Phase-1 `run` stub body with the real flow (spec §11):
  resolve config + target, `load_packs(default_packs_dir())`, filter by `--pack` (id or
  category; unknown `--pack` → echo stderr + `raise typer.Exit(2)`), `make_run_record(...)`
  with **[Fix #12]** `RunRecord.pack_ids` = the **resolved attack ids** selected (not the raw
  `--pack` strings), so resume re-derives the exact selection;
  `asyncio.run(Runner(adapter, cfg.run).run(attacks, record))`, `adapter.aclose()`, optional
  `--out` write, and a summary line (run id, attempts, executed/error counts, total tokens,
  est. cost, path). `--dry-run` → build adapter with `dry_run=True`, select attacks, print the
  plan (count + ids + `$0.00 (not sent)`), **no network, no record**.
  **[Fix #3 + #7]** `--resume PATH` → load the `RunRecord`; **re-derive selection by filtering
  `load_packs()` to `record.pack_ids`** (do not mix with fresh `--pack` flags) so only the
  original attacks run; set `cfg.run.output_dir = Path(PATH).parent` so incremental writes via
  `run_path` (which uses `record.run_id`) land back in `PATH`; persist back.
- `tests/test_cli_run.py` (Typer `CliRunner`): `--dry-run` prints the plan, writes nothing,
  exits 0, makes no network call; with **both** `gauntlet.cli.build_target` **and**
  `gauntlet.cli.load_packs` **monkeypatched** (**[Fix #2]** — `load_packs` → a small in-memory
  `list[Attack]`, or use a `tmp_path` packs dir, so the test never depends on the bundled
  packs), `run --target T` executes the full offline pipeline, writes a valid `RunRecord` JSON,
  and prints the summary; `--pack <id>` filters; unknown `--pack` exits 2. Add a `--resume`
  test: a partial record round-trips and only its `pack_ids` attacks run.

**Files**: `cli.py`, `tests/test_cli_run.py`.

**Checkpoint**
```
ruff check .
ruff format --check .
pytest -q
# [Fix #11] optional LOCAL smoke test only (needs a configured target in your config):
gauntlet run --target <configured-target> --dry-run
```
Passing: the **entire** suite is green offline with no API keys (Phase-1 41 + Phase-2 38 +
Phase-3 tests); `gauntlet run --dry-run` prints a plan with no network; the monkeypatched
integration test drives the full runner offline and writes a valid record. This satisfies all
acceptance criteria in spec §13 (#1 across all milestones, #8 here).

---

## Plan review

1. **[BLOCKING] `ERROR` attempt replacement appends duplicates.** Fixed: under the write-lock, remove all existing `AttemptRecord`s with that `attack_id` before appending the re-tried result (M4).
2. **[BLOCKING] CLI test has no `load_packs` seam.** Fixed: M5 test monkeypatches both `build_target` and `load_packs` (or uses a tmp packs dir) so it runs offline without bundled packs.
3. **[BLOCKING] `--resume` attack-list re-derivation undefined.** Fixed: CLI re-derives selection by filtering `load_packs()` to `record.pack_ids` (M5).
4. **[BLOCKING] M2 has no catch-all → unsafe checkpoint.** Fixed: M2 adds `except Exception → Verdict.ERROR` per task (re-raising `CancelledError`), making the runner crash-safe before M3.
5. **[BLOCKING] `TokenUsage.__add__` absent → `total_usage` unimplementable.** Fixed: add `TokenUsage.__add__` in records.py (M4).
6. **`AdapterError.__init__` must call `super().__init__(message)`** so `str(exc)` stays the message. Fixed + test (M3).
7. **`--resume` dual-write path.** Fixed: set `cfg.run.output_dir = Path(PATH).parent` so incremental writes land in `PATH` (M5).
8. **Rate-gate vs semaphore ordering.** Fixed: rate gate taken outside/before the semaphore so slots aren't burned while sleeping (M2).
9. **`cost_usd` on ERROR attempts.** Fixed: left as `None`, never `0.0` (M4).
10. **`asyncio.gather` exception mode.** Fixed: default `return_exceptions=False`; `CancelledError` not caught by per-task handler → ABORTED path (M2).
11. **M5 shell smoke command needs a live target.** Fixed: marked optional/local; automated coverage is `pytest tests/test_cli_run.py`.
12. **What `pack_ids` stores.** Fixed: resolved attack ids (not raw `--pack` strings), consistent with resume re-derivation (M5).

**Resolution:** all five BLOCKING items (1–5) and the seven non-blocking items (6–12) are
folded into the milestone build descriptions and checkpoints above. Ready to implement.

STATUS: PASS
