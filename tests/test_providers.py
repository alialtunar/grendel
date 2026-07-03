"""Tests for provider preset resolution."""

from __future__ import annotations

import pytest

from grendel.config import CustomProviderConfig, GrendelConfig
from grendel.errors import ConfigError
from grendel.targets.providers import PRESETS, resolve_provider


def test_five_presets_present() -> None:
    assert set(PRESETS) == {
        "openai",
        "anthropic",
        "openrouter",
        "ollama",
        "openai-compatible",
    }


@pytest.mark.parametrize("name", sorted(PRESETS))
def test_presets_resolve(name: str) -> None:
    preset = resolve_provider(name, GrendelConfig())
    assert preset.name == name


def test_custom_provider_resolves() -> None:
    cfg = GrendelConfig(
        providers={
            "my-local": CustomProviderConfig(
                base_url="http://localhost:8000/v1", api_style="openai"
            )
        }
    )
    preset = resolve_provider("my-local", cfg)
    assert preset.base_url == "http://localhost:8000/v1"
    assert preset.api_style == "openai"


def test_unknown_provider_raises() -> None:
    with pytest.raises(ConfigError, match="unknown provider"):
        resolve_provider("nope", GrendelConfig())


def test_collision_backstop_raises() -> None:
    # Build a config that bypasses the load-time check to exercise the backstop.
    cfg = GrendelConfig()
    cfg.providers["openai"] = CustomProviderConfig(base_url="http://x")
    with pytest.raises(ConfigError, match="collides"):
        resolve_provider("openai", cfg)
