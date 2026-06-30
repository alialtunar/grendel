"""Tests for the RunRecord data model."""

from __future__ import annotations

import json

from gauntlet.config import GauntletConfig, TargetConfig
from gauntlet.records import (
    AttemptRecord,
    RunRecord,
    TokenUsage,
    Verdict,
    make_run_record,
)


def _record_with(attempts: list[AttemptRecord]) -> RunRecord:
    return make_run_record(
        target_name="gpt",
        provider="openai",
        model="gpt-4o-mini",
        config=GauntletConfig(),
        attempts=attempts,
    )


def test_roundtrip_equal() -> None:
    rec = _record_with(
        [
            AttemptRecord(prompt="p1", verdict=Verdict.FAIL, category="injection"),
            AttemptRecord(prompt="p2", verdict=Verdict.PASS, category="jailbreak"),
        ]
    )
    assert RunRecord.from_json(rec.to_json()) == rec


def test_asr_empty_is_zero() -> None:
    rec = _record_with([])
    assert rec.asr == 0.0
    assert rec.total_attempts == 0


def test_asr_mixed() -> None:
    rec = _record_with(
        [
            AttemptRecord(prompt="a", verdict=Verdict.FAIL),
            AttemptRecord(prompt="b", verdict=Verdict.PASS),
            AttemptRecord(prompt="c", verdict=Verdict.FAIL),
            AttemptRecord(prompt="d", verdict=Verdict.SKIPPED),
        ]
    )
    assert rec.asr == 0.5


def test_by_category_groups() -> None:
    rec = _record_with(
        [
            AttemptRecord(prompt="a", category="injection"),
            AttemptRecord(prompt="b", category="injection"),
            AttemptRecord(prompt="c", category=None),
        ]
    )
    grouped = rec.by_category()
    assert set(grouped) == {"injection", "uncategorized"}
    assert len(grouped["injection"]) == 2
    assert len(grouped["uncategorized"]) == 1


def test_token_usage_total() -> None:
    usage = TokenUsage(prompt_tokens=10, completion_tokens=5)
    assert usage.total_tokens == 15


def test_config_snapshot_no_secret(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    cfg = GauntletConfig(targets={"gpt": TargetConfig(provider="openai", model="gpt-4o-mini")})
    rec = make_run_record(
        target_name="gpt",
        provider="openai",
        model="gpt-4o-mini",
        config=cfg,
    )
    assert "sk-test" not in json.dumps(rec.config_snapshot)
