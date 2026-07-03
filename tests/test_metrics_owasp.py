"""M2: by_owasp/by_atlas breakdowns + asr_by_owasp/asr_by_atlas (controls excluded)."""

from __future__ import annotations

from datetime import UTC, datetime

from grendel.records import AttemptRecord, RunRecord, RunStatus, Verdict


def _record() -> RunRecord:
    return RunRecord(
        run_id="m2",
        created_at=datetime.now(UTC),
        target_name="gpt",
        provider="openai",
        model="gpt-4o-mini",
        status=RunStatus.COMPLETED,
        attempts=[
            AttemptRecord(prompt="a", owasp="LLM01", atlas="AML.T0051", verdict=Verdict.FAIL),
            AttemptRecord(prompt="b", owasp="LLM01", atlas="AML.T0051", verdict=Verdict.PASS),
            AttemptRecord(prompt="c", owasp="LLM06", atlas="AML.T0054", verdict=Verdict.PASS),
            # legacy / unmapped attempt
            AttemptRecord(prompt="d", owasp=None, atlas=None, verdict=Verdict.FAIL),
            # a control — must be excluded from both breakdowns
            AttemptRecord(prompt="e", verdict=Verdict.PASS, is_control=True),
            # error attempt — counted as scored=0
            AttemptRecord(prompt="f", owasp="LLM06", atlas="AML.T0054", verdict=Verdict.ERROR),
        ],
    )


def test_by_owasp_breakdown() -> None:
    m = _record().metrics_summary()
    assert m["by_owasp"]["LLM01"] == {"asr": 0.5, "scored": 2, "succeeded": 1}
    assert m["by_owasp"]["LLM06"] == {"asr": 0.0, "scored": 1, "succeeded": 0}
    assert m["by_owasp"]["unmapped"] == {"asr": 1.0, "scored": 1, "succeeded": 1}
    # controls never appear
    assert all(code != "control" for code in m["by_owasp"])


def test_by_atlas_breakdown() -> None:
    m = _record().metrics_summary()
    assert m["by_atlas"]["AML.T0051"] == {"asr": 0.5, "scored": 2, "succeeded": 1}
    assert m["by_atlas"]["AML.T0054"] == {"asr": 0.0, "scored": 1, "succeeded": 0}
    assert m["by_atlas"]["unmapped"] == {"asr": 1.0, "scored": 1, "succeeded": 1}


def test_asr_by_helpers() -> None:
    rec = _record()
    assert rec.asr_by_owasp() == {"LLM01": 0.5, "LLM06": 0.0, "unmapped": 1.0}
    assert rec.asr_by_atlas() == {"AML.T0051": 0.5, "AML.T0054": 0.0, "unmapped": 1.0}


def test_existing_keys_unchanged() -> None:
    m = _record().metrics_summary()
    # additive only — the prior keys are all still present
    for key in (
        "overall_asr",
        "scored",
        "succeeded",
        "defended",
        "errored",
        "skipped",
        "total",
        "by_category",
        "utility_under_attack",
        "controls",
    ):
        assert key in m
    assert "by_owasp" in m and "by_atlas" in m


def test_attempt_record_has_owasp_atlas_default_none() -> None:
    a = AttemptRecord(prompt="x")
    assert a.owasp is None and a.atlas is None
    # round-trips through JSON
    rebuilt = AttemptRecord.model_validate_json(a.model_dump_json())
    assert rebuilt.owasp is None and rebuilt.atlas is None
