"""Tests for config loading and validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from gauntlet.config import GauntletConfig, load_config
from gauntlet.errors import ConfigError


def test_example_config_loads(example_config_path: Path) -> None:
    cfg = load_config(example_config_path)
    assert isinstance(cfg, GauntletConfig)
    assert "gpt" in cfg.targets
    assert cfg.targets["gpt"].provider == "openai"
    assert "my-local" in cfg.providers


def test_defaults_applied() -> None:
    cfg = GauntletConfig()
    assert cfg.version == 1
    assert cfg.log.level == "INFO"
    assert cfg.log.format == "text"
    assert cfg.run.max_tokens == 512
    assert cfg.run.temperature == 0.0
    assert cfg.run.output_dir == Path("runs")


def test_none_path_returns_defaults() -> None:
    cfg = load_config(None)
    assert cfg.targets == {}


def test_openai_compatible_without_base_url_raises(write_config) -> None:
    path = write_config("targets:\n  bad:\n    provider: openai-compatible\n    model: m\n")
    with pytest.raises(ConfigError, match="bad"):
        load_config(path)


def test_unknown_provider_raises(write_config) -> None:
    path = write_config("targets:\n  t:\n    provider: nope\n    model: m\n")
    with pytest.raises(ConfigError, match="nope"):
        load_config(path)


def test_unknown_yaml_key_rejected(write_config) -> None:
    path = write_config("bogus_key: 1\n")
    with pytest.raises(ConfigError):
        load_config(path)


def test_custom_provider_preset_collision_raises(write_config) -> None:
    path = write_config("providers:\n  openai:\n    base_url: http://x\n")
    with pytest.raises(ConfigError, match="openai"):
        load_config(path)


def test_missing_file_raises() -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_config(Path("does-not-exist.yaml"))


def test_catalog_defaults_empty() -> None:
    cfg = GauntletConfig()
    assert cfg.catalog.pack_dirs == []
    assert cfg.catalog.feed_cache_dir is None
    assert cfg.catalog.feeds == []
    assert cfg.catalog.allow_override is False
    assert cfg.catalog.allow_unlisted_licenses is False


def test_catalog_roundtrip(write_config) -> None:
    text = (
        "catalog:\n"
        "  pack_dirs:\n"
        "    - sub/packs\n"
        "  allow_override: true\n"
        "  feeds:\n"
        "    - name: community\n"
        "      url: https://feed.test/manifest.yaml\n"
    )
    path = write_config(text)
    cfg = load_config(path)
    assert cfg.catalog.allow_override is True
    assert cfg.catalog.feeds[0].name == "community"
    assert cfg.catalog.feeds[0].url == "https://feed.test/manifest.yaml"
    assert cfg.catalog.pack_dirs == [path.resolve().parent / "sub" / "packs"]


def test_catalog_relative_paths_resolve_against_config_dir(write_config) -> None:
    text = "catalog:\n  pack_dirs:\n    - mypacks\n  feed_cache_dir: cache\n"
    path = write_config(text)
    cfg = load_config(path)
    base = path.resolve().parent
    assert cfg.catalog.pack_dirs == [base / "mypacks"]
    assert cfg.catalog.feed_cache_dir == base / "cache"


def test_feed_source_empty_name_rejected(write_config) -> None:
    text = "catalog:\n  feeds:\n    - name: ''\n      url: https://x.test/m\n"
    with pytest.raises(ConfigError):
        load_config(write_config(text))
