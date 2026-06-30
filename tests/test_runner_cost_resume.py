"""M4: token/cost aggregation + resume skip/replace."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fakes import FakeAdapter, make_attack
from gauntlet.config import RunOptions
from gauntlet.pricing import estimate_cost
from gauntlet.records import AttemptRecord, RunRecord, RunStatus, TokenUsage, Verdict
from gauntlet.runner import Runner


def _record(provider: str = "fake", model: str = "fake-model") -> RunRecord:
    return RunRecord(
        run_id="run-cost",
        created_at=datetime.now(UTC),
        target_name="t",
        provider=provider,
        model=model,
    )


def test_token_usage_add_and_totals() -> None:
    rec = RunRecord(
        run_id="r",
        created_at=datetime.now(UTC),
        target_name="t",
        provider="p",
        model="m",
        attempts=[
            AttemptRecord(
                prompt="a", usage=TokenUsage(prompt_tokens=2, completion_tokens=3), cost_usd=0.5
            ),
            AttemptRecord(
                prompt="b", usage=TokenUsage(prompt_tokens=4, completion_tokens=1), cost_usd=None
            ),
        ],
    )
    assert rec.total_usage.prompt_tokens == 6
    assert rec.total_usage.completion_tokens == 4
    assert rec.total_cost_usd == 0.5  # None treated as 0


def test_estimate_cost_known_and_unknown() -> None:
    usage = TokenUsage(prompt_tokens=1000, completion_tokens=1000)
    cost, known = estimate_cost("openai", "gpt-4o-mini", usage)
    assert known is True
    assert cost > 0
    assert estimate_cost("nope", "nope", usage) == (0.0, False)


async def test_priced_model_sets_cost(tmp_path: Path) -> None:
    adapter = FakeAdapter(prompt_tokens=1000, completion_tokens=1000)
    runner = Runner(adapter, RunOptions(output_dir=tmp_path))
    record = await runner.run(
        [make_attack("cat/a")], _record(provider="openai", model="gpt-4o-mini")
    )
    att = record.attempts[0]
    assert att.cost_usd is not None and att.cost_usd > 0
    assert record.total_cost_usd == att.cost_usd


async def test_unlisted_model_cost_zero(tmp_path: Path) -> None:
    adapter = FakeAdapter(prompt_tokens=10, completion_tokens=10)
    runner = Runner(adapter, RunOptions(output_dir=tmp_path))
    record = await runner.run([make_attack("cat/a")], _record())
    assert record.attempts[0].cost_usd == 0.0


async def test_error_attempt_cost_is_none(tmp_path: Path) -> None:
    adapter = FakeAdapter(failures=[ValueError("boom")])
    runner = Runner(adapter, RunOptions(output_dir=tmp_path, max_retries=0))
    record = await runner.run([make_attack("cat/a")], _record())
    att = record.attempts[0]
    assert att.verdict == Verdict.ERROR
    assert att.cost_usd is None  # never 0.0 on ERROR


async def test_resume_skips_executed_reruns_error_and_missing(tmp_path: Path) -> None:
    # Partial record: cat/a executed (SKIPPED), cat/b ERROR; cat/c never attempted.
    record = _record()
    record.attempts = [
        AttemptRecord(
            attack_id="cat/a", prompt="x", verdict=Verdict.SKIPPED, response_text="ORIGINAL"
        ),
        AttemptRecord(attack_id="cat/b", prompt="x", verdict=Verdict.ERROR, error="boom"),
    ]
    # Persist mid-run then feed back into run() with the full attack list.
    runner = Runner(FakeAdapter(text="NEW"), RunOptions(output_dir=tmp_path, concurrency=1))
    path = runner.run_path(record)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(record.to_json(), encoding="utf-8")
    reloaded = RunRecord.from_json(path.read_text(encoding="utf-8"))

    attacks = [make_attack("cat/a"), make_attack("cat/b"), make_attack("cat/c")]
    result = await runner.run(attacks, reloaded)

    assert result.status == RunStatus.COMPLETED
    # No duplicate attack_ids ever.
    ids = [a.attack_id for a in result.attempts]
    assert sorted(ids) == ["cat/a", "cat/b", "cat/c"]
    assert len(ids) == len(set(ids))
    by_id = {a.attack_id: a for a in result.attempts}
    # cat/a was skipped (not re-sent) -> keeps its ORIGINAL response.
    assert by_id["cat/a"].response_text == "ORIGINAL"
    # cat/b (ERROR) and cat/c (missing) were executed now and scored (benign "NEW" -> PASS).
    assert by_id["cat/b"].verdict == Verdict.PASS
    assert by_id["cat/b"].response_text == "NEW"
    assert by_id["cat/c"].verdict == Verdict.PASS
    # Only the two pending attacks were sent.
    assert len(runner.adapter.requests) == 2

    # On-disk file is valid JSON and matches.
    final = RunRecord.from_json(path.read_text(encoding="utf-8"))
    assert final.status == RunStatus.COMPLETED
    assert len(final.attempts) == 3
