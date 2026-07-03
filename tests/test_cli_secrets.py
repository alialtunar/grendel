"""Phase 18 M3: gitignored local secrets (load/merge/save) + the API-keys menu."""

from __future__ import annotations

import os
from pathlib import Path

from typer.testing import CliRunner

from grendel.cli import app
from grendel.errors import ConfigError
from grendel.secrets import load_local_secrets, merge_secrets_into_env, save_local_secret

runner = CliRunner()


# --- pure secrets helpers ---------------------------------------------------------------------
def test_save_and_load_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "grendel.local.yaml"
    save_local_secret("OPENAI_API_KEY", "sk-abc123", path)
    save_local_secret("ANTHROPIC_API_KEY", "sk-ant-9", path)  # preserves the first
    loaded = load_local_secrets(path)
    assert loaded == {"OPENAI_API_KEY": "sk-abc123", "ANTHROPIC_API_KEY": "sk-ant-9"}


def test_merge_only_sets_unset_vars() -> None:
    env = {"OPENAI_API_KEY": "real-env-value"}
    merge_secrets_into_env({"OPENAI_API_KEY": "from-file", "NEW_KEY": "v"}, env)
    assert env["OPENAI_API_KEY"] == "real-env-value"  # a real env var always wins
    assert env["NEW_KEY"] == "v"


def test_missing_file_is_empty(tmp_path: Path) -> None:
    assert load_local_secrets(tmp_path / "nope.yaml") == {}


def test_malformed_secrets_file_raises_configerror(tmp_path: Path) -> None:
    # non-mapping root
    p1 = tmp_path / "a.yaml"
    p1.write_text("- just\n- a list\n", encoding="utf-8")
    try:
        load_local_secrets(p1)
        raise AssertionError("expected ConfigError")
    except ConfigError:
        pass
    # unknown top-level key (extra=forbid)
    p2 = tmp_path / "b.yaml"
    p2.write_text("secrets:\n  K: v\nbogus: 1\n", encoding="utf-8")
    try:
        load_local_secrets(p2)
        raise AssertionError("expected ConfigError")
    except ConfigError:
        pass


# --- startup merge (env isolation) ------------------------------------------------------------
def test_startup_merges_local_secrets_into_env(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    # Isolate os.environ: the CLI merge writes to it directly; a copy is restored after the test.
    monkeypatch.setattr(os, "environ", os.environ.copy())
    os.environ.pop("GRENDEL_NO_LOCAL_SECRETS", None)
    os.environ.pop("ZZ_TEST_KEY", None)
    (tmp_path / "grendel.local.yaml").write_text(
        "secrets:\n  ZZ_TEST_KEY: merged-value\n", encoding="utf-8"
    )
    # doctor runs through main() (which merges) — the key must be visible to the process now.
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0, result.output
    assert os.environ.get("ZZ_TEST_KEY") == "merged-value"


# --- API-keys menu ----------------------------------------------------------------------------
def test_api_keys_menu_save_masks_and_gitignores(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    # Isolate os.environ (the menu save does os.environ.setdefault) — restored after the test.
    monkeypatch.setattr(os, "environ", os.environ.copy())
    os.environ["GRENDEL_FORCE_MENU"] = "1"
    secret = "sk-supersecretvalue-999"
    # k -> api keys, s -> save, var name, value, b -> back, s -> save & quit (writes grendel.yaml)
    script = f"k\ns\nOPENAI_API_KEY\n{secret}\nb\ns\n"
    result = runner.invoke(app, [], input=script)
    assert result.exit_code == 0, result.output
    # saved to the gitignored local file, NOT to grendel.yaml, and never echoed in full
    assert secret not in result.output
    assert (tmp_path / "grendel.local.yaml").is_file()
    assert load_local_secrets(tmp_path / "grendel.local.yaml")["OPENAI_API_KEY"] == secret
    if (tmp_path / "grendel.yaml").is_file():
        assert secret not in (tmp_path / "grendel.yaml").read_text(encoding="utf-8")


def test_api_keys_menu_shows_status(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GRENDEL_FORCE_MENU", "1")
    result = runner.invoke(app, [], input="k\nb\nq\n")
    assert result.exit_code == 0, result.output
    assert "OPENAI_API_KEY" in result.output and "api keys" in result.output.lower()
