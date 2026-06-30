# Phase 3 — Runner engine: spec

> Phase 3 of 10. This is the **Runner** box in ROADMAP §3: given a target adapter (Phase 1)
> and a list of `Attack`s (Phase 2), it executes N attacks with **concurrency, rate-limit,
> retries, timeouts**, and **token/cost accounting**, folding each `AdapterResponse` into an
> `AttemptRecord` on a `RunRecord` (Phase 1 data model). It wires the Phase-1 `gauntlet run`
> stub to the real runner while staying **fully testable offline**.
>
> It is **reproducible by construction** (ROADMAP §2): pinned `temperature`/`max_tokens`
> (already in `RunOptions`), deterministic attack ordering (sorted by id), and a **seedable**
> backoff jitter so retry timing is deterministic in tests. The `RunRecord` is written to disk
> incrementally so a crashed/aborted run is **resumable** — already-executed attempts are
> skipped on resume.
>
> **Scoring is NOT in this phase (Phase 4).** The runner executes and records raw responses
> only. A successful send produces `Verdict.SKIPPED` (a neutral "executed, not yet scored"
> state); the runner never sets `PASS`/`FAIL`. A failed send produces `Verdict.ERROR`.

---

## 1. Goals

1. An async `Runner` that takes a `TargetAdapter` + `list[Attack]` + `RunOptions` and a
   `RunRecord`, builds one `AdapterRequest` per attack (payload → user prompt), calls
   `adapter.send()` concurrently under a bounded semaphore, and folds each response into an
   `AttemptRecord`.
2. **Concurrency** via `asyncio.Semaphore`; **rate-limit** via a global min-interval gate
   (`rps`); **per-request timeout** via `asyncio.wait_for`; **retries** with exponential
   backoff + **seedable** jitter on transient errors.
3. A clear **error taxonomy**: transient errors retry (capped); non-transient errors are
   recorded as `Verdict.ERROR` on the attempt and never crash the run.
4. **Token/cost accounting**: per-attempt `TokenUsage` from the response plus an estimated
   USD cost from a small, data-driven price table; run-level totals exposed as computed
   properties. Unknown model → cost `0.0` with a note.
5. **Resumability**: the `RunRecord` is persisted to `output_dir/<run_id>.json` (atomic
   writes, incrementally + at end). A resume loads that file and runs only the attacks not
   already executed (attempt key = `attack.id`); `ERROR` attempts are re-tried.
6. `gauntlet run` wired to the real runner: `--pack` selection, `--dry-run` (resolve + plan,
   no network), `--resume`, `--out`, with an offline seam so the full path is tested without
   network or API keys.
7. Everything testable with `pytest`, **offline**, deterministic (injected `sleep` + seeded
   RNG + injected clock). Phase-1 (41) and Phase-2 (38) tests stay green.

## 2. Scope

**In scope**
- `src/gauntlet/runner.py`: `Runner`, request building, the concurrency/rate-limit/timeout/
  retry loop, error classification, persistence, and resume skip-logic.
- `src/gauntlet/pricing.py`: `PRICES` table + `estimate_cost()`.
- Additive fields on `RunOptions` (`config.py`): `concurrency`, `rps`, `max_retries`,
  `retry_base_delay_s`, `retry_max_delay_s`, `retry_seed`.
- Additive field on `AttemptRecord` (`records.py`): `cost_usd`; additive computed properties
  on `RunRecord`: `total_usage`, `total_cost_usd`.
- Additive `status_code` on `AdapterError` (`errors.py`) + the one call-site in
  `http_adapter.py` that raises it, so 429/5xx are classifiable as transient.
- `cli.py`: `run` wired to the runner with `--pack` / `--dry-run` / `--resume` / `--out`.
- Tests with an in-memory `FakeAdapter` (canned responses, programmable failures).

**Out of scope (explicitly deferred)**
- **Any scoring/judging** — verdicts stay `SKIPPED`/`ERROR`; `PASS`/`FAIL` and ASR-by-verdict
  land in Phase 4. The runner must not import any scorer.
- Richer **surfaces** — Phase 3 injects every `attack.payload` as the user prompt regardless
  of `surface`. `tool-output`/`rag`/`mcp-desc` shaping comes later (Phases 7–8). `tool_calls`
  on the attempt stay `[]` (no agent/sandbox target yet).
- The TUI / live scoreboard (Phase 5) — the runner only writes the record; no live UI.
- New providers/adapters (Python-callable, MCP, sandbox) — Phase 7+. The runner is written
  against the `TargetAdapter` interface so those drop in unchanged.
- Real, authoritative price numbers — the table ships with **illustrative placeholders**
  (single data table, trivially editable); tests assert structure, not exact dollars.

## 3. Module layout

```
src/gauntlet/
├── errors.py        # AdapterError gains optional status_code (additive)
├── config.py        # RunOptions gains runner fields (additive, all defaulted)
├── records.py       # AttemptRecord.cost_usd; RunRecord.total_usage/total_cost_usd (additive)
├── pricing.py       # NEW: PRICES table + estimate_cost()
├── runner.py        # NEW: Runner, request building, exec loop, persistence, resume
├── targets/
│   └── http_adapter.py   # raise AdapterError(..., status_code=resp.status_code)
└── cli.py           # run wired to Runner (--pack/--dry-run/--resume/--out)
tests/
├── fakes.py             # FakeAdapter (TargetAdapter subclass) + helpers
├── test_runner_basic.py     # M1: request building, happy path, persistence
├── test_runner_concurrency.py  # M2: semaphore bound, rate-limit, timeout
├── test_runner_retries.py      # M3: backoff (seeded), error taxonomy
├── test_runner_cost_resume.py  # M4: token/cost aggregation, resume skip
└── test_cli_run.py             # M5: run wiring, --dry-run, offline full run
```

## 4. Runner API

`src/gauntlet/runner.py`. Pure stdlib `asyncio` + `random` + `time` + `os`; no new deps.

```python
class Runner:
    def __init__(
        self,
        adapter: TargetAdapter,
        options: RunOptions,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        rng: random.Random | None = None,
        now: Callable[[], datetime] = _utc_now,        # for started_at/finished_at
        monotonic: Callable[[], float] = time.monotonic, # for rate-limit + latency fallback
    ) -> None: ...

    async def run(self, attacks: list[Attack], record: RunRecord) -> RunRecord: ...

    def run_path(self, record: RunRecord) -> Path:       # options.output_dir / f"{run_id}.json"
        ...
```

- **`sleep` / `rng` / `now` / `monotonic` are injected** so every time/randomness source is
  controllable in tests (determinism, ROADMAP §2). Defaults are the real ones.
- `rng` defaults to `random.Random(options.retry_seed)` when not injected — so a pinned
  `retry_seed` makes backoff jitter reproducible even in production.
- **`run()` owns the lifecycle**: sets `record.status = RUNNING` and writes; sorts `attacks`
  by `id`; computes the resume skip-set from `record.attempts`; schedules the remaining
  attacks; on completion sets `status = COMPLETED` (or `ABORTED` on cancellation) and writes
  a final time. It returns the same `record` object (mutated in place + persisted).
- `run()` does **not** create the `RunRecord` — the caller builds it with
  `make_run_record(...)` (fresh run) or loads it from disk (resume). This keeps run-id /
  config-snapshot ownership in one place (Phase 1) and makes resume a pure load-then-run.

### `RunOptions` additions (`config.py`, `extra="forbid"` — all defaulted, backward-compatible)

| Field | Type | Default | Constraint | Meaning |
|-------|------|---------|-----------|---------|
| `concurrency` | `int` | `4` | `ge=1` | `asyncio.Semaphore` size — max in-flight `send()`s. |
| `rps` | `float \| None` | `None` | `gt=0` or `None` | Global requests/sec cap (min-interval gate). `None` = unlimited. |
| `max_retries` | `int` | `3` | `ge=0` | Retry attempts on **transient** errors. Total tries = `1 + max_retries`. |
| `retry_base_delay_s` | `float` | `0.5` | `ge=0` | Backoff base. |
| `retry_max_delay_s` | `float` | `30.0` | `ge=0` | Backoff cap (per-sleep). |
| `retry_seed` | `int \| None` | `None` | — | Seed for backoff jitter RNG (reproducibility). |

Existing fields reused as-is: `output_dir`, `max_tokens`, `temperature`, `request_timeout_s`.

## 5. Request building & surface

For each attack the runner builds:

```python
AdapterRequest(
    prompt=attack.payload,
    system=None,
    max_tokens=options.max_tokens,
    temperature=options.temperature,
)
```

- **Phase 3 surface rule:** the payload is always injected as the **user prompt**, regardless
  of `attack.surface`. Richer surfaces (`tool-output`/`rag`/`mcp-desc`) are deferred (§2). This
  is stated explicitly so Phase 7/8 knows where to extend.
- `temperature`/`max_tokens` come only from `RunOptions` (pinned → reproducible).

## 6. Concurrency, rate-limit, timeout

**Concurrency.** One `asyncio.Semaphore(options.concurrency)` shared across all attempts. Each
attempt acquires the semaphore for the duration of its send (incl. retries). With N attacks
and concurrency C, at most C `send()`s are ever in flight. `run()` schedules all remaining
attacks as tasks and `await asyncio.gather(...)`s them.

**Rate-limit.** A global **min-interval gate** (token-bucket-lite): interval = `1/rps`. A
single `asyncio.Lock` + a `last_dispatch` monotonic timestamp; before each send the task takes
the lock, computes `wait = max(0, last_dispatch + interval - monotonic())`, `await sleep(wait)`,
sets `last_dispatch = monotonic()`, releases. `rps=None` → the gate is a no-op. Uses the
injected `monotonic` + `sleep` so spacing is asserted against a fake clock. The gate runs once
per attempt (not per retry; retries have their own backoff sleep).

**Timeout.** Each send is wrapped: `await asyncio.wait_for(adapter.send(req), options.request_timeout_s)`.
`wait_for` is adapter-agnostic, so the `FakeAdapter` and the real httpx adapter are both
bounded (the httpx client also carries its own timeout, but `wait_for` is the authoritative
ceiling). A `TimeoutError` from `wait_for` is **transient** (§7). `request_timeout_s` is the
existing `RunOptions` field.

## 7. Retries, backoff, error taxonomy

Each attempt runs up to `1 + max_retries` tries. After each failed try, if the error is
**transient** and tries remain, sleep a backoff delay and retry; otherwise stop.

**Backoff (seedable, full-jitter):**
```
cap   = min(retry_max_delay_s, retry_base_delay_s * (2 ** attempt_index))   # attempt_index 0,1,2,...
delay = rng.uniform(0.0, cap)        # rng = random.Random(retry_seed) unless injected
await sleep(delay)
```
Full-jitter avoids thundering-herd and is fully determined by `rng` → tests inject
`random.Random(<seed>)` and assert the exact recorded sleep sequence.

**Error taxonomy:**

| Error | Classification | Action |
|-------|----------------|--------|
| `asyncio.TimeoutError` (from `wait_for`) | transient | retry; if exhausted → `ERROR` |
| `httpx.TimeoutException` | transient | retry |
| `httpx.TransportError` (connect/read/etc.) | transient | retry |
| `AdapterError` with `status_code == 429` | transient | retry |
| `AdapterError` with `500 <= status_code < 600` | transient | retry |
| `AdapterError` (other/`None` status), `ProviderError` | non-transient | record `ERROR` immediately |
| any other `Exception` (e.g. `ValueError`) | non-transient | record `ERROR` immediately |
| `asyncio.CancelledError` / `KeyboardInterrupt` | — | propagate → run `ABORTED` |

- **Non-transient and exhausted-transient both record `Verdict.ERROR`** on the
  `AttemptRecord` with `error=str(exc)` (and `started_at`/`finished_at` set). The run does
  **not** crash — one bad attack never takes the run down.
- To classify 429/5xx, `AdapterError` gains an optional `status_code: int | None`; the
  `http_adapter.py` non-2xx raise passes `status_code=resp.status_code`. This is additive
  (`AdapterError("msg")` still works; default `None`).

**Successful send** → `AttemptRecord` with `verdict=Verdict.SKIPPED` (executed, unscored),
`response_text`, `raw_response`, `usage`, `cost_usd`, `latency_ms`, timestamps. The runner
never sets `PASS`/`FAIL` (Phase 4).

## 8. Token/cost accounting + price table

`src/gauntlet/pricing.py`:

```python
# (provider, model) -> dollars per 1K tokens (input, output). Illustrative placeholders.
PRICES: dict[str, dict[str, tuple[float, float]]] = {
    "openai":    {"gpt-4o-mini": (0.00015, 0.00060), ...},
    "anthropic": {"claude-3-5-haiku": (0.00080, 0.00400), ...},
    # ollama / openai-compatible: local/unknown -> not listed -> cost 0.0
}

def estimate_cost(provider: str, model: str, usage: TokenUsage) -> tuple[float, bool]:
    """Return (cost_usd, known). Unknown (provider, model) -> (0.0, False)."""
```

- **Per attempt:** the runner reads `prompt_tokens`/`completion_tokens` off the
  `AdapterResponse` into `AttemptRecord.usage` (a `TokenUsage`; missing values → `0`), then
  `cost_usd, known = estimate_cost(record.provider, record.model, usage)` and stores
  `cost_usd`. When `known is False`, log one debug note ("no price entry for
  provider/model; cost recorded as 0").
- **Run totals** are computed properties on `RunRecord` (consistent with the existing `asr`
  property — derived, not stored, so no schema bump):
  - `total_usage -> TokenUsage` (sum over attempts),
  - `total_cost_usd -> float` (sum of attempt `cost_usd`, treating `None` as 0).
- The table is intentionally tiny and data-driven; adding a model is a one-line edit, never a
  code change. Unknown models cost `0.0` so a run never fails for lack of a price.

## 9. Resume mechanism

**File naming.** `run_path(record) = options.output_dir / f"{record.run_id}.json"`.
`output_dir` is created if missing.

**Writes are atomic + incremental.** Persistence writes the full `RunRecord` JSON
(`record.to_json()`, Phase 1) to a temp file then `os.replace()`s it onto the final path
(atomic on Windows + POSIX). An `asyncio.Lock` serializes writes so concurrent
attempt-completions never interleave. The record is written:
1. once at start (`status=RUNNING`),
2. after **each** attempt completes (so a crash loses at most the in-flight attempts), and
3. once at the end (`status=COMPLETED`/`ABORTED`).

**Attempt key + skip logic.** The attempt key is **`attack.id`**. On `run()` start the runner
builds `done = {a.attack_id for a in record.attempts if a.verdict != Verdict.ERROR}` — i.e.
attempts that **executed** (`SKIPPED`, or later `PASS`/`FAIL`) are skipped; `ERROR` attempts
are **dropped and re-tried** (transient failures shouldn't be permanent). Only attacks whose
`id not in done` are scheduled. New attempts are appended; re-tried `ERROR` attempts replace
their prior record (matched by `attack_id`).

**Resume API (caller side, e.g. CLI `--resume PATH`):**
```python
record = RunRecord.from_json(Path(path).read_text("utf-8"))   # Phase 1 (de)serialization
await Runner(adapter, cfg.run).run(attacks, record)           # same attacks; skips done ones
```
Resume is therefore "load the record, hand it back to `run()` with the same attack list."
No special resume code path beyond the skip-set — the same `run()` does fresh and resumed runs.

## 10. Records changes (additive, no schema bump)

`records.py`:
- `AttemptRecord` gains `cost_usd: float | None = None` (defaulted → old JSON still loads;
  Phase-1 round-trip tests unaffected).
- `RunRecord` gains `total_usage` and `total_cost_usd` **properties** (not fields → not
  serialized, mirrors the existing `asr`/`total_attempts` pattern).
- `schema_version` stays `1` (purely additive optional field; no breaking change).

## 11. CLI `run` wiring

`gauntlet run` (replacing the Phase-1 "nothing to run" stub):

```
gauntlet run --target T [--pack ID ...] [--dry-run] [--resume PATH] [--out PATH] [-c CONFIG]
```

Flow (non-dry-run, fresh):
1. resolve config; `info = resolve_target_info(target, cfg)`; `adapter = build_target(target, cfg)`.
2. `attacks = load_packs(default_packs_dir())`; if `--pack` given, **filter** to attacks whose
   `id` or `category` matches a requested value; error (exit 2) if a requested `--pack` matches
   nothing. No `--pack` → all bundled attacks.
3. `record = make_run_record(target_name=target, provider=info["provider"], model=info["model"], config=cfg, pack_ids=<selected>)`.
4. `asyncio.run(Runner(adapter, cfg.run).run(attacks, record))`, then `await adapter.aclose()`.
5. write to `--out` if given (else the run is already at `output_dir/<run_id>.json`); print a
   summary (run id, target, attempts, executed/error counts, total tokens, est. cost, path).

`--resume PATH`: load the `RunRecord` from `PATH`, reuse its `run_id`/snapshot, run the same
selected attacks (skip-set applies), persist back to `PATH` (and `output_dir/<run_id>.json`).

`--dry-run`: build the adapter with `dry_run=True` (no key resolution, no client, **no
network**), select attacks, and print the **plan** only — target, attack count, the attack
ids, and `est. cost: $0.00 (not sent)`. No `send()`, no record written. This is the
zero-dependency smoke path.

**Offline test seam.** `cli.run` calls the module-level name `build_target` (already imported
from `.targets`). The CLI integration test **monkeypatches `gauntlet.cli.build_target`** to
return a `FakeAdapter`, exercising the entire `run` → `Runner` → persisted-record path with
**no network and no API keys**. `--dry-run` covers the resolve-only path with no patching.

## 12. Testing strategy (offline + deterministic)

`tests/fakes.py` — `FakeAdapter(TargetAdapter)`:
- returns canned `AdapterResponse`s (configurable `text`, `prompt_tokens`, `completion_tokens`,
  `model`, `provider`), recording every `AdapterRequest` it received;
- programmable failures: raise `asyncio.TimeoutError` / `httpx.TransportError` / `AdapterError`
  (with `status_code`) for the first K calls of a given attack then succeed — to exercise
  retries and the taxonomy;
- a `barrier`/counter mode to observe **max concurrent** in-flight sends (assert ≤ `concurrency`).

Determinism: tests inject `sleep` (records the requested delays instead of really sleeping),
`rng=random.Random(<seed>)`, and a fake `monotonic` (manually advanced) so backoff sequences
and rate-limit spacing are asserted exactly. **No test touches the network or needs an API
key.** Phase-1 (41) and Phase-2 (38) suites remain green (changes are additive).

## 13. Acceptance criteria

A reviewer can confirm Phase 3 is done when:

1. `ruff check .` and `ruff format --check .` pass with zero findings; `pytest` is green
   **offline with no API keys**; the prior **79** tests (41 + 38) still pass.
2. `Runner.run([attack], record)` against a `FakeAdapter` returns the `record` with one
   `AttemptRecord`: `verdict == SKIPPED`, `response_text`/`raw_response`/`usage` populated,
   `latency_ms` set, and the built `AdapterRequest.prompt == attack.payload` with
   `max_tokens`/`temperature` from `RunOptions`. No `PASS`/`FAIL` ever set by the runner.
3. With `concurrency=2` and 6 attacks against a barrier `FakeAdapter`, the observed max
   in-flight sends is exactly 2.
4. With `rps` set and a fake clock, dispatch timestamps are spaced ≥ `1/rps`; with `rps=None`
   there is no added spacing.
5. A `FakeAdapter` that times out (or returns 429/5xx `AdapterError`) is retried up to
   `max_retries` times with **full-jitter** backoff; with an injected seeded RNG the recorded
   sleep sequence is exactly reproducible; after exhaustion the attempt is `Verdict.ERROR`
   with the error message. A **non-transient** error (`AdapterError` status `None`/4xx≠429,
   `ProviderError`, `ValueError`) is recorded as `ERROR` with **no** retry. The run completes
   (`status=COMPLETED`) regardless — a single failing attack never crashes it.
6. Token aggregation: `RunRecord.total_usage` equals the sum of attempt usages; `cost_usd` is
   `>0` for a priced `(provider, model)` and `0.0` for an unlisted one; `total_cost_usd` is the
   sum. `estimate_cost(unknown, unknown, usage) == (0.0, False)`.
7. Resume: a record persisted mid-run (some attempts `SKIPPED`, one `ERROR`, some missing) fed
   back into `run()` with the same attacks **skips** the executed ones, **re-runs** the `ERROR`
   and the missing ones, and ends `COMPLETED`. The on-disk file is `output_dir/<run_id>.json`,
   written atomically, valid JSON at every point.
8. `gauntlet run --target T --dry-run` resolves + prints the plan (attack count + ids) with
   **no network**, writes no record, exits 0. With `build_target` monkeypatched to a
   `FakeAdapter`, `gauntlet run --target T` runs the full pipeline offline, writes a valid
   `RunRecord` JSON, and prints a summary; `--pack ID` filters the selection and an unknown
   `--pack` exits 2.
