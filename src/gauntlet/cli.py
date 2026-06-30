"""The gauntlet Typer CLI: run / list / report (Phase 1 stubs)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Annotated

import typer

from .config import load_config
from .errors import ConfigError, PackError
from .logging_setup import configure_logging, get_logger
from .packloader import default_packs_dir, list_packs
from .records import RunRecord
from .targets import PRESETS, build_target, resolve_target_info

app = typer.Typer(
    name="gauntlet",
    help="Red-team your AI agents with authorized attack packs.",
    no_args_is_help=True,
)

log = get_logger("cli")

ConfigOpt = Annotated[
    Path | None, typer.Option("--config", "-c", help="Path to a gauntlet YAML config file.")
]


def _resolve_config(ctx: typer.Context, config: Path | None):
    """Return the config to use: a per-command --config overrides the global one."""
    if config is not None:
        try:
            return load_config(config)
        except ConfigError as exc:
            typer.echo(f"config error: {exc}", err=True)
            raise typer.Exit(code=2) from exc
    return ctx.obj["config"]


@app.callback()
def main(
    ctx: typer.Context,
    config: Annotated[
        Path | None, typer.Option("--config", "-c", help="Path to a gauntlet YAML config file.")
    ] = None,
    log_level: Annotated[
        str | None, typer.Option("--log-level", help="Override log level.")
    ] = None,
    log_format: Annotated[
        str | None, typer.Option("--log-format", help="Override log format (json/text).")
    ] = None,
) -> None:
    """Load config + configure logging into the Typer context."""
    try:
        cfg = load_config(config)
    except ConfigError as exc:
        typer.echo(f"config error: {exc}", err=True)
        raise typer.Exit(code=2) from exc

    level = log_level or cfg.log.level
    fmt = log_format or cfg.log.format
    configure_logging(level=level, fmt=fmt)

    ctx.ensure_object(dict)
    ctx.obj["config"] = cfg


@app.command()
def run(
    ctx: typer.Context,
    target: Annotated[str, typer.Option("--target", help="Name of the configured target.")],
    pack: Annotated[
        list[str] | None, typer.Option("--pack", help="Attack pack id (Phase 2+).")
    ] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Resolve only; no network.")] = False,
    out: Annotated[
        Path | None, typer.Option("--out", help="Where to write the run record.")
    ] = None,
    config: ConfigOpt = None,
) -> None:
    """Resolve a target and report what would run (no attacks exist until Phase 2)."""
    cfg = _resolve_config(ctx, config)
    pack = pack or []
    try:
        info = resolve_target_info(target, cfg)
        adapter = build_target(target, cfg, dry_run=dry_run)
    except ConfigError as exc:
        typer.echo(f"config error: {exc}", err=True)
        raise typer.Exit(code=2) from exc

    if not dry_run:
        # Close the client we just created; Phase 1 sends nothing.
        asyncio.run(adapter.aclose())

    log.info(
        "run dispatch",
        extra={"target": target, "dry_run": dry_run, "packs": pack},
    )
    typer.echo(
        f"target {target!r}: provider={info['provider']} model={info['model']} "
        f"base_url={info['base_url']} (api_style={info['api_style']})"
    )
    if out:
        typer.echo(f"would write run record to: {out}")
    typer.echo("no attack packs available until Phase 2; nothing to run.")


@app.command(name="list")
def list_(
    ctx: typer.Context,
    targets: bool = typer.Option(False, "--targets", help="List configured targets."),
    providers: bool = typer.Option(False, "--providers", help="List known providers."),
    packs: bool = typer.Option(False, "--packs", help="List attack packs (Phase 2+)."),
    config: ConfigOpt = None,
) -> None:
    """List configured targets, known providers, or attack packs."""
    cfg = _resolve_config(ctx, config)
    show_all = not (targets or providers or packs)

    if targets or show_all:
        typer.echo("Targets:")
        if cfg.targets:
            for name, tgt in cfg.targets.items():
                typer.echo(f"  {name}: provider={tgt.provider} model={tgt.model}")
        else:
            typer.echo("  (none configured)")

    if providers or show_all:
        typer.echo("Providers:")
        for name, preset in PRESETS.items():
            typer.echo(f"  {name} (preset, api_style={preset.api_style})")
        for name, custom in cfg.providers.items():
            typer.echo(f"  {name} (custom, api_style={custom.api_style})")

    if packs or show_all:
        try:
            infos = list_packs(default_packs_dir())
        except PackError as exc:
            typer.echo(f"pack error: {exc}", err=True)
            raise typer.Exit(code=2) from exc

        typer.echo("Packs:")
        by_category: dict[str, list] = {}
        for info in infos:
            by_category.setdefault(info.category, []).append(info)
        for category, rows in by_category.items():
            typer.echo(f"  {category} ({len(rows)}):")
            for info in rows:
                suffix = "" if info.license_ok else " (unlisted license)"
                typer.echo(
                    f"    {info.id:<42} {info.owasp}  {info.atlas:<12} "
                    f"{info.severity.value:<9} {info.success_type:<6} "
                    f"[{info.license}]{suffix}"
                )


@app.command()
def report(
    ctx: typer.Context,
    run: Annotated[Path, typer.Option("--run", help="Path to a RunRecord JSON file.")],
    format: Annotated[str, typer.Option("--format", help="Output format: text or json.")] = "text",
) -> None:
    """Load a RunRecord JSON and print a summary."""
    if not run.exists():
        typer.echo(f"run record not found: {run}", err=True)
        raise typer.Exit(code=2)

    try:
        record = RunRecord.from_json(run.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 — surface any parse failure as a usage error
        typer.echo(f"invalid run record {run}: {exc}", err=True)
        raise typer.Exit(code=2) from exc

    if format == "json":
        typer.echo(
            json.dumps(
                {
                    "run_id": record.run_id,
                    "target_name": record.target_name,
                    "status": record.status.value,
                    "total_attempts": record.total_attempts,
                    "asr": record.asr,
                }
            )
        )
        return

    typer.echo(f"Run {record.run_id}")
    typer.echo(f"  target: {record.target_name} ({record.provider}/{record.model})")
    typer.echo(f"  status: {record.status.value}")
    typer.echo(f"  attempts: {record.total_attempts}")
    typer.echo(f"  ASR: {record.asr:.2%}")
