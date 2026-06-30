"""M5: gauntlet report prints overall ASR + by-category; json adds the metrics block."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from gauntlet.cli import app
from gauntlet.records import AttemptRecord, RunRecord, RunStatus, Verdict

runner = CliRunner()


def _record_file(tmp_path: Path) -> Path:
    rec = RunRecord(
        run_id="rep1",
        created_at=datetime.now(UTC),
        target_name="gpt",
        provider="openai",
        model="gpt-4o-mini",
        status=RunStatus.COMPLETED,
        attempts=[
            AttemptRecord(prompt="a", category="inj", verdict=Verdict.FAIL),
            AttemptRecord(prompt="b", category="inj", verdict=Verdict.PASS),
            AttemptRecord(prompt="c", category="jail", verdict=Verdict.FAIL),
            AttemptRecord(prompt="d", category="jail", verdict=Verdict.SKIPPED),
        ],
    )
    path = tmp_path / "rep1.json"
    path.write_text(rec.to_json(), encoding="utf-8")
    return path


def test_report_text_prints_asr_and_categories(tmp_path: Path) -> None:
    path = _record_file(tmp_path)
    result = runner.invoke(app, ["report", "--run", str(path)])
    assert result.exit_code == 0, result.output
    # Overall: 2 FAIL / 3 scored = 66.67%.
    assert "ASR (overall): 66.67%" in result.output
    assert "by category:" in result.output
    assert "inj:" in result.output
    assert "jail:" in result.output


def _record_file_with_controls(tmp_path: Path) -> Path:
    rec = RunRecord(
        run_id="rep2",
        created_at=datetime.now(UTC),
        target_name="gpt",
        provider="openai",
        model="gpt-4o-mini",
        status=RunStatus.COMPLETED,
        attempts=[
            AttemptRecord(prompt="a", category="inj", verdict=Verdict.FAIL),
            AttemptRecord(prompt="b", category="inj", verdict=Verdict.PASS),
            AttemptRecord(prompt="c", category="control", verdict=Verdict.PASS, is_control=True),
            AttemptRecord(prompt="d", category="control", verdict=Verdict.FAIL, is_control=True),
        ],
    )
    path = tmp_path / "rep2.json"
    path.write_text(rec.to_json(), encoding="utf-8")
    return path


def test_report_text_prints_utility_when_controls(tmp_path: Path) -> None:
    path = _record_file_with_controls(tmp_path)
    result = runner.invoke(app, ["report", "--run", str(path)])
    assert result.exit_code == 0, result.output
    assert "utility-under-attack: 50.00%" in result.output
    assert "controls: answered 1 / 2" in result.output
    # control is never a category row
    assert "control:" not in result.output


def test_report_text_utility_na_without_controls(tmp_path: Path) -> None:
    path = _record_file(tmp_path)
    result = runner.invoke(app, ["report", "--run", str(path)])
    assert result.exit_code == 0, result.output
    assert "utility-under-attack: n/a" in result.output


def test_report_json_includes_utility(tmp_path: Path) -> None:
    path = _record_file_with_controls(tmp_path)
    result = runner.invoke(app, ["report", "--run", str(path), "--format", "json"])
    obj = json.loads(result.output)
    m = obj["metrics"]
    assert m["utility_under_attack"] == 0.5
    assert m["controls"] == {"total": 2, "answered": 1, "refused": 1, "errored": 0}
    assert "control" not in m["by_category"]


def test_report_json_includes_metrics(tmp_path: Path) -> None:
    path = _record_file(tmp_path)
    result = runner.invoke(app, ["report", "--run", str(path), "--format", "json"])
    assert result.exit_code == 0, result.output
    obj = json.loads(result.output)
    assert obj["asr"] == 2 / 3
    m = obj["metrics"]
    assert m["overall_asr"] == 2 / 3
    assert m["scored"] == 3
    assert m["succeeded"] == 2
    assert m["defended"] == 1
    assert m["skipped"] == 1
    assert m["by_category"]["inj"] == {"asr": 0.5, "scored": 2, "succeeded": 1}
    assert m["by_category"]["jail"] == {"asr": 1.0, "scored": 1, "succeeded": 1}
