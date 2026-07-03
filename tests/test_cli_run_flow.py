"""Phase 20: the guided interactive run flow (model suggestions, add-custom, explained prompts).

Offline convention (same as test_cli_home): CliRunner has a non-TTY stdin, so with
GRENDEL_FORCE_MENU the run flow uses the letter/numbered fallbacks; the arrow-key questionary
paths stay offline-untestable. The shared pure helpers are unit-tested directly.
"""

from __future__ import annotations

from typer.testing import CliRunner

import grendel.cli as cli
from fakes import make_attack
from grendel.config import load_config

runner = CliRunner()


def _menu(monkeypatch, tmp_path, script: str):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GRENDEL_FORCE_MENU", "1")
    return runner.invoke(cli.app, [], input=script)


# --- model suggestions are data, not a closed list --------------------------------------------
def test_preset_models_returns_suggestions() -> None:
    cfg = load_config(None)
    openai_models = cli._preset_models("openai", cfg)
    assert "gpt-4o" in openai_models and "o3-mini" in openai_models and len(openai_models) >= 5
    assert cli._preset_models("does-not-exist", cfg) == []  # unknown -> [], no crash


# --- provider letter picker: add-custom only when explicitly allowed --------------------------
def test_provider_letter_add_custom_gated_by_flag(tmp_path, monkeypatch) -> None:
    cfg = load_config(None)
    # allow_add_custom=True: '0' -> the add-custom sentinel
    monkeypatch.setattr(cli.typer, "prompt", lambda *a, **k: "0")
    assert cli._prompt_provider_letter(cfg, allow_add_custom=True) == cli._ADD_CUSTOM
    # default (no flag): '0' is not a valid index -> returned verbatim as a name, NOT the sentinel
    assert cli._prompt_provider_letter(cfg) == "0"


# --- the run flow no longer asks for packs or dry-run -----------------------------------------
def test_run_flow_no_packs_or_dry_run_prompt(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(cli, "_load_attacks", lambda *a, **k: [make_attack("jailbreak/a")])
    # x -> run (no targets -> ad-hoc), provider default, model, then a single fire confirm; decline
    result = _menu(monkeypatch, tmp_path, "x\n\ngpt-4o-mini\nn\nq\n")
    assert result.exit_code == 0, result.output
    assert "packs (comma" not in result.output  # no packs step
    assert "dry-run (plan only" not in result.output  # no dry-run step
    assert "fire 1 attack(s)" in result.output  # straight to the fire confirm


# --- add a custom agent inline from the run flow ----------------------------------------------
def test_run_flow_add_custom_agent_inline(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(cli, "_load_attacks", lambda *a, **k: [make_attack("jailbreak/a")])
    body = '{"message": "{prompt}"}'
    # x -> run, provider '0' (add custom), name, base_url, path, body, text_path, model label,
    # confirm add; then a single fire confirm (decline, no network) -> save & quit.
    script = (
        "x\n0\nmyagent\n"
        f"http://localhost:8080\n/chat\n{body}\nreply\n-\ny\n"
        "n\ns\n"
    )
    result = _menu(monkeypatch, tmp_path, script)
    assert result.exit_code == 0, result.output
    assert "added target 'myagent'" in result.output
    assert "vs myagent" in result.output  # the fire confirm targets the just-added agent
    # the configured agent PERSISTS to disk (unlike a throwaway ad-hoc hosted model)
    cfg = load_config(tmp_path / "grendel.yaml")
    assert cfg.providers["myagent"].api_style == "custom"
    assert cfg.providers["myagent"].response.text_path == "reply"
    assert "myagent" in cfg.targets


# --- live progress counter --------------------------------------------------------------------
class _FakeVerdict:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeAttempt:
    def __init__(self, name: str) -> None:
        self.verdict = _FakeVerdict(name)


def test_run_progress_off_tty_is_none(monkeypatch) -> None:
    import sys

    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    assert cli._run_progress(5) is None  # pipes/tests get no live counter


def test_run_progress_counts_attempts_and_hits(monkeypatch, capsys) -> None:
    import sys

    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    cb = cli._run_progress(3)
    assert cb is not None
    cb(_FakeAttempt("FAIL"))  # a hit
    cb(_FakeAttempt("PASS"))  # defended
    cb(_FakeAttempt("FAIL"))  # a hit
    out = capsys.readouterr().out
    assert "3/3" in out and "2 hit(s)" in out


def test_run_flow_empty_model_cancels_run(tmp_path, monkeypatch) -> None:
    # Cancelling the model picker (empty model) must abort — never build a model="" target and fire.
    monkeypatch.setattr(cli, "_load_attacks", lambda *a, **k: [make_attack("jailbreak/a")])
    monkeypatch.setattr(cli, "_prompt_model", lambda *a, **k: "")  # simulate Esc / no entry
    # x -> run, provider default openai, model cancelled -> back at menu, quit
    result = _menu(monkeypatch, tmp_path, "x\n\nq\n")
    assert result.exit_code == 0, result.output
    assert "fire 1 attack(s)" not in result.output  # never reached the fire confirm
    assert "next: grendel report" not in result.output  # nothing ran


def test_run_flow_warns_and_defaults_no_when_key_missing(tmp_path, monkeypatch) -> None:
    # A real run needs the provider's key: warn + default the fire confirm to No (blank = cancel).
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(cli, "_load_attacks", lambda *a, **k: [make_attack("jailbreak/a")])
    # x -> run, provider default openai, model, blank confirm -> default No -> cancelled, quit
    result = _menu(monkeypatch, tmp_path, "x\n\ngpt-4o-mini\n\nq\n")
    assert result.exit_code == 0, result.output
    assert "OPENAI_API_KEY is not set" in result.output
    assert "cancelled" in result.output


def test_run_flow_add_custom_declined_adds_nothing(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(cli, "_load_attacks", lambda *a, **k: [make_attack("jailbreak/a")])
    body = '{"message": "{prompt}"}'
    # x -> run, provider '0' (add custom), fields, decline the confirm -> nothing added, then quit
    script = (
        "x\n0\nmyagent\n"
        f"http://localhost:8080\n/chat\n{body}\nreply\n-\nn\n"
        "q\n"
    )
    result = _menu(monkeypatch, tmp_path, script)
    assert result.exit_code == 0, result.output
    assert "cancelled" in result.output
    assert not (tmp_path / "grendel.yaml").exists()  # nothing saved
