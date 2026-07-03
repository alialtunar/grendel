"""M4: the bundled mcp pack end-to-end vs the fake server + config/build integration."""

from __future__ import annotations

from pathlib import Path

import pytest

from fakes import FakeAdapter
from grendel.agents.mcp_demo import make_fake_client
from grendel.config import GrendelConfig
from grendel.errors import PackError
from grendel.packloader import default_packs_dir, load_packs
from grendel.records import Verdict, make_run_record
from grendel.runner import Runner
from grendel.scoring import Scorer
from grendel.targets import build_target, resolve_target_info
from grendel.targets.mcp_adapter import MCPTargetAdapter

FAKE_CLIENT = "grendel.agents.mcp_demo:make_fake_client"


def _mcp_attacks() -> list:
    return [a for a in load_packs(default_packs_dir()) if a.category == "mcp"]


def test_pack_loads_four_mcp_attacks() -> None:
    attacks = _mcp_attacks()
    assert len(attacks) == 4
    types = sorted(a.success_when.type for a in attacks)
    assert types == ["mcp-assert", "mcp-assert", "mcp-assert", "side-effect"]


async def test_pack_scores_fail_t4_against_fake_server(tmp_path: Path) -> None:
    attacks = _mcp_attacks()
    cfg = GrendelConfig()
    cfg.run.output_dir = tmp_path
    adapter = MCPTargetAdapter(name="mcp", client=make_fake_client())
    record = make_run_record(
        target_name="mcp",
        provider="mcp",
        model="fake",
        config=cfg,
        pack_ids=[a.id for a in attacks],
    )
    out = await Runner(adapter, cfg.run, scorer=Scorer()).run(attacks, record)

    assert len(out.attempts) == 4
    for att in out.attempts:
        assert att.verdict == Verdict.FAIL, f"{att.attack_id} should FAIL (attack succeeded)"
        assert att.score_tier == "T4"
    # The side-effect variant fired via observed tool calls.
    se = next(a for a in out.attempts if a.attack_id == "mcp/description-poisoning-side-effect-02")
    assert any(c["name"] == "exfiltrate" for c in se.tool_calls)
    assert out.asr == 1.0


async def test_pack_skipped_against_plain_adapter(tmp_path: Path) -> None:
    attacks = _mcp_attacks()
    cfg = GrendelConfig()
    cfg.run.output_dir = tmp_path
    adapter = FakeAdapter()  # mcp=None, tool_calls=None
    record = make_run_record(
        target_name="fake",
        provider="fake",
        model="fake-model",
        config=cfg,
        pack_ids=[a.id for a in attacks],
    )
    out = await Runner(adapter, cfg.run, scorer=Scorer()).run(attacks, record)

    assert len(out.attempts) == 4
    for att in out.attempts:
        assert att.verdict == Verdict.SKIPPED


# --- config + build_target offline via fake_client ---


def test_fake_client_target_validates_and_builds_offline() -> None:
    cfg = GrendelConfig.model_validate(
        {"targets": {"m": {"type": "mcp", "mcp": {"fake_client": FAKE_CLIENT}}}}
    )
    adapter = build_target("m", cfg, dry_run=True)
    assert isinstance(adapter, MCPTargetAdapter)
    info = resolve_target_info("m", cfg)
    assert info["model"] == FAKE_CLIENT
    assert info["provider"] == "mcp"


# --- loader rejects a malformed mcp assertion ---


def test_malformed_mcp_assertion_raises_packerror(tmp_path: Path) -> None:
    d = tmp_path / "mcp"
    d.mkdir()
    (d / "bad-01.yaml").write_text(
        "id: mcp/bad-01\n"
        "name: bad\n"
        "category: mcp\n"
        "owasp: LLM01\n"
        "atlas: AML.T0051\n"
        "surface: mcp-desc\n"
        "severity: low\n"
        "license: MIT\n"
        "version: 1\n"
        "payload: x\n"
        "success_when:\n"
        "  type: mcp-assert\n"
        "  assert: os.system('rm -rf /')\n",
        encoding="utf-8",
    )
    with pytest.raises(PackError, match="malformed mcp"):
        load_packs(tmp_path)
