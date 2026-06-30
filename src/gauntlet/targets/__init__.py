"""Target adapter factory and re-exports."""

from __future__ import annotations

import os

import httpx

from ..config import GauntletConfig
from ..errors import ConfigError
from .base import AdapterRequest, AdapterResponse, TargetAdapter
from .http_adapter import HTTPTargetAdapter
from .providers import PRESETS, ProviderPreset, resolve_provider

__all__ = [
    "PRESETS",
    "AdapterRequest",
    "AdapterResponse",
    "HTTPTargetAdapter",
    "ProviderPreset",
    "TargetAdapter",
    "build_target",
    "resolve_provider",
    "resolve_target_info",
]


def _resolve_base_url(target_name: str, target, preset: ProviderPreset) -> str:
    base_url = target.base_url or preset.base_url
    if not base_url:
        raise ConfigError(
            f"target {target_name!r} has no base_url and provider {preset.name!r} "
            f"defines no default; set base_url on the target"
        )
    return base_url


def resolve_target_info(name: str, config: GauntletConfig) -> dict:
    """Return provider/model/base_url/api_style for a target without reading env vars."""
    target = config.targets.get(name)
    if target is None:
        known = ", ".join(sorted(config.targets)) or "(none)"
        raise ConfigError(f"unknown target {name!r}; configured targets: {known}")

    # Fix #10: non-http targets have no provider/preset; return synthetic info (no
    # resolve_provider, which would fail on provider=None) so --dry-run still prints.
    if target.type != "http":
        if target.type == "mcp":
            mcp = target.mcp
            model = (mcp.url or " ".join(mcp.command or [])) if mcp else name
            base_url = (mcp.url if mcp else None) or "(mcp stdio)"
        else:  # python / agent
            model = target.entrypoint or name
            base_url = "(in-process)"
        return {
            "provider": target.type,
            "model": model,
            "base_url": base_url,
            "api_style": "n/a",
        }

    preset = resolve_provider(target.provider, config)
    return {
        "provider": preset.name,
        "model": target.model,
        "base_url": _resolve_base_url(name, target, preset),
        "api_style": preset.api_style,
    }


def build_target(
    name: str,
    config: GauntletConfig,
    client: httpx.AsyncClient | None = None,
    dry_run: bool = False,
) -> TargetAdapter:
    """Build a TargetAdapter for the named target, dispatching by ``type``.

    With dry_run=True, env-var key resolution AND client construction are skipped, so
    the call works fully offline with no keys set. When client is None (and not
    dry_run), the adapter owns the client it creates and the caller must close it.
    Non-http types build offline shells (no callable invocation, no MCP connect).
    """
    target = config.targets.get(name)
    if target is None:
        known = ", ".join(sorted(config.targets)) or "(none)"
        raise ConfigError(f"unknown target {name!r}; configured targets: {known}")

    if target.type in ("python", "agent"):
        from ..agents import load_callable
        from .python_adapter import AgentSandboxAdapter, PythonCallableAdapter

        fn = load_callable(target.entrypoint)
        adapter_cls = PythonCallableAdapter if target.type == "python" else AgentSandboxAdapter
        return adapter_cls(fn, name=name, entrypoint=target.entrypoint)

    if target.type == "mcp":
        # Construction stays offline — the real `mcp` import only fires on connect/send.
        from .mcp_adapter import MCPTargetAdapter

        return MCPTargetAdapter(name=name, config=target.mcp)

    preset = resolve_provider(target.provider, config)
    base_url = _resolve_base_url(name, target, preset)

    if dry_run:
        return HTTPTargetAdapter(
            name=name,
            preset=preset,
            model=target.model,
            base_url=base_url,
            api_key=None,
            client=None,
            extra_headers=target.extra_headers,
            owns_client=False,
        )

    api_key_env = target.api_key_env or preset.api_key_env
    api_key = os.environ.get(api_key_env) if api_key_env else None

    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=config.run.request_timeout_s)

    return HTTPTargetAdapter(
        name=name,
        preset=preset,
        model=target.model,
        base_url=base_url,
        api_key=api_key,
        client=client,
        extra_headers=target.extra_headers,
        owns_client=owns_client,
    )
