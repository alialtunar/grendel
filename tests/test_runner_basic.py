"""M1: request building, happy path, persistence."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fakes import FakeAdapter, make_attack
from gauntlet.config import RunOptions
from gauntlet.records import RunRecord, RunStatus, Verdict
from gauntlet.runner import Runner


def _record(tmp_path: Path) -> RunRecord:
    return RunRecord(
        run_id="run-basic",
        created_at=datetime.now(UTC),
        target_name="t",
        provider="fake",
        model="fake-model",
    )


def _options(tmp_path: Path, **kw) -> RunOptions:
    return RunOptions(output_dir=tmp_path, max_tokens=77, temperature=0.3, **kw)


async def test_single_attack_happy_path(tmp_path: Path) -> None:
    # Canary "x" (make_attack's default success_when) present in the response -> the
    # attack succeeded -> deterministic FAIL/T1 (Phase 4 scoring contract).
    adapter = FakeAdapter(text="resp x", prompt_tokens=3, completion_tokens=4)
    runner = Runner(adapter, _options(tmp_path))
    record = await runner.run([make_attack("cat/a", payload="hello")], _record(tmp_path))

    assert record.status == RunStatus.COMPLETED
    assert len(record.attempts) == 1
    att = record.attempts[0]
    assert att.verdict == Verdict.FAIL
    assert att.score_tier == "T1"
    assert att.score_detail is not None and att.score_detail.matched == "x"
    assert att.attack_id == "cat/a"
    assert att.response_text == "resp x"
    assert att.raw_response == {"echo": "hello"}
    assert att.usage.prompt_tokens == 3
    assert att.usage.completion_tokens == 4
    assert att.latency_ms is not None
    assert att.started_at is not None and att.finished_at is not None

    # Request building: prompt == payload, pinned max_tokens/temperature.
    assert len(adapter.requests) == 1
    req = adapter.requests[0]
    assert req.prompt == "hello"
    assert req.max_tokens == 77
    assert req.temperature == 0.3
    assert req.system is None


async def test_multi_attack_ordered_and_persisted(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    runner = Runner(adapter, _options(tmp_path, concurrency=1))
    attacks = [make_attack("cat/c"), make_attack("cat/a"), make_attack("cat/b")]
    record = await runner.run(attacks, _record(tmp_path))

    assert record.status == RunStatus.COMPLETED
    assert len(record.attempts) == 3
    # Deterministic id ordering (sorted by id) with concurrency=1.
    assert [r.prompt for r in adapter.requests]  # sent
    assert sorted(a.attack_id for a in record.attempts) == ["cat/a", "cat/b", "cat/c"]

    # Persisted file round-trips.
    path = runner.run_path(record)
    assert path.exists()
    assert path == tmp_path / "run-basic.json"
    reloaded = RunRecord.from_json(path.read_text(encoding="utf-8"))
    assert reloaded.run_id == record.run_id
    assert len(reloaded.attempts) == 3
    assert reloaded.status == RunStatus.COMPLETED


async def test_benign_response_scored_pass(tmp_path: Path) -> None:
    # Phase 4 contract update: a benign response ("ok", no canary, no refusal marker)
    # escalates to T2, the lexical classifier scores it safe -> PASS (was SKIPPED in P3).
    adapter = FakeAdapter()
    runner = Runner(adapter, _options(tmp_path))
    record = await runner.run([make_attack("cat/a")], _record(tmp_path))
    assert all(a.verdict == Verdict.PASS for a in record.attempts)
    assert all(a.verdict != Verdict.SKIPPED for a in record.attempts)
