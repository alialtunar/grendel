"""Phase 17: cwd ./grendel.yaml auto-discovery (with the env/flag escape hatches)."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from grendel.cli import app

runner = CliRunner()


def _seed_cwd(tmp_path: Path) -> None:
    """Write a grendel.yaml + a one-pack user catalog dir in tmp_path."""
    pack_dir = tmp_path / "extra"
    (pack_dir / "jailbreak").mkdir(parents=True)
    (pack_dir / "jailbreak" / "auto-x.yaml").write_text(
        "id: jailbreak/auto-x\n"
        "name: auto discovered\n"
        "category: jailbreak\n"
        "owasp: LLM01\n"
        "atlas: AML.T0054\n"
        "surface: prompt\n"
        "severity: medium\n"
        "license: Apache-2.0\n"
        "version: 1\n"
        "payload: hello from the auto-discovered catalog\n"
        "success_when:\n"
        "  type: classifier\n"
        "  classifier: lexical\n"
        "  label: attack_succeeded\n"
        "  threshold: 0.5\n",
        encoding="utf-8",
    )
    (tmp_path / "grendel.yaml").write_text(
        "catalog:\n  pack_dirs:\n    - extra\n", encoding="utf-8"
    )


def test_autoloads_cwd_config(tmp_path, monkeypatch) -> None:
    _seed_cwd(tmp_path)
    monkeypatch.delenv("GRENDEL_NO_AUTOCONFIG", raising=False)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["list", "--packs"])
    assert result.exit_code == 0, result.output
    assert "jailbreak/auto-x" in result.output
    assert "using ./grendel.yaml" in result.output


def test_env_flag_suppresses_autoload(tmp_path, monkeypatch) -> None:
    _seed_cwd(tmp_path)
    monkeypatch.setenv("GRENDEL_NO_AUTOCONFIG", "1")
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["list", "--packs"])
    assert result.exit_code == 0, result.output
    assert "jailbreak/auto-x" not in result.output


def test_no_config_flag_suppresses_autoload(tmp_path, monkeypatch) -> None:
    _seed_cwd(tmp_path)
    monkeypatch.delenv("GRENDEL_NO_AUTOCONFIG", raising=False)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["--no-config", "list", "--packs"])
    assert result.exit_code == 0, result.output
    assert "jailbreak/auto-x" not in result.output
