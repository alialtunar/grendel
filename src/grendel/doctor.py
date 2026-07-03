"""`grendel doctor` — a plain-CLI status & diagnostics report (the welcome/status view).

Pure: ``build_doctor_report(cfg, *, env, color)`` returns a multi-section string (Install, Catalog,
Env keys, Targets, Proxy) with a context-aware "next: …" hint. It is presence-only — it reports
whether each provider's API-key env var is SET (✓/✗), never the value — so it is safe to print and
to assert in tests. The env is injected (defaults to ``os.environ``) so the report is deterministic
under test; ``color`` adds ANSI styling for a terminal.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping

import typer

from .config import GrendelConfig
from .errors import ConfigError, PackError
from .packloader import list_packs
from .targets import PRESETS


def _style(text: str, color: bool, **kw) -> str:
    return typer.style(text, **kw) if color else text


def _version() -> str:
    try:
        from importlib.metadata import PackageNotFoundError, version

        try:
            return version("grendel")
        except PackageNotFoundError:
            return "unknown (not installed)"
    except Exception:  # noqa: BLE001 — a diagnostics report must never itself crash
        return "unknown"


def _catalog_lines(cfg: GrendelConfig) -> list[str]:
    try:
        infos = list_packs(config=cfg)
    except (PackError, ConfigError) as exc:
        return [f"  error reading catalog: {exc}", "  fix: check catalog.pack_dirs / --pack-dir"]
    if not infos:
        return ["  (no packs found)"]
    by_cat = Counter(i.category for i in infos)
    by_src = Counter(i.source.value for i in infos)
    lines = [f"  {len(infos)} packs total"]
    lines.append("  by category: " + ", ".join(f"{c}={n}" for c, n in sorted(by_cat.items())))
    lines.append("  by source:   " + ", ".join(f"{s}={n}" for s, n in sorted(by_src.items())))
    return lines


def _env_key_lines(env: Mapping[str, str], color: bool, unicode: bool) -> list[str]:
    yes, no = ("✓", "✗") if unicode else ("[set]", "[   ]")
    lines: list[str] = []
    for name, preset in PRESETS.items():
        var = preset.api_key_env
        if var is None:
            lines.append(f"  {name:<18} (no key needed)")
        elif env.get(var):
            lines.append(f"  {name:<18} {_style(yes, color, fg=typer.colors.GREEN)} {var} set")
        else:
            lines.append(f"  {name:<18} {_style(no, color, fg=typer.colors.RED)} {var} not set")
    return lines


def _next_hint(cfg: GrendelConfig) -> str:
    """A context-aware next step: configure a target if none, else run against one."""
    if not cfg.targets:
        return "next: grendel run --provider openai --model gpt-4o-mini --pack jailbreak --dry-run"
    name = next(iter(cfg.targets))
    return f"next: grendel run --target {name} --pack jailbreak"


def build_doctor_report(
    cfg: GrendelConfig,
    *,
    env: Mapping[str, str] | None = None,
    color: bool = False,
    unicode: bool = True,
) -> str:
    """Return the inline status report. ``env`` defaults to the real environment (presence-only)."""
    if env is None:
        import os

        env = os.environ

    dash = "—" if unicode else "-"

    def head(text: str) -> str:
        return _style(text, color, fg=typer.colors.BRIGHT_CYAN, bold=True)

    out: list[str] = []
    out.append(head("Install"))
    out.append(f"  grendel {_version()}")
    out.append("")
    out.append(head("Catalog"))
    out.extend(_catalog_lines(cfg))
    out.append("")
    out.append(head("Provider API keys") + f" (presence only {dash} values never shown)")
    out.extend(_env_key_lines(env, color, unicode))
    out.append("")
    out.append(head("Targets"))
    if cfg.targets:
        for name, tgt in cfg.targets.items():
            desc = f"{tgt.type} {tgt.provider or ''}/{tgt.model or ''}".rstrip("/")
            out.append(f"  {name}: {desc}")
    else:
        out.append(f"  (none) {dash} add one with: grendel config")
    out.append("")
    out.append(head("Proxy"))
    routes = cfg.proxy.routes
    out.append(f"  {cfg.proxy.host}:{cfg.proxy.port}  routes={len(routes)}")
    for path in sorted(routes):
        out.append(f"    {path} -> {routes[path]}")
    out.append("")
    out.append(_style(_next_hint(cfg), color, fg=typer.colors.GREEN))
    return "\n".join(out)
