"""M5: the written deliverables (README + VHS tape) exist with the required markers.

Fix #11: locate files repo-relative via parents[1], NOT cwd. No VHS is invoked.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_readme_exists_with_authorized_use_framing() -> None:
    readme = ROOT / "README.md"
    assert readme.exists()
    text = readme.read_text(encoding="utf-8")
    lower = text.lower()
    # The ROADMAP §7 HARD requirement: prominent authorized-use / defensive-only framing.
    assert "authorized" in lower
    assert "defensive" in lower
    assert "not an offensive tool" in lower
    assert "not a general llm benchmark" in lower


def test_readme_has_quickstart_commands() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    for cmd in (
        "grendel list --packs",
        "grendel run --target",
        "grendel report",
        "grendel diff",
        "grendel update",
        "--fail-under",
    ):
        assert cmd in text, cmd
    # The CI exit-code contract is documented.
    assert "exit code" in text.lower()


def test_demo_tape_exists_with_commands_and_output() -> None:
    tape = ROOT / "demo" / "grendel.tape"
    assert tape.exists()
    text = tape.read_text(encoding="utf-8")
    assert "Output" in text  # the VHS output directive
    assert "grendel list --packs" in text
    assert "grendel run" in text
