"""build_cli_target_config: the pure flag→TargetConfig synthesis + its usage-error branches."""

from __future__ import annotations

import pytest

from grendel.config import build_cli_target_config
from grendel.errors import ConfigError


def test_build_cli_target_none_when_no_flags() -> None:
    assert build_cli_target_config() is None


def test_build_cli_target_happy_http() -> None:
    tc = build_cli_target_config(provider="openai", model="m")
    assert tc.type == "http" and tc.provider == "openai" and tc.model == "m"


@pytest.mark.parametrize(
    "kwargs, match",
    [
        ({"target": "x", "provider": "openai", "model": "m"}, "not both"),
        ({"provider": "openai", "model": "m", "python": "a:b"}, "exactly one target source"),
        ({"provider": "openai"}, "must be given together"),
        ({"provider": "openai", "model": "m", "header": ["nope"]}, "key=value"),
        ({"mcp_url": "http://x", "mcp_fake_client": "a:b"}, "exactly one of --mcp"),
    ],
)
def test_build_cli_target_usage_errors(kwargs, match) -> None:
    with pytest.raises(ConfigError, match=match):
        build_cli_target_config(**kwargs)
