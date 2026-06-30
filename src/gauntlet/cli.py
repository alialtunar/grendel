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
from .packloader import default_packs_dir, list_packs, load_packs
from .records import RunRecord, make_run_record
from .runner import Runner
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


def _select_attacks(attacks, pack):
    """Filter attacks by --pack values (each matches an attack id or category).

    Returns the selected attacks. A requested --pack matching nothing raises a usage
    error (exit 2). No --pack -> all attacks.
    """
    if not pack:
        return list(attacks)
    requested = set(pack)
    selected = [a for a in attacks if a.id in requested or a.category in requested]
    matched = {a.id for a in attacks} | {a.category for a in attacks}
    unknown = sorted(requested - matched)
    if unknown:
        typer.echo(f"unknown --pack value(s): {', '.join(unknown)}", err=True)
        raise typer.Exit(code=2)
    return selected


async def _execute(adapter, options, attacks, record) -> None:
    try:
        await Runner(adapter, options).run(attacks, record)
    finally:
        await adapter.aclose()


def _summary(record, path: Path | None) -> str:
    executed = sum(1 for a in record.attempts if a.verdict.value == "skipped")
    errors = sum(1 for a in record.attempts if a.verdict.value == "error")
    usage = record.total_usage
    where = str(path) if path is not None else "(not written)"
    return (
        f"run {record.run_id}: target={record.target_name} "
        f"attempts={record.total_attempts} executed={executed} error={errors} "
        f"tokens={usage.total_tokens} est_cost=${record.total_cost_usd:.4f} -> {where}"
    )


@app.command()
def run(
    ctx: typer.Context,
    target: Annotated[str, typer.Option("--target", help="Name of the configured target.")],
    pack: Annotated[
        list[str] | None, typer.Option("--pack", help="Attack pack id or category.")
    ] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Resolve + plan only; no network.")] = (
        False
    ),
    resume: Annotated[
        Path | None, typer.Option("--resume", help="Resume a RunRecord JSON in place.")
    ] = None,
    out: Annotated[
        Path | None, typer.Option("--out", help="Also write the run record here.")
    ] = None,
    config: ConfigOpt = None,
) -> None:
    """Run selected attack packs against a target, recording every attempt."""
    cfg = _resolve_config(ctx, config)
    pack = pack or []
    try:
        info = resolve_target_info(target, cfg)
        adapter = build_target(target, cfg, dry_run=dry_run)
        attacks = load_packs(default_packs_dir())
    except ConfigError as exc:
        typer.echo(f"config error: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    except PackError as exc:
        typer.echo(f"pack error: {exc}", err=True)
        raise typer.Exit(code=2) from exc

    # --- dry run: plan only, no network, no record ---
    if dry_run:
        selected = _select_attacks(attacks, pack)
        typer.echo(
            f"target {target!r}: provider={info['provider']} model={info['model']} "
            f"base_url={info['base_url']} (api_style={info['api_style']})"
        )
        typer.echo(f"plan: {len(selected)} attack(s)")
        for atk in selected:
            typer.echo(f"  {atk.id}")
        typer.echo("est. cost: $0.00 (not sent)")
        return

    # --- resume: re-derive selection from the record's pack_ids ---
    if resume is not None:
        if not resume.exists():
            typer.echo(f"resume record not found: {resume}", err=True)
            raise typer.Exit(code=2)
        record = RunRecord.from_json(resume.read_text(encoding="utf-8"))
        wanted = set(record.pack_ids)
        selected = [a for a in attacks if a.id in wanted]
        cfg.run.output_dir = resume.parent
    else:
        selected = _select_attacks(attacks, pack)
        record = make_run_record(
            target_name=target,
            provider=info["provider"],
            model=info["model"],
            config=cfg,
            pack_ids=[a.id for a in selected],
        )

    log.info("run dispatch", extra={"target": target, "attacks": len(selected)})
    asyncio.run(_execute(adapter, cfg.run, selected, record))

    record_path = Runner(adapter, cfg.run).run_path(record)
    if resume is not None:
        resume.write_text(record.to_json(), encoding="utf-8")
        record_path = resume
    if out is not None:
        out.write_text(record.to_json(), encoding="utf-8")

    typer.echo(_summary(record, out or record_path))


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
