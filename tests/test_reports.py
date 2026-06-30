"""M3+M4: markdown + html report renderers — strings, escaping, self-containment."""

from __future__ import annotations

from datetime import UTC, datetime

from gauntlet.records import AttemptRecord, RunRecord, RunStatus, ScoreDetail, Verdict
from gauntlet.reports import render_html, render_markdown

# A payload that is adversarial for BOTH renderers: triple-backticks (breaks MD fences)
# and HTML metacharacters (breaks HTML).
NASTY = 'ignore previous ```\n<script>alert(1)</script> & "quotes"'


def _record(*, with_controls: bool) -> RunRecord:
    attempts = [
        # A succeeded attack WITH full detail + tool calls + the nasty payload.
        AttemptRecord(
            attack_id="inj/a",
            category="inj",
            owasp="LLM01",
            atlas="AML.T0051",
            prompt=NASTY,
            response_text="sure, here you go <b>",
            tool_calls=[{"name": "send_email", "args": {"to": "x@y.z"}}],
            verdict=Verdict.FAIL,
            latency_ms=12.0,
            cost_usd=0.001,
            score_detail=ScoreDetail(tier="T1", reason="canary matched"),
        ),
        # Fix #1: a succeeded attack with score_detail=None AND response_text=None.
        AttemptRecord(
            attack_id="inj/b",
            category="inj",
            owasp="LLM01",
            atlas="AML.T0051",
            prompt="plain",
            response_text=None,
            verdict=Verdict.FAIL,
            latency_ms=8.0,
            score_detail=None,
        ),
        AttemptRecord(
            attack_id="inj/c",
            category="inj",
            owasp="LLM01",
            atlas="AML.T0051",
            prompt="p",
            verdict=Verdict.PASS,
        ),
        AttemptRecord(
            attack_id="jb/d",
            category="jail",
            owasp="LLM06",
            atlas="AML.T0054",
            prompt="p",
            verdict=Verdict.ERROR,
        ),
        AttemptRecord(
            attack_id="jb/e",
            category="jail",
            owasp="LLM06",
            atlas="AML.T0054",
            prompt="p",
            verdict=Verdict.SKIPPED,
        ),
    ]
    if with_controls:
        attempts.append(
            AttemptRecord(
                prompt="benign", category="control", verdict=Verdict.PASS, is_control=True
            )
        )
    return RunRecord(
        run_id="rep",
        created_at=datetime(2024, 1, 1, tzinfo=UTC),
        target_name="gpt",
        provider="openai",
        model="gpt-4o-mini",
        status=RunStatus.COMPLETED,
        pack_ids=["inj", "jail"],
        attempts=attempts,
    )


# ------------------------------------------------------------------------- markdown


def test_markdown_headline_and_breakdowns() -> None:
    md = render_markdown(_record(with_controls=False))
    # overall ASR: 2 FAIL / 3 scored = 66.67%
    assert "66.67%" in md
    assert "## By category" in md
    assert "## By OWASP" in md
    assert "## By ATLAS" in md
    assert "LLM01" in md and "AML.T0051" in md
    assert "## Failures (2)" in md
    assert "inj/a" in md and "inj/b" in md


def test_markdown_null_guards() -> None:
    md = render_markdown(_record(with_controls=False))
    # response_text=None -> "(no response)"; score_detail=None -> no Reason line crash
    assert "(no response)" in md


def test_markdown_backtick_safe_fence() -> None:
    md = render_markdown(_record(with_controls=False))
    # The nasty payload contains ``` so the fence must be >= 4 backticks.
    assert "````" in md
    assert NASTY in md  # payload rendered verbatim inside the (longer) fence


def test_markdown_controls_conditional() -> None:
    assert "## Utility under attack" in render_markdown(_record(with_controls=True))
    assert "## Utility under attack" not in render_markdown(_record(with_controls=False))


def test_markdown_deterministic() -> None:
    r = _record(with_controls=True)
    assert render_markdown(r) == render_markdown(r)


# ----------------------------------------------------------------------------- html


def test_html_self_contained() -> None:
    h = render_html(_record(with_controls=False))
    assert h.startswith("<!DOCTYPE html>")
    assert "<style>" in h
    # no external assets, no script tags from our template
    assert "http://" not in h and "https://" not in h
    assert "<script>" not in h  # the only <script> would be the escaped payload


def test_html_escapes_adversarial_payload() -> None:
    h = render_html(_record(with_controls=False))
    assert "&lt;script&gt;" in h
    assert "<script>alert(1)</script>" not in h
    assert "&amp;" in h


def test_html_headline_tables_failures() -> None:
    h = render_html(_record(with_controls=False))
    assert "66.67%" in h
    assert "<table>" in h
    assert "inj/a" in h
    assert "Failures (2)" in h


def test_html_null_guards() -> None:
    h = render_html(_record(with_controls=False))
    assert "(no response)" in h


def test_html_controls_conditional() -> None:
    assert "Utility under attack" in render_html(_record(with_controls=True))
    assert "Utility under attack" not in render_html(_record(with_controls=False))


def test_html_deterministic() -> None:
    r = _record(with_controls=True)
    assert render_html(r) == render_html(r)
