"""M5: grendel report prints overall ASR + by-category; json adds the metrics block."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from grendel.cli import app
from grendel.records import AttemptRecord, RunRecord, RunStatus, Verdict

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
            AttemptRecord(
                prompt="a", category="inj", owasp="LLM01", atlas="AML.T0051", verdict=Verdict.FAIL
            ),
            AttemptRecord(
                prompt="b", category="inj", owasp="LLM01", atlas="AML.T0051", verdict=Verdict.PASS
            ),
            AttemptRecord(
                prompt="c", category="jail", owasp="LLM06", atlas="AML.T0054", verdict=Verdict.FAIL
            ),
            AttemptRecord(prompt="d", category="jail", verdict=Verdict.SKIPPED),
        ],
    )
    path = tmp_path / "rep1.json"
    path.write_text(rec.to_json(), encoding="utf-8")
    return path


def test_render_text_is_the_single_source(tmp_path: Path) -> None:
    # The report command's text body now comes from reports.render_text (shared with the menu).
    from grendel import reports
    from grendel.records import RunRecord

    rec = RunRecord.from_json(_record_file(tmp_path).read_text(encoding="utf-8"))
    text = reports.render_text(rec)
    assert "Run rep1" in text
    assert "ASR (overall): 66.67%" in text
    assert "by category:" in text and "by OWASP:" in text and "by ATLAS:" in text


def test_report_text_prints_asr_and_categories(tmp_path: Path) -> None:
    path = _record_file(tmp_path)
    result = runner.invoke(app, ["report", "--run", str(path)])
    assert result.exit_code == 0, result.output
    # Overall: 2 FAIL / 3 scored = 66.67%.
    assert "ASR (overall): 66.67%" in result.output
    assert "by category:" in result.output
    assert "inj:" in result.output
    assert "jail:" in result.output
    # Phase 9: OWASP/ATLAS breakdowns render.
    assert "by OWASP:" in result.output
    assert "LLM01:" in result.output
    assert "by ATLAS:" in result.output
    assert "AML.T0051:" in result.output


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


def test_report_md_prints_and_out_roundtrip(tmp_path: Path) -> None:
    path = _record_file(tmp_path)
    stdout = runner.invoke(app, ["report", "--run", str(path), "--format", "md"])
    assert stdout.exit_code == 0, stdout.output
    assert "# Grendel report" in stdout.output

    out = tmp_path / "rep.md"
    written = runner.invoke(
        app, ["report", "--run", str(path), "--format", "md", "--out", str(out)]
    )
    assert written.exit_code == 0, written.output
    assert "wrote md report ->" in written.output
    # Fix #13: the file content equals the stdout-rendered string (modulo the trailing newline).
    assert out.read_text(encoding="utf-8").rstrip("\n") == stdout.output.rstrip("\n")


def test_report_html_prints(tmp_path: Path) -> None:
    path = _record_file(tmp_path)
    result = runner.invoke(app, ["report", "--run", str(path), "--format", "html"])
    assert result.exit_code == 0, result.output
    assert "<!DOCTYPE html>" in result.output


def test_report_bad_format_exit_2(tmp_path: Path) -> None:
    path = _record_file(tmp_path)
    result = runner.invoke(app, ["report", "--run", str(path), "--format", "xml"])
    assert result.exit_code == 2


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
