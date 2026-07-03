"""M2: the `grendel diff` CLI surface (text/json/md, --out, missing file -> exit 2)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from grendel.cli import app
from grendel.records import AttemptRecord, RunRecord, Verdict

runner = CliRunner()


def _write(tmp_path: Path, run_id: str, verdict: Verdict) -> Path:
    rec = RunRecord(
        run_id=run_id,
        created_at=datetime.now(UTC),
        target_name="gpt",
        provider="openai",
        model="gpt-4o-mini",
        attempts=[
            AttemptRecord(
                attack_id="inj/x",
                category="inj",
                owasp="LLM01",
                atlas="AML.T0051",
                prompt="p",
                verdict=verdict,
            )
        ],
    )
    path = tmp_path / f"{run_id}.json"
    path.write_text(rec.to_json(), encoding="utf-8")
    return path


def test_diff_text(tmp_path: Path) -> None:
    a = _write(tmp_path, "a", Verdict.PASS)
    b = _write(tmp_path, "b", Verdict.FAIL)
    result = runner.invoke(app, ["diff", str(a), str(b), "--format", "text"])
    assert result.exit_code == 0, result.output
    assert "overall ASR" in result.output
    assert "newly failing: inj/x" in result.output


def test_diff_json(tmp_path: Path) -> None:
    a = _write(tmp_path, "a", Verdict.PASS)
    b = _write(tmp_path, "b", Verdict.FAIL)
    result = runner.invoke(app, ["diff", str(a), str(b), "--format", "json"])
    assert result.exit_code == 0, result.output
    obj = json.loads(result.output)
    assert obj["newly_failing"] == ["inj/x"]
    assert obj["overall_asr_delta"] == 1.0


def test_diff_md_to_out(tmp_path: Path) -> None:
    a = _write(tmp_path, "a", Verdict.PASS)
    b = _write(tmp_path, "b", Verdict.FAIL)
    out = tmp_path / "diff.md"
    result = runner.invoke(app, ["diff", str(a), str(b), "--format", "md", "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert out.exists()
    assert "# Score diff" in out.read_text(encoding="utf-8")


def test_diff_missing_file_exit_2(tmp_path: Path) -> None:
    a = _write(tmp_path, "a", Verdict.PASS)
    result = runner.invoke(app, ["diff", str(a), str(tmp_path / "nope.json")])
    assert result.exit_code == 2


def test_diff_bad_format_exit_2(tmp_path: Path) -> None:
    a = _write(tmp_path, "a", Verdict.PASS)
    b = _write(tmp_path, "b", Verdict.FAIL)
    result = runner.invoke(app, ["diff", str(a), str(b), "--format", "xml"])
    assert result.exit_code == 2
