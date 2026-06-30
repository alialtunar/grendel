"""Shared test fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

EXAMPLE_CONFIG = Path(__file__).resolve().parents[1] / "examples" / "gauntlet.example.yaml"


@pytest.fixture
def example_config_path() -> Path:
    """Path to the bundled example config."""
    return EXAMPLE_CONFIG


@pytest.fixture
def write_config(tmp_path: Path):
    """Return a helper that writes YAML text to a tmp file and returns its path."""

    def _write(text: str, name: str = "gauntlet.yaml") -> Path:
        path = tmp_path / name
        path.write_text(text, encoding="utf-8")
        return path

    return _write
