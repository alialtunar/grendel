"""M5: CLI ``run --tui`` wiring — real engine drive (fake headless app), dry-run guard."""

from __future__ import annotations

import asyncio
from pathlib import Path

from typer.testing import CliRunner

import gauntlet.cli as cli
import gauntlet.tui.app as appmod
from fakes import FakeAdapter, make_attack
from gauntlet.cli import app
from gauntlet.records import RunRecord, RunStatus, Verdict

runner = CliRunner()

EXAMPLE = str(Path(__file__).resolve().parents[1] / "examples" / "gauntlet.example.yaml")


def _patch_packs(monkeypatch, attacks):
    monkeypatch.setattr(cli, "load_packs", lambda *a, **k: list(attacks))


def _patch_target(monkeypatch, adapter):
    monkeypatch.setattr(cli, "build_target", lambda *a, **k: adapter)


class FakeApp:
    """Headless stand-in for ScoreboardApp: runs the REAL engine synchronously (fix #7).

    This exercises the actual wiring (runner executes, record persists, adapter closes) so
    the test can assert the durable artifact + summary — no terminal, no monkeypatched run.
    """

    def __init__(self, attacks, record, *, target_name, engine) -> None:
        self.engine = engine

    def run(self) -> None:
        asyncio.run(self.engine(lambda attempt: None))


def test_tui_dry_run_exits_2(monkeypatch) -> None:
    attacks = [make_attack("cat/a")]
    _patch_packs(monkeypatch, attacks)
    _patch_target(monkeypatch, FakeAdapter())
    result = runner.invoke(app, ["-c", EXAMPLE, "run", "--target", "gpt", "--tui", "--dry-run"])
    assert result.exit_code == 2
    assert "incompatible" in result.output


def test_tui_runs_engine_persists_and_summarizes(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(appmod, "ScoreboardApp", FakeApp)
    attacks = [make_attack("cat/a"), make_attack("cat/b")]
    adapter = FakeAdapter()
    _patch_packs(monkeypatch, attacks)
    _patch_target(monkeypatch, adapter)

    out = tmp_path / "rec.json"
    result = runner.invoke(
        app, ["-c", EXAMPLE, "run", "--target", "gpt", "--tui", "--out", str(out)]
    )
    assert result.exit_code == 0, result.output
    # Summary line echoed on exit (both benign "ok" responses -> PASS/defended).
    assert "defended=2" in result.output
    assert "asr=0.00%" in result.output
    # The engine drove the real runner: adapter closed in finally, record persisted.
    assert adapter.closed is True
    assert len(adapter.requests) == 2

    record = RunRecord.from_json(out.read_text(encoding="utf-8"))
    assert record.status == RunStatus.COMPLETED
    assert sorted(a.attack_id for a in record.attempts) == ["cat/a", "cat/b"]
    assert all(a.verdict == Verdict.PASS for a in record.attempts)
