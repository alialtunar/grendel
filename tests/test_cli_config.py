"""The interactive `grendel config` menu + save_config round-trip (inline, no TUI)."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from grendel.cli import app
from grendel.config import GrendelConfig, ProxyConfig, TargetConfig, load_config, save_config

runner = CliRunner()


def test_save_config_round_trip(tmp_path: Path) -> None:
    cfg = GrendelConfig(
        targets={"gpt": TargetConfig(type="http", provider="openai", model="gpt-4o-mini")},
        proxy=ProxyConfig(host="0.0.0.0", port=9000, routes={"/openai": "openai"}),
    )
    cfg.judge.enabled = True
    path = tmp_path / "grendel.yaml"
    save_config(cfg, path)
    back = load_config(path)
    assert back.model_dump() == cfg.model_dump()


def test_config_interactive_edit_and_save(tmp_path, monkeypatch) -> None:
    # session: edit run (concurrency=9), edit proxy (port=8200 + a route), save.
    monkeypatch.chdir(tmp_path)
    script = "r\n\n9\n\n\np\n\n8200\n/openai=openai\ns\n"
    result = runner.invoke(app, ["config"], input=script)
    assert result.exit_code == 0, result.output
    assert "saved ->" in result.output
    cfg = load_config(tmp_path / "grendel.yaml")
    assert cfg.run.concurrency == 9
    assert cfg.proxy.port == 8200
    assert cfg.proxy.routes == {"/openai": "openai"}


def test_config_quit_without_saving(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["config"], input="q\n")
    assert result.exit_code == 0, result.output
    assert "no changes saved" in result.output
    assert not (tmp_path / "grendel.yaml").exists()


def test_config_bad_int_keeps_current(tmp_path, monkeypatch) -> None:
    # a non-integer concurrency is rejected inline (kept), then saved.
    monkeypatch.chdir(tmp_path)
    script = "r\n\nnotnum\n\n\ns\n"
    result = runner.invoke(app, ["config"], input=script)
    assert result.exit_code == 0, result.output
    assert "keeping" in result.output
    cfg = load_config(tmp_path / "grendel.yaml")
    assert cfg.run.concurrency == 4  # unchanged default


# --- Phase 16: editable targets (letter-menu fallback) + pure helpers -------------------------
from grendel.cli import _add_target, _remove_target  # noqa: E402
from grendel.errors import ConfigError  # noqa: E402


def test_config_add_hosted_model_target(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    # t->targets, a->add, name=gpt, intent 1 (hosted), provider(openai), model, api_key_env,
    # y->confirm, b->back, s->save
    script = "t\na\ngpt\n1\n\n\n\ny\nb\ns\n"
    result = runner.invoke(app, ["config"], input=script)
    assert result.exit_code == 0, result.output
    cfg = load_config(tmp_path / "grendel.yaml")
    assert "gpt" in cfg.targets
    assert cfg.targets["gpt"].provider == "openai"
    assert cfg.targets["gpt"].model == "gpt-4o-mini"


def test_config_add_chat_url_target(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    # intent 2 (an agent) -> how 'a' (OpenAI-compatible chat URL): base_url, model, api_key_env
    script = "t\na\nlocal\n2\na\nhttp://localhost:1234/v1\nmodel-x\n\ny\nb\ns\n"
    result = runner.invoke(app, ["config"], input=script)
    assert result.exit_code == 0, result.output
    assert "POST http://localhost:1234/v1/chat/completions" in result.output
    cfg = load_config(tmp_path / "grendel.yaml")
    assert cfg.targets["local"].provider == "openai-compatible"
    assert cfg.targets["local"].base_url == "http://localhost:1234/v1"
    assert cfg.targets["local"].model == "model-x"


def test_config_add_target_menu_has_no_proxy_option(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    # The add-target menu is now model/agent only; the proxy left it (demoted to indirect).
    script = "t\na\ngpt\n1\n\n\n\ny\nb\ns\n"
    result = runner.invoke(app, ["config"], input=script)
    assert result.exit_code == 0, result.output
    assert "[2] an agent" in result.output
    assert "via proxy" not in result.output


def test_config_add_then_remove_target(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    script = "t\na\ngpt\n1\n\n\n\ny\nr\ngpt\nb\ns\n"
    result = runner.invoke(app, ["config"], input=script)
    assert result.exit_code == 0, result.output
    cfg = load_config(tmp_path / "grendel.yaml")
    assert "gpt" not in cfg.targets


def test_config_add_unknown_provider_errors_inline(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    # intent 1, provider "nope" -> add-time ConfigError, target NOT added, session survives
    script = "t\na\nbad\n1\nnope\n\n\nb\ns\n"
    result = runner.invoke(app, ["config"], input=script)
    assert result.exit_code == 0, result.output
    assert "error" in result.output.lower()
    cfg = load_config(tmp_path / "grendel.yaml")
    assert "bad" not in cfg.targets


def test_config_targets_list_no_mutation(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["config"], input="t\nl\nb\nq\n")
    assert result.exit_code == 0, result.output
    assert "no changes saved" in result.output


def test_add_target_helper_duplicate_and_unknown_provider() -> None:
    base = _add_target(GrendelConfig(), name="a", kind="http", provider="openai", model="m")
    assert "a" in base.targets
    # duplicate name
    try:
        _add_target(base, name="a", kind="http", provider="openai", model="m")
        raise AssertionError("expected ConfigError for duplicate")
    except ConfigError:
        pass
    # unknown provider
    try:
        _add_target(GrendelConfig(), name="b", kind="http", provider="nope", model="m")
        raise AssertionError("expected ConfigError for unknown provider")
    except ConfigError:
        pass


def test_remove_target_helper_clears_judge_reference() -> None:
    cfg = _add_target(GrendelConfig(), name="jt", kind="http", provider="openai", model="m")
    cfg.judge.target = "jt"
    _remove_target(cfg, "jt")
    assert "jt" not in cfg.targets
    assert cfg.judge.target is None
    try:
        _remove_target(cfg, "absent")
        raise AssertionError("expected ConfigError for absent target")
    except ConfigError:
        pass


# --- Phase 17: provider select (letter fallback) + editable catalog pack dirs ------------------
from grendel.cli import _add_pack_dir, _remove_pack_dir  # noqa: E402


def test_config_add_target_picks_provider_by_number(tmp_path, monkeypatch) -> None:
    # intent 1 (hosted), provider chosen as "1" from the numbered valid set (anthropic is #1).
    monkeypatch.chdir(tmp_path)
    script = "t\na\ngpt\n1\n1\nmodel-x\n\ny\nb\ns\n"
    result = runner.invoke(app, ["config"], input=script)
    assert result.exit_code == 0, result.output
    cfg = load_config(tmp_path / "grendel.yaml")
    assert cfg.targets["gpt"].provider == "anthropic"
    assert cfg.targets["gpt"].model == "model-x"


def test_config_add_catalog_pack_dir(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    # add a pack dir, save -> saved YAML lists it (resolved to absolute on load).
    result = runner.invoke(app, ["config"], input="c\na\nmydir\nb\ns\n")
    assert result.exit_code == 0, result.output
    cfg = load_config(tmp_path / "grendel.yaml")
    assert "mydir" in [d.name for d in cfg.catalog.pack_dirs]


def test_config_remove_catalog_pack_dir_in_session(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    # add THEN remove within one CLI session, save -> the dir is genuinely gone (if remove had
    # silently failed, 'mydir' would persist in the saved file and this assertion would catch it).
    result = runner.invoke(app, ["config"], input="c\na\nmydir\nr\nmydir\nb\ns\n")
    assert result.exit_code == 0, result.output
    cfg = load_config(tmp_path / "grendel.yaml")
    assert "mydir" not in [d.name for d in cfg.catalog.pack_dirs]


# --- Phase 18: self-explanatory add-target (describe_target + confirmation) --------------------
from grendel.cli import _make_target_config, describe_target  # noqa: E402


def test_describe_target_http_openai() -> None:
    tc = _make_target_config("http", provider="openai", model="gpt-4o-mini")
    desc = describe_target(tc, GrendelConfig())
    assert "POST https://api.openai.com/v1/chat/completions" in desc
    assert "model gpt-4o-mini" in desc
    assert "OPENAI_API_KEY" in desc  # env var NAME only


def test_describe_target_openai_compatible_uses_base_url_and_ollama_path() -> None:
    tc = _make_target_config(
        "http", provider="openai-compatible", model="local", base_url="http://localhost:1234/v1"
    )
    desc = describe_target(tc, GrendelConfig())
    assert "POST http://localhost:1234/v1/chat/completions" in desc
    # anthropic preset uses /messages, ollama uses /api/chat — branch on api_style, not hardcoded
    a = describe_target(
        _make_target_config("http", provider="anthropic", model="claude"), GrendelConfig()
    )  # noqa: E501
    assert "/messages" in a
    o = describe_target(
        _make_target_config("http", provider="ollama", model="llama3"), GrendelConfig()
    )  # noqa: E501
    assert "/api/chat" in o


def test_describe_target_python_is_in_process() -> None:
    tc = _make_target_config("python", entrypoint="my.mod:agent")
    assert describe_target(tc, GrendelConfig()) == "in-process call → my.mod:agent"


def test_describe_target_unknown_provider_raises() -> None:
    tc = _make_target_config("http", provider="nope", model="m")
    try:
        describe_target(tc, GrendelConfig())
        raise AssertionError("expected ConfigError for unknown provider")
    except ConfigError:
        pass


def test_config_add_target_shows_summary_then_confirms(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    script = "t\na\ngpt\n1\n\n\n\ny\nb\ns\n"
    result = runner.invoke(app, ["config"], input=script)
    assert result.exit_code == 0, result.output
    assert "this target will: POST https://api.openai.com/v1/chat/completions" in result.output


def test_config_add_target_provider_list_annotated(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    # intent 1 (hosted) -> provider list shown; cancel; assert the annotations are shown.
    result = runner.invoke(app, ["config"], input="t\na\ngpt\n1\n\n\n\nn\nb\ns\n")
    assert result.exit_code == 0, result.output
    assert "openai (openai; https://api.openai.com/v1)" in result.output
    # 'openai-compatible' needs a base_url -> it's the intent-2 (chat URL) path, not offered here
    assert "openai-compatible (openai; needs base_url)" not in result.output


def test_config_add_target_cancel_adds_nothing(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    # intent 1, confirm = n -> cancelled, nothing added
    script = "t\na\ngpt\n1\n\n\n\nn\nb\ns\n"
    result = runner.invoke(app, ["config"], input=script)
    assert result.exit_code == 0, result.output
    assert "cancelled" in result.output
    cfg = load_config(tmp_path / "grendel.yaml")
    assert "gpt" not in cfg.targets


def test_pack_dir_helpers_dedupe_and_absent() -> None:
    cfg = GrendelConfig()
    _add_pack_dir(cfg, "a")
    _add_pack_dir(cfg, "a")  # duplicate ignored
    assert cfg.catalog.pack_dirs == [Path("a")]
    _remove_pack_dir(cfg, "a")
    assert cfg.catalog.pack_dirs == []
    try:
        _remove_pack_dir(cfg, "a")  # absent
        raise AssertionError("expected ConfigError for absent pack dir")
    except ConfigError:
        pass
    try:
        _add_pack_dir(cfg, "   ")  # empty
        raise AssertionError("expected ConfigError for empty path")
    except ConfigError:
        pass
