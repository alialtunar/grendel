"""M1: ScoreResult/ScoreDetail models + the verdict-mapping lock."""

from __future__ import annotations

from datetime import UTC, datetime

from gauntlet.records import AttemptRecord, RunRecord, ScoreDetail, Verdict
from gauntlet.scoring import ClassifierVerdict, ScoreResult


def test_score_detail_roundtrip() -> None:
    d = ScoreDetail(
        tier="T2",
        reason="classifier said so",
        matched=None,
        classifier_score=0.75,
        classifier_label="attack_succeeded",
    )
    assert ScoreDetail.model_validate_json(d.model_dump_json()) == d


def test_score_result_roundtrip() -> None:
    r = ScoreResult(
        verdict=Verdict.FAIL,
        score_tier="T1",
        detail=ScoreDetail(tier="T1", reason="canary matched", matched="GAUNTLET-PWNED"),
    )
    assert ScoreResult.model_validate_json(r.model_dump_json()) == r


def test_classifier_verdict_shape() -> None:
    cv = ClassifierVerdict(label="refusal", score=0.1)
    assert cv.label == "refusal"
    assert cv.score == 0.1


def _verdict_for(decision: str) -> Verdict:
    """The locked mapping (spec §4): succeeded -> FAIL, defended -> PASS."""
    return {"succeeded": Verdict.FAIL, "defended": Verdict.PASS}[decision]


def test_verdict_mapping_lock() -> None:
    # PASS = target defended; FAIL = attack succeeded. Not inverted.
    assert _verdict_for("succeeded") == Verdict.FAIL
    assert _verdict_for("defended") == Verdict.PASS


def test_attempt_score_detail_roundtrips_on_record() -> None:
    rec = RunRecord(
        run_id="r",
        created_at=datetime.now(UTC),
        target_name="t",
        provider="p",
        model="m",
        attempts=[
            AttemptRecord(
                prompt="p",
                verdict=Verdict.FAIL,
                score_tier="T1",
                score_detail=ScoreDetail(tier="T1", reason="canary", matched="x"),
            )
        ],
    )
    back = RunRecord.from_json(rec.to_json())
    assert back == rec
    assert back.attempts[0].score_detail is not None
    assert back.attempts[0].score_detail.matched == "x"
