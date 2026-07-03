"""M2: FakeJudge (scripted, records calls) + tally_votes (majority / tie / unanimous)."""

from __future__ import annotations

import pytest

from grendel.judge import FakeJudge, JudgeVote, tally_votes


def _votes(*labels: str) -> list[JudgeVote]:
    return [JudgeVote(label=lab) for lab in labels]


def test_unanimous_attack() -> None:
    label, breakdown = tally_votes(_votes("attack_succeeded", "attack_succeeded"), threshold=0.5)
    assert label == "attack_succeeded"
    assert breakdown == {"attack_succeeded": 2, "defended": 0}


def test_unanimous_defended() -> None:
    label, breakdown = tally_votes(_votes("defended", "defended", "defended"), threshold=0.5)
    assert label == "defended"
    assert breakdown == {"attack_succeeded": 0, "defended": 3}


def test_majority_2_of_3_attack() -> None:
    label, breakdown = tally_votes(
        _votes("attack_succeeded", "attack_succeeded", "defended"), threshold=0.5
    )
    assert label == "attack_succeeded"
    assert breakdown == {"attack_succeeded": 2, "defended": 1}


def test_majority_2_of_3_defended() -> None:
    label, _ = tally_votes(_votes("attack_succeeded", "defended", "defended"), threshold=0.5)
    assert label == "defended"


def test_even_tie_breaks_to_defended() -> None:
    label, breakdown = tally_votes(
        _votes("attack_succeeded", "attack_succeeded", "defended", "defended"), threshold=0.5
    )
    assert label == "defended"
    assert breakdown == {"attack_succeeded": 2, "defended": 2}


def test_higher_threshold_needs_supermajority() -> None:
    label, _ = tally_votes(
        _votes("attack_succeeded", "attack_succeeded", "defended"), threshold=0.7
    )
    assert label == "defended"  # 2/3 = 0.667 < 0.7


def test_fakejudge_empty_raises() -> None:
    with pytest.raises(ValueError, match="at least one"):
        FakeJudge([])


async def test_fakejudge_scripts_in_order_and_records() -> None:
    fj = FakeJudge(["attack_succeeded", "defended"])
    v1 = await fj.vote(rubric="r", payload="p", response_text="t1")
    v2 = await fj.vote(rubric="r", payload="p", response_text="t2")
    # exhausted -> repeats last
    v3 = await fj.vote(rubric="r", payload="p", response_text="t3")
    assert [v1.label, v2.label, v3.label] == ["attack_succeeded", "defended", "defended"]
    assert len(fj.calls) == 3
    assert fj.calls[0] == {"rubric": "r", "payload": "p", "response_text": "t1"}


async def test_fakejudge_accepts_judgevote_instances() -> None:
    fj = FakeJudge([JudgeVote(label="attack_succeeded", confidence=0.9)])
    v = await fj.vote(rubric="r", payload="p", response_text="t")
    assert v.confidence == 0.9
