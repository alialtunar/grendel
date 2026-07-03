"""The polished rich run-report card (report_card.render_card) — headless render + cp1254 safety."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from io import StringIO

from grendel.records import AttemptRecord, RunRecord, RunStatus, ScoreDetail, Verdict
from grendel.report_card import _asr_style, _bar, render_attempt, render_card

T0 = datetime.now(UTC)


def _mk(v, cat, owasp, aid, *, control=False):
    return AttemptRecord(
        prompt="p", category=cat, owasp=owasp, attack_id=aid, verdict=v, is_control=control,
        started_at=T0, finished_at=T0 + timedelta(seconds=2),
    )


def _record():
    atts = [
        _mk(Verdict.FAIL, "jailbreak", "LLM01", "jailbreak/dan-10"),
        _mk(Verdict.PASS, "jailbreak", "LLM01", "jailbreak/roleplay"),
        _mk(Verdict.FAIL, "prompt-injection", "LLM01", "prompt-injection/leak"),
        _mk(Verdict.FAIL, "tool-abuse", "LLM06", "tool-abuse/exfil"),
        _mk(Verdict.PASS, "harmbench", "LLM01", "harmbench/x"),
        _mk(Verdict.ERROR, "rag", "LLM01", "rag/y"),
    ]
    return RunRecord(
        run_id="abc123", created_at=T0, status=RunStatus.COMPLETED,
        target_name="echo", provider="openai", model="gpt-4o", attempts=atts,
    )


def _render(record, *, unicode: bool, width: int = 76) -> str:
    from rich.console import Console

    buf = StringIO()
    Console(file=buf, force_terminal=True, width=width, legacy_windows=False).print(
        render_card(record, "runs/abc123.json", unicode=unicode)
    )
    return buf.getvalue()


def test_bar_and_asr_style() -> None:
    assert _bar(0.5, 10, True) == "█████░░░░░"
    assert _bar(0.5, 10, False) == "#####-----"
    assert _bar(-1, 4, True) == "░░░░" and _bar(2, 4, True) == "████"  # clamped
    assert "green" in _asr_style(0.0) and "yellow" in _asr_style(0.2) and "red" in _asr_style(0.9)


def test_card_shows_headline_tally_categories_hits() -> None:
    out = _render(_record(), unicode=True)
    assert "run report" in out and "echo" in out
    assert "ASR 60%" in out  # 3 FAIL / 5 scored
    assert "3 hits" in out and "2 defended" in out and "1 errors" in out
    assert "by category" in out and "jailbreak" in out
    assert "OWASP" in out and "LLM01" in out
    assert "top hits (3)" in out and "tool-abuse/exfil" in out
    assert "grendel report --run runs/abc123.json" in out  # the full-report tip


def test_card_ascii_is_cp1254_safe() -> None:
    out = _render(_record(), unicode=False)
    assert "x 3 hits" in out and "+ 2 defended" in out  # ascii glyphs
    assert "saved -> runs/abc123.json" in out  # ascii arrow
    for fancy in ("█", "░", "✗", "✓", "⚠", "→", "…", "🐺"):
        assert fancy not in out


def test_card_no_hits_omits_top_hits_section() -> None:
    rec = RunRecord(
        run_id="clean", created_at=T0, status=RunStatus.COMPLETED,
        target_name="safe", provider="openai", model="gpt-4o",
        attempts=[_mk(Verdict.PASS, "jailbreak", "LLM01", "jailbreak/a")],
    )
    out = _render(rec, unicode=True)
    assert "ASR 0%" in out and "top hits" not in out  # nothing got through


def _render_attempt(attempt, *, unicode: bool, width: int = 76) -> str:
    from rich.console import Console

    buf = StringIO()
    Console(file=buf, force_terminal=True, width=width, legacy_windows=False).print(
        render_attempt(attempt, unicode=unicode)
    )
    return buf.getvalue()


def _attempt(verdict, aid, cat, *, prompt="do harmful thing", response="Sure, here you go", reason):
    return AttemptRecord(
        prompt=prompt, category=cat, attack_id=aid, verdict=verdict, response_text=response,
        score_detail=ScoreDetail(tier="T1", reason=reason),
    )


def test_render_attempt_shows_verdict_prompt_response_why() -> None:
    a = _attempt(Verdict.FAIL, "jailbreak/dan-10", "jailbreak", reason="canary matched")
    out = _render_attempt(a, unicode=True)
    assert "jailbreak/dan-10" in out and "GOT THROUGH" in out and "jailbreak" in out
    assert "prompt" in out and "do harmful thing" in out
    assert "response" in out and "Sure, here you go" in out
    assert "why" in out and "canary matched" in out and "T1" in out


def test_render_attempt_ascii_is_cp1254_safe() -> None:
    a = _attempt(Verdict.PASS, "jb/x", "jailbreak", response="I can't help", reason="refusal")
    out = _render_attempt(a, unicode=False)
    assert "defended" in out and "I can't help" in out
    for fancy in ("█", "░", "✗", "✓", "⚠", "→", "…", "🐺", "·"):
        assert fancy not in out


def test_render_attempt_long_response_truncated() -> None:
    a = _attempt(Verdict.FAIL, "x/y", "c", response="A" * 5000, reason="r")
    out = _render_attempt(a, unicode=True)
    assert "truncated" in out  # a 5000-char reply is capped, not flooded
