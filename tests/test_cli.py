"""Tests for the Typer CLI."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from gauntlet.cli import app
from gauntlet.records import AttemptRecord, RunRecord, Verdict

runner = CliRunner()

EXAMPLE = str(Path(__file__).resolve().parents[1] / "examples" / "gauntlet.example.yaml")


def test_help() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "run" in result.output
    assert "list" in result.output
    assert "report" in result.output


def test_subcommand_help() -> None:
    for cmd in ("run", "list", "report"):
        result = runner.invoke(app, [cmd, "--help"])
        assert result.exit_code == 0


def test_list_providers() -> None:
    result = runner.invoke(app, ["-c", EXAMPLE, "list", "--providers"])
    assert result.exit_code == 0
    for preset in ("openai", "anthropic", "openrouter", "ollama", "openai-compatible"):
        assert preset in result.output
    assert "my-local" in result.output  # custom provider from example config


def test_run_dry_run_offline(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = runner.invoke(app, ["-c", EXAMPLE, "run", "--target", "gpt", "--dry-run"])
    assert result.exit_code == 0
    assert "openai" in result.output
    assert "gpt-4o-mini" in result.output
    assert "not sent" in result.output


def test_invalid_config_exit_code_2(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("targets:\n  t:\n    provider: nope\n    model: m\n", encoding="utf-8")
    result = runner.invoke(app, ["-c", str(bad), "list"])
    assert result.exit_code == 2


def test_report_summary(tmp_path: Path) -> None:
    rec = RunRecord(
        run_id="abc123",
        created_at=datetime.now(UTC),
        target_name="gpt",
        provider="openai",
        model="gpt-4o-mini",
        attempts=[AttemptRecord(prompt="p", verdict=Verdict.FAIL)],
    )
    path = tmp_path / "run.json"
    path.write_text(rec.to_json(), encoding="utf-8")
    result = runner.invoke(app, ["report", "--run", str(path)])
    assert result.exit_code == 0
    assert "abc123" in result.output
    assert "100.00%" in result.output


def test_report_missing_file() -> None:
    result = runner.invoke(app, ["report", "--run", "nope.json"])
    assert result.exit_code == 2
