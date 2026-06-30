"""M5: runner awaits score_async + runs controls; injected FakeJudge, end to end."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fakes import FakeAdapter, make_attack
from gauntlet.config import JudgeConfig, RunOptions
from gauntlet.controls import BenignControl
from gauntlet.judge import FakeJudge
from gauntlet.records import RunRecord, RunStatus, Verdict
from gauntlet.scoring import ClassifierVerdict, Scorer


def _record() -> RunRecord:
    return RunRecord(
        run_id="run-judge",
        created_at=datetime.now(UTC),
        target_name="t",
        provider="fake",
        model="fake-model",
    )


def _opts(tmp_path: Path) -> RunOptions:
    return RunOptions(output_dir=tmp_path)


class StubClassifier:
    def __init__(self, score: float) -> None:
        self._score = score

    def classify(self, text: str) -> ClassifierVerdict:
        return ClassifierVerdict(label="attack_succeeded", score=self._score)


def _controls() -> list[BenignControl]:
    return [
        BenignControl(id="control/a", name="A", license="MIT", prompt="Summarize the water cycle."),
        BenignControl(id="control/b", name="B", license="MIT", prompt="Explain photosynthesis."),
    ]


async def test_controls_recorded_and_scored(tmp_path: Path) -> None:
    adapter = FakeAdapter(text="here is a helpful answer")
    record = await Runner_run(adapter, tmp_path, [make_attack("cat/a")], controls=_controls())
    controls = [a for a in record.attempts if a.is_control]
    assert {c.attack_id for c in controls} == {"control/a", "control/b"}
    assert all(c.is_control and c.category == "control" for c in controls)
    assert all(c.verdict == Verdict.PASS and c.score_tier == "control" for c in controls)
    # attacks remain non-control
    attacks = [a for a in record.attempts if not a.is_control]
    assert all(not a.is_control for a in attacks)
    assert record.status == RunStatus.COMPLETED


async def test_contested_attack_escalates_to_t3(tmp_path: Path) -> None:
    adapter = FakeAdapter(text="a neutral ambiguous reply")
    scorer = Scorer(
        classifier=StubClassifier(0.5),
        judge=FakeJudge(["attack_succeeded", "attack_succeeded", "defended"]),
        judge_config=JudgeConfig(enabled=True, target="judge-tgt"),
    )
    record = await Runner_run(
        adapter, tmp_path, [make_attack("cat/a", payload="do bad")], scorer=scorer
    )
    att = next(a for a in record.attempts if a.attack_id == "cat/a")
    assert att.score_tier == "T3"
    assert att.verdict == Verdict.FAIL
    assert att.score_detail.judge_votes == {"attack_succeeded": 2, "defended": 1}


async def test_judge_disabled_matches_phase5(tmp_path: Path) -> None:
    adapter = FakeAdapter(text="I'm sorry, but I can't help with that.")
    record = await Runner_run(adapter, tmp_path, [make_attack("cat/a")])
    att = record.attempts[0]
    assert att.verdict == Verdict.PASS
    assert att.score_tier == "T1"  # no T3 when judge disabled


# small helper to reduce Runner boilerplate
async def Runner_run(adapter, tmp_path, attacks, *, controls=(), scorer=None):
    from gauntlet.runner import Runner

    return await Runner(adapter, _opts(tmp_path), scorer=scorer).run(
        attacks, _record(), controls=controls
    )
