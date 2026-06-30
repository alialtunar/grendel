"""M4 (Fix #12): the authoring guide deliverable cannot ship empty."""

from __future__ import annotations

from pathlib import Path

DOC = Path(__file__).resolve().parents[1] / "docs" / "authoring-packs.md"


def test_authoring_guide_exists_with_required_sections() -> None:
    assert DOC.is_file(), f"missing authoring guide: {DOC}"
    text = DOC.read_text(encoding="utf-8")
    required = [
        "## 1. The Attack schema",  # schema / every field
        "## 2. The `success_when` types",  # success_when types
        "## 3. License requirement",  # license requirement
        "## 4. Where to put the file",  # where to put the file
        "## 5. How to validate",  # validation command
        "## 6. The feed manifest format",  # feed manifest format
    ]
    for header in required:
        assert header in text, f"authoring guide missing section: {header!r}"
    # every success_when type is documented
    for t in ("string", "side-effect", "mcp-assert", "classifier", "judge"):
        assert t in text
    # the validation command is shown
    assert "list --packs" in text
