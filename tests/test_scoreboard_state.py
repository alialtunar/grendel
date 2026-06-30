"""M1: pure ScoreboardState view-model — no Textual import, fully deterministic."""

from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime, timedelta

from fakes import make_attack
from gauntlet.attacks import Severity
from gauntlet.records import (
    AttemptRecord,
    RunRecord,
    RunStatus,
    ScoreDetail,
    TokenUsage,
    Verdict,
)
from gauntlet.tui.state import (
    AttemptFilter,
    build_scoreboard,
    repro_for,
    select_next,
    toggle_explain,
    with_filter,
)

T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def test_state_imports_no_textual() -> None:
    # Machine guard (fix #10): importing the pure model must never pull in Textual. Run in a
    # clean subprocess so the assertion holds regardless of suite import order (other test
    # modules import the Textual app).
    code = (
        "import sys; import gauntlet.tui.state; "
        "assert 'textual' not in sys.modules, sorted(m for m in sys.modules if 'textual' in m)"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def _attempt(
    attack_id: str,
    verdict: Verdict,
    *,
    category: str | None = None,
    response_text: str | None = "resp",
    reason: str | None = None,
    matched: str | None = None,
    classifier_score: float | None = None,
    error: str | None = None,
    score_tier: str | None = None,
    start_offset: float = 0.0,
    duration: float = 1.0,
    prompt_tokens: int = 1,
    completion_tokens: int = 2,
    cost: float | None = 0.001,
) -> AttemptRecord:
    cat = category if category is not None else attack_id.split("/", 1)[0]
    detail = None
    if reason is not None or matched is not None or classifier_score is not None:
        detail = ScoreDetail(
            tier=score_tier or "T1",
            reason=reason or "",
            matched=matched,
            classifier_score=classifier_score,
        )
    return AttemptRecord(
        attack_id=attack_id,
        category=cat,
        prompt=f"prompt for {attack_id}",
        response_text=response_text,
        verdict=verdict,
        score_tier=score_tier,
        score_detail=detail,
        error=error,
        usage=TokenUsage(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens),
        cost_usd=cost,
        started_at=T0 + timedelta(seconds=start_offset),
        finished_at=T0 + timedelta(seconds=start_offset + duration),
    )


def _record(status: RunStatus = RunStatus.COMPLETED, attempts=None) -> RunRecord:
    return RunRecord(
        run_id="run-1",
        created_at=T0,
        status=status,
        target_name="gpt",
        provider="openai",
        model="gpt-4o-mini",
        attempts=attempts or [],
    )


def _plan() -> list:
    # alpha: a1 (crit FAIL), a2 (PASS), a3 (planned-not-run). beta: b1 (FAIL high), b2 (ERROR).
    return [
        make_attack("alpha/a1", severity="critical", owasp="LLM02", atlas="AML.T0010"),
        make_attack("alpha/a2", severity="low"),
        make_attack("alpha/a3", severity="medium"),
        make_attack("beta/b1", severity="high"),
        make_attack("beta/b2", severity="medium"),
    ]


def _full_record() -> RunRecord:
    return _record(
        attempts=[
            _attempt(
                "alpha/a1",
                Verdict.FAIL,
                reason="canary matched",
                matched="x",
                score_tier="T1",
                start_offset=0.0,
                duration=2.0,
            ),
            _attempt("alpha/a2", Verdict.PASS, reason="refusal", score_tier="T1", start_offset=1.0),
            _attempt(
                "beta/b1",
                Verdict.FAIL,
                reason="classifier",
                score_tier="T2",
                classifier_score=0.9,
                start_offset=3.0,
                duration=1.0,
            ),
            _attempt(
                "beta/b2",
                Verdict.ERROR,
                response_text=None,
                error="boom",
                start_offset=2.0,
                duration=0.5,
            ),
        ]
    )


def test_header_counts_and_overall_asr() -> None:
    state = build_scoreboard(_plan(), _full_record())
    assert state.total == 5  # plan size (a3 not yet run)
    assert state.done == 4
    assert state.passed == 1
    assert state.failed == 2
    assert state.errored == 1
    assert state.skipped == 0
    # ASR = FAIL / (PASS+FAIL) = 2 / 3.
    assert abs(state.overall_asr - (2 / 3)) < 1e-9
    assert abs(state.progress - 4 / 5) < 1e-9
    assert state.progress < 1.0
    assert state.total_tokens == 4 * 3  # each attempt 1+2
    assert abs(state.total_cost_usd - 0.004) < 1e-9
    assert state.status == RunStatus.COMPLETED


def test_category_rows_counts_asr_and_flag() -> None:
    state = build_scoreboard(_plan(), _full_record())
    rows = {r.category: r for r in state.categories}
    assert set(rows) == {"alpha", "beta"}
    alpha = rows["alpha"]
    assert alpha.total == 3  # a1, a2, a3 planned
    assert alpha.done == 2
    assert alpha.passed == 1 and alpha.failed == 1
    assert abs(alpha.asr - 0.5) < 1e-9
    assert alpha.flag_severity == Severity.CRITICAL  # a1 FAIL is critical
    beta = rows["beta"]
    assert beta.total == 2 and beta.done == 2
    assert beta.failed == 1 and beta.errored == 1
    assert abs(beta.asr - 1.0) < 1e-9  # 1 FAIL / 1 scored
    assert beta.flag_severity == Severity.HIGH  # b1 FAIL high; b2 ERROR not counted


def test_total_from_plan_with_unrun_attack() -> None:
    # Only a1 executed; the plan still has 5 -> done < total, progress < 1.
    rec = _record(status=RunStatus.RUNNING, attempts=[_attempt("alpha/a1", Verdict.PASS)])
    state = build_scoreboard(_plan(), rec, now=T0 + timedelta(seconds=10))
    assert state.total == 5
    assert state.done == 1
    rows = {r.category: r for r in state.categories}
    assert rows["alpha"].total == 3 and rows["alpha"].done == 1
    assert rows["alpha"].done < rows["alpha"].total


def test_elapsed_from_timestamps() -> None:
    # COMPLETED -> end = max finished_at. Starts at T0, latest finish = 4.0s.
    state = build_scoreboard(_plan(), _full_record())
    assert abs(state.elapsed_s - 4.0) < 1e-9


def test_elapsed_running_uses_now() -> None:
    rec = _record(status=RunStatus.RUNNING, attempts=[_attempt("alpha/a1", Verdict.PASS)])
    state = build_scoreboard(_plan(), rec, now=T0 + timedelta(seconds=12.5))
    assert abs(state.elapsed_s - 12.5) < 1e-9


def test_elapsed_zero_when_no_starts() -> None:
    rec = _record(attempts=[AttemptRecord(attack_id="alpha/a1", prompt="p", verdict=Verdict.PASS)])
    assert build_scoreboard(_plan(), rec).elapsed_s == 0.0


def test_failure_join_and_sort_order() -> None:
    state = build_scoreboard(_plan(), _full_record())
    failures = state.failures
    # FAIL/ERROR only (a1, b1, b2). Sort: severity desc, category, attack_id.
    # a1 critical > b1 high > b2 medium.
    assert [f.attack_id for f in failures] == ["alpha/a1", "beta/b1", "beta/b2"]
    a1 = failures[0]
    assert a1.severity == Severity.CRITICAL
    assert a1.owasp == "LLM02" and a1.atlas == "AML.T0010"
    assert a1.payload == "do the bad thing"
    assert a1.reason == "canary matched" and a1.matched == "x"
    assert a1.name == "attack alpha/a1"
    b2 = failures[2]
    assert b2.verdict == Verdict.ERROR
    assert b2.error == "boom"
    assert b2.response_text is None


def test_filter_by_category_verdict_severity() -> None:
    state = build_scoreboard(_plan(), _full_record())

    cat = with_filter(state, AttemptFilter(category="beta"))
    assert {f.attack_id for f in cat.failures} == {"beta/b1", "beta/b2"}

    fail_only = with_filter(state, AttemptFilter(verdict=Verdict.FAIL))
    assert {f.attack_id for f in fail_only.failures} == {"alpha/a1", "beta/b1"}

    err_only = with_filter(state, AttemptFilter(verdict=Verdict.ERROR))
    assert {f.attack_id for f in err_only.failures} == {"beta/b2"}

    # "this severity or worse": high -> a1(critical) + b1(high), drops b2(medium).
    sev = with_filter(state, AttemptFilter(severity=Severity.HIGH))
    assert {f.attack_id for f in sev.failures} == {"alpha/a1", "beta/b1"}


def test_select_next_clamps_both_ends() -> None:
    state = build_scoreboard(_plan(), _full_record())
    assert state.selected_index == 0
    state = select_next(state, -1)
    assert state.selected_index == 0  # clamp at start
    state = select_next(select_next(state, 1), 1)
    assert state.selected_index == 2
    state = select_next(state, 1)
    assert state.selected_index == 2  # clamp at end
    assert state.selected_failure is not None


def test_select_next_empty_is_minus_one() -> None:
    state = build_scoreboard(_plan(), _record(attempts=[_attempt("alpha/a2", Verdict.PASS)]))
    assert state.failures == ()
    assert state.selected_index == -1
    assert select_next(state, 1).selected_index == -1
    assert state.selected_failure is None


def test_toggle_explain() -> None:
    state = build_scoreboard(_plan(), _full_record())
    assert state.explain_visible is False
    flipped = toggle_explain(state)
    assert flipped.explain_visible is True
    assert toggle_explain(flipped).explain_visible is False


def test_repro_for_exact_string() -> None:
    state = build_scoreboard(_plan(), _full_record())
    a1 = state.failures[0]
    repro = repro_for(a1, target_name="gpt")
    expected = (
        "# gauntlet repro — alpha/a1\n"
        "# category=alpha severity=critical owasp=LLM02 atlas=AML.T0010\n"
        "gauntlet run --target gpt --pack alpha/a1\n"
        "# payload sent:\n"
        "do the bad thing\n"
        "# target response:\n"
        "resp\n"
        "# verdict: FAIL [T1] — canary matched"
    )
    assert repro == expected


def test_repro_for_none_and_missing_response() -> None:
    state = build_scoreboard(_plan(), _full_record())
    b2 = state.failures[2]  # ERROR row, no response
    repro = repro_for(b2, target_name="gpt")
    assert "# target response:\n(no response)" in repro
    assert repro.endswith("# verdict: ERROR [-] — boom")
