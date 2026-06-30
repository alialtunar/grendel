"""CLI tests for `gauntlet list --packs` wired to the real loader."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from gauntlet.cli import app

runner = CliRunner()

EXAMPLE = str(Path(__file__).resolve().parents[1] / "examples" / "gauntlet.example.yaml")

BUNDLED_IDS = [
    "prompt-injection/direct-override-01",
    "prompt-injection/ignore-previous-02",
    "prompt-injection/delimiter-escape-03",
    "prompt-injection/system-prompt-leak-04",
    "prompt-injection/indirect-rag-05",
    "prompt-injection/tool-output-inject-06",
    "jailbreak/persona-dan-01",
    "jailbreak/roleplay-fiction-02",
    "jailbreak/hypothetical-frame-03",
    "jailbreak/refusal-suppression-04",
    "jailbreak/payload-split-05",
    "jailbreak/base64-obfuscation-06",
]


def test_list_packs_prints_twelve_grouped() -> None:
    result = runner.invoke(app, ["-c", EXAMPLE, "list", "--packs"])
    assert result.exit_code == 0
    assert "prompt-injection (6):" in result.output
    assert "jailbreak (6):" in result.output
    for attack_id in BUNDLED_IDS:
        assert attack_id in result.output


def test_list_packs_includes_mcp_category() -> None:
    # M5 (additive): the mcp category surfaces in `gauntlet list --packs`.
    result = runner.invoke(app, ["-c", EXAMPLE, "list", "--packs"])
    assert result.exit_code == 0
    assert "mcp (4):" in result.output
    assert "mcp/rug-pull-03" in result.output


def test_phase1_placeholder_absent() -> None:
    # Review fix #12.
    result = runner.invoke(app, ["-c", EXAMPLE, "list", "--packs"])
    assert "no attack packs available until Phase 2" not in result.output


def test_bare_list_includes_packs() -> None:
    result = runner.invoke(app, ["-c", EXAMPLE, "list"])
    assert result.exit_code == 0
    assert "Packs:" in result.output
    assert "jailbreak/persona-dan-01" in result.output
