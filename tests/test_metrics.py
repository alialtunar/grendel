"""M4: asr (scored-only) + asr_by_category + metrics_summary."""

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


def _mixed() -> RunRecord:
    return _rec(
        [
            AttemptRecord(prompt="a", category="inj", verdict=Verdict.FAIL),
            AttemptRecord(prompt="b", category="inj", verdict=Verdict.FAIL),
            AttemptRecord(prompt="c", category="inj", verdict=Verdict.PASS),
            AttemptRecord(prompt="d", category="jail", verdict=Verdict.PASS),
            AttemptRecord(prompt="e", category="jail", verdict=Verdict.ERROR),
            AttemptRecord(prompt="f", category="skip", verdict=Verdict.SKIPPED),
            AttemptRecord(prompt="g", category=None, verdict=Verdict.FAIL),
        ]
    )


def test_asr_excludes_skipped_and_error() -> None:
    # 3 FAIL / 5 scored (PASS+FAIL); ERROR + SKIPPED excluded.
    assert _mixed().asr == 3 / 5


def test_asr_by_category() -> None:
    by = _mixed().asr_by_category()
    assert by["inj"] == 2 / 3
    assert by["jail"] == 0.0  # 1 PASS scored, 0 succeeded
    assert by["skip"] == 0.0  # 0 scored -> 0.0
    assert by["uncategorized"] == 1.0  # Fix #8: category=None bucket


def test_metrics_summary_counts() -> None:
    m = _mixed().metrics_summary()
    assert m["overall_asr"] == 3 / 5
    assert m["scored"] == 5
    assert m["succeeded"] == 3
    assert m["defended"] == 2
    assert m["errored"] == 1
    assert m["skipped"] == 1
    assert m["total"] == 7
    assert m["by_category"]["inj"] == {"asr": 2 / 3, "scored": 3, "succeeded": 2}
    assert m["by_category"]["skip"] == {"asr": 0.0, "scored": 0, "succeeded": 0}
    assert m["by_category"]["uncategorized"] == {"asr": 1.0, "scored": 1, "succeeded": 1}


def test_empty_and_all_skipped_are_zero() -> None:
    assert _rec([]).asr == 0.0
    assert _rec([]).metrics_summary()["overall_asr"] == 0.0
    allskip = _rec(
        [
            AttemptRecord(prompt="a", verdict=Verdict.SKIPPED),
            AttemptRecord(prompt="b", verdict=Verdict.SKIPPED),
        ]
    )
    assert allskip.asr == 0.0
    m = allskip.metrics_summary()
    assert m["overall_asr"] == 0.0
    assert m["scored"] == 0
    assert m["skipped"] == 2
