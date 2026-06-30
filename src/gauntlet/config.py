"""Pydantic config models and the YAML loader for gauntlet."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .errors import ConfigError


class LogConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    format: Literal["json", "text"] = "text"


class RunOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    output_dir: Path = Path("runs")
    max_tokens: int = 512
    temperature: float = 0.0
    request_timeout_s: float = 30.0
    concurrency: int = Field(default=4, ge=1)
    rps: float | None = Field(default=None, gt=0)
    max_retries: int = Field(default=3, ge=0)
    retry_base_delay_s: float = Field(default=0.5, ge=0)
    retry_max_delay_s: float = Field(default=30.0, ge=0)
    retry_seed: int | None = None


class TargetConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["http"] = "http"
    provider: str
    model: str
    base_url: str | None = None
    api_key_env: str | None = None
    extra_headers: dict[str, str] = {}


class CustomProviderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_url: str
    api_style: Literal["openai", "anthropic", "ollama"] = "openai"
    api_key_env: str | None = None
    default_headers: dict[str, str] = {}


class GauntletConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = 1
    log: LogConfig = LogConfig()
    run: RunOptions = RunOptions()
    providers: dict[str, CustomProviderConfig] = {}
    targets: dict[str, TargetConfig] = {}

    @model_validator(mode="after")
    def _check_provider_collisions_and_targets(self) -> GauntletConfig:
        # Import preset names lazily to avoid an import cycle with targets.providers.
        from .targets.providers import PRESETS

        for name in self.providers:
            if name in PRESETS:
                raise ConfigError(
                    f"custom provider {name!r} collides with a built-in preset name; "
                    f"rename it (reserved names: {', '.join(sorted(PRESETS))})"
                )

        known = set(PRESETS) | set(self.providers)
        for target_name, target in self.targets.items():
            if target.provider not in known:
                raise ConfigError(
                    f"target {target_name!r} references unknown provider "
                    f"{target.provider!r}; known providers: {', '.join(sorted(known))}"
                )
            if target.provider == "openai-compatible" and not target.base_url:
                raise ConfigError(
                    f"target {target_name!r} uses provider 'openai-compatible' but has "
                    f"no base_url; a base_url is required for openai-compatible targets"
                )
        return self


def load_config(path: Path | None) -> GauntletConfig:
    """Load a GauntletConfig from a YAML file, or return defaults when path is None.

    Validation failures (unknown keys, unknown providers, missing base_url, preset
    collisions) are re-raised as ConfigError naming the offending field/target.
    """
    if path is None:
        return GauntletConfig()

    path = Path(path)
    if not path.exists():
        raise ConfigError(f"config file not found: {path}")

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {path}: {exc}") from exc

    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ConfigError(f"config root must be a mapping in {path}, got {type(raw).__name__}")

    try:
        return GauntletConfig.model_validate(raw)
    except ConfigError:
        raise
    except ValidationError as exc:
        raise ConfigError(f"invalid config in {path}: {exc}") from exc
