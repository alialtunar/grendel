"""M2: RunDiff over two hand-built records — deltas, transitions, renderings."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from grendel.diff import diff_runs, render_markdown, render_text
from grendel.records import AttemptRecord, RunRecord, Verdict


def _record(run_id: str, attempts: list[AttemptRecord]) -> RunRecord:
    return RunRecord(
        run_id=run_id,
        created_at=datetime.now(UTC),
        target_name="gpt",
        provider="openai",
        model="gpt-4o-mini",
        attempts=attempts,
    )


def _att(attack_id, verdict, *, owasp="LLM01", atlas="AML.T0051", category="inj", **kw):
    return AttemptRecord(
        attack_id=attack_id,
        category=category,
        owasp=owasp,
        atlas=atlas,
        prompt="p",
        verdict=verdict,
        **kw,
    )


def _build_pair() -> tuple[RunRecord, RunRecord]:
    # A: x1 defended (PASS), x2 succeeded (FAIL), x3 PASS, err ERROR, None-id FAIL
    a = _record(
        "runA",
        [
            _att("inj/x1", Verdict.PASS, latency_ms=10.0, cost_usd=0.001),
            _att("inj/x2", Verdict.FAIL, latency_ms=20.0, cost_usd=0.001),
            _att("inj/x3", Verdict.PASS),
            _att("inj/err", Verdict.ERROR),
            _att(None, Verdict.FAIL),  # Fix #2: None-id excluded from join
        ],
    )
    # B: x1 now FAIL (newly failing), x2 now PASS (newly fixed), x3 PASS, err ERROR, None-id FAIL
    b = _record(
        "runB",
        [
            _att("inj/x1", Verdict.FAIL, latency_ms=30.0, cost_usd=0.002),
            _att("inj/x2", Verdict.PASS, latency_ms=40.0, cost_usd=0.002),
            _att("inj/x3", Verdict.PASS),
            _att("inj/err", Verdict.ERROR),
            _att(None, Verdict.FAIL),
        ],
    )
    return a, b


def test_overall_and_transitions() -> None:
    a, b = _build_pair()
    d = diff_runs(a, b)
    # A scored non-control: x1 PASS, x2 FAIL, x3 PASS, None-id FAIL -> 2/4 = 0.5
    assert d.overall_asr_a == 0.5
    # B scored: x1 FAIL, x2 PASS, x3 PASS, None-id FAIL -> 2/4 = 0.5
    assert d.overall_asr_b == 0.5
    assert d.overall_asr_delta == 0.0
    # Transitions exclude None-id, ERROR, one-sided.
    assert d.newly_failing == ["inj/x1"]
    assert d.newly_fixed == ["inj/x2"]


def test_cost_and_latency_delta() -> None:
    a, b = _build_pair()
    d = diff_runs(a, b)
    assert round(d.cost_delta_usd, 6) == round((0.004) - (0.002), 6)
    # mean latency A = (10+20)/2 = 15; B = (30+40)/2 = 35 -> +20
    assert d.latency_delta_ms == 20.0


def test_latency_none_when_a_side_lacks_latency() -> None:
    a = _record("a", [_att("inj/x", Verdict.PASS)])  # no latency
    b = _record("b", [_att("inj/x", Verdict.FAIL, latency_ms=5.0)])
    d = diff_runs(a, b)
    assert d.latency_delta_ms is None
    assert "latency: n/a" in render_text(d)
    assert "latency: n/a" in render_markdown(d)


def test_axis_union_missing_side_zero() -> None:
    a = _record("a", [_att("inj/x", Verdict.FAIL, owasp="LLM01")])
    b = _record("b", [_att("inj/y", Verdict.FAIL, owasp="LLM06")])
    d = diff_runs(a, b)
    codes = {row.code: row for row in d.by_owasp}
    assert set(codes) == {"LLM01", "LLM06"}
    assert codes["LLM06"].asr_a == 0.0  # missing in A
    assert codes["LLM01"].asr_b == 0.0  # missing in B
    # sorted by code
    assert [r.code for r in d.by_owasp] == ["LLM01", "LLM06"]


def test_self_diff_is_zero() -> None:
    # Fix #6: a record against itself -> zero overall delta, no transitions.
    a, _ = _build_pair()
    d = diff_runs(a, a)
    assert d.overall_asr_delta == 0.0
    assert d.newly_failing == []
    assert d.newly_fixed == []


def test_renderings_deterministic_and_have_markers() -> None:
    a, b = _build_pair()
    d = diff_runs(a, b)
    text = render_text(d)
    assert text == render_text(d)  # deterministic
    assert "overall ASR" in text
    assert "newly failing: inj/x1" in text
    assert "newly fixed: inj/x2" in text

    md = render_markdown(d)
    assert md == render_markdown(d)
    assert "# Score diff" in md
    assert "inj/x1" in md

    obj = json.loads(json.dumps(d.model_dump()))
    assert obj["newly_failing"] == ["inj/x1"]
    assert obj["overall_asr_delta"] == 0.0
