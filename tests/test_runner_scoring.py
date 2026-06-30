"""M5: the runner sets real scoring verdicts on successful sends."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fakes import FakeAdapter, make_attack
from gauntlet.attacks import Attack
from gauntlet.config import RunOptions
from gauntlet.records import RunRecord, RunStatus, Verdict
from gauntlet.runner import Runner


def _record() -> RunRecord:
    return RunRecord(
        run_id="run-score",
        created_at=datetime.now(UTC),
        target_name="t",
        provider="fake",
        model="fake-model",
    )


def _opts(tmp_path: Path) -> RunOptions:
    return RunOptions(output_dir=tmp_path)


async def test_canary_response_is_fail_t1(tmp_path: Path) -> None:
    adapter = FakeAdapter(text="oops, leaked x in the output")
    record = await Runner(adapter, _opts(tmp_path)).run([make_attack("cat/a")], _record())
    assert record.status == RunStatus.COMPLETED
    att = record.attempts[0]
    assert att.verdict == Verdict.FAIL
    assert att.score_tier == "T1"
    assert att.score_detail is not None and att.score_detail.matched == "x"


async def test_refusal_response_is_pass(tmp_path: Path) -> None:
    adapter = FakeAdapter(text="I'm sorry, but I can't help with that.")
    record = await Runner(adapter, _opts(tmp_path)).run([make_attack("cat/a")], _record())
    att = record.attempts[0]
    assert att.verdict == Verdict.PASS
    assert att.score_tier == "T1"


async def test_side_effect_attack_is_skipped(tmp_path: Path) -> None:
    side = Attack(
        id="cat/se",
        name="se",
        category="cat",
        owasp="LLM01",
        atlas="AML.T0051",
        surface="prompt",
        severity="high",
        license="MIT",
        version=1,
        payload="p",
        success_when={"type": "side-effect", "assert": "file deleted"},
    )
    adapter = FakeAdapter(text="anything")
    record = await Runner(adapter, _opts(tmp_path)).run([side], _record())
    assert record.status == RunStatus.COMPLETED
    att = record.attempts[0]
    assert att.verdict == Verdict.SKIPPED
    assert att.score_tier is None
