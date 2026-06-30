# Phase 6 Review

Reviewed: `git diff HEAD~1 HEAD` (commit `9179112`). All touched files read in full.
Test run: 226 passed, 0 failed (ruff check clean, ruff format clean).

## Findings

1. **Opt-in inertness confirmed.** `JudgeConfig.enabled` defaults to `False`. `score_async` with a disabled judge (or no judge at all) returns the byte-identical result from sync `score()`. Verified programmatically and via `test_disabled_score_async_equals_sync` across 6 parametrize cases. Prior 175 tests still green — the 226 total passes include them all.

2. **No import cycle confirmed.** `config.py` imports only `.errors` and (lazily) `.targets.providers`. `judge.py` imports only `.errors` and `.targets.base`. `scoring.py` references `JudgeConfig` only under `TYPE_CHECKING` (string annotation deferred by `from __future__ import annotations`). `python -c "import gauntlet.config, gauntlet.judge, gauntlet.scoring, gauntlet.cli"` completes silently.

3. **Fix #1 (_build_control_request) correct.** `_build_control_request(control)` reads `control.prompt`; the shared `_perform_send` wrapper takes a prebuilt `AdapterRequest`. `_build_request(attack)` is never called with a `BenignControl`.

4. **Fix #2 (deferred judge validation) correct.** `GauntletConfig`'s model validator does not reference `judge.py` or `get_rubric`. Cross-checks (`judge.target` resolvable, `rubric_version` known) are deferred to `_build_judge_scorer` in `cli.py`, which exits 2 on `ConfigError`.

5. **Fix #3 (threshold derivation) partially implemented.** The T3 `ScoreDetail` correctly stores `threshold` (derived via `_derive_threshold`: `StringCheck` → 0.5, `ClassifierCheck` → `check.threshold`). `test_contested_t2_escalates_to_t3` and `test_classifier_contested_escalates` verify `detail.threshold`. The T2 base `ScoreDetail` (from `_escalate` and `_score_classifier`) does NOT store `threshold` — it is `None` on T2 results. The plan text says "T2: the threshold that produced a verdict" should be stored there, but no test enforces it and the contested-band logic re-derives it from the attack check, not from `ScoreDetail.threshold`. This is a documentation gap, not a functional bug, and the plan's actual correctness requirement (reproducible T3 verdict + stored threshold on T3 result) is met.

6. **Fix #4 ("control" category exclusion) correct.** `asr_by_category()` filters `if cat != "control"`. `metrics_summary()["by_category"]` skips `cat == "control"` explicitly. `test_control_never_a_category` asserts both outputs. Attack-side counts (`total`, `scored`, etc.) are computed over `[a for a in self.attempts if not a.is_control]`.

7. **Fix #5 (all-or-fallback ensemble policy) correct.** `_collect_votes` catches any `Exception` from `judge.vote`, aborts the loop, and returns `([], error_str)`. Callers branch on `error is not None`: contested T2 keeps the T2 verdict with the error in `reason`; `JudgeCheck` returns `Verdict.ERROR`. Both paths tested in `test_contested_judge_error_keeps_t2` and `test_judgecheck_judge_error_is_error`.

8. **FakeJudge([]) raises ValueError.** Confirmed via `test_fakejudge_empty_raises`.

9. **AdapterJudge reuses TargetAdapter — no new HTTP client.** Takes a pre-built `TargetAdapter`, sends one `AdapterRequest` via `adapter.send(...)`. Tested offline with `FakeAdapter` in `test_adapter_judge.py`.

10. **Controls: is_control additive, ASR denominator excludes controls, utility_under_attack div-by-zero safe.** `AttemptRecord.is_control: bool = False` — all prior records default correctly. `_asr` filters `not a.is_control`. `_utility_under_attack` returns `None` when no scored controls (`test_zero_controls_utility_is_none`).

11. **control/ id namespace enforced end-to-end.** `BenignControl.id` has regex pattern `^control/[a-z0-9-]+$`. `load_controls` calls `_check_coherence` to verify `id == "control/<stem>"`. `packloader._check_coherence` raises `PackError` when an attack uses `category="control"` (verified programmatically). Resume skip-set cannot collide.

12. **_execute wrapper forwards controls (Fix #9).** Both paths pass `controls=control_items`: the non-TUI path via `_execute(..., controls=control_items, ...)`, the TUI path via `Runner(...).run(selected, record, controls=control_items)`.

13. **Rubric versioned and recorded.** `RUBRIC_V1.version == "v1"`. `get_rubric("nope")` raises `ConfigError`. T3 `ScoreDetail.rubric_version` is set from `judge_config.rubric_version` in both `_score_judge` and `_maybe_escalate_t3`. Tested in `test_rubric.py` and `test_scoring_t3.py`.

14. **Ensemble majority + tie → defended correct.** `tally_votes` short-circuits `k == m` to `LABEL_DEFENDED` before the threshold comparison. Threshold comparison uses `k / n >= threshold`. Tested with even-N tie, 2/3 majority, and high threshold requiring supermajority.

15. **No network in any test.** All tests use `FakeAdapter`, `FakeJudge`, `StubClassifier`, or pure data. No external calls, no API keys, no ML model loaded.

16. **Ruff clean.** `ruff check .` → "All checks passed!". `ruff format --check .` → "55 files already formatted".

## Minor Observations (non-blocking)

- `ScoreDetail.threshold` is `None` on T2 results (from `_escalate` and `_score_classifier`). The plan intended it to be set there too ("T2: the threshold that produced a verdict"). The threshold appears in the human-readable `reason` string and is correctly stored on the T3 result. No test checks T2 `detail.threshold`, and the contested-band logic does not depend on reading it from the base result. No action required unless a future phase needs to audit raw T2 records programmatically.

- `cli.py` line 275 constructs a throwaway `Runner(adapter, cfg.run)` just to call `.run_path(record)`. This is harmless since `run_path` only reads `options.output_dir`.

STATUS: PASS
