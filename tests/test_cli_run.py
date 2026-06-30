"""M5: CLI run wiring — dry-run, full offline pipeline, --pack filter, --resume."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

import gauntlet.cli as cli
from fakes import FakeAdapter, make_attack
from gauntlet.cli import app
from gauntlet.records import RunRecord, RunStatus, Verdict

runner = CliRunner()

EXAMPLE = str(Path(__file__).resolve().parents[1] / "examples" / "gauntlet.example.yaml")


def _patch_packs(monkeypatch, attacks):
    monkeypatch.setattr(cli, "load_packs", lambda *a, **k: list(attacks))


def _patch_target(monkeypatch, adapter):
    monkeypatch.setattr(cli, "build_target", lambda *a, **k: adapter)


def test_dry_run_plan_no_network(monkeypatch) -> None:
    attacks = [make_attack("cat/a"), make_attack("cat/b")]
    _patch_packs(monkeypatch, attacks)
    # build_target with dry_run still returns a real (clientless) adapter; no send happens.
    result = runner.invoke(app, ["-c", EXAMPLE, "run", "--target", "gpt", "--dry-run"])
    assert result.exit_code == 0
    assert "plan: 2 attack(s)" in result.output
    assert "cat/a" in result.output and "cat/b" in result.output
    assert "not sent" in result.output


def test_full_offline_run(monkeypatch, tmp_path: Path) -> None:
    attacks = [make_attack("cat/a"), make_attack("cat/b")]
    adapter = FakeAdapter()
    _patch_packs(monkeypatch, attacks)
    _patch_target(monkeypatch, adapter)

    out = tmp_path / "rec.json"
    result = runner.invoke(app, ["-c", EXAMPLE, "run", "--target", "gpt", "--out", str(out)])
    assert result.exit_code == 0, result.output
    # Phase 4 summary reports real scoring: both benign "ok" responses -> PASS (defended).
    assert "defended=2" in result.output
    assert "asr=0.00%" in result.output
    assert adapter.closed is True

    record = RunRecord.from_json(out.read_text(encoding="utf-8"))
    assert record.status == RunStatus.COMPLETED
    assert sorted(a.attack_id for a in record.attempts) == ["cat/a", "cat/b"]
    assert sorted(record.pack_ids) == ["cat/a", "cat/b"]
    assert all(a.verdict == Verdict.PASS for a in record.attempts)


def test_pack_filter(monkeypatch, tmp_path: Path) -> None:
    attacks = [make_attack("cat/a"), make_attack("cat/b")]
    adapter = FakeAdapter()
    _patch_packs(monkeypatch, attacks)
    _patch_target(monkeypatch, adapter)

    out = tmp_path / "rec.json"
    result = runner.invoke(
        app,
        ["-c", EXAMPLE, "run", "--target", "gpt", "--pack", "cat/a", "--out", str(out)],
    )
    assert result.exit_code == 0, result.output
    record = RunRecord.from_json(out.read_text(encoding="utf-8"))
    assert [a.attack_id for a in record.attempts] == ["cat/a"]
    assert record.pack_ids == ["cat/a"]


def test_unknown_pack_exits_2(monkeypatch) -> None:
    attacks = [make_attack("cat/a")]
    adapter = FakeAdapter()
    _patch_packs(monkeypatch, attacks)
    _patch_target(monkeypatch, adapter)
    result = runner.invoke(
        app, ["-c", EXAMPLE, "run", "--target", "gpt", "--pack", "does-not-exist"]
    )
    assert result.exit_code == 2


def test_resume_runs_only_pack_ids(monkeypatch, tmp_path: Path) -> None:
    # Bundled packs would offer a,b,c; the resumed record only selected a + b.
    attacks = [make_attack("cat/a"), make_attack("cat/b"), make_attack("cat/c")]
    adapter = FakeAdapter()
    _patch_packs(monkeypatch, attacks)
    _patch_target(monkeypatch, adapter)

    # A partial record: cat/a already executed, cat/b errored; pack_ids = [a, b].
    from datetime import UTC, datetime

    from gauntlet.records import AttemptRecord

    record = RunRecord(
        run_id="resumeid",
        created_at=datetime.now(UTC),
        target_name="gpt",
        provider="openai",
        model="gpt-4o-mini",
        pack_ids=["cat/a", "cat/b"],
        attempts=[
            AttemptRecord(attack_id="cat/a", prompt="x", verdict=Verdict.SKIPPED),
            AttemptRecord(attack_id="cat/b", prompt="x", verdict=Verdict.ERROR),
        ],
    )
    path = tmp_path / "resumeid.json"
    path.write_text(record.to_json(), encoding="utf-8")

    result = runner.invoke(app, ["-c", EXAMPLE, "run", "--target", "gpt", "--resume", str(path)])
    assert result.exit_code == 0, result.output

    final = RunRecord.from_json(path.read_text(encoding="utf-8"))
    assert final.status == RunStatus.COMPLETED
    # cat/c was NOT in pack_ids -> never run; no duplicate ids.
    assert sorted(a.attack_id for a in final.attempts) == ["cat/a", "cat/b"]
    # Only cat/b (the ERROR) was re-sent; cat/a skipped.
    assert len(adapter.requests) == 1


def test_run_with_controls_reports_utility(monkeypatch, tmp_path: Path) -> None:
    from gauntlet.controls import BenignControl

    attacks = [make_attack("cat/a")]
    adapter = FakeAdapter(text="here is a helpful answer")
    _patch_packs(monkeypatch, attacks)
    _patch_target(monkeypatch, adapter)
    monkeypatch.setattr(
        cli,
        "load_controls",
        lambda *a, **k: [BenignControl(id="control/x", name="X", license="MIT", prompt="hi")],
    )

    out = tmp_path / "rec.json"
    result = runner.invoke(
        app, ["-c", EXAMPLE, "run", "--target", "gpt", "--controls", "--out", str(out)]
    )
    assert result.exit_code == 0, result.output
    assert "utility=100.00%" in result.output

    record = RunRecord.from_json(out.read_text(encoding="utf-8"))
    controls = [a for a in record.attempts if a.is_control]
    assert len(controls) == 1
    assert controls[0].attack_id == "control/x" and controls[0].verdict == Verdict.PASS
    # ASR still computed over attacks only.
    assert record.metrics_summary()["controls"]["total"] == 1
