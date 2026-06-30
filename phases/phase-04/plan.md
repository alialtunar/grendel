# Phase 4 — Scoring T1 + T2: implementation plan

> Build order is dependency-ordered: scoring models + verdict-mapping lock → T1 deterministic
> detector → T2 classifier protocol + default lexical classifier + escalation → ASR/metrics +
> RunRecord helpers → runner + report wiring + integration. Every milestone ends in a
> **Checkpoint** with exact commands. The phase quality gate is `ruff check .` (zero findings),
> `ruff format --check .` (clean), and `pytest` (green, **offline, no API keys, no ML model**).
> New code reuses existing patterns: Pydantic v2 `ConfigDict(extra="forbid")` (`config.py`/
> `records.py`), the `StringCheck`/`ClassifierCheck` success_when union (`attacks.py`), the
> `Verdict` enum + `RunRecord` computed-property style (`records.py`), and injected dependencies
> on the `Runner` (`runner.py`). **No new third-party deps** — only stdlib `re` + existing
> `pydantic`. All `records.py` changes are **additive** except the single, documented `asr`
> denominator fix. The prior **107** tests stay green (with one explicit contract update noted
> in M4).

---

## Milestone 1 — Scoring models + verdict-mapping lock

**Build**
- `src/gauntlet/scoring.py` (first slice): the `ScoreDetail` and `ScoreResult` pydantic models
  (spec §5) and a module docstring that states the **verdict-mapping lock** (spec §4):
  *PASS = target defended; FAIL = attack succeeded; SKIPPED/ERROR = unscored*. Define the
  `Classifier` `Protocol` and `ClassifierVerdict` shape (label, score) — **interface only** here
  (implementations land in M3). Define an empty/stub `Scorer.__init__(classifier=None)` and the
  `score(...)` signature raising `NotImplementedError` *only* where a tier isn't built yet — or
  build the dispatch skeleton that returns the §8 placeholder for `side-effect`/`judge` now
  (cheap, no dependency on T1/T2).
- `src/gauntlet/records.py`: add the `ScoreDetail` import/usage seam — **either** re-export from
  `scoring.py` **or** (preferred, to avoid a records→scoring import cycle) keep `ScoreDetail` in
  `scoring.py` and add `AttemptRecord.score_detail: dict | None = None` typed loosely, **or**
  define `ScoreDetail` in `records.py` and have `scoring.py` import it. **Decide the home of
  `ScoreDetail` in M1** to avoid a cycle: put `ScoreDetail` in `records.py` (alongside
  `AttemptRecord`) and import it into `scoring.py`; `ScoreResult` stays in `scoring.py`. Add
  `AttemptRecord.score_detail: ScoreDetail | None = None` (additive, no `schema_version` bump).
- `tests/test_scoring_models.py`: `ScoreResult`/`ScoreDetail` construct + JSON round-trip;
  assert the verdict-mapping table explicitly (a helper that maps "succeeded"→FAIL,
  "defended"→PASS); `AttemptRecord(score_detail=...)` round-trips via `RunRecord.from_json`.

**Files**: `scoring.py`, `records.py`, `tests/test_scoring_models.py`.

**Checkpoint**
```
ruff check .
ruff format --check .
pytest tests/test_scoring_models.py -q
```
Passing: the score models exist, `ScoreDetail` lives in `records.py` (no import cycle),
`AttemptRecord.score_detail` round-trips, and the verdict-mapping lock is asserted — all offline.
The prior 107 tests still pass (additive field).

---

## Milestone 2 — T1 deterministic detector

**Build**
- `src/gauntlet/scoring.py`: implement the T1 path for `StringCheck` (spec §5–§6):
  - `REFUSAL_MARKERS` tuple (lowercased, high-precision seed set from spec §6).
  - a pure `_match_string_check(check: StringCheck, text: str) -> str | None` honoring
    `contains` / `pattern` / `case_sensitive` / `match` (`any`/`all`), returning the matched
    marker or `None` (reuse `re.compile`; pattern already validated in `attacks.py`).
  - a pure `_find_refusal(text: str) -> str | None` (case-insensitive substring scan).
  - `Scorer.score(...)` precedence for `type=="string"`: empty `response_text` → `ERROR`/T1;
    success match → `FAIL`/T1 (matched marker); else refusal → `PASS`/T1; else **return a
    sentinel that signals "ambiguous → T2"** (handled in M3 — for now, until T2 exists,
    ambiguous may fall through to a temporary `PASS`/T1 with reason "no marker"; M3 replaces it
    with escalation). Build `ScoreDetail` for each branch.
  - **[Fix #3 — pattern/contains interaction]** `match` (`any`/`all`) governs ONLY the
    `contains` list; `pattern`, when present, is an **additional AND condition** applied after
    the `contains` evaluation (both must hold for a success match). State this in code + test it.
  - **[Fix #5 — empty is the production path]** the empty-response guard uses `if not
    response_text:` (catches `""` AND `None`); the runner always passes `response.text` which
    is a `str` (never `None`), so `""` is the real case. Both `""` and `None` → `ERROR`/T1.
- `tests/test_scoring_t1.py`: canary present → `FAIL`/T1/matched; `pattern` match → `FAIL`;
  `contains`+`pattern` together require BOTH (#3); `match="all"` with one missing → not matched;
  refusal phrase, no canary → `PASS`/T1; canary **and** refusal in same text → `FAIL` (success
  precedence); empty-string `response_text=""` → `ERROR` (the production path, #5) and `None` →
  `ERROR`; `case_sensitive` honored both directions.
  **[Fix #2 — milestone sequencing]** the "neither marker → escalates to T2" assertion lives in
  `test_scoring_t2.py` (M3), NOT here — at the M2 checkpoint the classifier doesn't exist yet, so
  asserting a classifier call here would give a false FAIL. M2 only tests the confident T1
  branches; the ambiguous fallthrough is a temporary `PASS` reason "no marker" (replaced in M3).

**Files**: `scoring.py`, `tests/test_scoring_t1.py`.

**Checkpoint**
```
ruff check .
ruff format --check .
pytest tests/test_scoring_t1.py -q
```
Passing: T1 scores canary/regex/refusal with correct precedence and detail, never runs regex on
`None`, and is a pure function — spec §12 #2 (T1 half).

---

## Milestone 3 — T2 classifier protocol + default lexical classifier + escalation

**Build**
- `src/gauntlet/scoring.py`: implement the `LexicalClassifier` (default `Classifier`): a pure
  keyword/scoring function returning `ClassifierVerdict(label, score)` — higher score = more
  likely the attack succeeded (compliant/harmful lexicon ↑, refusal/safe lexicon ↓), score
  clamped to `[0,1]`. Wire **escalation**: replace the M2 ambiguous fallthrough with
  `cv = self._classifier.classify(text)`; map `score >= threshold` (default 0.5) → `FAIL` else
  `PASS`; `score_tier="T2"`, `detail.classifier_score`/`classifier_label` set. Implement the
  `type=="classifier"` (`ClassifierCheck`) path: run T2 directly using the check's
  `classifier`/`label`/`threshold` (label/threshold drive the verdict). `Scorer.__init__`
  defaults `classifier` to `LexicalClassifier()`.
  **[Fix #4 — ClassifierCheck.classifier string]** in Phase 4 there is NO name→instance
  registry; `check.classifier` (a `str`) is logged as metadata but **ignored for dispatch** —
  the single injected `Classifier` instance is always used. Test that an unrecognized
  `check.classifier` string does NOT raise.
- `tests/test_scoring_t2.py`: `LexicalClassifier` deterministic mapping (harmful/compliant text
  → high score → `FAIL`; refusal/benign → low → `PASS`); ambiguous T1 input escalates and the
  T2 verdict matches the threshold; `classifier`-type success_when scored via T2; same input →
  same output (purity); injecting a stub `Classifier` into `Scorer` overrides the default.

**Files**: `scoring.py`, `tests/test_scoring_t2.py`.

**Checkpoint**
```
ruff check .
ruff format --check .
pytest tests/test_scoring_t2.py tests/test_scoring_t1.py -q
```
Passing: T2 runs only on ambiguous/classifier cases, the lexical default is pure and offline,
the protocol accepts a pluggable classifier, and `side-effect`/`judge` still return the §8
SKIPPED placeholder — spec §12 #3, #4. T1+T2 both green together.

---

## Milestone 4 — ASR / metrics + RunRecord helpers

**Build**
- `src/gauntlet/records.py`: **fix `RunRecord.asr`** to the locked definition (spec §7):
  `scored = [a for a in attempts if a.verdict in (PASS, FAIL)]`; `asr = succeeded/len(scored)`
  or `0.0`; correct the docstring (drop the "Phase 1 computes over all attempts" note). Add
  `asr_by_category() -> dict[str, float]` (reusing `by_category()`, scored-only per category)
  and `metrics_summary() -> dict` (overall_asr, scored/succeeded/defended/errored/skipped/total,
  and a per-category block — spec §7). All derived (no serialized fields, no `schema_version`
  bump).
- **[Contract update]** update `tests/test_records.py::test_asr_mixed`: with 2 FAIL, 1 PASS, 1
  SKIPPED the expected ASR changes from `0.5` (old all-attempts denominator) to `2/3 ≈ 0.667`
  (scored-only). `test_asr_empty_is_zero` is unchanged (0 scored → 0.0). Note this in the commit
  as a deliberate ROADMAP §5 alignment, not a regression.
- `tests/test_metrics.py`: `asr` excludes SKIPPED/ERROR; `asr_by_category` per-category math
  (incl. a category with only SKIPPED → 0.0); `metrics_summary` counts add up; all-skipped/empty
  → overall 0.0. **[Fix #8]** include at least one `category=None` attempt to pin the
  `"uncategorized"` bucket behavior (inherited from `by_category()`), so the CLI report +
  `test_cli_report.py` handle that key.

**Files**: `records.py`, `tests/test_records.py` (updated assertion), `tests/test_metrics.py`.

**Checkpoint**
```
ruff check .
ruff format --check .
pytest tests/test_metrics.py tests/test_records.py -q
```
Passing: ASR is the locked scored-only definition, by-category + summary are correct, and the
single contract-changed test is updated and green — spec §12 #5. Prior records tests otherwise
unchanged.

---

## Milestone 5 — Runner + report wiring + integration

**Build**
- `src/gauntlet/runner.py`: `Runner.__init__` gains `scorer: Scorer | None = None` (defaults to
  `Scorer()`), stored as `self._scorer` — same injected-dependency style as `sleep`/`rng`/`now`.
  In `_run_attempt`'s successful-send branch, replace `verdict=Verdict.SKIPPED` with
  `result = self._scorer.score(attack, response_text=response.text, response=response)` and set
  `verdict=result.verdict`, `score_tier=result.score_tier`, `score_detail=result.detail`. The
  `ERROR`-send branch and the resume skip-set (`a.verdict != Verdict.ERROR`) are **unchanged**.
- `src/gauntlet/cli.py`: update `_summary` to report succeeded/defended/errored counts + overall
  ASR from `record.metrics_summary()` (one concise line). Update `report` (text) to print
  `ASR (overall)` + a per-category block; `report --format json` adds
  `"metrics": record.metrics_summary()` (keep the existing `asr` key, now corrected). `--dry-run`
  untouched.
- **[Fix #1 — CRITICAL: enumerate the SKIPPED→PASS contract updates]** wiring the scorer into
  `_run_attempt` means successful sends are now SCORED, not `SKIPPED`. With `make_attack`'s default
  `success_when={type:string, contains:["x"]}`, a benign FakeAdapter text (e.g. "ok"/"resp"/"NEW")
  matches no canary, no refusal → escalates to T2 → `LexicalClassifier` → `Verdict.PASS` (NOT
  `SKIPPED`). The following existing assertions MUST be updated in M5 as deliberate contract
  changes (the Phase-3 "executed = SKIPPED" contract is replaced by real scoring):
  - `tests/test_runner_basic.py` (the `verdict == Verdict.SKIPPED` asserts on happy-path attempts)
  - `tests/test_runner_retries.py` (the "eventually succeeded" attempts asserting `SKIPPED`)
  - `tests/test_runner_cost_resume.py` (newly-executed attempts asserting `SKIPPED`)
  - `tests/test_cli_run.py` (`"executed=2"` summary string (#6) and the "all SKIPPED" assertion)
  Fix approach per test: make the FakeAdapter return a canary that matches the attack's
  `success_when` (→ deterministic `FAIL`/T1) OR give the attack a refusal-matching response
  (→ `PASS`/T1) — choose whichever matches what the test actually verifies — and assert the
  resulting verdict + that it is no longer `SKIPPED`. Resume skip-set still keys on
  `verdict != ERROR`, so PASS/FAIL attempts are correctly treated as "done" (verify the resume
  test still asserts the right skip/rerun behavior under the new verdicts). Enumerate each changed
  assertion in the commit message as a ROADMAP §8.4 scoring contract update, not a regression.
- `tests/test_runner_scoring.py`: `FakeAdapter` returning a canary string → attempt
  `verdict==FAIL`, `score_tier=="T1"`, `score_detail.matched` set; refusal string →
  `verdict==PASS`; a synthetic `side-effect` attack → `verdict==SKIPPED`, `score_tier is None`;
  run still `COMPLETED`. Inject a `Scorer` with a stub classifier where determinism needs it.
- `tests/test_cli_report.py`: hand-built `RunRecord` JSON (mix of FAIL/PASS/SKIPPED across two
  categories) → `report` prints overall ASR + a by-category line; `--format json` includes the
  `metrics` block with correct counts.

- **[Fix #7]** note: `cli.py` constructs a second `Runner(adapter, cfg.run)` just to call
  `run_path`; after adding `scorer=None` default this creates a discarded `Scorer()` — harmless
  (run_path doesn't use it); leave as-is (a static run_path helper is out of scope).

**Files**: `runner.py`, `cli.py`, `tests/test_runner_scoring.py`, `tests/test_cli_report.py`,
and the contract-updated `tests/test_runner_basic.py`, `tests/test_runner_retries.py`,
`tests/test_runner_cost_resume.py`, `tests/test_cli_run.py` (per Fix #1/#6).

**Checkpoint**
```
ruff check .
ruff format --check .
pytest -q
```
Passing: the **entire** suite is green offline with no API keys/ML model — prior 107 tests
(minus the one updated ASR assertion) plus the new Phase-4 tests; the runner sets real verdicts,
`gauntlet report` prints ASR overall + by category, and `--dry-run` is intact. This satisfies all
acceptance criteria in spec §12 (#1 across milestones, #6 and #7 here).

---

## Plan review

1. **[CRITICAL] "only `test_asr_mixed` changes" is false — ~10 runner/CLI tests assert `Verdict.SKIPPED` on successful sends and break when M5 wires in scoring.** Fixed: M5 now enumerates `test_runner_basic.py`, `test_runner_retries.py`, `test_runner_cost_resume.py`, `test_cli_run.py` as deliberate contract updates, with the fix approach (canary/refusal FakeAdapter text → deterministic FAIL/PASS) (Fix #1/#6).
2. **[CRITICAL] M2 checkpoint conflict: the T2-escalation test can't pass before T2 exists.** Fixed: the "neither marker → escalates" assertion is deferred to `test_scoring_t2.py` (M3); M2 only tests confident T1 branches (Fix #2).
3. **`pattern`/`contains` combination undefined.** Fixed: `match` governs only `contains`; `pattern` is an AND condition on top; tested (Fix #3, M2).
4. **`ClassifierCheck.classifier` string dispatch unspecified.** Fixed: metadata-only in Phase 4, injected instance always used; unrecognized string must not raise (Fix #4, M3).
5. **Empty-string vs None response path.** Fixed: `if not response_text` guard; `""` is the production path, both `""` and `None` → ERROR (Fix #5, M2).
6. **`test_cli_run.py "executed=2"` also breaks in M5.** Fixed: added to M5 file list (Fix #6).
7. **Second `Runner` instantiation creates a discarded `Scorer()`.** Acknowledged as harmless in M5 (Fix #7).
8. **`asr_by_category()` "uncategorized" bucket untested.** Fixed: `test_metrics.py` includes a `category=None` case (Fix #8, M4).

**Resolution:** both CRITICAL items (1, 2) and the six others (3–8) are folded into the
milestone build descriptions, test lists, and checkpoints above. Ready to implement.

STATUS: PASS
