"""Pydantic config models and the YAML loader for gauntlet."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

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


class McpConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: list[str] | None = None  # stdio server launch argv (real path; Phase 8 detail)
    url: str | None = None  # or a server URL
    tool: str | None = None  # optional default tool to probe


class TargetConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["http", "python", "agent", "mcp"] = "http"
    provider: str | None = None  # now optional; required only for type == "http"
    model: str | None = None  # now optional; defaults to entrypoint for python/agent
    base_url: str | None = None
    api_key_env: str | None = None
    extra_headers: dict[str, str] = {}
    entrypoint: str | None = None  # "module:attr" — required for python/agent
    mcp: McpConfig | None = None  # required for mcp


class CustomProviderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_url: str
    api_style: Literal["openai", "anthropic", "ollama"] = "openai"
    api_key_env: str | None = None
    default_headers: dict[str, str] = {}


class JudgeConfig(BaseModel):
    """T3 LLM-judge config (Phase 6, additive, default OFF).

    Only simple field constraints are validated here. The cross-checks that an enabled
    judge has a resolvable ``target`` and a known ``rubric_version`` are deferred to CLI
    startup (Fix #2) so ``config.py`` never imports ``judge.py`` (no import cycle).
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False  # OFF by default — nothing changes unless set
    target: str | None = None  # name of a configured target used as the judge endpoint
    rubric_version: str = "v1"  # pinned; selects RUBRIC_V1 (unknown -> ConfigError at CLI)
    ensemble_size: int = Field(default=3, ge=1)
    vote_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    contested_band: float = Field(default=0.15, ge=0.0, le=1.0)
    temperature: float = 0.7  # judge sampling temp for ensemble diversity (real backend)
    max_tokens: int = Field(default=256, ge=1)

    @field_validator("target")
    @classmethod
    def _target_non_empty(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("judge target must be a non-empty string when set")
        return v


class GauntletConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = 1
    log: LogConfig = LogConfig()
    run: RunOptions = RunOptions()
    providers: dict[str, CustomProviderConfig] = {}
    targets: dict[str, TargetConfig] = {}
    judge: JudgeConfig = JudgeConfig()

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
            # Fix #2: scope provider/collision checks to http; non-http targets have their
            # own required-field validation and no provider.
            if target.type != "http":
                if target.type in ("python", "agent") and not target.entrypoint:
                    raise ConfigError(
                        f"target {target_name!r} of type {target.type!r} requires "
                        f"'entrypoint' (\"module:attr\")"
                    )
                if target.type == "mcp" and (
                    target.mcp is None or not (target.mcp.command or target.mcp.url)
                ):
                    raise ConfigError(
                        f"target {target_name!r} of type 'mcp' requires an 'mcp' block "
                        f"with 'command' or 'url'"
                    )
                continue
            # Fix #6: provider/model are now Optional at the field level; re-require them
            # for http (else model=None would blow up at RunRecord build time).
            if target.provider is None or target.model is None:
                raise ConfigError(
                    f"target {target_name!r} of type 'http' requires 'provider' and 'model'"
                )
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
