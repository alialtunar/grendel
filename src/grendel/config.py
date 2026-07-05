"""Pydantic config models and the YAML loader for grendel."""

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
from .scoring_defaults import (
    DEFAULT_COMPLIANT_LEXICON,
    DEFAULT_CONTESTED_CRITERIA,
    DEFAULT_REFUSAL_LEXICON,
    DEFAULT_REFUSAL_MARKERS,
)


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

    command: list[str] | None = None  # stdio server launch argv (real path; still stubbed)
    url: str | None = None  # or a server URL
    tool: str | None = None  # optional default tool to probe
    fake_client: str | None = None  # "module:attr" factory -> in-memory client (OFFLINE seam)


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


class CustomRequestSpec(BaseModel):
    """How a `custom` provider builds its HTTP request (config, not code).

    ``body`` is a JSON template; the string leaves may contain the placeholders
    ``{prompt}`` / ``{system}`` / ``{model}`` / ``{api_key}``, substituted per call.
    Unknown ``{...}`` braces are left verbatim (an agent's own payload is untouched).
    """

    model_config = ConfigDict(extra="forbid")

    path: str = ""  # appended to base_url (e.g. "/chat")
    body: dict = {}  # JSON body template with {prompt}/{system}/{model}/{api_key}
    headers: dict[str, str] = {}


class CustomResponseSpec(BaseModel):
    """How a `custom` provider reads the reply: a dotted path into the JSON response."""

    model_config = ConfigDict(extra="forbid")

    text_path: str  # e.g. "reply" or "choices.0.message.content"


class CustomProviderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_url: str
    api_style: Literal["openai", "anthropic", "ollama", "custom"] = "openai"
    api_key_env: str | None = None
    default_headers: dict[str, str] = {}
    requires_key: bool | None = None  # None -> derived from api_style
    request: CustomRequestSpec | None = None  # required iff api_style == "custom"
    response: CustomResponseSpec | None = None  # required iff api_style == "custom"

    @model_validator(mode="after")
    def _check_custom_shape(self) -> CustomProviderConfig:
        if self.api_style == "custom":
            if self.request is None or self.response is None:
                raise ConfigError(
                    "custom provider requires both 'request' and 'response' "
                    "(request.body + response.text_path)"
                )
        elif self.request is not None or self.response is not None:
            raise ConfigError(
                f"'request'/'response' are only valid for api_style 'custom', "
                f"not {self.api_style!r}"
            )
        return self


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


class ScoringConfig(BaseModel):
    """Overridable T1/T2/T3 scoring vocabulary (additive; defaults == the built-ins).

    Moves the refusal markers, T2 lexicons, and contested-case judge criteria out of
    source and into config, so they can be edited or localized without a code change.
    Defaults come from ``scoring_defaults`` (a dependency-free module) to keep this
    section import-cycle-free.
    """

    model_config = ConfigDict(extra="forbid")

    refusal_markers: list[str] = list(DEFAULT_REFUSAL_MARKERS)
    compliant_lexicon: list[str] = list(DEFAULT_COMPLIANT_LEXICON)
    refusal_lexicon: list[str] = list(DEFAULT_REFUSAL_LEXICON)
    contested_criteria: str = DEFAULT_CONTESTED_CRITERIA


class FeedSource(BaseModel):
    """A remote feed manifest to pull packs from (Phase 9)."""

    model_config = ConfigDict(extra="forbid")

    name: str  # logical feed name (shown in `update` output)
    url: str  # URL of the feed manifest (JSON or YAML)

    @field_validator("name", "url")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must be a non-empty string")
        return v


class CatalogConfig(BaseModel):
    """Multi-source catalog config (Phase 9, additive, default empty == bundled-only)."""

    model_config = ConfigDict(extra="forbid")

    pack_dirs: list[Path] = []  # extra user pack directories (USER source)
    feed_cache_dir: Path | None = None  # where `grendel update` writes pulled packs (FEED)
    feeds: list[FeedSource] = []  # remote feed manifests to pull
    staged_dir: Path | None = None  # optional: staged-for-approval packs (§9)
    allow_override: bool = False  # cross-source dup id -> precedence vs error (§5.2)
    allow_unlisted_licenses: bool = False  # gate override applied to ALL sources + the feed


# The built-in default feed `grendel update` pulls from when catalog.feeds is empty — a manifest
# hosted in this repo (GitHub raw), refreshed by the feed-refresh workflow. NOT a model default
# (config stays "empty == bundled-only"); applied at the update/catalog-load layer instead.
DEFAULT_FEED = FeedSource(
    name="grendel",
    url="https://raw.githubusercontent.com/alialtunar/grendel/master/feeds/manifest.json",
)
DEFAULT_FEED_CACHE_DIR = Path("feed_cache")  # where a zero-config `grendel update` writes + reads


class ProxyConfig(BaseModel):
    """LLM-proxy config (Phase 12: configurable from the terminal; served in Phase 13).

    Provider-known-ness of a route target is validated at the CLI (where PRESETS + custom
    providers are available), mirroring how TargetConfig.provider is handled — so config.py
    stays free of a targets.providers import.
    """

    model_config = ConfigDict(extra="forbid")

    host: str = "127.0.0.1"
    port: int = Field(default=8100, ge=1, le=65535)
    routes: dict[str, str] = {}  # URL path prefix (e.g. "/openai") -> provider name

    @field_validator("routes")
    @classmethod
    def _routes_well_formed(cls, v: dict[str, str]) -> dict[str, str]:
        for path, provider in v.items():
            if not path.startswith("/"):
                raise ValueError(f"route path {path!r} must start with '/'")
            if not provider.strip():
                raise ValueError(f"route {path!r} has an empty provider")
        return v


class GrendelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = 1
    log: LogConfig = LogConfig()
    run: RunOptions = RunOptions()
    providers: dict[str, CustomProviderConfig] = {}
    targets: dict[str, TargetConfig] = {}
    judge: JudgeConfig = JudgeConfig()
    scoring: ScoringConfig = ScoringConfig()  # ADDITIVE — default == built-in vocabulary
    catalog: CatalogConfig = CatalogConfig()  # ADDITIVE — default empty == bundled-only
    proxy: ProxyConfig = ProxyConfig()  # ADDITIVE (Phase 12) — default is inert

    def with_cli_target(self, name: str, target: TargetConfig) -> GrendelConfig:
        """Return a revalidated copy with a CLI-synthesized target injected under ``name``.

        Re-runs the cross-field checks (unknown provider, missing base_url/entrypoint/mcp) on
        the merged targets map. ``ConfigError`` from the validator propagates raw (it does not
        subclass ValueError, so pydantic does not wrap it in a ValidationError).
        """
        if name in self.targets:
            raise ConfigError(f"target {name!r} already exists in config; rename or omit --target")
        data = self.model_dump(mode="python")
        data["targets"] = {**data["targets"], name: target.model_dump(mode="python")}
        return GrendelConfig.model_validate(data)

    @model_validator(mode="after")
    def _check_provider_collisions_and_targets(self) -> GrendelConfig:
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
                    target.mcp is None
                    or not (target.mcp.command or target.mcp.url or target.mcp.fake_client)
                ):
                    raise ConfigError(
                        f"target {target_name!r} of type 'mcp' requires an 'mcp' block "
                        f"with 'command' or 'url' or 'fake_client'"
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
            # A provider with no default base_url (e.g. the openai-compatible preset) needs the
            # target to supply one — generalized from the former hardcoded 'openai-compatible'
            # name check. Custom providers always carry their own base_url.
            preset = PRESETS.get(target.provider)
            custom = self.providers.get(target.provider)
            provider_base_url = (preset.base_url if preset else None) or (
                custom.base_url if custom else None
            )
            if not provider_base_url and not target.base_url:
                raise ConfigError(
                    f"target {target_name!r} uses provider {target.provider!r} which has no "
                    f"default base_url; set a base_url on the target"
                )
        return self


def build_cli_target_config(
    *,
    target: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    api_key_env: str | None = None,
    header: list[str] | None = None,
    python: str | None = None,
    agent: str | None = None,
    mcp_command: str | None = None,
    mcp_url: str | None = None,
    mcp_fake_client: str | None = None,
    mcp_tool: str | None = None,
) -> TargetConfig | None:
    """Synthesize a TargetConfig from flag-style inputs (pure; ConfigError on any usage error).

    Returns ``None`` when no target-flag group is present (caller falls back to a named target).
    Enforces exactly-one-source. Provider-known-ness is NOT checked here (the caller runs
    ``with_cli_target``). Shared by the CLI ``run`` command and the control-center TUI.
    """
    header = header or []
    http = (
        provider is not None
        or model is not None
        or base_url is not None
        or api_key_env is not None
        or bool(header)
    )
    mcp = mcp_command is not None or mcp_url is not None or mcp_fake_client is not None
    groups = [
        g
        for g, on in (
            ("http", http),
            ("python", python is not None),
            ("agent", agent is not None),
            ("mcp", mcp),
        )
        if on
    ]
    if not groups:
        return None
    if target is not None:
        raise ConfigError("use --target OR the target flags, not both")
    if len(groups) > 1:
        raise ConfigError(f"choose exactly one target source; got: {', '.join(groups)}")

    group = groups[0]
    if group == "http":
        if provider is None or model is None:
            raise ConfigError("--provider and --model must be given together for an HTTP target")
        headers: dict[str, str] = {}
        for h in header:
            if "=" not in h:
                raise ConfigError(f"--header must be key=value, got {h!r}")
            k, v = h.split("=", 1)
            headers[k] = v
        return TargetConfig(
            type="http",
            provider=provider,
            model=model,
            base_url=base_url,
            api_key_env=api_key_env,
            extra_headers=headers,
        )
    if group == "python":
        return TargetConfig(type="python", entrypoint=python)
    if group == "agent":
        return TargetConfig(type="agent", entrypoint=agent)
    # mcp
    srcs = [s for s in (mcp_command, mcp_url, mcp_fake_client) if s is not None]
    if len(srcs) > 1:
        raise ConfigError("choose exactly one of --mcp-command / --mcp-url / --mcp-fake-client")
    return TargetConfig(
        type="mcp",
        mcp=McpConfig(
            command=mcp_command.split() if mcp_command else None,
            url=mcp_url,
            fake_client=mcp_fake_client,
            tool=mcp_tool,
        ),
    )


def save_config(config: GrendelConfig, path: Path) -> None:
    """Write a GrendelConfig to a YAML file (round-trips through load_config).

    ``mode="json"`` so enum/Path fields serialize to plain scalars. Used by the interactive
    ``grendel config`` editor.
    """
    path = Path(path)
    text = yaml.safe_dump(config.model_dump(by_alias=True, mode="json"), sort_keys=False)
    path.write_text(text, encoding="utf-8")


def load_config(path: Path | None) -> GrendelConfig:
    """Load a GrendelConfig from a YAML file, or return defaults when path is None.

    Validation failures (unknown keys, unknown providers, missing base_url, preset
    collisions) are re-raised as ConfigError naming the offending field/target.
    """
    if path is None:
        return GrendelConfig()

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
        cfg = GrendelConfig.model_validate(raw)
    except ConfigError:
        raise
    except ValidationError as exc:
        raise ConfigError(f"invalid config in {path}: {exc}") from exc

    # Resolve relative catalog paths against the config-file directory so they are
    # stable regardless of the process cwd (Fix #11). Absolute paths are left as-is.
    base_dir = path.resolve().parent
    cat = cfg.catalog
    cat.pack_dirs = [p if p.is_absolute() else base_dir / p for p in cat.pack_dirs]
    if cat.feed_cache_dir is not None and not cat.feed_cache_dir.is_absolute():
        cat.feed_cache_dir = base_dir / cat.feed_cache_dir
    if cat.staged_dir is not None and not cat.staged_dir.is_absolute():
        cat.staged_dir = base_dir / cat.staged_dir
    return cfg
