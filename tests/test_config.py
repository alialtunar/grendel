"""Tests for config loading and validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from grendel.config import GrendelConfig, load_config
from grendel.errors import ConfigError


def test_example_config_loads(example_config_path: Path) -> None:
    cfg = load_config(example_config_path)
    assert isinstance(cfg, GrendelConfig)
    assert "gpt" in cfg.targets
    assert cfg.targets["gpt"].provider == "openai"
    assert "my-local" in cfg.providers


def test_defaults_applied() -> None:
    cfg = GrendelConfig()
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
    cfg = GrendelConfig()
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


# --- Phase 12: ProxyConfig + with_cli_target --------------------------------------------------
from pydantic import ValidationError  # noqa: E402

from grendel.config import ProxyConfig, TargetConfig  # noqa: E402


def test_proxy_config_defaults() -> None:
    p = ProxyConfig()
    assert p.host == "127.0.0.1" and p.port == 8100 and p.routes == {}


def test_proxy_config_port_range() -> None:
    with pytest.raises(ValidationError):
        ProxyConfig(port=0)
    with pytest.raises(ValidationError):
        ProxyConfig(port=70000)


def test_proxy_config_route_must_start_with_slash() -> None:
    with pytest.raises(ValidationError):
        ProxyConfig(routes={"openai": "openai"})


def test_grendel_config_has_default_proxy() -> None:
    assert GrendelConfig().proxy == ProxyConfig()


def test_with_cli_target_injects_and_revalidates() -> None:
    cfg = GrendelConfig.model_validate({"catalog": {"pack_dirs": ["/abs/packs"]}})
    t = TargetConfig(type="http", provider="openai", model="gpt-4o-mini")
    out = cfg.with_cli_target("cli", t)
    assert out.targets["cli"].provider == "openai"
    # Path survives the round-trip unchanged.
    assert out.catalog.pack_dirs == cfg.catalog.pack_dirs
    assert isinstance(out.catalog.pack_dirs[0], Path)


def test_with_cli_target_unknown_provider_raises_configerror() -> None:
    cfg = GrendelConfig()
    t = TargetConfig(type="http", provider="nope", model="m")
    # ConfigError (not ValidationError) must propagate from the validator.
    with pytest.raises(ConfigError):
        cfg.with_cli_target("cli", t)


def test_with_cli_target_duplicate_name_raises() -> None:
    cfg = GrendelConfig.model_validate(
        {"targets": {"cli": {"type": "http", "provider": "openai", "model": "m"}}}
    )
    with pytest.raises(ConfigError, match="already exists"):
        cfg.with_cli_target("cli", TargetConfig(type="python", entrypoint="m:f"))
