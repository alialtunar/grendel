"""Shared test fixtures."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# Suppress cwd grendel.yaml auto-discovery for the WHOLE suite, set at import time (before
# collection) so a CLI invocation from any test module — even one that doesn't chdir away from
# the repo root, which has a real grendel.yaml + ~1500-file catalog/ — never silently picks up
# the real catalog. The dedicated test_cli_autoconfig.py monkeypatch.delenv's this in a tmp cwd.
os.environ["GRENDEL_NO_AUTOCONFIG"] = "1"
# Likewise never pick up a stray ./grendel.local.yaml during the suite (a dedicated test
# delenv's this in a tmp cwd to exercise the merge).
os.environ["GRENDEL_NO_LOCAL_SECRETS"] = "1"

EXAMPLE_CONFIG = Path(__file__).resolve().parents[1] / "examples" / "grendel.example.yaml"


@pytest.fixture(autouse=True)
def _clear_menu_attack_cache():
    """The menu run caches the loaded catalog module-globally; clear it between tests so a
    monkeypatched _load_attacks in one test can't leak into another with the same catalog sig."""
    import grendel.cli as cli

    cli._MENU_ATTACK_CACHE.clear()
    yield
    cli._MENU_ATTACK_CACHE.clear()


@pytest.fixture
def example_config_path() -> Path:
    """Path to the bundled example config."""
    return EXAMPLE_CONFIG


@pytest.fixture
def write_config(tmp_path: Path):
    """Return a helper that writes YAML text to a tmp file and returns its path."""

    def _write(text: str, name: str = "grendel.yaml") -> Path:
        path = tmp_path / name
        path.write_text(text, encoding="utf-8")
        return path

    return _write
