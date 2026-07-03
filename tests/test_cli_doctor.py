"""Phase 17: `grendel doctor` — inline status report (pure builder + CLI), presence-only."""

from __future__ import annotations

from typer.testing import CliRunner

from grendel.cli import app
from grendel.config import GrendelConfig, ProxyConfig, TargetConfig
from grendel.doctor import build_doctor_report

runner = CliRunner()


def test_report_has_all_sections() -> None:
    cfg = GrendelConfig(
        targets={"gpt": TargetConfig(type="http", provider="openai", model="gpt-4o-mini")},
        proxy=ProxyConfig(routes={"/openai": "openai"}),
    )
    text = build_doctor_report(cfg, env={})
    for section in ("Install", "Catalog", "Provider API keys", "Targets", "Proxy"):
        assert section in text
    assert "gpt: http openai/gpt-4o-mini" in text
    assert "/openai -> openai" in text


def test_env_key_presence_never_shows_value() -> None:
    cfg = GrendelConfig()
    secret = "sk-should-never-appear-1234567890"
    text = build_doctor_report(cfg, env={"OPENAI_API_KEY": secret})
    assert "openai" in text
    assert "✓ OPENAI_API_KEY set" in text
    assert secret not in text  # presence only, never the value
    # an unset key shows ✗
    assert "✗ ANTHROPIC_API_KEY not set" in text


def test_empty_targets_points_to_config() -> None:
    text = build_doctor_report(GrendelConfig(), env={})
    assert "grendel config" in text


def test_doctor_command_runs_offline() -> None:
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0, result.output
    assert "Install" in result.output and "Catalog" in result.output


def test_doctor_ascii_fallback_encodable_on_legacy_console() -> None:
    # On a cp1254 console the ✓/✗ glyphs would crash; the ASCII fallback must encode cleanly.
    text = build_doctor_report(GrendelConfig(), env={"OPENAI_API_KEY": "x"}, unicode=False)
    text.encode("cp1254")
    text.encode("ascii")
    assert "[set]" in text  # ASCII presence marker instead of ✓
    assert "Provider API keys" in text
