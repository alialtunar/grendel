"""Phase 18 M1: the interactive home menu (bare `grendel` on a TTY).

Offline: bare `grendel` under CliRunner has a non-TTY stdin, so with GRENDEL_FORCE_MENU set it
enters the LETTER home menu (the arrow-key questionary path stays offline-untestable). The banner
path (default, no force) and the --no-menu escape hatch are asserted too.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

import grendel.cli as cli
from fakes import FakeAdapter, make_attack
from grendel.cli import app
from grendel.config import load_config

runner = CliRunner()

FIXTURE = str(Path(__file__).resolve().parent / "fixtures" / "garak")


def _menu(monkeypatch, tmp_path, script: str):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GRENDEL_FORCE_MENU", "1")
    return runner.invoke(app, [], input=script)


# --- banner vs menu gating --------------------------------------------------------------------
def test_bare_grendel_non_tty_still_prints_banner(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GRENDEL_FORCE_MENU", raising=False)
    result = runner.invoke(app, [])  # CliRunner => non-TTY => banner, unchanged
    assert result.exit_code == 0
    assert "Commands:" in result.output and "defensive use only" in result.output


def test_no_menu_flag_forces_banner_even_when_menu_forced(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GRENDEL_FORCE_MENU", "1")
    result = runner.invoke(app, ["--no-menu"])
    assert result.exit_code == 0
    assert "Commands:" in result.output  # banner, not the menu


# --- home-menu navigation (letter fallback) ---------------------------------------------------
def test_home_menu_quit_writes_nothing(tmp_path, monkeypatch) -> None:
    result = _menu(monkeypatch, tmp_path, "q\n")
    assert result.exit_code == 0, result.output
    assert "no changes saved" in result.output
    assert not (tmp_path / "grendel.yaml").exists()


def test_home_menu_shows_grendel_logo(tmp_path, monkeypatch) -> None:
    result = _menu(monkeypatch, tmp_path, "q\n")
    assert result.exit_code == 0, result.output
    assert "█" in result.output  # the GRENDEL block-art wordmark at the top of the menu


def test_render_welcome_orients_the_newcomer() -> None:
    from grendel.banner import render_welcome

    out = render_welcome(unicode=True)
    assert "New here?" in out and "Get started:" in out
    assert "add a target" in out and "(targets)" in out  # step 1
    assert "fire attacks" in out and "(run)" in out  # step 2
    assert "read results" in out and "doctor" in out  # step 3 + nudge
    ascii_out = render_welcome(unicode=False)  # cp1254-safe: no em-dash / dot / wolf
    for fancy in ("—", "·", "🐺"):
        assert fancy not in ascii_out


def test_home_menu_welcome_shown_when_no_targets(tmp_path, monkeypatch) -> None:
    result = _menu(monkeypatch, tmp_path, "q\n")  # empty config → fresh user
    assert result.exit_code == 0, result.output
    assert "Get started:" in result.output and "add a target" in result.output


def test_render_concepts_explains_the_jargon() -> None:
    from grendel.banner import render_concepts

    out = render_concepts(unicode=True)
    # every core term a newcomer meets is defined in the app's own explainer
    for term in ("target", "provider", "api key", "pack", "ASR", "got through", "defended"):
        assert term in out
    ascii_out = render_concepts(unicode=False)  # cp1254-safe: no fancy glyphs
    for fancy in ("—", "·", "🐺", "→"):
        assert fancy not in ascii_out


def test_home_menu_learn_screen(tmp_path, monkeypatch) -> None:
    # ? -> learn (the concepts explainer prints), then q
    result = _menu(monkeypatch, tmp_path, "?\nq\n")
    assert result.exit_code == 0, result.output
    assert "What is Grendel?" in result.output and "Attack Success Rate" in result.output


def test_home_menu_guided_setup_offered_only_when_no_targets(tmp_path, monkeypatch) -> None:
    # fresh user sees the guided-setup entry...
    fresh = _menu(monkeypatch, tmp_path, "q\n")
    assert "guided setup" in fresh.output
    # ...but a configured user does not (it's a first-run affordance)
    (tmp_path / "grendel.yaml").write_text(
        "targets:\n  gpt:\n    type: http\n    provider: openai\n    model: gpt-4o-mini\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("GRENDEL_NO_AUTOCONFIG", raising=False)
    configured = _menu(monkeypatch, tmp_path, "q\n")
    assert "guided setup" not in configured.output


def test_home_menu_guided_setup_runs_the_flow(tmp_path, monkeypatch) -> None:
    # 1 -> guided setup prints the intro then enters the run flow (provider+model, decline), then q
    monkeypatch.setattr(cli, "_load_attacks", lambda *a, **k: [make_attack("jailbreak/a")])
    result = _menu(monkeypatch, tmp_path, "1\n\ngpt-4o-mini\nn\nq\n")
    assert result.exit_code == 0, result.output
    assert "Guided setup" in result.output  # the plain-language intro
    assert "fire 1 attack(s)" in result.output  # it reached the normal run confirm


def test_home_menu_guided_key_gated_once_targets_exist(tmp_path, monkeypatch) -> None:
    # With a target configured the [1] line is hidden AND typing '1' must not launch guided setup.
    (tmp_path / "grendel.yaml").write_text(
        "targets:\n  gpt:\n    type: http\n    provider: openai\n    model: gpt-4o-mini\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("GRENDEL_NO_AUTOCONFIG", raising=False)
    result = _menu(monkeypatch, tmp_path, "1\nq\n")
    assert result.exit_code == 0, result.output
    assert "unknown option '1'" in result.output  # falls through, not a hidden guided launch
    assert "Guided setup" not in result.output


def test_home_menu_welcome_hidden_once_a_target_exists(tmp_path, monkeypatch) -> None:
    (tmp_path / "grendel.yaml").write_text(
        "targets:\n  gpt:\n    type: http\n    provider: openai\n    model: gpt-4o-mini\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("GRENDEL_NO_AUTOCONFIG", raising=False)  # let ./grendel.yaml load
    result = _menu(monkeypatch, tmp_path, "q\n")
    assert result.exit_code == 0, result.output
    assert "Get started:" not in result.output  # a configured user isn't nagged


def test_home_menu_packs_lists_attacks(tmp_path, monkeypatch) -> None:
    # p -> packs, blank category (all) -> lists bundled attack ids, then q
    result = _menu(monkeypatch, tmp_path, "p\n\nq\n")
    assert result.exit_code == 0, result.output
    assert "attacks · categories:" in result.output
    assert "jailbreak/advbench-" in result.output  # a bundled attack id is listed (first 50)


def test_home_menu_packs_filter_by_category(tmp_path, monkeypatch) -> None:
    result = _menu(monkeypatch, tmp_path, "p\njailbreak\nq\n")
    assert result.exit_code == 0, result.output
    assert "jailbreak/advbench-" in result.output
    assert "prompt-injection/" not in result.output  # filtered out


def test_home_menu_doctor_entry(tmp_path, monkeypatch) -> None:
    result = _menu(monkeypatch, tmp_path, "o\nq\n")
    assert result.exit_code == 0, result.output
    assert "Install" in result.output and "Catalog" in result.output


def test_home_menu_settings_edits_and_saves(tmp_path, monkeypatch) -> None:
    # a -> settings, r -> run, concurrency 7, b -> back, s -> save
    result = _menu(monkeypatch, tmp_path, "a\nr\n\n7\n\n\nb\ns\n")
    assert result.exit_code == 0, result.output
    assert "saved ->" in result.output
    cfg = load_config(tmp_path / "grendel.yaml")
    assert cfg.run.concurrency == 7


def test_home_menu_add_target_and_save(tmp_path, monkeypatch) -> None:
    # t->targets, a->add, name=gpt, intent 1 (hosted), provider default, model default,
    # api_key_env blank, y->confirm, b->back, s->save
    result = _menu(monkeypatch, tmp_path, "t\na\ngpt\n1\n\n\n\ny\nb\ns\n")
    assert result.exit_code == 0, result.output
    assert "this target will: POST" in result.output  # self-explanatory confirmation summary
    cfg = load_config(tmp_path / "grendel.yaml")
    assert "gpt" in cfg.targets


def test_home_menu_add_custom_agent(tmp_path, monkeypatch) -> None:
    # t->targets, a->add, name, intent 2 (agent), how b (custom JSON), base_url, path, body JSON,
    # text_path, model default, y confirm, b back, s save.
    body = '{"message": "{prompt}"}'
    script = (
        "t\na\nmyagent\n2\nb\n"
        f"http://localhost:8080\n/chat\n{body}\nreply\n-\n"
        "y\nb\ns\n"
    )
    result = _menu(monkeypatch, tmp_path, script)
    assert result.exit_code == 0, result.output
    assert "added target 'myagent'" in result.output
    cfg = load_config(tmp_path / "grendel.yaml")
    assert "myagent" in cfg.targets
    assert cfg.targets["myagent"].provider == "myagent"
    assert cfg.providers["myagent"].api_style == "custom"
    assert cfg.providers["myagent"].response.text_path == "reply"


def test_add_custom_agent_helper_rejects_name_collision(tmp_path, monkeypatch) -> None:
    # The pure helper both shells call: a provider-name collision must raise, not clobber.
    from grendel.config import CustomProviderConfig, CustomRequestSpec, CustomResponseSpec
    from grendel.errors import ConfigError

    cfg = load_config(None)
    cfg.providers["taken"] = CustomProviderConfig(
        base_url="http://x",
        api_style="custom",
        request=CustomRequestSpec(body={"m": "{prompt}"}),
        response=CustomResponseSpec(text_path="r"),
    )
    with pytest.raises(ConfigError, match="already exists"):
        cli._add_custom_agent(
            cfg, "taken", base_url="http://y", path="/c", body={"m": "{prompt}"}, text_path="r"
        )


def test_remove_target_cleans_up_paired_custom_provider(tmp_path) -> None:
    # Adding then removing a custom agent must not leave an orphan provider behind (re-add works).
    cfg = load_config(None)
    cfg = cli._add_custom_agent(
        cfg, "ag", base_url="http://x", path="/c", body={"m": "{prompt}"}, text_path="r"
    )
    assert "ag" in cfg.providers and "ag" in cfg.targets
    cli._remove_target(cfg, "ag")
    assert "ag" not in cfg.targets and "ag" not in cfg.providers
    # re-add under the same name now succeeds (no leftover collision)
    cfg = cli._add_custom_agent(
        cfg, "ag", base_url="http://z", path="/d", body={"q": "{prompt}"}, text_path="out"
    )
    assert cfg.providers["ag"].request.path == "/d"


def test_home_menu_run_confirm_cancel(tmp_path, monkeypatch) -> None:
    # No packs/dry-run prompts anymore: run goes straight to a single "fire N?" confirm; decline it.
    monkeypatch.setattr(cli, "_load_attacks", lambda *a, **k: [make_attack("jailbreak/a")])
    # x -> run, provider default openai, model, decline the fire confirm, then q
    result = _menu(monkeypatch, tmp_path, "x\n\ngpt-4o-mini\nn\nq\n")
    assert result.exit_code == 0, result.output
    assert "fire 1 attack(s)" in result.output  # a single confirm, no packs/dry-run steps
    assert "packs (comma" not in result.output
    assert "cancelled" in result.output


def test_home_menu_run_full_writes_record(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(cli, "_load_attacks", lambda *a, **k: [make_attack("jailbreak/a")])
    monkeypatch.setattr(cli, "build_target", lambda *a, **k: FakeAdapter())
    # x -> run, provider+model, fire confirm YES, results browser blank->back, then save & quit
    result = _menu(monkeypatch, tmp_path, "x\n\ngpt-4o-mini\ny\n\ns\n")
    assert result.exit_code == 0, result.output
    assert "next: grendel report" in result.output


def test_home_menu_run_applies_config_scoring(tmp_path, monkeypatch) -> None:
    # Regression: the menu Run path must wire cfg.scoring into the Scorer (was bypassed).
    (tmp_path / "grendel.yaml").write_text(
        "scoring:\n  refusal_markers:\n    - zzz-menu-marker\n", encoding="utf-8"
    )
    monkeypatch.delenv("GRENDEL_NO_AUTOCONFIG", raising=False)  # let ./grendel.yaml be discovered
    monkeypatch.setattr(cli, "_load_attacks", lambda *a, **k: [make_attack("jailbreak/a")])
    monkeypatch.setattr(cli, "build_target", lambda *a, **k: FakeAdapter())
    captured: dict = {}

    async def fake_execute(adapter, options, attacks, record, **kw):
        captured["scorer"] = kw.get("scorer")

    monkeypatch.setattr(cli, "_execute", fake_execute)
    result = _menu(monkeypatch, tmp_path, "x\n\ngpt-4o-mini\ny\n\ns\n")
    assert result.exit_code == 0, result.output
    assert captured["scorer"] is not None  # scorer was passed, not left None
    assert captured["scorer"]._refusal_markers == ("zzz-menu-marker",)


def test_home_menu_run_picks_configured_target(tmp_path, monkeypatch) -> None:
    # A configured target is offered as a numbered pick (no typing a name); [1] selects it.
    (tmp_path / "grendel.yaml").write_text(
        "targets:\n  gpt:\n    type: http\n    provider: openai\n    model: gpt-4o-mini\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("GRENDEL_NO_AUTOCONFIG", raising=False)  # let ./grendel.yaml load
    monkeypatch.setattr(cli, "_load_attacks", lambda *a, **k: [make_attack("jailbreak/a")])
    # x -> run, target picker [1] (the configured gpt), decline the fire confirm, then q
    result = _menu(monkeypatch, tmp_path, "x\n1\nn\nq\n")
    assert result.exit_code == 0, result.output
    assert "which target?" in result.output
    assert "[1] gpt" in result.output
    assert "vs gpt" in result.output  # the fire confirm targets the picked target, not ad-hoc


def test_home_menu_adhoc_run_does_not_leak_cli_target(tmp_path, monkeypatch) -> None:
    # An ad-hoc provider+model run must NOT persist the synthetic 'cli' target into grendel.yaml,
    # and a second ad-hoc run in the same session must not collide.
    monkeypatch.setattr(cli, "_load_attacks", lambda *a, **k: [make_attack("jailbreak/a")])
    monkeypatch.setattr(cli, "build_target", lambda *a, **k: FakeAdapter())
    # run 1 (fire, browser back) -> run 2 (fire, browser back) -> save & quit
    script = "x\n\ngpt-4o-mini\ny\n\nx\n\ngpt-4o-mini\ny\n\ns\n"
    result = _menu(monkeypatch, tmp_path, script)
    assert result.exit_code == 0, result.output
    assert result.output.count("next: grendel report") == 2  # both ad-hoc runs fired, no collision
    cfg = load_config(tmp_path / "grendel.yaml")
    assert "cli" not in cfg.targets  # synthetic target never leaked to disk


def test_home_menu_reports_lists_and_renders(tmp_path, monkeypatch) -> None:
    # A run record under output_dir is listed and its text report is printed (survives the pause).
    from datetime import UTC, datetime

    from grendel.records import AttemptRecord, RunRecord, RunStatus, Verdict

    runs = tmp_path / "runs"
    runs.mkdir()
    rec = RunRecord(
        run_id="rep1",
        created_at=datetime.now(UTC),
        target_name="gpt",
        provider="openai",
        model="gpt-4o-mini",
        status=RunStatus.COMPLETED,
        attempts=[
            AttemptRecord(prompt="a", category="inj", verdict=Verdict.FAIL),
            AttemptRecord(prompt="b", category="inj", verdict=Verdict.PASS),
        ],
    )
    (runs / "rep1.json").write_text(rec.to_json(), encoding="utf-8")
    (tmp_path / "grendel.yaml").write_text("run:\n  output_dir: runs\n", encoding="utf-8")
    monkeypatch.delenv("GRENDEL_NO_AUTOCONFIG", raising=False)  # let ./grendel.yaml load
    # r -> reports, pick [1], results browser blank->back, then q
    result = _menu(monkeypatch, tmp_path, "r\n1\n\nq\n")
    assert result.exit_code == 0, result.output
    assert "which run?" in result.output and "[1] gpt" in result.output
    assert "ASR (overall):" in result.output  # the text report rendered
    assert "full: grendel report --run" in result.output  # the export hint
    assert "got through 1" in result.output and "defended 1" in result.output  # browser summary


def test_attempts_by_outcome_buckets_exclude_controls() -> None:
    from grendel.records import AttemptRecord, RunRecord, Verdict

    rec = RunRecord(
        run_id="r", created_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
        target_name="t", provider="openai", model="m",
        attempts=[
            AttemptRecord(prompt="a", attack_id="jb/hit", category="jb", verdict=Verdict.FAIL),
            AttemptRecord(prompt="b", attack_id="jb/def", category="jb", verdict=Verdict.PASS),
            AttemptRecord(prompt="c", attack_id="jb/err", category="jb", verdict=Verdict.ERROR),
            AttemptRecord(prompt="d", attack_id="ctl", verdict=Verdict.FAIL, is_control=True),
        ],
    )
    b = cli._attempts_by_outcome(rec)
    assert [a.attack_id for a in b["hits"]] == ["jb/hit"]  # control FAIL excluded
    assert [a.attack_id for a in b["defended"]] == ["jb/def"]
    assert [a.attack_id for a in b["errors"]] == ["jb/err"]


def test_home_menu_results_browser_drills_into_a_hit(tmp_path, monkeypatch) -> None:
    # After viewing a run, filter 'h' (got through) -> pick [1] -> see the attempt detail.
    from datetime import UTC, datetime

    from grendel.records import AttemptRecord, RunRecord, RunStatus, ScoreDetail, Verdict

    runs = tmp_path / "runs"
    runs.mkdir()
    rec = RunRecord(
        run_id="rep2", created_at=datetime.now(UTC), status=RunStatus.COMPLETED,
        target_name="gpt", provider="openai", model="gpt-4o-mini",
        attempts=[
            AttemptRecord(
                prompt="do bad", category="jailbreak", attack_id="jailbreak/dan-10",
                verdict=Verdict.FAIL, response_text="Sure, here is the bad thing",
                score_detail=ScoreDetail(tier="T1", reason="canary matched"),
            ),
            AttemptRecord(prompt="ok", category="jailbreak", attack_id="jailbreak/safe",
                          verdict=Verdict.PASS, response_text="I can't help with that"),
        ],
    )
    (runs / "rep2.json").write_text(rec.to_json(), encoding="utf-8")
    (tmp_path / "grendel.yaml").write_text("run:\n  output_dir: runs\n", encoding="utf-8")
    monkeypatch.delenv("GRENDEL_NO_AUTOCONFIG", raising=False)
    # r -> reports, pick [1], filter h (got through), pick [1], (pause), back b, then q
    result = _menu(monkeypatch, tmp_path, "r\n1\nh\n1\nb\nq\n")
    assert result.exit_code == 0, result.output
    assert "[1] jailbreak/dan-10" in result.output  # the hit is listed under the filter
    assert "GOT THROUGH" in result.output or "FAIL" in result.output  # verdict in the detail
    assert "Sure, here is the bad thing" in result.output  # the agent's response is shown
    assert "canary matched" in result.output  # the scorer's reason (why)


def test_home_menu_reports_empty(tmp_path, monkeypatch) -> None:
    # No records → a clear empty-state line, no crash.
    result = _menu(monkeypatch, tmp_path, "r\nq\n")
    assert result.exit_code == 0, result.output
    assert "no run records in" in result.output


def test_home_menu_import_wires_catalog(tmp_path, monkeypatch) -> None:
    # i -> import, out dir default 'catalog', path = FIXTURE, limit blank, then save & quit
    result = _menu(monkeypatch, tmp_path, f"i\n\n{FIXTURE}\n\ns\n")
    assert result.exit_code == 0, result.output
    assert "imported" in result.output and "wired" in result.output
    cfg = load_config(tmp_path / "grendel.yaml")
    assert any(d.name == "catalog" for d in cfg.catalog.pack_dirs)
