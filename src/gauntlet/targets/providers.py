"""Provider preset table and provider resolution."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel

from ..errors import ConfigError

if TYPE_CHECKING:
    from ..config import GauntletConfig


class ProviderPreset(BaseModel):
    name: str
    base_url: str | None
    api_style: Literal["openai", "anthropic", "ollama"]
    api_key_env: str | None
    default_headers: dict[str, str] = {}


PRESETS: dict[str, ProviderPreset] = {
    "openai": ProviderPreset(
        name="openai",
        base_url="https://api.openai.com/v1",
        api_style="openai",
        api_key_env="OPENAI_API_KEY",
    ),
    "anthropic": ProviderPreset(
        name="anthropic",
        base_url="https://api.anthropic.com/v1",
        api_style="anthropic",
        api_key_env="ANTHROPIC_API_KEY",
        default_headers={"anthropic-version": "2023-06-01"},
    ),
    "openrouter": ProviderPreset(
        name="openrouter",
        base_url="https://openrouter.ai/api/v1",
        api_style="openai",
        api_key_env="OPENROUTER_API_KEY",
    ),
    "ollama": ProviderPreset(
        name="ollama",
        base_url="http://localhost:11434",
        api_style="ollama",
        api_key_env=None,
    ),
    "openai-compatible": ProviderPreset(
        name="openai-compatible",
        base_url=None,
        api_style="openai",
        api_key_env=None,
    ),
}


def resolve_provider(name: str, config: GauntletConfig) -> ProviderPreset:
    """Return a ProviderPreset for ``name``, from presets or config custom providers.

    Custom provider names must not collide with preset names (the load-time check in
    config.py is authoritative; this is a defensive backstop). Unknown names raise
    ConfigError.
    """
    custom = config.providers.get(name)
    if name in PRESETS:
        if custom is not None:
            raise ConfigError(f"custom provider {name!r} collides with a built-in preset name")
        return PRESETS[name]

    if custom is not None:
        return ProviderPreset(
            name=name,
            base_url=custom.base_url,
            api_style=custom.api_style,
            api_key_env=custom.api_key_env,
            default_headers=custom.default_headers,
        )

    known = sorted(set(PRESETS) | set(config.providers))
    raise ConfigError(f"unknown provider {name!r}; known providers: {', '.join(known)}")
