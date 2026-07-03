"""M3: AdapterJudge over a FakeAdapter (offline) + reply parsing + pinned sampling."""

from __future__ import annotations

from fakes import FakeAdapter
from grendel.judge import RUBRIC_V1, AdapterJudge


async def _vote(reply: str):
    adapter = FakeAdapter(text=reply)
    judge = AdapterJudge(adapter, RUBRIC_V1, temperature=0.7, max_tokens=256)
    vote = await judge.vote(rubric="leaks the canary", payload="PAY", response_text="RESP")
    return vote, adapter


async def test_attack_succeeded_reply() -> None:
    vote, adapter = await _vote("Reasoning here.\nVERDICT: attack_succeeded")
    assert vote.label == "attack_succeeded"
    # exactly one judge call was sent, with the pinned judge sampling params
    assert len(adapter.requests) == 1
    assert adapter.requests[0].temperature == 0.7
    assert adapter.requests[0].max_tokens == 256
    # rendered prompt carries the criteria/payload/response
    assert "leaks the canary" in adapter.requests[0].prompt
    assert "PAY" in adapter.requests[0].prompt


async def test_defended_reply() -> None:
    vote, _ = await _vote("The model refused.\nVERDICT: defended")
    assert vote.label == "defended"


async def test_unparseable_reply_falls_back_to_defended() -> None:
    vote, _ = await _vote("I have no idea, here is some prose with no verdict line.")
    assert vote.label == "defended"
    assert "unparseable" in (vote.reasoning or "")
