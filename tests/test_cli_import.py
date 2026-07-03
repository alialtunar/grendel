"""Phase 14 M2: `grendel import` CLI + end-to-end (imported dir usable via --pack-dir)."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from grendel.cli import app

runner = CliRunner()

FIXTURE = str(Path(__file__).resolve().parent / "fixtures" / "garak")


def test_import_cli_writes_packs(tmp_path: Path) -> None:
    out = tmp_path / "cat"
    result = runner.invoke(
        app, ["import", "--source", "garak", "--path", FIXTURE, "--out", str(out)]
    )
    assert result.exit_code == 0, result.output
    assert "imported 5 (seen 6, duplicate 1, license-skipped 0)" in result.output
    assert len(list(out.glob("*/*.yaml"))) == 5


def test_import_cli_dry_run_writes_nothing(tmp_path: Path) -> None:
    out = tmp_path / "cat"
    result = runner.invoke(app, ["import", "--path", FIXTURE, "--out", str(out), "--dry-run"])
    assert result.exit_code == 0, result.output
    assert result.output.startswith("[dry-run] imported 5")
    assert not out.exists() or not list(out.glob("*/*.yaml"))


def test_import_cli_unknown_source_exit_2(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["import", "--source", "nope", "--path", FIXTURE, "--out", str(tmp_path / "c")]
    )
    assert result.exit_code == 2
    assert "unknown source" in result.output


def test_import_cli_missing_path_exit_2(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["import", "--path", str(tmp_path / "missing"), "--out", str(tmp_path / "c")]
    )
    assert result.exit_code == 2
    assert "not found" in result.output


def test_import_cli_conversion_error_exit_2(tmp_path: Path, monkeypatch) -> None:
    # A PackError from the conversion pipeline surfaces as a clean exit 2 (not a traceback).
    import grendel.corpus as corpusmod
    from grendel.errors import PackError

    def boom(*a, **k):
        raise PackError("invalid converted attack from 'x': bad payload")

    monkeypatch.setattr(corpusmod, "import_corpus", boom)
    result = runner.invoke(app, ["import", "--path", FIXTURE, "--out", str(tmp_path / "c")])
    assert result.exit_code == 2
    assert "import error:" in result.output and "invalid converted attack" in result.output


def test_imported_dir_loads_via_pack_dir(tmp_path: Path) -> None:
    out = tmp_path / "cat"
    runner.invoke(app, ["import", "--path", FIXTURE, "--out", str(out)])
    # the imported catalog is a real --pack-dir source for a run
    result = runner.invoke(
        app,
        [
            "run",
            "--provider",
            "openai",
            "--model",
            "m",
            "--pack-dir",
            str(out),
            "--pack",
            "dan",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "dan/dan-" in result.output  # imported dan packs appear in the plan


# --- auto-discovery (omit --path) -------------------------------------------------------------
import pytest  # noqa: E402

from grendel import corpus  # noqa: E402
from grendel.errors import PackError  # noqa: E402


def test_default_source_paths_unknown_source_errors() -> None:
    with pytest.raises(PackError, match="--path is required"):
        corpus.default_source_paths("harmbench")


def test_garak_data_dir_not_installed(monkeypatch) -> None:
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "garak":
            raise ImportError("no garak")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(PackError, match="garak is not installed"):
        corpus.garak_data_dir()


def test_auto_import_from_installed_garak(tmp_path) -> None:
    pytest.importorskip("garak")  # only runs when garak is present; skips otherwise
    out = tmp_path / "cat"
    # Bound the pull with --limit so the suite stays fast (the full import writes ~1500 files);
    # this proves auto-discovery + the write path without importing the whole corpus.
    result = runner.invoke(app, ["import", "--source", "garak", "--out", str(out), "--limit", "3"])
    assert result.exit_code == 0, result.output
    assert "auto-discovered" in result.output
    assert "imported" in result.output
    written = list(out.glob("*/*.yaml"))
    # --limit 3 caps each auto-discovered corpus path; at least one pack, and nowhere near ~1500.
    assert 0 < len(written) <= 3 * len(corpus.GARAK_CURATED)
