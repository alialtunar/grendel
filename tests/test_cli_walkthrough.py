"""Phase 17 (spec §0): a scripted first-run walkthrough a newcomer could follow blind.

Offline + deterministic: the one full `run` is monkeypatched with a FakeAdapter (same seam the
other run tests use). Every step must exit cleanly and print a helpful next step — so the smooth
first-run experience can't silently regress. The interactive `config` step exercises the non-TTY
letter-menu (CliRunner has no PTY), same as the existing config tests.
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

import grendel.cli as cli
from fakes import FakeAdapter, make_attack
from grendel.cli import app

runner = CliRunner()

FIXTURE = str(Path(__file__).resolve().parent / "fixtures" / "garak")


def test_first_run_walkthrough(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GRENDEL_NO_AUTOCONFIG", "1")  # isolate; we drive config explicitly

    # 1. Discover — bare `grendel` greets a newcomer with a next step.
    r = runner.invoke(app, [])
    assert r.exit_code == 0, r.output
    assert "New here?" in r.output and "grendel doctor" in r.output

    # 2. First attack (planned, no network) — the dry run shows what would fire.
    r = runner.invoke(
        app,
        [
            "run",
            "--provider",
            "openai",
            "--model",
            "gpt-4o-mini",
            "--pack",
            "jailbreak",
            "--dry-run",
        ],
    )
    assert r.exit_code == 0, r.output
    assert "plan:" in r.output

    # 3. Configure a named target + wire a catalog dir, then save (letter menu, non-TTY).
    # add: name, intent 1 (hosted), provider default, model=model-x, api_key_env blank, confirm y.
    r = runner.invoke(app, ["config"], input="t\na\ngpt\n1\n\nmodel-x\n\ny\nb\nc\na\nmine\nb\ns\n")
    assert r.exit_code == 0, r.output
    assert "saved ->" in r.output
    assert (tmp_path / "grendel.yaml").is_file()

    # 4. Grow the catalog from a corpus — the success line tells you how to load it.
    out = tmp_path / "catalog"
    r = runner.invoke(app, ["import", "--path", FIXTURE, "--out", str(out)])
    assert r.exit_code == 0, r.output
    assert "load them with:" in r.output

    # 5. Browse packs, filtered — the count line orients you.
    r = runner.invoke(app, ["list", "--packs", "--category", "jailbreak"])
    assert r.exit_code == 0, r.output
    assert "Packs:" in r.output and "category=jailbreak" in r.output

    # 6. Status — doctor tells you where you are and what to do next.
    r = runner.invoke(app, ["-c", "grendel.yaml", "doctor"])
    assert r.exit_code == 0, r.output
    assert "Install" in r.output and "next:" in r.output

    # 7. A real run → a record → a report. Success ends with the report hint.
    monkeypatch.setattr(cli, "_load_attacks", lambda *a, **k: [make_attack("jailbreak/a")])
    monkeypatch.setattr(cli, "build_target", lambda *a, **k: FakeAdapter())
    rec = tmp_path / "rec.json"
    r = runner.invoke(
        app, ["run", "--provider", "openai", "--model", "gpt-4o-mini", "--out", str(rec)]
    )
    assert r.exit_code == 0, r.output
    assert "next: grendel report" in r.output

    r = runner.invoke(app, ["report", "--run", str(rec), "--format", "md"])
    assert r.exit_code == 0, r.output
    assert "# " in r.output  # rendered markdown report
