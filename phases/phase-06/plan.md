# Phase 6 — LLM-judge (T3, optional) + benign controls: implementation plan

> Build order is dependency-ordered and **judge-last**, so the prior 175 tests stay green at
> every checkpoint: (1) controls + `is_control` + utility metric (records/metrics only, **no
> judge**); (2) the `Judge` protocol + `FakeJudge` + versioned rubric + pure ensemble/vote
> logic (offline, no Scorer changes); (3) the real adapter-backed judge backend (tested via
> `FakeAdapter`, no network); (4) wire T3 into the `Scorer` opt-in + `JudgeCheck` + the async
> `score_async` decision; (5) config + runner + CLI run/report wiring + integration. Every
> milestone ends in a **Checkpoint** with exact commands. Quality gate: `ruff check .` (zero
> findings), `ruff format --check .` (clean), `pytest` (green, **offline, no API keys, no ML
> model, no network**). New code reuses existing patterns: Pydantic v2
> `ConfigDict(extra="forbid")`, the `Classifier` protocol + `StubClassifier`/`FakeAdapter`
> test-double style, the `Verdict`/`ScoreDetail` models, `build_target`/`TargetAdapter`, the
> packloader's license-gate, and the injected-dependency `Scorer`/`Runner` style. **No new
> third-party deps.** Everything additive; the only contract refinements (ASR excludes
> `is_control`; runner awaits `score_async`) are **inert** because no existing test runs
> controls or enables the judge — noted explicitly where they occur.

---

## Milestone 1 — `is_control` + benign controls data + utility metric (no judge yet)

**Build**
- `src/gauntlet/records.py`: add `AttemptRecord.is_control: bool = False` (additive, no
  `schema_version` bump). Add additive `ScoreDetail` fields for later judge use **now** so the
  schema is stable: `rubric_version: str | None = None`, `judge_votes: dict | None = None`
  (the `{attack_succeeded: k, defended: m}` breakdown). **Refine `_asr`** to exclude controls:
  `scored = [a for a in attempts if not a.is_control and a.verdict in (PASS, FAIL)]`. This is an
  **inert contract refinement** — no existing test has `is_control=True`, so every prior ASR
  value is unchanged. Add `utility_under_attack` (answered/scored controls, `None` when no
  scored controls) and extend `metrics_summary()` with a `"controls"` block + a top-level
  `"utility_under_attack"`; the attack-side keys are computed over **non-control** attempts.
  **[Fix #3]** also add `ScoreDetail.threshold: float | None = None` so the T2 threshold that
  produced a verdict is recoverable for the contested-band check in M4.
  **[Fix #4 — no spurious "control" category]** `metrics_summary()["by_category"]` and
  `asr_by_category()` must **actively drop the reserved `"control"` key** (controls carry
  `category="control"`; with `_asr` excluding them the row would be a nonsensical 0/0). Filter it
  out explicitly and test it never appears in either output.
  **[Fix #7 — id namespace]** controls live in the reserved `control/` id namespace; `load_controls`
  enforces `id` starts with `control/`, and `packloader` rejects any ATTACK whose category is
  `control` (reserved) — so the resume skip-set (keyed by attack_id) can never collide.
- `src/gauntlet/controls.py` (NEW): `BenignControl` pydantic model (spec §7) + `load_controls()`
  (offline discovery + validation of `packs/controls/*.yaml`, license-gated against
  `ALLOWED_LICENSES`, id/category coherence — mirror `packloader._check_*`).
- `src/gauntlet/packs/controls/` (NEW data): a small set (≈4–6) of clean Apache/MIT benign
  control prompts the model **should** answer.
- `src/gauntlet/scoring.py`: add `Scorer.score_control(prompt, response_text) -> ScoreResult`
  (spec §7) — pure, offline, reuses `_find_refusal`: refusal → `FAIL`/`control`; answered →
  `PASS`/`control`; empty → `ERROR`/`control`. **No judge, no T2.**
- `tests/test_controls.py`: `load_controls()` validates the bundled set + rejects an unlisted
  license / mismatched id (temp dir); `score_control` answered/refused/empty mapping.
- `tests/test_metrics_utility.py`: ASR identical with vs. without controls present; utility
  math; zero controls → `None`; control counts in `metrics_summary`.

**Files**: `records.py`, `controls.py`, `packs/controls/*.yaml`, `scoring.py` (control path
only), `tests/test_controls.py`, `tests/test_metrics_utility.py`.

**Checkpoint**
```
ruff check .
ruff format --check .
pytest -q   # [Fix #6] FULL suite — _asr/metrics_summary changes are not purely additive, run all 175 prior + new
```
Passing: controls load + score offline, `is_control` is additive, ASR excludes controls
(inert), and utility-under-attack computes — all with **no judge**. Prior 175 tests still pass.

---

## Milestone 2 — Judge protocol + FakeJudge + versioned rubric + ensemble/vote (pure, offline)

**Build**
- `src/gauntlet/judge.py` (NEW): `JudgeVote` model; the `Judge` `Protocol`
  (`async def vote(...)`); `FakeJudge` (scripted votes, records every call, repeats the last
  vote when exhausted) — the offline test double, peer of `StubClassifier`/`FakeAdapter`.
  **[Fix #8]** `FakeJudge.__init__` raises `ValueError` on an empty vote list (no "last vote" to
  repeat → avoids an obscure `IndexError` in the ensemble loop).
  **[Fix #2 — no import cycle]** `judge.py` imports adapter types ONLY from `targets.base`
  (which has no `config` dependency), NEVER from `targets/__init__.py` (which imports
  `GauntletConfig`). `AdapterJudge` (M3) receives an already-built `TargetAdapter` — it does
  not call `build_target`, so `judge.py` need not import `targets/__init__` or `config` at all.
  Config-side validation of `judge.target`/`rubric_version` is **deferred to CLI startup** (M5),
  not done in the `GauntletConfig` model validator — keeping the disabled-default path free of
  any judge import.
- Versioned rubric: `Rubric(version, template, render(...))` + bundled `RUBRIC_V1`
  (version `"v1"`) with the security-test framing and the required
  `VERDICT: attack_succeeded|defended` instruction (spec §5). A `get_rubric(version)` lookup
  (`unknown -> ConfigError`).
- `tally_votes(votes, *, threshold) -> (label, breakdown)`: **pure** majority with the defined
  **tie → defended** rule (spec §5); returns the decided label + `{attack_succeeded, defended}`
  breakdown. (The N-call ensemble loop that *collects* votes lands in M4 inside the Scorer; M2
  ships the pure tally + the vote primitive so they can be unit-tested in isolation.)
- `tests/test_judge_vote.py`: `tally_votes` for unanimous / 2-of-3 / even-N tie → defended;
  `FakeJudge` returns scripted votes in order and records calls.
- `tests/test_rubric.py`: `RUBRIC_V1.version == "v1"`; `render(...)` deterministic + contains
  criteria/payload/response + the VERDICT instruction; `get_rubric("nope")` → `ConfigError`.

**Files**: `judge.py`, `tests/test_judge_vote.py`, `tests/test_rubric.py`.

**Checkpoint**
```
ruff check .
ruff format --check .
pytest tests/test_judge_vote.py tests/test_rubric.py -q
```
Passing: the judge seam + scripted `FakeJudge` exist, the rubric is a pinned versioned
artifact, and the ensemble tally (majority + tie-break) is pure and offline. No Scorer/runner
changes yet; prior 175 tests untouched.

---

## Milestone 3 — Real adapter-backed judge backend (`AdapterJudge`, offline-testable)

**Build**
- `src/gauntlet/judge.py`: `AdapterJudge` (the bundled real backend, spec §4) holding a
  `TargetAdapter` + a `Rubric` + the pinned judge `temperature`/`max_tokens`. Its async
  `vote(...)` builds the judge prompt via `rubric.render(...)`, sends **one**
  `AdapterRequest` through `adapter.send(...)`, and parses the reply with
  `parse_vote(text) -> JudgeVote` (find the `VERDICT:` token; unparseable → defined fallback
  label `"defended"` with a `reasoning` note, spec §6). **Reuses the existing adapter — no new
  HTTP client.**
- `tests/test_adapter_judge.py`: drive `AdapterJudge` with a `FakeAdapter` returning canned
  judge replies → `attack_succeeded` / `defended` / unparseable→fallback; assert the sent
  `AdapterRequest` used the judge `temperature`/`max_tokens`; confirm **no network**.

**Files**: `judge.py`, `tests/test_adapter_judge.py`.

**Checkpoint**
```
ruff check .
ruff format --check .
pytest tests/test_adapter_judge.py tests/test_judge_vote.py tests/test_rubric.py -q
```
Passing: `AdapterJudge` makes a single judge call over the existing adapter machinery and
parses a `JudgeVote`, fully offline via `FakeAdapter`. Prior 175 tests untouched (judge not yet
wired into the Scorer).

---

## Milestone 4 — Wire T3 into the Scorer (opt-in, contested-only, JudgeCheck) + async decision

**Build**
- `src/gauntlet/config.py`: add `JudgeConfig` (spec §8, default OFF) and
  `GauntletConfig.judge: JudgeConfig = JudgeConfig()` (additive; existing configs default to
  disabled). `JudgeConfig` validates only **simple field constraints** (ensemble_size ge 1,
  threshold in [0,1], non-empty target string when set). **[Fix #2]** the cross-checks that
  `enabled=True` has a resolvable `judge.target` and a known `rubric_version` are **deferred to
  CLI startup (M5)** — NOT done in the `GauntletConfig` model validator — to avoid importing
  `judge.py`/`get_rubric` (and the targets→config cycle) from `config.py`. CLI raises exit 2 on
  a bad judge target / unknown rubric version.
- `src/gauntlet/scoring.py`: `Scorer.__init__` gains `judge: Judge | None = None` and
  `judge_config: JudgeConfig | None = None` (additive; both `None` → T3 inert). Add the async
  `score_async(...)` (spec §6):
  - delegates to the **unchanged** sync `score()` for T1/T2 first;
  - **judge enabled** = `judge_config and judge_config.enabled and judge is not None`;
  - if disabled → return the `score()` result verbatim (no await of any backend) — including
    `JudgeCheck` → `SKIPPED` exactly as Phase 4;
  - if enabled: for `JudgeCheck` run the ensemble (collect `ensemble_size` `judge.vote(...)`
    calls, `tally_votes`, map `pass_if`); for a **contested** T2 result
    (`abs(classifier_score - threshold) <= contested_band`) escalate to the same ensemble and
    override with `score_tier="T3"`; non-contested / T1-confident → return the T1/T2 result
    unchanged. Set `ScoreDetail(tier="T3", rubric_version=..., judge_votes=breakdown,
    reason=...)`.
    **[Fix #3 — threshold derivation]** the `threshold` in the contested test is re-derived from
    `attack.success_when` at the call site: `StringCheck` (escalated) → the hardcoded `0.5`;
    `ClassifierCheck` → `check.threshold`. Store it in `ScoreDetail.threshold` so the band check
    is reproducible and consistent across both paths.
  - **[Fix #5 — ensemble exception policy]** the policy is **all-or-fallback**: if ANY
    `judge.vote(...)` call in the ensemble raises (after the adapter's own retries), abort the
    ensemble and fall back — escalated `string`/`classifier` keeps the T2 verdict (judge error in
    `reason`), `JudgeCheck` → `Verdict.ERROR`. (Deterministic; no variable-size partial tally.)
    Test both: contested→T2-kept-on-judge-error and JudgeCheck→ERROR-on-judge-error.
  - The sync `score()` body is **not modified** (the 175 tests that call it stay green).
- `tests/test_scoring_t3.py`: disabled → `JudgeCheck` SKIPPED and `score_async == score` across
  a matrix (canary/refusal/contested/non-contested/classifier); enabled → contested escalates
  (FakeJudge call recorded), non-contested does not (FakeJudge uncalled), `JudgeCheck` → PASS/
  FAIL via ensemble with the recorded breakdown + rubric_version; tie-break and fallback paths.

**Files**: `config.py`, `scoring.py`, `tests/test_scoring_t3.py`.

**Checkpoint**
```
ruff check .
ruff format --check .
pytest tests/test_scoring_t3.py tests/test_config.py tests/test_scoring_t1.py tests/test_scoring_t2.py -q
```
Passing: T3 is opt-in and contested-only, `JudgeCheck` is handled when enabled, `score_async`
disabled == `score`, config defaults keep the judge off. Prior scoring/config tests green
(additive field + inert default).

---

## Milestone 5 — Config-driven runner + CLI run/report wiring + integration

**Build**
- `src/gauntlet/runner.py`: in `_run_attempt`'s successful-send branch, replace
  `result = self._scorer.score(...)` with
  `result = await self._scorer.score_async(attack, response_text=response.text,
  response=response)`. **Inert** when the judge is disabled (identical verdicts), so prior
  runner tests stay green. Add `controls` to `run(...)`: `run(self, attacks, record, *,
  controls=())` — after attacks, send each `BenignControl` and score via
  `self._scorer.score_control(...)`, recording an `AttemptRecord(is_control=True,
  attack_id=control.id, category="control", ...)`. No controls passed → behavior identical to
  Phase 5. Resume skip-set (`verdict != ERROR`) and persistence unchanged.
  **[Fix #1 — control request interface]** `_build_request(attack)` reads `attack.payload`, but
  `BenignControl` has a `prompt` field (no `payload`). Add a separate
  `_build_control_request(control: BenignControl) -> AdapterRequest` (using `control.prompt`) —
  do NOT pass a `BenignControl` to `_build_request` (would `AttributeError`). The retry/rate-gate/
  timeout/cost wrapper is shared by factoring the send loop to take a prebuilt `AdapterRequest`.
- `src/gauntlet/cli.py`:
  - `run` gains `--judge/--no-judge` (default follows `cfg.judge.enabled`) and
    `--controls/--no-controls` (default off). When the judge is on, build `AdapterJudge` from
    `build_target(cfg.judge.target, cfg)` and construct `Scorer(judge=..., judge_config=
    cfg.judge)`; pass that Scorer to `Runner`. When controls on, `load_controls()` and pass to
    `Runner.run(..., controls=...)`. Missing/unknown judge target OR unknown `rubric_version`
    → exit 2 (the deferred validation from M4/Fix #2). `--dry-run` unchanged (no send;
    judge/controls don't fire).
  - **[Fix #9]** the `_execute(adapter, options, attacks, record)` helper (used by BOTH the plain
    and TUI run paths) gains a `controls=()` parameter forwarded to `Runner.run(...)`, so controls
    are not silently dropped on the non-TUI path.
  - `_summary`: append `utility=<pct>` when controls ran (from `metrics_summary`).
  - `report` (text): print `utility-under-attack` (or `n/a`) + a one-line control summary after
    ASR; `--format json` automatically carries the new `metrics_summary` keys.
- `tests/test_runner_judge.py`: `FakeAdapter` + injected `Scorer(judge=FakeJudge(...),
  judge_config=enabled)` + a couple of controls → control rows have `is_control=True` and PASS/
  FAIL; a contested attack → `score_tier=="T3"`; run `COMPLETED`; judge-disabled run matches
  Phase-5 verdicts.
- Extend `tests/test_cli_run.py` / `tests/test_cli_report.py` minimally (additive cases) for
  the `--controls` summary + the report utility line; **do not** change existing assertions
  (defaults keep judge off / controls off, so prior CLI tests are unaffected).

**Files**: `runner.py`, `cli.py`, `tests/test_runner_judge.py`, additive cases in
`tests/test_cli_run.py` / `tests/test_cli_report.py`.

**Checkpoint**
```
ruff check .
ruff format --check .
pytest -q
```
Passing: the **entire** suite is green offline with no API keys / ML model / network — the
prior 175 tests plus the new Phase-6 tests; the runner awaits `score_async` and runs controls
alongside attacks, `gauntlet run --judge --controls` works against a configured judge target,
and `gauntlet report` prints utility-under-attack alongside ASR. Satisfies spec §12.

---

## Plan review

1. **[BLOCKING] `_build_request` reads `attack.payload` but `BenignControl` has `prompt`.** Fixed (M5): separate `_build_control_request(control)`; shared send/retry wrapper takes a prebuilt `AdapterRequest`.
2. **[BLOCKING] Import cycle config→judge→targets→config.** Fixed (M2/M4): `judge.py` imports only from `targets.base`; `AdapterJudge` takes a prebuilt adapter (no `build_target`); judge.target/rubric_version validation deferred to CLI startup, not the model validator.
3. **[BLOCKING] Contested-band threshold not recoverable from `ScoreDetail`.** Fixed (M1/M4): add `ScoreDetail.threshold`; re-derive at the call site (StringCheck→0.5, ClassifierCheck→check.threshold).
4. **[BLOCKING] Spurious "control" category in `metrics_summary`/`asr_by_category`.** Fixed (M1): actively drop the reserved `"control"` key; tested.
5. **[BLOCKING] Partial ensemble failure undefined.** Fixed (M4): all-or-fallback — any judge.vote exception aborts the ensemble; contested→keep T2, JudgeCheck→ERROR; both tested.
6. **M1 checkpoint ran only 2 files though `_asr`/`metrics_summary` change.** Fixed: M1 checkpoint now `pytest -q` (full suite).
7. **Control id namespace collision in resume skip-set.** Fixed (M1): reserved `control/` id namespace; `load_controls` enforces it; packloader rejects attacks with category `control`.
8. **`FakeJudge([])` undefined.** Fixed (M2): `__init__` raises `ValueError` on empty vote list.
9. **`_execute` wrapper must also forward controls.** Fixed (M5): `_execute(..., controls=())` on both run paths.
10. **`pytest-asyncio asyncio_mode=auto` confirmed present** — no action needed.

**Resolution:** all five BLOCKING items (1–5) and the four others (6–9) are folded into the
milestone build descriptions, test lists, and checkpoints above. Ready to implement.

STATUS: PASS
