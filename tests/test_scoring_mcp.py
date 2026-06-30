"""M3: T4 MCP scorer (PASS/FAIL/ERROR/SKIPPED) + score_async wiring (judge OFF)."""

from __future__ import annotations

from gauntlet.attacks import Attack
from gauntlet.mcp_surface import McpObservation
from gauntlet.records import Verdict
from gauntlet.scoring import Scorer, score_mcp
from gauntlet.targets.base import AdapterResponse


def _attack(expr: str) -> Attack:
    return Attack(
        id="mcp/probe",
        name="probe",
        category="mcp",
        owasp="LLM01",
        atlas="AML.T0051",
        surface="mcp-desc",
        severity="high",
        license="MIT",
        version=1,
        payload="x",
        success_when={"type": "mcp-assert", "assert": expr},
    )


def _check(expr: str):
    return _attack(expr).success_when


def _obs_changed() -> McpObservation:
    return McpObservation(
        approved_descriptions={"send_email": "old"},
        current_descriptions={"send_email": "new"},
    )


def _mcp_response(obs: McpObservation | None) -> AdapterResponse:
    return AdapterResponse(text="", raw={}, model="m", provider="mcp", mcp=obs)


# --- score_mcp decision table ---


def test_score_mcp_none_observation_skipped() -> None:
    r = score_mcp(_check("mcp.description_changed('send_email')"), None)
    assert r.verdict == Verdict.SKIPPED
    assert r.score_tier is None
    assert "not-applicable" in r.detail.reason


def test_score_mcp_satisfied_fail_t4() -> None:
    r = score_mcp(_check("mcp.description_changed('send_email')"), _obs_changed())
    assert r.verdict == Verdict.FAIL
    assert r.score_tier == "T4"


def test_score_mcp_unsatisfied_pass_t4() -> None:
    obs = McpObservation(
        approved_descriptions={"send_email": "same"},
        current_descriptions={"send_email": "same"},
    )
    r = score_mcp(_check("mcp.description_changed('send_email')"), obs)
    assert r.verdict == Verdict.PASS
    assert r.score_tier == "T4"


def test_score_mcp_bad_assertion_error_t4() -> None:
    r = score_mcp(_check("mcp.bogus('x')"), _obs_changed())
    assert r.verdict == Verdict.ERROR
    assert r.score_tier == "T4"


# --- score_async wiring (judge disabled by default) ---


async def test_score_async_t4_fires_with_judge_disabled() -> None:
    scorer = Scorer()  # judge OFF
    attack = _attack("mcp.description_changed('send_email')")
    resp = _mcp_response(_obs_changed())
    result = await scorer.score_async(attack, response_text="", response=resp)
    assert result.verdict == Verdict.FAIL
    assert result.score_tier == "T4"


def test_sync_score_mcp_assert_is_skipped() -> None:
    scorer = Scorer()
    attack = _attack("mcp.description_changed('send_email')")
    result = scorer.score(attack, response_text="", response=_mcp_response(_obs_changed()))
    assert result.verdict == Verdict.SKIPPED
    assert "mcp-assert" in result.detail.reason


async def test_score_async_non_mcp_response_stays_skipped() -> None:
    scorer = Scorer()
    attack = _attack("mcp.description_changed('send_email')")
    # A non-mcp response: mcp=None -> not-applicable -> SKIPPED (inert refinement).
    resp = AdapterResponse(text="hi", raw={}, model="m", provider="python", mcp=None)
    result = await scorer.score_async(attack, response_text="hi", response=resp)
    assert result.verdict == Verdict.SKIPPED
