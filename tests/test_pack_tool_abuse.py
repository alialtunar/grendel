"""M5: the bundled tool-abuse pack end-to-end + config/build/dry-run integration."""

from __future__ import annotations

from pathlib import Path

import pytest

from fakes import FakeAdapter
from gauntlet.agents.demo import weak_agent
from gauntlet.config import GauntletConfig
from gauntlet.errors import ConfigError, PackError
from gauntlet.packloader import default_packs_dir, load_packs
from gauntlet.records import Verdict, make_run_record
from gauntlet.runner import Runner
from gauntlet.scoring import Scorer
from gauntlet.targets import build_target, resolve_target_info
from gauntlet.targets.python_adapter import AgentSandboxAdapter, PythonCallableAdapter

DEMO = "gauntlet.agents.demo:weak_agent"


def _tool_abuse_attacks() -> list:
    return [a for a in load_packs(default_packs_dir()) if a.category == "tool-abuse"]


def test_pack_loads_five_side_effect_attacks() -> None:
    attacks = _tool_abuse_attacks()
    assert len(attacks) == 5
    assert all(a.success_when.type == "side-effect" for a in attacks)


async def test_pack_scores_fail_t4_against_weak_agent(tmp_path: Path) -> None:
    attacks = _tool_abuse_attacks()
    cfg = GauntletConfig()
    cfg.run.output_dir = tmp_path
    adapter = AgentSandboxAdapter(weak_agent, entrypoint=DEMO)
    record = make_run_record(
        target_name="demo",
        provider="agent",
        model="weak_agent",
        config=cfg,
        pack_ids=[a.id for a in attacks],
    )
    out = await Runner(adapter, cfg.run, scorer=Scorer()).run(attacks, record)

    assert len(out.attempts) == 5
    for att in out.attempts:
        assert att.verdict == Verdict.FAIL, f"{att.attack_id} should FAIL (attack succeeded)"
        assert att.score_tier == "T4"
        assert att.tool_calls  # populated observed calls
        assert att.tool_observed is True
    assert out.asr == 1.0


async def test_pack_skipped_against_plain_adapter(tmp_path: Path) -> None:
    attacks = _tool_abuse_attacks()
    cfg = GauntletConfig()
    cfg.run.output_dir = tmp_path
    adapter = FakeAdapter()  # tool_calls defaults to None
    record = make_run_record(
        target_name="fake",
        provider="fake",
        model="fake-model",
        config=cfg,
        pack_ids=[a.id for a in attacks],
    )
    out = await Runner(adapter, cfg.run, scorer=Scorer()).run(attacks, record)

    assert len(out.attempts) == 5
    for att in out.attempts:
        assert att.verdict == Verdict.SKIPPED
        assert att.tool_observed is False
        assert att.tool_calls == []


# --- config + build_target + resolve_target_info (non-http) ---


def test_build_agent_target_and_info() -> None:
    cfg = GauntletConfig.model_validate(
        {"targets": {"demo": {"type": "agent", "entrypoint": DEMO}}}
    )
    adapter = build_target("demo", cfg, dry_run=True)
    assert isinstance(adapter, AgentSandboxAdapter)
    info = resolve_target_info("demo", cfg)
    assert info == {
        "provider": "agent",
        "model": DEMO,
        "base_url": "(in-process)",
        "api_style": "n/a",
    }


def test_build_python_target() -> None:
    cfg = GauntletConfig.model_validate({"targets": {"p": {"type": "python", "entrypoint": DEMO}}})
    adapter = build_target("p", cfg, dry_run=True)
    assert isinstance(adapter, PythonCallableAdapter)


def test_agent_target_requires_entrypoint() -> None:
    with pytest.raises(ConfigError, match="entrypoint"):
        GauntletConfig.model_validate({"targets": {"bad": {"type": "agent"}}})


def test_mcp_target_requires_block() -> None:
    with pytest.raises(ConfigError, match="mcp"):
        GauntletConfig.model_validate({"targets": {"bad": {"type": "mcp"}}})


def test_http_target_still_requires_provider_and_model() -> None:
    with pytest.raises(ConfigError, match="provider"):
        GauntletConfig.model_validate({"targets": {"h": {"type": "http"}}})


# --- Fix #8: loader rejects malformed side-effect assertions ---


def test_malformed_side_effect_assertion_raises_packerror(tmp_path: Path) -> None:
    d = tmp_path / "tool-abuse"
    d.mkdir()
    (d / "bad-01.yaml").write_text(
        "id: tool-abuse/bad-01\n"
        "name: bad\n"
        "category: tool-abuse\n"
        "owasp: LLM06\n"
        "atlas: AML.T0051\n"
        "surface: prompt\n"
        "severity: low\n"
        "license: MIT\n"
        "version: 1\n"
        "payload: x\n"
        "success_when:\n"
        "  type: side-effect\n"
        "  assert: os.system('rm -rf /')\n",
        encoding="utf-8",
    )
    with pytest.raises(PackError, match="malformed side-effect"):
        load_packs(tmp_path)
