"""Provider preset table and provider resolution."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, model_validator

from ..errors import ConfigError

if TYPE_CHECKING:
    from ..config import GrendelConfig

# The wire-format endpoint suffix per api_style — the single source of truth, imported by
# the HTTP adapter, the proxy, and the CLI preview (was previously duplicated in all three).
API_PATHS: dict[str, str] = {
    "openai": "/chat/completions",
    "anthropic": "/messages",
    "ollama": "/api/chat",
}

# api_styles that require an API key by default (was http_adapter._STYLES_REQUIRING_KEY).
# A preset/custom provider can override this via the explicit `requires_key` field.
_AUTH_REQUIRING_STYLES = frozenset({"openai", "anthropic"})


class ProviderPreset(BaseModel):
    name: str
    base_url: str | None
    api_style: Literal["openai", "anthropic", "ollama", "custom"]
    api_key_env: str | None
    default_headers: dict[str, str] = {}
    default_model: str | None = None  # convenience default offered in the add-target wizard
    # suggested model ids for the run picker (NOT a closed list; user can type any model)
    models: list[str] = []
    requires_key: bool | None = None  # None -> derived from api_style (see validator)
    # For api_style == "custom" only: the config-authored request/response shape, carried as
    # plain dicts so this module keeps zero runtime import of config.py (no import cycle).
    request: dict | None = None
    response: dict | None = None

    @model_validator(mode="after")
    def _default_requires_key(self) -> ProviderPreset:
        if self.requires_key is None:
            self.requires_key = self.api_style in _AUTH_REQUIRING_STYLES
        return self


PRESETS: dict[str, ProviderPreset] = {
    "openai": ProviderPreset(
        name="openai",
        base_url="https://api.openai.com/v1",
        api_style="openai",
        api_key_env="OPENAI_API_KEY",
        default_model="gpt-4o-mini",
        # static FALLBACK only (live /v1/models is authoritative when a key is set)
        models=[
            "gpt-4o", "gpt-4o-mini", "o3", "o3-mini", "o1", "o1-mini",
            "gpt-4.1", "gpt-4.1-mini", "gpt-4-turbo", "gpt-3.5-turbo",
        ],
    ),
    "anthropic": ProviderPreset(
        name="anthropic",
        base_url="https://api.anthropic.com/v1",
        api_style="anthropic",
        api_key_env="ANTHROPIC_API_KEY",
        default_headers={"anthropic-version": "2023-06-01"},
        models=[
            "claude-opus-4-8", "claude-sonnet-5", "claude-haiku-4-5",
            "claude-3-7-sonnet-latest", "claude-3-5-sonnet-latest", "claude-3-5-haiku-latest",
            "claude-3-opus-latest",
        ],
    ),
    "openrouter": ProviderPreset(
        name="openrouter",
        base_url="https://openrouter.ai/api/v1",
        api_style="openai",
        api_key_env="OPENROUTER_API_KEY",
        models=[
            "openai/gpt-4o", "openai/gpt-4o-mini", "anthropic/claude-3.5-sonnet",
            "google/gemini-2.0-flash-001", "meta-llama/llama-3.1-70b-instruct",
            "mistralai/mistral-large", "deepseek/deepseek-chat",
        ],
    ),
    "ollama": ProviderPreset(
        name="ollama",
        base_url="http://localhost:11434",
        api_style="ollama",
        api_key_env=None,
        models=["llama3.1", "llama3.2", "mistral", "qwen2.5", "phi3", "gemma2"],
    ),
    "openai-compatible": ProviderPreset(
        name="openai-compatible",
        base_url=None,
        api_style="openai",
        api_key_env=None,
    ),
}


def resolve_provider(name: str, config: GrendelConfig) -> ProviderPreset:
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
            requires_key=custom.requires_key,  # None -> derived from api_style
            # custom-style shape carried as plain dicts (no config import here).
            request=custom.request.model_dump() if custom.request else None,
            response=custom.response.model_dump() if custom.response else None,
        )

    known = sorted(set(PRESETS) | set(config.providers))
    raise ConfigError(f"unknown provider {name!r}; known providers: {', '.join(known)}")
