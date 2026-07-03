"""M1: ASR excludes controls; utility_under_attack math; no spurious 'control' category."""

from __future__ import annotations

from datetime import UTC, datetime

from grendel.records import AttemptRecord, RunRecord, Verdict


def _rec(attempts: list[AttemptRecord]) -> RunRecord:
    return RunRecord(
        run_id="r",
        created_at=datetime.now(UTC),
        target_name="t",
        provider="p",
        model="m",
        attempts=attempts,
    )


def _attacks() -> list[AttemptRecord]:
    return [
        AttemptRecord(prompt="a", category="inj", verdict=Verdict.FAIL),
        AttemptRecord(prompt="b", category="inj", verdict=Verdict.PASS),
        AttemptRecord(prompt="c", category="jail", verdict=Verdict.FAIL),
    ]


def _controls() -> list[AttemptRecord]:
    return [
        AttemptRecord(prompt="x", category="control", verdict=Verdict.PASS, is_control=True),
        AttemptRecord(prompt="y", category="control", verdict=Verdict.PASS, is_control=True),
        AttemptRecord(prompt="z", category="control", verdict=Verdict.FAIL, is_control=True),
        AttemptRecord(prompt="w", category="control", verdict=Verdict.ERROR, is_control=True),
    ]


def test_asr_identical_with_or_without_controls() -> None:
    without = _rec(_attacks())
    with_controls = _rec(_attacks() + _controls())
    assert without.asr == with_controls.asr == 2 / 3
    a = without.metrics_summary()["overall_asr"]
    b = with_controls.metrics_summary()["overall_asr"]
    assert a == b


def test_utility_math() -> None:
    rec = _rec(_attacks() + _controls())
    # 2 answered / 3 scored (PASS+FAIL); ERROR control excluded from denominator.
    assert rec.utility_under_attack == 2 / 3
    m = rec.metrics_summary()
    assert m["utility_under_attack"] == 2 / 3
    assert m["controls"] == {"total": 4, "answered": 2, "refused": 1, "errored": 1}


def test_zero_controls_utility_is_none() -> None:
    rec = _rec(_attacks())
    assert rec.utility_under_attack is None
    assert rec.metrics_summary()["utility_under_attack"] is None
    assert rec.metrics_summary()["controls"]["total"] == 0


def test_control_never_a_category() -> None:
    rec = _rec(_attacks() + _controls())
    assert "control" not in rec.metrics_summary()["by_category"]
    assert "control" not in rec.asr_by_category()


def test_attack_side_counts_exclude_controls() -> None:
    rec = _rec(_attacks() + _controls())
    m = rec.metrics_summary()
    assert m["total"] == 3  # attacks only
    assert m["scored"] == 3
    assert m["succeeded"] == 2
    assert m["defended"] == 1
