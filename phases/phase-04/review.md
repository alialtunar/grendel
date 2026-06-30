# Phase 4 Review

## Quality gates

1. ruff check . -- zero findings. PASS.
2. ruff format --check . -- 39 files already formatted. PASS.
3. pytest -q -- 137 passed (107 prior + 30 new), 0 failures, 0 errors. PASS.

---

## Verdict convention (single most important property)

Verified in src/gauntlet/scoring.py and tests/test_scoring_models.py.

- _match_string_check returns a marker -> Verdict.FAIL (attack succeeded). scoring.py line 201.
- _find_refusal returns a marker -> Verdict.PASS (target defended). scoring.py line 211.
- Module docstring and test_verdict_mapping_lock assert succeeded->FAIL, defended->PASS. Not inverted.
- RunRecord.asr = FAIL / (PASS + FAIL). More attack successes raise ASR correctly.
  Confirmed in records.py _asr() and test_asr_excludes_skipped_and_error.

---

## T1 deterministic detector

2. T1 precedence: success marker check runs before refusal check in _score_string.
   If both appear in the same text, FAIL is returned.
   Confirmed by test_success_precedence_over_refusal.

3. Fix #3 -- pattern AND contains: match (any/all) governs only contains;
   pattern is an additional AND condition applied on top (both must hold).
   Verified manually and by test_contains_and_pattern_require_both.

4. Fix #5 -- empty/None -> ERROR: the if-not-text guard catches both empty string
   and None before any regex execution. Confirmed by test_empty_and_none_are_error.

5. match=all semantics: len(present) == len(check.contains) requires every marker present.
   Confirmed by test_match_all_requires_every_marker.

6. case_sensitive: both directions exercised in test_case_sensitive_both_directions.
   _match_string_check applies casefold() to needle and haystack when case_sensitive=False.

---

## T2 LexicalClassifier

7. Pure and deterministic: LexicalClassifier.classify() is stateless with no I/O.
   Same input -> same output every call. test_lexical_classifier_is_pure confirms this.

8. Offline: only stdlib operations (casefold, membership, arithmetic).
   No network, no ML model, no third-party dependency beyond pydantic.

9. Escalation path: ambiguous T1 (no success marker, no refusal marker) calls
   self._escalate(text, threshold=0.5), which calls self._classifier.classify(text).
   score >= 0.5 -> FAIL, else PASS, tier T2.
   Confirmed by test_ambiguous_string_escalates_to_t2 (stub classifier injected).

10. Fix #4 -- ClassifierCheck.classifier is metadata-only: _score_classifier logs
    check.classifier in the reason string but ignores it for dispatch.
    An unrecognized string does not raise.
    Confirmed by test_unrecognized_classifier_string_does_not_raise.

11. ClassifierCheck empty response -> ERROR at T2: _score_classifier has the same
    if-not-text guard, returning Verdict.ERROR with score_tier=T2.
    Confirmed by test_classifier_empty_response_is_error.

---

## side-effect / judge placeholders

12. Any success_when.type other than string or classifier returns
    ScoreResult(verdict=Verdict.SKIPPED, score_tier=None). No crash.
    Confirmed by test_side_effect_attack_is_skipped: run still COMPLETED, score_tier is None.

13. SKIPPED is excluded from the ASR denominator in _asr().
    Confirmed by test_asr_excludes_skipped_and_error.

---

## ASR / metrics

14. Division-by-zero guard: _asr() returns 0.0 when scored list is empty.
    Handles all-SKIPPED, all-ERROR, and empty attempts.
    Confirmed by test_empty_and_all_skipped_are_zero.

15. asr_by_category: delegates to by_category() then applies _asr() per group.
    Category with only SKIPPED returns 0.0. Confirmed by test_asr_by_category.

16. Fix #8 -- uncategorized bucket: by_category() maps category=None to key uncategorized.
    Both test_asr_by_category and test_metrics_summary_counts include a category=None
    attempt and assert the uncategorized bucket. Confirmed.

17. metrics_summary count consistency: total == scored + errored + skipped (7=5+1+1).
    defended == PASS count == scored - succeeded (2=5-3).
    All verified by test_metrics_summary_counts.

---

## RunRecord.asr denominator fix

18. Contract update is legitimate: test_asr_mixed changed from asserting 0.5
    (4-attempt denominator) to 2/3 (3 scored-attempt denominator). The fixture
    (2 FAIL, 1 PASS, 1 SKIPPED) exercises the same scenario; only the expected
    value updated to the locked definition. Correct alignment with spec, not a regression.

---

## Runner wiring

19. runner._run_attempt calls self._scorer.score(attack, response_text=response.text,
    response=response) and sets verdict, score_tier, score_detail from the result.
    The ERROR branch (failed send) is unchanged. Confirmed at runner.py lines 203-219.

20. Runner.__init__ accepts scorer: Scorer | None = None and defaults to Scorer().
    Injected-dependency style matches sleep/rng/now.
    Confirmed by test_runner_scoring.py.

21. Resume skip-set preserved: done excludes only Verdict.ERROR -- PASS and FAIL are
    treated as done, ERROR is retried.
    test_resume_skips_executed_reruns_error_and_missing confirms cat/a (pre-existing
    SKIPPED) is not re-sent and keeps its ORIGINAL response; cat/b (ERROR) and cat/c
    (missing) are re-run and scored PASS.

---

## CLI changes

22. _summary now reads record.metrics_summary() and reports succeeded, defended,
    errored, asr. test_full_offline_run asserts defended=2 and asr=0.00% in output.

23. report (text) prints ASR (overall) and a by category: block with per-category ASR.
    report --format json includes a metrics key with full summary and retains the
    existing asr key. Confirmed by test_cli_report.py.

---

## Contract updates -- original intent preserved

24. test_runner_basic.py -- test_single_attack_happy_path: now sends text=resp x
    (canary x present) -> deterministic FAIL/T1. Asserts verdict==FAIL, score_tier==T1,
    score_detail.matched==x, plus all original request-building assertions
    (prompt, max_tokens, temperature, system=None). Original intent fully preserved.

25. test_runner_basic.py -- test_benign_response_scored_pass: replaces the old
    all-SKIPPED assertion with a named test confirming benign ok responses go through
    T2 and return PASS. Correct contract update.

26. test_runner_retries.py -- test_transient_retries_then_succeeds: now asserts
    Verdict.PASS instead of SKIPPED. The backoff-sleep-sequence assertion (the original
    purpose) is unchanged: sleep.calls == expected. Intent preserved.

27. test_runner_retries.py -- test_429_and_5xx_are_transient,
    test_httpx_transport_error_is_transient,
    test_failing_attack_does_not_crash_mixed_run: all updated to Verdict.PASS for
    successful sends. Retry and error-taxonomy assertions unchanged.

28. test_runner_cost_resume.py -- test_resume_skips_executed_reruns_error_and_missing:
    now asserts Verdict.PASS for newly-executed attempts (cat/b and cat/c).
    Resume skip behavior (cat/a keeps ORIGINAL response, only 2 requests sent)
    is unchanged and still asserted.

29. test_cli_run.py -- test_full_offline_run: now asserts defended=2 and asr=0.00%
    instead of old executed=2 and all-SKIPPED. Intent (2 attacks run, adapter closed,
    record persisted with correct attack IDs, all verdicts PASS) is preserved.

---

## Security and no-network guarantees

30. No test file imports any network library, LLM client, or ML framework. No
    environment keys read. All tests use canned response strings. LexicalClassifier
    uses only string operations and arithmetic. test_config_snapshot_no_secret
    confirms API key values never appear in the config snapshot.

---

## Minor observations (non-blocking)

31. _match_string_check with a regex that can match the empty string: would return
    empty string as the matched value. StringCheck validator ensures the pattern
    compiles but not that it cannot match empty. Configuration edge case not
    triggered by any bundled pack; does not affect correctness for normal use.

32. Second Runner() in cli.py line 176 (Runner(adapter, cfg.run).run_path(record)):
    creates a discarded Scorer() instance. Acknowledged as harmless in Fix #7
    and explicitly left out of scope.

33. _score_classifier verdict condition requires BOTH cv.label == check.label AND
    cv.score >= check.threshold for FAIL. Stricter than score-only; behavior is
    intentional, tested, and consistent with the ClassifierCheck contract.

STATUS: PASS