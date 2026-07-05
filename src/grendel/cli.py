"""The grendel Typer CLI: run / list / report (Phase 1 stubs)."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Annotated

import click
import typer
from pydantic import ValidationError

from .config import GrendelConfig, load_config
from .controls import load_controls
from .errors import ConfigError, FeedError, PackError
from .feed import update_feeds
from .judge import AdapterJudge, get_rubric
from .logging_setup import configure_logging, get_logger
from .packloader import Source, list_packs, load_catalog
from .records import RunRecord, make_run_record
from .runner import Runner
from .scoring import LexicalClassifier, Scorer
from .targets import PRESETS, build_target, resolve_target_info
from .targets.providers import API_PATHS, resolve_provider

app = typer.Typer(
    name="grendel",
    help="Red-team your AI agents with authorized attack packs.",
)

log = get_logger("cli")

ConfigOpt = Annotated[
    Path | None, typer.Option("--config", "-c", help="Path to a grendel YAML config file.")
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


def _autodiscover_config(config: Path | None, no_config: bool) -> Path | None:
    """Pick up a cwd ./grendel.yaml when no -c/--no-config is given (GRENDEL_NO_AUTOCONFIG off).

    Shared by the subcommand path and the TTY home-menu path so auto-discovery isn't duplicated.
    """
    if config is None and not no_config and not os.environ.get("GRENDEL_NO_AUTOCONFIG"):
        auto = Path("grendel.yaml")
        if auto.is_file():
            typer.echo("(using ./grendel.yaml)", err=True)
            return auto
    return config


def _load_startup_config(config: Path | None) -> GrendelConfig:
    """load_config with the standard usage-error handling (exit 2 on a bad config)."""
    try:
        return load_config(config)
    except ConfigError as exc:
        typer.echo(f"config error: {exc}", err=True)
        raise typer.Exit(code=2) from exc


def _merge_local_secrets() -> None:
    """Merge a cwd grendel.local.yaml into the environment (only for unset vars).

    Suppressed by GRENDEL_NO_LOCAL_SECRETS (set for the test suite so a stray file never leaks).
    A malformed file is a clean usage error (exit 2), not a traceback.
    """
    if os.environ.get("GRENDEL_NO_LOCAL_SECRETS"):
        return
    from .secrets import LOCAL_SECRETS_FILE, load_local_secrets, merge_secrets_into_env

    try:
        secrets = load_local_secrets(Path(LOCAL_SECRETS_FILE))
    except ConfigError as exc:
        typer.echo(f"local secrets error: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    merge_secrets_into_env(secrets, os.environ)


def _wants_home_menu(no_menu: bool) -> bool:
    """Whether bare `grendel` opens the interactive home menu (vs. printing the banner).

    Precedence: --no-menu / GRENDEL_NO_MENU force the banner; GRENDEL_FORCE_MENU forces the menu
    (a deterministic test/power-user seam since CliRunner can't present a real TTY); otherwise the
    menu opens only on a real terminal (both stdin and stdout are TTYs).
    """
    import sys

    if no_menu or os.environ.get("GRENDEL_NO_MENU"):
        return False
    if os.environ.get("GRENDEL_FORCE_MENU"):
        return True
    return sys.stdin.isatty() and sys.stdout.isatty()


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    config: Annotated[
        Path | None, typer.Option("--config", "-c", help="Path to a grendel YAML config file.")
    ] = None,
    no_config: Annotated[
        bool,
        typer.Option("--no-config", help="Ignore any ./grendel.yaml; use built-in defaults."),
    ] = False,
    no_menu: Annotated[
        bool,
        typer.Option("--no-menu", help="Bare `grendel` prints the banner, not the home menu."),
    ] = False,
    log_level: Annotated[
        str | None, typer.Option("--log-level", help="Override log level.")
    ] = None,
    log_format: Annotated[
        str | None, typer.Option("--log-format", help="Override log format (json/text).")
    ] = None,
) -> None:
    """Load config + configure logging into the Typer context."""
    # Make every console write crash-proof on a non-UTF-8 terminal (un-encodable glyphs degrade
    # to ASCII) before we print anything. Runs for the banner and every subcommand.
    from .banner import install_console_fallback

    install_console_fallback()

    # Bare `grendel` (no subcommand): open the interactive home menu on a real terminal, else print
    # the branded landing banner. Non-TTY (pipe/CI/tests) stays on the banner path — byte-identical
    # to before — and, like today, loads NO config there.
    if ctx.invoked_subcommand is None:
        import sys

        from .banner import render_banner, stream_supports_unicode

        if _wants_home_menu(no_menu):
            _merge_local_secrets()
            eff = _autodiscover_config(config, no_config)
            cfg = _load_startup_config(eff)
            _home_menu(cfg, eff or Path("grendel.yaml"))
            raise typer.Exit()
        uni = stream_supports_unicode(sys.stdout)
        typer.echo(render_banner(color=sys.stdout.isatty(), unicode=uni))
        raise typer.Exit()

    _merge_local_secrets()
    config = _autodiscover_config(config, no_config)
    cfg = _load_startup_config(config)

    level = log_level or cfg.log.level
    fmt = log_format or cfg.log.format
    configure_logging(level=level, fmt=fmt)

    ctx.ensure_object(dict)
    ctx.obj["config"] = cfg


def _load_attacks(cfg):
    """The single armed-attack load point (Fix #1): merged multi-source catalog.

    With an empty ``catalog`` this is byte-identical to the bundled set. Both ``run``
    paths call this; tests monkeypatch it.
    """
    return [e.attack for e in load_catalog(cfg) if e.armed]


_MENU_ATTACK_CACHE: dict = {}  # session cache: catalog signature -> loaded attacks (menu path only)


def _catalog_sig(cfg):
    """A hashable signature of the catalog sources; changes when the user edits dirs/imports."""
    c = cfg.catalog
    return (
        tuple(sorted(str(d) for d in c.pack_dirs)),
        str(c.feed_cache_dir),
        str(c.staged_dir),
        bool(c.allow_override),
        bool(c.allow_unlisted_licenses),
    )


def _menu_load_attacks(cfg):
    """Load the armed catalog for the menu run, cached per catalog signature within the session.

    A large imported catalog (thousands of YAML files) takes many seconds to read the FIRST time —
    print a notice so the wait doesn't look like a freeze — then reuse it on subsequent runs.
    """
    sig = _catalog_sig(cfg)
    cached = _MENU_ATTACK_CACHE.get(sig)
    if cached is not None:
        return cached
    typer.echo("  loading attack catalog… (first run may take a moment for a large catalog)")
    attacks = _load_attacks(cfg)  # module-level, still monkeypatchable in tests
    _MENU_ATTACK_CACHE[sig] = attacks
    return attacks


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


async def _execute(
    adapter, options, attacks, record, *, controls=(), scorer=None, judge_adapter=None,
    on_attempt=None,
) -> None:
    try:
        await Runner(adapter, options, scorer=scorer, on_attempt=on_attempt).run(
            attacks, record, controls=controls
        )
    finally:
        await adapter.aclose()
        if judge_adapter is not None:
            await judge_adapter.aclose()


def _summary(record, path: Path | None) -> str:
    m = record.metrics_summary()
    usage = record.total_usage
    where = str(path) if path is not None else "(not written)"
    util = ""
    if m["controls"]["total"] > 0:
        u = m["utility_under_attack"]
        util = f" utility={u:.2%}" if u is not None else " utility=n/a"
    return (
        f"run {record.run_id}: target={record.target_name} "
        f"attempts={record.total_attempts} succeeded={m['succeeded']} "
        f"defended={m['defended']} error={m['errored']} asr={m['overall_asr']:.2%}{util} "
        f"tokens={usage.total_tokens} est_cost=${record.total_cost_usd:.4f} -> {where}"
    )


def _apply_gate(record: RunRecord, fail_under: float | None) -> None:
    """The CI regression gate (spec §4): exit 3 when overall ASR exceeds the threshold.

    Called at the END of both the plain and the TUI run paths — after the record is
    persisted and the summary printed — so CI still gets the artifact on a gate trip.
    A None threshold (the default) is a no-op.
    """
    if fail_under is None:
        return
    if record.metrics_summary()["overall_asr"] > fail_under:
        raise typer.Exit(code=3)


def _build_scorer(cfg, *, judge=None, judge_config=None) -> Scorer:
    """Build a Scorer wired with the (overridable) cfg.scoring vocabulary.

    Applied on every run path — judge on or off — so the config's scoring section is the
    single source for the T1 refusal markers, T2 lexicons, and T3 contested criteria.
    """
    s = cfg.scoring
    classifier = LexicalClassifier(compliant=s.compliant_lexicon, refusal=s.refusal_lexicon)
    return Scorer(
        classifier,
        judge=judge,
        judge_config=judge_config,
        refusal_markers=s.refusal_markers,
        contested_criteria=s.contested_criteria,
    )


def _build_judge_scorer(cfg, *, dry_run: bool):
    """Build a judge-enabled Scorer + its (separate) adapter; exit 2 on bad config (Fix #2)."""
    target = cfg.judge.target
    if not target:
        typer.echo("judge enabled but no judge target configured (set judge.target)", err=True)
        raise typer.Exit(code=2)
    try:
        rubric = get_rubric(cfg.judge.rubric_version)
        judge_adapter = build_target(target, cfg, dry_run=dry_run)
    except ConfigError as exc:
        typer.echo(f"judge config error: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    judge = AdapterJudge(
        judge_adapter,
        rubric,
        temperature=cfg.judge.temperature,
        max_tokens=cfg.judge.max_tokens,
    )
    return _build_scorer(cfg, judge=judge, judge_config=cfg.judge), judge_adapter


_CLI_TARGET_NAME = "cli"  # synthetic name for a flag-defined target injected into cfg.targets


def _cli_target(
    cfg,
    *,
    target: str | None,
    provider: str | None,
    model: str | None,
    base_url: str | None,
    api_key_env: str | None,
    header: list[str],
    python: str | None,
    agent: str | None,
    mcp_command: str | None,
    mcp_url: str | None,
    mcp_fake_client: str | None,
    mcp_tool: str | None,
):
    """Synthesize a target from CLI flags (no config needed) and return (name, augmented cfg).

    Returns ``None`` when no target flags are given (the caller falls back to ``--target``).
    Enforces exactly-one-source; every violation is a usage error (exit 2).
    """
    from .config import build_cli_target_config

    def _die(msg: str):
        typer.echo(msg, err=True)
        raise typer.Exit(code=2)

    try:
        tc = build_cli_target_config(
            target=target,
            provider=provider,
            model=model,
            base_url=base_url,
            api_key_env=api_key_env,
            header=header,
            python=python,
            agent=agent,
            mcp_command=mcp_command,
            mcp_url=mcp_url,
            mcp_fake_client=mcp_fake_client,
            mcp_tool=mcp_tool,
        )
    except ConfigError as exc:
        _die(str(exc))
    if tc is None:
        return None  # only --target (or nothing) — caller handles the nothing case
    try:
        return _CLI_TARGET_NAME, cfg.with_cli_target(_CLI_TARGET_NAME, tc)
    except ConfigError as exc:
        _die(f"config error: {exc}")


@app.command(
    epilog="Example: grendel run --provider openai --model gpt-4o-mini --pack jailbreak --dry-run",
)
def run(
    ctx: typer.Context,
    target: Annotated[
        str | None, typer.Option("--target", help="Name of a configured target.")
    ] = None,
    provider: Annotated[
        str | None, typer.Option("--provider", help="HTTP target provider (with --model).")
    ] = None,
    model: Annotated[
        str | None, typer.Option("--model", help="HTTP target model (with --provider).")
    ] = None,
    base_url: Annotated[
        str | None, typer.Option("--base-url", help="HTTP target base_url override.")
    ] = None,
    api_key_env: Annotated[
        str | None, typer.Option("--api-key-env", help="Env var holding the HTTP target API key.")
    ] = None,
    header: Annotated[
        list[str] | None, typer.Option("--header", help="Extra HTTP header key=value (repeatable).")
    ] = None,
    python: Annotated[
        str | None, typer.Option("--python", help="Python-callable target 'module:attr'.")
    ] = None,
    agent: Annotated[
        str | None, typer.Option("--agent", help="Agent-sandbox target 'module:attr'.")
    ] = None,
    mcp_command: Annotated[
        str | None, typer.Option("--mcp-command", help="MCP stdio server launch command.")
    ] = None,
    mcp_url: Annotated[str | None, typer.Option("--mcp-url", help="MCP server URL.")] = None,
    mcp_fake_client: Annotated[
        str | None,
        typer.Option("--mcp-fake-client", help="In-memory MCP client factory 'module:attr'."),
    ] = None,
    mcp_tool: Annotated[
        str | None, typer.Option("--mcp-tool", help="Default MCP tool to probe.")
    ] = None,
    output_dir: Annotated[
        Path | None, typer.Option("--output-dir", help="Directory to write run records into.")
    ] = None,
    pack_dir: Annotated[
        list[Path] | None,
        typer.Option("--pack-dir", help="Extra user pack directory (repeatable)."),
    ] = None,
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
    judge: Annotated[
        bool | None,
        typer.Option("--judge/--no-judge", help="Enable the T3 LLM-judge (default: config)."),
    ] = None,
    controls: Annotated[
        bool, typer.Option("--controls/--no-controls", help="Also run benign controls.")
    ] = False,
    fail_under: Annotated[
        float | None,
        typer.Option(
            "--fail-under",
            help="Fail (exit 3) if overall ASR exceeds this threshold [0.0-1.0]; CI gate.",
        ),
    ] = None,
    config: ConfigOpt = None,
) -> None:
    """Run selected attack packs against a target, recording every attempt."""
    cfg = _resolve_config(ctx, config)
    pack = pack or []
    if fail_under is not None and not (0.0 <= fail_under <= 1.0):
        typer.echo(f"--fail-under must be in [0.0, 1.0], got {fail_under}", err=True)
        raise typer.Exit(code=2)

    # Flag-defined target (no config file needed). Synthesizes + validates a target and returns
    # (name, augmented cfg); None when only --target is used.
    flag_target = _cli_target(
        cfg,
        target=target,
        provider=provider,
        model=model,
        base_url=base_url,
        api_key_env=api_key_env,
        header=header or [],
        python=python,
        agent=agent,
        mcp_command=mcp_command,
        mcp_url=mcp_url,
        mcp_fake_client=mcp_fake_client,
        mcp_tool=mcp_tool,
    )
    if flag_target is not None:
        target, cfg = flag_target
    elif target is None:
        typer.echo(
            "specify a target: --target NAME, or --provider/--model, --python, --agent, --mcp-*",
            err=True,
        )
        typer.echo(
            "  try:  grendel run --provider openai --model gpt-4o-mini --pack jailbreak\n"
            "  or:   grendel config   (to add a named target)",
            err=True,
        )
        raise typer.Exit(code=2)

    # CLI-driven dirs (config-free): output dir (resume overrides below) and extra pack dirs.
    if output_dir is not None:
        cfg.run.output_dir = output_dir
    if pack_dir:
        cfg.catalog.pack_dirs = [*cfg.catalog.pack_dirs, *pack_dir]

    try:
        info = resolve_target_info(target, cfg)
        adapter = build_target(target, cfg, dry_run=dry_run)
        attacks = _load_attacks(cfg)
    except ConfigError as exc:
        typer.echo(f"config error: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    except PackError as exc:
        typer.echo(f"pack error: {exc}", err=True)
        raise typer.Exit(code=2) from exc

    judge_enabled = cfg.judge.enabled if judge is None else judge
    judge_adapter = None
    if judge_enabled:
        scorer, judge_adapter = _build_judge_scorer(cfg, dry_run=dry_run)
    else:
        scorer = _build_scorer(cfg)

    control_items: tuple = ()
    if controls:
        try:
            control_items = tuple(load_controls())
        except PackError as exc:
            typer.echo(f"control error: {exc}", err=True)
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

    asyncio.run(
        _execute(
            adapter,
            cfg.run,
            selected,
            record,
            controls=control_items,
            scorer=scorer,
            judge_adapter=judge_adapter,
        )
    )

    record_path = Runner(adapter, cfg.run).run_path(record)
    if resume is not None:
        resume.write_text(record.to_json(), encoding="utf-8")
        record_path = resume
    if out is not None:
        out.write_text(record.to_json(), encoding="utf-8")

    typer.echo(_summary(record, out or record_path))
    typer.echo(f"  next: grendel report --run {out or record_path} --format md")
    _apply_gate(record, fail_under)


@app.command(
    name="list",
    epilog="Example: grendel list --packs --category jailbreak",
)
def list_(
    ctx: typer.Context,
    targets: bool = typer.Option(False, "--targets", help="List configured targets."),
    providers: bool = typer.Option(False, "--providers", help="List known providers."),
    packs: bool = typer.Option(False, "--packs", help="List attack packs (Phase 2+)."),
    staged: bool = typer.Option(False, "--staged", help="Include staged (not-armed) packs."),
    category: Annotated[
        str | None, typer.Option("--category", help="Only show packs in this category.")
    ] = None,
    source: Annotated[
        str | None,
        typer.Option("--source", help="Only show packs from this source (bundled/user/feed)."),
    ] = None,
    pack_dir: Annotated[
        list[Path] | None,
        typer.Option("--pack-dir", help="Extra user pack directory (repeatable)."),
    ] = None,
    config: ConfigOpt = None,
) -> None:
    """List configured targets, known providers, or attack packs."""
    cfg = _resolve_config(ctx, config)
    if pack_dir:
        cfg.catalog.pack_dirs = [*cfg.catalog.pack_dirs, *pack_dir]
    show_all = not (targets or providers or packs)

    if targets or show_all:
        typer.echo("Targets:")
        if cfg.targets:
            for name, tgt in cfg.targets.items():
                typer.echo(f"  {name}: provider={tgt.provider} model={tgt.model}")
        else:
            typer.echo("  (none configured) — add one with: grendel config")

    if providers or show_all:
        typer.echo("Providers:")
        for name, preset in PRESETS.items():
            typer.echo(f"  {name} (preset, api_style={preset.api_style})")
        for name, custom in cfg.providers.items():
            typer.echo(f"  {name} (custom, api_style={custom.api_style})")

    if packs or show_all:
        try:
            infos = list_packs(config=cfg)
        except (PackError, ConfigError) as exc:
            typer.echo(f"pack error: {exc}", err=True)
            raise typer.Exit(code=2) from exc

        # Staged packs (armed=False) are only shown with --staged (spec §9).
        if not staged:
            infos = [i for i in infos if i.source is not Source.STAGED]

        # Valid values for the filters (from what's actually loaded) — used to nudge on a typo.
        avail_cats = sorted({i.category for i in infos})
        avail_srcs = sorted({i.source.value for i in infos})
        if source is not None and source not in avail_srcs:
            typer.echo(
                f"unknown --source {source!r}; available: {', '.join(avail_srcs) or '(none)'}",
                err=True,
            )
            raise typer.Exit(code=2)
        if category is not None and category not in avail_cats:
            typer.echo(
                f"unknown --category {category!r}; available: {', '.join(avail_cats) or '(none)'}",
                err=True,
            )
            raise typer.Exit(code=2)

        if category is not None:
            infos = [i for i in infos if i.category == category]
        if source is not None:
            infos = [i for i in infos if i.source.value == source]

        filt = []
        if category is not None:
            filt.append(f"category={category}")
        if source is not None:
            filt.append(f"source={source}")
        suffix = f" ({', '.join(filt)})" if filt else ""
        typer.echo(f"Packs: {len(infos)} total{suffix}")
        by_category: dict[str, list] = {}
        for info in infos:
            by_category.setdefault(info.category, []).append(info)
        for cat, rows in by_category.items():
            typer.echo(f"  {cat} ({len(rows)}):")
            for info in rows:
                suffix = "" if info.license_ok else " (unlisted license)"
                staged_tag = " (staged)" if info.source is Source.STAGED else ""
                typer.echo(
                    f"    {info.id:<42} {info.owasp}  {info.atlas:<12} "
                    f"{info.severity.value:<9} {info.success_type:<6} "
                    f"[{info.license}]{suffix} [{info.source.value}]{staged_tag}"
                )


def _emit(rendered: str, out: Path | None, label: str) -> None:
    """Write the rendered report to --out (utf-8) or print it to stdout."""
    if out is not None:
        out.write_text(rendered, encoding="utf-8")
        typer.echo(f"wrote {label} report -> {out}")
    else:
        typer.echo(rendered)


@app.command(
    epilog="Example: grendel report --run runs/<id>.json --format md --out report.md",
)
def report(
    ctx: typer.Context,
    run: Annotated[Path, typer.Option("--run", help="Path to a RunRecord JSON file.")],
    format: Annotated[
        str, typer.Option("--format", help="Output format: text, json, md, or html.")
    ] = "text",
    out: Annotated[
        Path | None, typer.Option("--out", help="Write the rendered report here (else stdout).")
    ] = None,
) -> None:
    """Load a RunRecord JSON and print a summary."""
    from . import reports as reportsmod

    if not run.exists():
        typer.echo(f"run record not found: {run}", err=True)
        raise typer.Exit(code=2)

    try:
        record = RunRecord.from_json(run.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 — surface any parse failure as a usage error
        typer.echo(f"invalid run record {run}: {exc}", err=True)
        raise typer.Exit(code=2) from exc

    if format == "md":
        _emit(reportsmod.render_markdown(record), out, "md")
        return
    if format == "html":
        _emit(reportsmod.render_html(record), out, "html")
        return
    if format == "json":
        rendered = json.dumps(
            {
                "run_id": record.run_id,
                "target_name": record.target_name,
                "status": record.status.value,
                "total_attempts": record.total_attempts,
                "asr": record.asr,
                "metrics": record.metrics_summary(),
            }
        )
        _emit(rendered, out, "json")
        return
    if format != "text":
        typer.echo(f"unknown --format {format!r}; valid values: text, json, md, html", err=True)
        raise typer.Exit(code=2)

    typer.echo(reportsmod.render_text(record))


def _load_record(path: Path) -> RunRecord:
    """Load a RunRecord JSON or exit 2 (the report/diff load convention)."""
    if not path.exists():
        typer.echo(f"run record not found: {path}", err=True)
        raise typer.Exit(code=2)
    try:
        return RunRecord.from_json(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 — surface any parse failure as a usage error
        typer.echo(f"invalid run record {path}: {exc}", err=True)
        raise typer.Exit(code=2) from exc


@app.command(
    epilog="Example: grendel diff runs/before.json runs/after.json --format md",
)
def diff(
    ctx: typer.Context,
    run_a: Annotated[Path, typer.Argument(help="Baseline RunRecord JSON (A).")],
    run_b: Annotated[Path, typer.Argument(help="New RunRecord JSON (B).")],
    format: Annotated[
        str, typer.Option("--format", help="Output format: text, json, or md.")
    ] = "text",
    out: Annotated[
        Path | None, typer.Option("--out", help="Write the rendered diff here (else stdout).")
    ] = None,
) -> None:
    """Diff two run records: ASR deltas, newly-failing/fixed attacks, cost/latency."""
    from . import diff as diffmod

    a = _load_record(run_a)
    b = _load_record(run_b)
    d = diffmod.diff_runs(a, b)

    if format == "text":
        rendered = diffmod.render_text(d)
    elif format == "md":
        rendered = diffmod.render_markdown(d)
    elif format == "json":
        rendered = json.dumps(d.model_dump())
    else:
        typer.echo(f"unknown --format {format!r}; valid values: text, json, md", err=True)
        raise typer.Exit(code=2)

    if out is not None:
        out.write_text(rendered, encoding="utf-8")
        typer.echo(f"wrote diff -> {out}")
    else:
        typer.echo(rendered)


@app.command(
    epilog="Example: grendel update            (pulls all configured catalog.feeds)",
)
def update(
    ctx: typer.Context,
    feed: Annotated[str | None, typer.Option("--feed", help="Update only the named feed.")] = None,
    allow_unlisted_licenses: Annotated[
        bool,
        typer.Option(
            "--allow-unlisted-licenses", help="Pull packs with licenses outside the allowlist."
        ),
    ] = False,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Fetch + verify only; write nothing.")
    ] = False,
    config: ConfigOpt = None,
) -> None:
    """Pull versioned packs from configured feeds into the feed cache."""
    cfg = _resolve_config(ctx, config)

    # Fix #9: --feed NAME that matches no configured feed is a usage error.
    if feed is not None and feed not in {f.name for f in cfg.catalog.feeds}:
        typer.echo(f"no feed named {feed!r} in catalog.feeds", err=True)
        raise typer.Exit(code=2)

    try:
        result = asyncio.run(
            update_feeds(
                cfg,
                feed_name=feed,
                dry_run=dry_run,
                allow_unlisted_licenses=allow_unlisted_licenses,
            )
        )
    except FeedError as exc:
        typer.echo(f"feed error: {exc}", err=True)
        raise typer.Exit(code=2) from exc

    prefix = "[dry-run] " if dry_run else ""
    typer.echo(
        f"{prefix}feeds: pulled {result.pulled} updated {result.updated} "
        f"unchanged {result.unchanged} skipped-license {result.skipped_license} "
        f"checksum-failed {result.checksum_failed} errors {result.errors}"
    )
    for d in result.details:
        if d.action in ("skipped_license", "checksum_failed", "error"):
            who = f"{d.feed}/{d.id}" if d.id else d.feed
            typer.echo(f"  {d.action}: {who} — {d.reason}")


@app.command(
    epilog="Example: grendel proxy --route /openai=openai --pack jailbreak --serve",
)
def proxy(
    ctx: typer.Context,
    host: Annotated[str | None, typer.Option("--host", help="Proxy bind host.")] = None,
    port: Annotated[int | None, typer.Option("--port", help="Proxy bind port [1-65535].")] = None,
    route: Annotated[
        list[str] | None,
        typer.Option("--route", help="Route PATH=PROVIDER (repeatable); PATH starts with '/'."),
    ] = None,
    serve_: Annotated[
        bool, typer.Option("--serve", help="Bind and serve the OpenAI-compatible proxy endpoint.")
    ] = False,
    pack: Annotated[
        list[str] | None,
        typer.Option("--pack", help="Attack pack id or category to inject (repeatable)."),
    ] = None,
    judge: Annotated[
        bool | None,
        typer.Option("--judge/--no-judge", help="Enable the T3 LLM-judge (default: config)."),
    ] = None,
    out: Annotated[
        Path | None, typer.Option("--out", help="Write the run record here on shutdown.")
    ] = None,
    config: ConfigOpt = None,
) -> None:
    """Configure and (with --serve) run the LLM-proxy: a zero-touch OpenAI-compatible endpoint.

    Without --serve, merges/validates host/port/routes and previews the resolved config. With
    --serve, injects the selected attacks into each proxied call, forwards to the routed provider
    carrying the agent's own key, scores the returned tool_calls/text, and records the run.
    """
    from .config import ProxyConfig

    cfg = _resolve_config(ctx, config)
    known_providers = set(PRESETS) | set(cfg.providers)

    routes = dict(cfg.proxy.routes)
    for spec in route or []:
        if "=" not in spec:
            typer.echo(f"--route must be PATH=PROVIDER, got {spec!r}", err=True)
            raise typer.Exit(code=2)
        path, provider = spec.split("=", 1)
        if not path.startswith("/"):
            typer.echo(f"route path {path!r} must start with '/'", err=True)
            raise typer.Exit(code=2)
        if provider not in known_providers:
            typer.echo(
                f"route {path!r} references unknown provider {provider!r}; "
                f"known: {', '.join(sorted(known_providers))}",
                err=True,
            )
            raise typer.Exit(code=2)
        routes[path] = provider  # last-wins on a repeated PATH

    try:
        merged = ProxyConfig(
            host=host if host is not None else cfg.proxy.host,
            port=port if port is not None else cfg.proxy.port,
            routes=routes,
        )
    except (ConfigError, ValidationError) as exc:
        typer.echo(f"proxy config error: {exc}", err=True)
        raise typer.Exit(code=2) from exc

    typer.echo("proxy config:")
    typer.echo(f"  host: {merged.host}")
    typer.echo(f"  port: {merged.port}")
    if merged.routes:
        typer.echo("  routes:")
        for path in sorted(merged.routes):
            typer.echo(f"    {path} -> {merged.routes[path]}")
    else:
        typer.echo("  routes: (none)")

    if not serve_:
        typer.echo("(pass --serve to run the endpoint; this previews the resolved configuration)")
        _echo_proxy_hint()
        return

    # --- serve: bind the endpoint and red-team every proxied call ---
    if not merged.routes:
        typer.echo("--serve requires at least one --route (nothing to route)", err=True)
        raise typer.Exit(code=2)
    cfg.proxy = merged
    try:
        attacks = _select_attacks(_load_attacks(cfg), pack or [])
    except (PackError, ConfigError) as exc:
        typer.echo(f"pack error: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    if not attacks:
        typer.echo("no attacks selected to inject (check --pack)", err=True)
        raise typer.Exit(code=2)

    import httpx

    from .proxy import ProxySession, serve, startup_banner

    judge_adapter = None
    if cfg.judge.enabled if judge is None else judge:
        scorer, judge_adapter = _build_judge_scorer(cfg, dry_run=False)
    else:
        scorer = _build_scorer(cfg)

    session = ProxySession(cfg, attacks, client=httpx.AsyncClient(), scorer=scorer)
    # Persist incrementally (after every proxied call) so a kill/crash never loses the run —
    # the record is complete even without a clean Ctrl-C shutdown.
    record_path = out or (Path(cfg.run.output_dir) / f"{session.record.run_id}.json")
    session.enable_persistence(record_path)
    typer.echo(startup_banner(session, merged.host, merged.port))
    typer.echo(f"  writing run record to {record_path} (updated live)")
    try:
        record = serve(session, merged.host, merged.port)
    finally:
        if judge_adapter is not None:
            asyncio.run(judge_adapter.aclose())

    record_path.parent.mkdir(parents=True, exist_ok=True)
    record_path.write_text(record.to_json(), encoding="utf-8")
    typer.echo(_summary(record, record_path))


@app.command(
    name="import",
    epilog=(
        "Example: grendel import --source garak --out catalog   "
        '(needs `pip install -e ".[corpora]"`; omit --path to auto-discover)'
    ),
)
def import_(
    ctx: typer.Context,
    out: Annotated[Path, typer.Option("--out", help="Catalog directory to write packs into.")],
    path: Annotated[
        Path | None,
        typer.Option("--path", help="Corpus path; omit to auto-discover the source's corpora."),
    ] = None,
    source: Annotated[str, typer.Option("--source", help="Corpus source connector.")] = "garak",
    limit: Annotated[
        int | None, typer.Option("--limit", help="Cap the number of new packs written.")
    ] = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Convert + report only; write nothing.")
    ] = False,
    allow_unlisted_licenses: Annotated[
        bool,
        typer.Option(
            "--allow-unlisted-licenses", help="Import packs with licenses outside the allowlist."
        ),
    ] = False,
) -> None:
    """Import attacks from a public red-team corpus (garak) into a catalog directory.

    Omit --path to auto-discover the source's corpora (garak: its installed jailbreak + DAN sets).
    Re-runnable: only new payloads are added (dedup); existing ones are skipped.
    """
    from . import corpus
    from .corpus import ImportResult

    try:
        if path is None:
            paths = corpus.default_source_paths(source)  # auto-discover (e.g. installed garak data)
            typer.echo(f"auto-discovered {len(paths)} {source} corpora")
        else:
            if not path.exists():
                typer.echo(f"corpus path not found: {path}", err=True)
                raise typer.Exit(code=2)
            paths = [path]
        total = ImportResult()
        for p in paths:  # each call re-scans `out` first, so dedup spans all sources + prior runs
            r = corpus.import_corpus(
                source,
                p,
                out,
                limit=limit,
                allow_unlisted_licenses=allow_unlisted_licenses,
                dry_run=dry_run,
            )
            total.seen += r.seen
            total.imported += r.imported
            total.duplicate += r.duplicate
            total.license_skipped += r.license_skipped
            total.written.extend(r.written)
    except PackError as exc:
        typer.echo(f"import error: {exc}", err=True)
        raise typer.Exit(code=2) from exc

    prefix = "[dry-run] " if dry_run else ""
    typer.echo(
        f"{prefix}imported {total.imported} (seen {total.seen}, duplicate {total.duplicate}, "
        f"license-skipped {total.license_skipped}) -> {out}"
    )
    if not dry_run and total.imported:
        typer.echo(f"load them with: grendel list --packs --pack-dir {out}")


@app.command(
    epilog="Example: grendel doctor        (shows version, catalog, provider keys, targets)",
)
def doctor(ctx: typer.Context, config: ConfigOpt = None) -> None:
    """Print an inline status report: version, catalog totals, provider env-keys, targets, proxy."""
    import sys

    from .banner import stream_supports_unicode
    from .doctor import build_doctor_report

    cfg = _resolve_config(ctx, config)
    typer.echo(
        build_doctor_report(
            cfg, color=sys.stdout.isatty(), unicode=stream_supports_unicode(sys.stdout)
        )
    )


# --- interactive `grendel config` -------------------------------------------------------------
def _parse_int(raw: str, current: int) -> int:
    try:
        return int(raw)
    except (ValueError, TypeError):
        typer.echo(f"  keeping {current} (not an integer)")
        return current


def _parse_float(raw: str, current: float) -> float:
    try:
        return float(raw)
    except (ValueError, TypeError):
        typer.echo(f"  keeping {current} (not a number)")
        return current


def _apply_route(cfg, spec: str) -> None:
    spec = (spec or "").strip()
    if not spec:
        return
    path, _, provider = spec.partition("=")
    if provider:
        cfg.proxy.routes = {**cfg.proxy.routes, path: provider}
    else:
        typer.echo("  skipped route (expected PATH=PROVIDER)")


def _show_targets(cfg) -> None:
    for name, tgt in cfg.targets.items():
        desc = f"{tgt.type} {tgt.provider or ''}/{tgt.model or ''}".rstrip("/")
        typer.echo(f"  {name}: {desc}")
    if not cfg.targets:
        typer.echo("  (none yet — add one below, or use `run` flags)")


def _make_target_config(
    kind, *, provider=None, model=None, base_url=None, api_key_env=None, entrypoint=None
):
    """Build a TargetConfig from menu fields (pure; ConfigError on a bad field/type)."""
    from .config import TargetConfig

    try:
        if kind == "http":
            return TargetConfig(
                type="http",
                provider=provider,
                model=model,
                base_url=(base_url or None),
                api_key_env=(api_key_env or None),
            )
        if kind in ("python", "agent"):
            return TargetConfig(type=kind, entrypoint=entrypoint)
    except ValidationError as exc:
        raise ConfigError(str(exc)) from exc
    raise ConfigError(f"unknown target type {kind!r} (use http/python/agent)")


def _add_target(
    cfg, *, name, kind, provider=None, model=None, base_url=None, api_key_env=None, entrypoint=None
):
    """Return a revalidated config with a new target (add-time validation via with_cli_target)."""
    name = (name or "").strip()
    if not name:
        raise ConfigError("target name is required")
    tc = _make_target_config(
        kind,
        provider=provider,
        model=model,
        base_url=base_url,
        api_key_env=api_key_env,
        entrypoint=entrypoint,
    )
    return cfg.with_cli_target(name, tc)  # raises on duplicate name / unknown provider


def _add_target_tc(cfg, name, tc):
    """Add an already-built TargetConfig under ``name`` (name + duplicate/provider checks)."""
    name = (name or "").strip()
    if not name:
        raise ConfigError("target name is required")
    return cfg.with_cli_target(name, tc)


def _add_custom_agent(cfg, name, *, base_url, path, body, text_path, model="-"):
    """Add a custom-JSON agent: a `custom` provider + a target referencing it (both named ``name``).

    Pure/revalidating. Raises ConfigError on a blank/duplicate name, a provider-name collision
    (a leftover custom provider, distinct from the PRESETS collision the validator checks), or an
    invalid request/response shape. ``_remove_target`` cleans up the paired provider.
    """
    from .config import (
        CustomProviderConfig,
        CustomRequestSpec,
        CustomResponseSpec,
        GrendelConfig,
        TargetConfig,
    )

    name = (name or "").strip()
    if not name:
        raise ConfigError("target name is required")
    if name in cfg.targets:
        raise ConfigError(f"target {name!r} already exists; rename or remove it first")
    if name in cfg.providers:
        raise ConfigError(f"provider {name!r} already exists; choose another name")
    try:
        provider = CustomProviderConfig(
            base_url=base_url,
            api_style="custom",
            request=CustomRequestSpec(path=(path or ""), body=body),
            response=CustomResponseSpec(text_path=text_path),
        )
    except ValidationError as exc:
        raise ConfigError(str(exc)) from exc
    tc = TargetConfig(type="http", provider=name, model=(model or "-"))
    data = cfg.model_dump(mode="python")
    data["providers"] = {**data["providers"], name: provider.model_dump(mode="python")}
    data["targets"] = {**data["targets"], name: tc.model_dump(mode="python")}
    try:
        return GrendelConfig.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(str(exc)) from exc



def describe_target(tc, cfg) -> str:
    """Plain-words resolution of a (not-yet-saved) target: what request/behaviour it produces.

    Reuses the SAME provider/base_url resolution as the runner (via a throwaway preview cfg), so the
    confirmation can't drift from real request building. Raises ConfigError for an invalid target
    (unknown provider, missing base_url/entrypoint) — the caller shows it and returns to the prompt.
    Only ever names the api-key ENV VAR, never a value.
    """
    preview = cfg.with_cli_target("__preview__", tc)  # validates the candidate
    if tc.type in ("python", "agent"):
        return f"in-process call → {tc.entrypoint}"
    if tc.type == "mcp":
        m = tc.mcp
        cmd = " ".join(m.command) if (m and m.command) else None
        where = (m and (m.url or cmd or m.fake_client)) or "?"
        return f"MCP server → {where}"
    info = resolve_target_info("__preview__", preview)
    base = str(info["base_url"]).rstrip("/")
    if info["api_style"] == "custom":
        preset = resolve_provider(info["provider"], preview)
        req_path = (preset.request or {}).get("path", "")
        text_path = (preset.response or {}).get("text_path", "?")
        return f"POST {base}{req_path}  ·  reads response.{text_path}"
    path = API_PATHS.get(info["api_style"], API_PATHS["openai"])
    key_env = tc.api_key_env
    if not key_env:
        provider = info["provider"]
        if provider in PRESETS:
            key_env = PRESETS[provider].api_key_env
        elif provider in cfg.providers:
            key_env = cfg.providers[provider].api_key_env
    key_note = f"key env: {key_env}" if key_env else "no API key needed"
    return f"POST {base}{path}  ·  model {info['model']}  ·  {key_note}"


def _remove_target(cfg, name: str) -> None:
    name = (name or "").strip()
    if name not in cfg.targets:
        raise ConfigError(f"no target named {name!r}")
    provider = cfg.targets[name].provider
    del cfg.targets[name]
    # Clean up a paired custom provider (added by _add_custom_agent under the same name), but
    # only if it's a custom provider no other target still references.
    if (
        provider == name
        and name in cfg.providers
        and not any(t.provider == name for t in cfg.targets.values())
    ):
        del cfg.providers[name]
        typer.echo(f"  (removed custom provider {name!r})")
    if cfg.judge.target == name:
        cfg.judge.target = None
        typer.echo(f"  (cleared judge.target — it referenced {name!r})")


def _known_providers(cfg) -> list[str]:
    """Valid provider names for a target: built-in presets + any custom providers."""
    return sorted(set(PRESETS) | set(cfg.providers))


def _provider_hint(name: str, cfg) -> str:
    """A one-line annotation for a provider: its api_style + base_url (or 'needs base_url')."""
    preset = PRESETS.get(name) or cfg.providers.get(name)
    if preset is None:
        return name
    base = getattr(preset, "base_url", None)
    return f"{name} ({preset.api_style}; {base or 'needs base_url'})"


def _hosted_providers_label(cfg) -> str:
    """The known hosted providers, listed from data (presets + custom), not a hardcoded string.
    Excludes 'openai-compatible' — that's reached via the 'agent' intent (chat URL)."""
    names = [p for p in _known_providers(cfg) if p != "openai-compatible"]
    return " / ".join(names)


def _preset_default_model(provider: str, cfg) -> str:
    """The provider's preset ``default_model`` (data, not a hardcoded literal), or '' if none."""
    try:
        return resolve_provider(provider, cfg).default_model or ""
    except ConfigError:
        return ""


def _preset_models(provider: str, cfg) -> list[str]:
    """The provider's suggested model ids (data, not a closed list), or [] if none/unknown."""
    try:
        return list(resolve_provider(provider, cfg).models)
    except ConfigError:
        return []


_TYPE_ANOTHER = "__type_another__"  # sentinel: "✎ type another model…" escape in the model picker


def _resolve_model_choices(provider: str, cfg) -> tuple[list[str], str]:
    """Model ids + a label for the picker: the provider's LIVE /models when reachable, else the
    preset's static suggestions, else ([], ...) so the caller drops to a typed prompt."""
    from .targets.model_list import fetch_models

    try:
        preset = resolve_provider(provider, cfg)
    except ConfigError:
        return [], "model"
    key = os.environ.get(preset.api_key_env) if preset.api_key_env else None
    live = fetch_models(preset, key)
    if live:
        return live, f"model ({provider} · {len(live)} live)"
    static = list(preset.models)
    if static:
        return static, f"model ({provider} · suggestions)"
    return [], "model"


def _prompt_model(provider: str, cfg) -> str:
    """Prompt for a model. On a TTY: the provider's live models (or static suggestions) as an
    arrow-key list plus a 'type another' escape; otherwise a typed prompt (any model works)."""
    import sys

    default = _preset_default_model(provider, cfg)
    if sys.stdin.isatty():
        try:
            import questionary
        except ImportError:
            questionary = None
        if questionary is not None:
            models, label = _resolve_model_choices(provider, cfg)
            if models:
                choices = [questionary.Choice(m, m) for m in models]
                choices.append(questionary.Separator())
                choices.append(questionary.Choice("✎ type another model…", _TYPE_ANOTHER))
                sel = questionary.select(
                    label, choices=choices, default=default if default in models else None
                ).ask()
                if sel is None:
                    return ""
                if sel != _TYPE_ANOTHER:
                    return sel
                return (questionary.text("model").ask() or "").strip()
    hint = f" (e.g. {default})" if default else " (type it — any model works)"
    return typer.prompt(f"model{hint}", default=default).strip()


# sentinel: the "add a custom agent (its own JSON API)" choice in the run provider picker
_ADD_CUSTOM = "__add_custom__"


def _prompt_provider_letter(cfg, allow_add_custom: bool = False) -> str:
    """Letter-menu provider picker for a HOSTED model: annotated list; accept a number or name.

    Excludes 'openai-compatible' (it needs a base_url — that's the 'agent' intent, which collects
    the chat URL) so a hosted-model pick can't dead-end on a missing base_url. When
    ``allow_add_custom`` is set (the run flow), '[0]' returns the ``_ADD_CUSTOM`` sentinel.
    """
    providers = [p for p in _known_providers(cfg) if p != "openai-compatible"]
    typer.echo("  providers:")
    if allow_add_custom:
        typer.echo("    [0] add a custom agent (its own JSON API)")
    for i, p in enumerate(providers, 1):
        typer.echo(f"    [{i}] {_provider_hint(p, cfg)}")
    default = str(providers.index("openai") + 1) if "openai" in providers else "1"
    raw = typer.prompt("provider #", default=default).strip()
    if allow_add_custom and raw == "0":
        return _ADD_CUSTOM
    if raw.isdigit() and 1 <= int(raw) <= len(providers):
        return providers[int(raw) - 1]
    return raw  # a name (or an unknown value — _add_target rejects it with a clear error)


def _prompt_provider(cfg) -> str | None:
    """Pick a provider for the run flow: an arrow-key list on a TTY, the numbered fallback else.

    No preselected provider on the TTY path. Offers a '+ add a custom agent' choice returning the
    ``_ADD_CUSTOM`` sentinel; returns ``None`` if the user cancels the arrow-key picker.
    """
    import sys

    if sys.stdin.isatty():
        try:
            import questionary
        except ImportError:
            pass
        else:
            providers = [p for p in _known_providers(cfg) if p != "openai-compatible"]
            choices = [questionary.Choice(_provider_hint(p, cfg), p) for p in providers]
            choices.append(questionary.Separator())
            choices.append(
                questionary.Choice("+ add a custom agent (its own JSON API)", _ADD_CUSTOM)
            )
            return questionary.select("provider", choices=choices).ask()
    return _prompt_provider_letter(cfg, allow_add_custom=True)


# --- editable catalog pack dirs (pure helpers) ------------------------------------------------
def _add_pack_dir(cfg, path) -> None:
    """Append a pack dir to cfg.catalog.pack_dirs (idempotent: a duplicate is ignored)."""
    raw = str(path or "").strip()
    if not raw:
        raise ConfigError("pack dir path is required")
    p = Path(raw)
    if p not in cfg.catalog.pack_dirs:
        cfg.catalog.pack_dirs = [*cfg.catalog.pack_dirs, p]


def _remove_pack_dir(cfg, path) -> None:
    """Remove a pack dir from cfg.catalog.pack_dirs (ConfigError if it isn't present)."""
    p = Path(str(path or "").strip())
    if p not in cfg.catalog.pack_dirs:
        raise ConfigError(f"no pack dir {p} in catalog.pack_dirs")
    cfg.catalog.pack_dirs = [d for d in cfg.catalog.pack_dirs if d != p]


def _show_pack_dirs(cfg) -> None:
    if cfg.catalog.pack_dirs:
        for d in cfg.catalog.pack_dirs:
            typer.echo(f"  {d}")
    else:
        typer.echo("  (none — run `grendel import` to build a catalog, then add its dir here)")


def _echo_proxy_hint() -> None:
    """Explain the proxy's niche: indirect (RAG/tool-output) injection, put grendel IN FRONT."""
    typer.echo("  The proxy is for INDIRECT injection (poisoning data an agent pulls, e.g. RAG):")
    typer.echo("    1) grendel proxy --serve --route /openai=openai --pack tool-abuse")
    typer.echo("    2) point the agent's base_url at that address + /openai/v1")
    typer.echo("       (proxy prints its host:port on start; e.g. http://127.0.0.1:8100/openai/v1)")
    typer.echo("  To test the agent's own API directly, add it as an agent target instead.")


def _prompt_custom_agent_letter(cfg, name):
    """Letter-menu flow for a custom-JSON agent: collect fields, preview, confirm, return cfg."""
    import json

    base_url = typer.prompt("agent base URL (e.g. http://localhost:8080)").strip()
    path = typer.prompt("request path (appended to base URL, e.g. /chat)", default="").strip()
    raw = typer.prompt('request body (JSON, use {prompt}; e.g. {"message": "{prompt}"})').strip()
    try:
        body = json.loads(raw)
    except json.JSONDecodeError as exc:
        typer.echo(f"  error: invalid JSON body: {exc}")
        return cfg
    text_path = typer.prompt("response text path (e.g. reply or choices.0.message.content)").strip()
    model = typer.prompt("model label (optional)", default="-").strip()
    try:
        candidate = _add_custom_agent(
            cfg, name, base_url=base_url, path=path, body=body, text_path=text_path, model=model
        )
        summary = describe_target(candidate.targets[name.strip()], candidate)
    except ConfigError as exc:
        typer.echo(f"  error: {exc}")
        return cfg
    typer.echo(f"  → this target will: {summary}")
    if not typer.confirm("  add this target?", default=True):
        typer.echo("  cancelled")
        return cfg
    typer.echo(f"  added target {name.strip()!r}")
    return candidate


def _prompt_custom_agent_questionary(cfg, name):
    """Arrow-key flow for a custom-JSON agent: collect fields, preview, confirm, return cfg."""
    import json

    import questionary

    base_url = (questionary.text("agent base URL (e.g. http://localhost:8080)").ask() or "").strip()
    path = (
        questionary.text("request path (appended to base URL, e.g. /chat)").ask() or ""
    ).strip()
    raw = (
        questionary.text('request body (JSON, use {prompt}; e.g. {"message": "{prompt}"})').ask()
        or ""
    ).strip()
    try:
        body = json.loads(raw)
    except json.JSONDecodeError as exc:
        typer.echo(f"  error: invalid JSON body: {exc}")
        return cfg
    text_path = (
        questionary.text("response text path (e.g. reply or choices.0.message.content)").ask() or ""
    ).strip()
    model = (questionary.text("model label (optional)", default="-").ask() or "-").strip()
    try:
        candidate = _add_custom_agent(
            cfg, name, base_url=base_url, path=path, body=body, text_path=text_path, model=model
        )
        summary = describe_target(candidate.targets[name.strip()], candidate)
    except ConfigError as exc:
        typer.echo(f"  error: {exc}")
        return cfg
    typer.echo(f"  → this target will: {summary}")
    if not questionary.confirm("add this target?", default=True).ask():
        typer.echo("  cancelled")
        return cfg
    typer.echo(f"  added target {name.strip()!r}")
    return candidate


def _prompt_custom_agent(cfg):
    """Run-flow wrapper: prompt a name (TTY-aware), collect a custom agent, persist it into cfg.

    Returns ``(new_cfg, name)`` on success (``name in new_cfg.targets``), else ``(cfg, None)`` when
    the name is blank or the underlying flow was cancelled/errored (cfg returned unchanged).
    """
    import sys

    label = "name (a short label, e.g. my-agent)"
    use_q = False
    if sys.stdin.isatty():
        try:
            import questionary  # noqa: F401

            use_q = True
        except ImportError:
            pass
    if use_q:
        import questionary

        name = (questionary.text(label).ask() or "").strip()
        new_cfg = _prompt_custom_agent_questionary(cfg, name) if name else cfg
    else:
        name = typer.prompt(label).strip()
        new_cfg = _prompt_custom_agent_letter(cfg, name) if name else cfg
    if name and name in new_cfg.targets:
        return new_cfg, name
    return cfg, None


def _targets_letter(cfg):
    """Letter-menu targets sub-loop (list/add/remove); returns the (possibly new) config."""
    while True:
        typer.echo("targets: [l] list  [a] add  [r] remove  [b] back")
        ch = typer.prompt("targets", default="b").strip().lower()
        if ch == "l":
            _show_targets(cfg)
        elif ch == "a":
            name = typer.prompt("name (a short label, e.g. my-gpt)").strip()
            typer.echo("  what are you testing?")
            typer.echo(f"    [1] a model ({_hosted_providers_label(cfg)})")
            typer.echo("    [2] an agent (its own HTTP API)")
            intent = typer.prompt("choice [1/2]", default="1").strip()
            try:
                if intent == "1":
                    provider = _prompt_provider_letter(cfg)
                    tc = _make_target_config(
                        "http",
                        provider=provider,
                        model=_prompt_model(provider, cfg),
                        api_key_env=typer.prompt(
                            "api_key_env (blank = provider default, e.g. OPENAI_API_KEY)",
                            default="",
                        ).strip(),
                    )
                elif intent == "2":
                    typer.echo("  how does grendel reach the agent?")
                    typer.echo("    [a] an OpenAI-compatible chat URL")
                    typer.echo("    [b] a custom JSON API (you describe request/response)")
                    how = typer.prompt("choice [a/b]", default="a").strip().lower()
                    if how == "b":
                        cfg = _prompt_custom_agent_letter(cfg, name)
                        continue
                    if how != "a":
                        typer.echo(f"  unknown choice {how!r} (enter a or b)")
                        continue
                    tc = _make_target_config(
                        "http",
                        provider="openai-compatible",
                        base_url=typer.prompt(
                            "chat URL (OpenAI-compatible base_url, e.g. http://localhost:11434/v1)"
                        ).strip(),
                        model=_prompt_model("openai-compatible", cfg),
                        api_key_env=typer.prompt("api_key_env (blank = none)", default="").strip(),
                    )
                else:
                    typer.echo(f"  unknown choice {intent!r} (enter 1 or 2)")
                    continue
                summary = describe_target(tc, cfg)  # validates; raises ConfigError if invalid
            except ConfigError as exc:
                typer.echo(f"  error: {exc}")
                continue
            typer.echo(f"  → this target will: {summary}")
            if not typer.confirm("  add this target?", default=True):
                typer.echo("  cancelled")
                continue
            try:
                cfg = _add_target_tc(cfg, name, tc)
                typer.echo(f"  added target {name!r}")
            except ConfigError as exc:
                typer.echo(f"  error: {exc}")
        elif ch == "r":
            try:
                _remove_target(cfg, typer.prompt("remove which target"))
                typer.echo("  removed")
            except ConfigError as exc:
                typer.echo(f"  error: {exc}")
        elif ch in ("b", ""):
            return cfg
        else:
            typer.echo(f"  unknown option {ch!r}")


def _catalog_letter(cfg):
    """Letter-menu catalog sub-loop: list/add/remove pack dirs; returns the config."""
    while True:
        typer.echo("catalog: [l] list  [a] add dir  [r] remove dir  [b] back")
        ch = typer.prompt("catalog", default="b").strip().lower()
        if ch == "l":
            _show_pack_dirs(cfg)
        elif ch == "a":
            try:
                _add_pack_dir(cfg, typer.prompt("pack dir path"))
                typer.echo("  added")
            except ConfigError as exc:
                typer.echo(f"  error: {exc}")
        elif ch == "r":
            try:
                _remove_pack_dir(cfg, typer.prompt("remove which dir"))
                typer.echo("  removed")
            except ConfigError as exc:
                typer.echo(f"  error: {exc}")
        elif ch in ("b", ""):
            return cfg
        else:
            typer.echo(f"  unknown option {ch!r}")


def _catalog_questionary(cfg):
    """Arrow-key catalog sub-loop: list/add/remove pack dirs; returns the config."""
    import questionary

    while True:
        action = questionary.select(
            "catalog pack dirs",
            choices=[
                questionary.Choice("list", "list"),
                questionary.Choice("add", "add"),
                questionary.Choice("remove", "remove"),
                questionary.Choice("back", "back"),
            ],
        ).ask()
        if action in (None, "back"):
            return cfg
        if action == "list":
            _show_pack_dirs(cfg)
        elif action == "add":
            try:
                _add_pack_dir(cfg, questionary.text("pack dir path").ask())
                typer.echo("  added")
            except ConfigError as exc:
                typer.echo(f"  error: {exc}")
        elif action == "remove":
            if not cfg.catalog.pack_dirs:
                typer.echo("  (no pack dirs to remove)")
                continue
            choice = questionary.select(
                "remove which?", choices=[str(d) for d in cfg.catalog.pack_dirs]
            ).ask()
            if choice:
                try:
                    _remove_pack_dir(cfg, choice)
                    typer.echo("  removed")
                except ConfigError as exc:
                    typer.echo(f"  error: {exc}")


def _targets_questionary(cfg):
    """Arrow-key targets sub-loop (list/add/remove); returns the (possibly new) config."""
    import questionary

    while True:
        action = questionary.select(
            "targets",
            choices=[
                questionary.Choice("list", "list"),
                questionary.Choice("add", "add"),
                questionary.Choice("remove", "remove"),
                questionary.Choice("back", "back"),
            ],
        ).ask()
        if action in (None, "back"):
            return cfg
        if action == "list":
            _show_targets(cfg)
        elif action == "add":
            name = (questionary.text("name (a short label, e.g. my-gpt)").ask() or "").strip()
            intent = questionary.select(
                "what are you testing?",
                choices=[
                    questionary.Choice(f"a model ({_hosted_providers_label(cfg)})", "model"),
                    questionary.Choice("an agent (its own HTTP API)", "agent"),
                ],
            ).ask()
            if intent is None:
                continue
            try:
                if intent == "model":
                    provider = questionary.select(
                        "provider",
                        choices=[
                            questionary.Choice(_provider_hint(p, cfg), p)
                            for p in _known_providers(cfg)
                            if p != "openai-compatible"  # that's the agent chat-URL path
                        ],
                        default="openai",
                    ).ask()
                    tc = _make_target_config(
                        "http",
                        provider=provider,
                        model=(
                            questionary.text(
                                "model", default=_preset_default_model(provider, cfg)
                            ).ask()
                            or ""
                        ).strip(),
                        api_key_env=(
                            questionary.text(
                                "api_key_env (blank = provider default, e.g. OPENAI_API_KEY)"
                            ).ask()
                            or ""
                        ).strip(),
                    )
                else:  # "agent" — reach it by an OpenAI-compatible URL or a custom JSON API
                    how = questionary.select(
                        "how does grendel reach the agent?",
                        choices=[
                            questionary.Choice("an OpenAI-compatible chat URL", "url"),
                            questionary.Choice(
                                "a custom JSON API (you describe request/response)", "custom"
                            ),
                        ],
                    ).ask()
                    if how is None:
                        continue
                    if how == "custom":
                        cfg = _prompt_custom_agent_questionary(cfg, name)
                        continue
                    tc = _make_target_config(
                        "http",
                        provider="openai-compatible",
                        base_url=(
                            questionary.text(
                                "chat URL (OpenAI-compatible base_url, "
                                "e.g. http://localhost:11434/v1)"
                            ).ask()
                            or ""
                        ).strip(),
                        model=(
                            questionary.text(
                                "model", default=_preset_default_model("openai-compatible", cfg)
                            ).ask()
                            or ""
                        ).strip(),
                        api_key_env=(
                            questionary.text("api_key_env (blank = none)").ask() or ""
                        ).strip(),
                    )
                summary = describe_target(tc, cfg)
            except ConfigError as exc:
                typer.echo(f"  error: {exc}")
                continue
            typer.echo(f"  → this target will: {summary}")
            if not questionary.confirm("add this target?", default=True).ask():
                typer.echo("  cancelled")
                continue
            try:
                cfg = _add_target_tc(cfg, name, tc)
                typer.echo(f"  added target {name!r}")
            except ConfigError as exc:
                typer.echo(f"  error: {exc}")
        elif action == "remove":
            if not cfg.targets:
                typer.echo("  (no targets to remove)")
                continue
            name = questionary.select("remove which?", choices=list(cfg.targets)).ask()
            if name:
                try:
                    _remove_target(cfg, name)
                    typer.echo("  removed")
                except ConfigError as exc:
                    typer.echo(f"  error: {exc}")


def _save_config_and_report(cfg, path: Path) -> bool:
    """Revalidate + save; echo the result. Returns True on success."""
    from .config import save_config

    try:
        validated = GrendelConfig.model_validate(cfg.model_dump(mode="python"))
        save_config(validated, path)
    except (ConfigError, ValidationError) as exc:
        typer.echo(f"error: {exc}", err=True)
        return False
    typer.echo(f"saved -> {path}")
    return True


def _run_label(cfg) -> str:
    r = cfg.run
    return (
        f"run     · output_dir={r.output_dir} concurrency={r.concurrency} "
        f"max_tokens={r.max_tokens} temperature={r.temperature}"
    )


def _judge_label(cfg) -> str:
    j = cfg.judge
    return (
        f"judge   · LLM that grades borderline replies (T3) · "
        f"enabled={'yes' if j.enabled else 'no'} target={j.target or '-'}"
    )


def _proxy_label(cfg) -> str:
    p = cfg.proxy
    return f"proxy   · {p.host}:{p.port} routes={len(p.routes)}"


def _config_interactive(cfg, path: Path, *, unicode: bool = True) -> None:
    """Arrow-key (↑/↓ + Enter) inline config menu via questionary."""
    import questionary

    from .banner import config_header

    while True:
        choice = questionary.select(
            config_header(path, unicode=unicode),
            choices=[
                questionary.Choice(_run_label(cfg), "run"),
                questionary.Choice(_judge_label(cfg), "judge"),
                questionary.Choice(_proxy_label(cfg), "proxy"),
                questionary.Choice(f"targets · {len(cfg.targets)} configured", "targets"),
                questionary.Choice(
                    f"catalog · {len(cfg.catalog.pack_dirs)} pack dir(s)", "catalog"
                ),
                questionary.Separator(),
                questionary.Choice("save & quit", "save"),
                questionary.Choice("quit without saving", "quit"),
            ],
        ).ask()

        if choice is None or choice == "quit":
            typer.echo("no changes saved")
            return
        if choice == "run":
            _edit_run_q(cfg.run)
        elif choice == "judge":
            _edit_judge_q(cfg)
        elif choice == "proxy":
            _edit_proxy_q(cfg)
        elif choice == "targets":
            cfg = _targets_questionary(cfg)
        elif choice == "catalog":
            cfg = _catalog_questionary(cfg)
        elif choice == "save":
            if _save_config_and_report(cfg, path):
                return


def _config_prompt_loop(cfg, path: Path, *, unicode: bool = True) -> None:
    """Fallback letter-menu (used when stdin is not a TTY — e.g. tests / pipes)."""
    from .banner import config_header

    while True:
        r, j = cfg.run, cfg.judge
        typer.echo("")
        typer.echo(config_header(path, unicode=unicode))
        typer.echo(f"  [r] {_run_label(cfg)[8:]}")
        typer.echo(f"  [j] {_judge_label(cfg)[8:]}")
        typer.echo(f"  [p] {_proxy_label(cfg)[8:]}")
        typer.echo(f"  [t] targets · {len(cfg.targets)} configured")
        typer.echo(f"  [c] catalog · {len(cfg.catalog.pack_dirs)} pack dir(s)")
        typer.echo("  [s] save    [q] quit without saving")
        choice = typer.prompt("select", default="q").strip().lower()
        if choice == "r":
            _edit_run_letter(r)
        elif choice == "j":
            _edit_judge_letter(j)
        elif choice == "p":
            _edit_proxy_letter(cfg)
        elif choice == "t":
            cfg = _targets_letter(cfg)
        elif choice == "c":
            cfg = _catalog_letter(cfg)
        elif choice == "s":
            if _save_config_and_report(cfg, path):
                return
        elif choice in ("q", ""):
            typer.echo("no changes saved")
            return
        else:
            typer.echo(f"unknown option {choice!r}")


# --- shared field editors (reused by `config` and the home-menu settings submenu) -------------
def _edit_run_letter(r) -> None:
    r.output_dir = Path(typer.prompt("output_dir", default=str(r.output_dir)).strip())
    r.concurrency = _parse_int(
        typer.prompt("concurrency", default=str(r.concurrency)), r.concurrency
    )
    r.max_tokens = _parse_int(typer.prompt("max_tokens", default=str(r.max_tokens)), r.max_tokens)
    r.temperature = _parse_float(
        typer.prompt("temperature", default=str(r.temperature)), r.temperature
    )


def _edit_judge_letter(j) -> None:
    typer.echo("  judge = an LLM that grades borderline attack replies (T3); off by default.")
    typer.echo("  when on, contested cases are sent to the target below for a verdict.")
    j.enabled = typer.confirm("enable judge?", default=j.enabled)
    j.target = (typer.prompt("judge target (blank = none)", default=j.target or "").strip()) or None


def _edit_proxy_letter(cfg) -> None:
    px = cfg.proxy
    px.host = typer.prompt("host", default=px.host).strip()
    px.port = _parse_int(typer.prompt("port", default=str(px.port)), px.port)
    _apply_route(cfg, typer.prompt("add route PATH=PROVIDER (blank to skip)", default=""))


def _edit_run_q(r) -> None:
    import questionary

    r.output_dir = Path(questionary.text("output_dir", default=str(r.output_dir)).ask())
    r.concurrency = _parse_int(
        questionary.text("concurrency", default=str(r.concurrency)).ask(), r.concurrency
    )
    r.max_tokens = _parse_int(
        questionary.text("max_tokens", default=str(r.max_tokens)).ask(), r.max_tokens
    )
    r.temperature = _parse_float(
        questionary.text("temperature", default=str(r.temperature)).ask(), r.temperature
    )


def _edit_judge_q(cfg) -> None:
    import questionary

    typer.echo("  judge = an LLM that grades borderline attack replies (T3); off by default.")
    cfg.judge.enabled = questionary.confirm("enable judge?", default=cfg.judge.enabled).ask()
    tgt = (questionary.text("judge target", default=cfg.judge.target or "").ask() or "").strip()
    cfg.judge.target = tgt or None


def _edit_proxy_q(cfg) -> None:
    import questionary

    cfg.proxy.host = questionary.text("host", default=cfg.proxy.host).ask()
    cfg.proxy.port = _parse_int(
        questionary.text("port", default=str(cfg.proxy.port)).ask(), cfg.proxy.port
    )
    _apply_route(cfg, questionary.text("add route PATH=PROVIDER (blank to skip)").ask())


# --- home-menu submenus -----------------------------------------------------------------------
def _settings_letter(cfg):
    """Advanced settings submenu (run/judge/proxy) for the letter home menu."""
    while True:
        typer.echo("settings:")
        typer.echo("  [r] run    · engine speed & limits (concurrency, tokens, timeout)")
        typer.echo("  [j] judge  · grade borderline replies with an LLM (T3)")
        typer.echo("  [p] proxy  · indirect-injection endpoint (RAG/tool poisoning)")
        typer.echo("  [b] back")
        ch = typer.prompt("settings", default="b").strip().lower()
        if ch == "r":
            _edit_run_letter(cfg.run)
        elif ch == "j":
            _edit_judge_letter(cfg.judge)
        elif ch == "p":
            _edit_proxy_letter(cfg)
        elif ch in ("b", ""):
            return cfg
        else:
            typer.echo(f"  unknown option {ch!r}")


def _settings_questionary(cfg):
    import questionary

    while True:
        action = questionary.select(
            "settings",
            choices=[
                questionary.Choice("run    · engine speed & limits (concurrency, tokens)", "run"),
                questionary.Choice("judge  · grade borderline replies with an LLM (T3)", "judge"),
                questionary.Choice("proxy  · indirect-injection endpoint (RAG/tool)", "proxy"),
                questionary.Choice("back", "back"),
            ],
        ).ask()
        if action in (None, "back"):
            return cfg
        if action == "run":
            _edit_run_q(cfg.run)
        elif action == "judge":
            _edit_judge_q(cfg)
        elif action == "proxy":
            _edit_proxy_q(cfg)


def _api_key_status_lines() -> list[str]:
    """Per-provider API-key env status (presence only) + the exact export hint for missing ones."""
    lines: list[str] = []
    for name, preset in PRESETS.items():
        var = preset.api_key_env
        if var is None:
            lines.append(f"  {name}: no API key needed")
        elif os.environ.get(var):
            lines.append(f"  {name}: {var} set")
        else:
            lines.append(f"  {name}: {var} NOT set  —  export {var}=... (or save it below)")
    return lines


def _mask(value: str) -> str:
    return f"{value[:2]}…{value[-2:]}" if len(value) > 4 else "…"


def _api_keys_letter(cfg):
    """API-keys submenu: show ✓/✗ status; optionally save a key to the gitignored local file."""
    from .secrets import LOCAL_SECRETS_FILE, save_local_secret

    while True:
        typer.echo("api keys (presence only — values never shown):")
        for ln in _api_key_status_lines():
            typer.echo(ln)
        typer.echo("  [s] save a key to a local (gitignored) file   [b] back")
        ch = typer.prompt("api keys", default="b").strip().lower()
        if ch == "s":
            var = typer.prompt("env var name (e.g. OPENAI_API_KEY)").strip()
            value = typer.prompt("value", hide_input=True).strip()
            if not var or not value:
                typer.echo("  (skipped — name and value are required)")
                continue
            try:
                save_local_secret(var, value, Path(LOCAL_SECRETS_FILE))
            except ConfigError as exc:
                typer.echo(f"  error: {exc}")
                continue
            os.environ.setdefault(var, value)  # usable this session too
            typer.echo(f"  saved {var} -> {LOCAL_SECRETS_FILE} (gitignored) [{_mask(value)}]")
        elif ch in ("b", ""):
            return cfg
        else:
            typer.echo(f"  unknown option {ch!r}")


def _api_keys_questionary(cfg):
    import questionary

    from .secrets import LOCAL_SECRETS_FILE, save_local_secret

    while True:
        typer.echo("api keys (presence only — values never shown):")
        for ln in _api_key_status_lines():
            typer.echo(ln)
        action = questionary.select(
            "api keys", choices=["save a key to a local file", "back"]
        ).ask()
        if action in (None, "back"):
            return cfg
        var = (questionary.text("env var name (e.g. OPENAI_API_KEY)").ask() or "").strip()
        value = (questionary.password("value").ask() or "").strip()
        if not var or not value:
            typer.echo("  (skipped — name and value are required)")
            continue
        try:
            save_local_secret(var, value, Path(LOCAL_SECRETS_FILE))
        except ConfigError as exc:
            typer.echo(f"  error: {exc}")
            continue
        os.environ.setdefault(var, value)
        typer.echo(f"  saved {var} -> {LOCAL_SECRETS_FILE} (gitignored) [{_mask(value)}]")


def _menu_packs(cfg):
    """Browse the attack catalog from the menu (all packs, optionally filtered by category)."""
    try:
        infos = list_packs(config=cfg)
    except (PackError, ConfigError) as exc:
        typer.echo(f"  pack error: {exc}")
        return cfg
    infos = [i for i in infos if i.source is not Source.STAGED]
    if not infos:
        typer.echo("  (no packs — add a catalog dir or run `import`)")
        return cfg
    cats = sorted({i.category for i in infos})
    typer.echo(f"  {len(infos)} attacks · categories: {', '.join(cats)}")
    cat = typer.prompt("filter by category (blank = all)", default="").strip()
    if cat:
        infos = [i for i in infos if i.category == cat]
        if not infos:
            typer.echo(f"  no attacks in category {cat!r}")
            return cfg
    for info in infos[:50]:
        typer.echo(f"    {info.id:<46} {info.severity.value:<8} [{info.source.value}]")
    if len(infos) > 50:
        typer.echo(f"    … and {len(infos) - 50} more (filter by category, or `list --packs`)")
    return cfg


def _menu_learn(cfg) -> None:
    """Print the app's own plain-language explainer of every concept, then wait for a keypress."""
    import sys

    from .banner import render_concepts, stream_supports_unicode

    typer.echo(
        render_concepts(
            color=sys.stdout.isatty(), unicode=stream_supports_unicode(sys.stdout)
        )
    )
    _pause_menu()


def _menu_doctor(cfg) -> None:
    import sys

    from .banner import stream_supports_unicode
    from .doctor import build_doctor_report

    typer.echo(
        build_doctor_report(
            cfg, color=sys.stdout.isatty(), unicode=stream_supports_unicode(sys.stdout)
        )
    )


def _do_import(cfg, out: str, path: str | None, limit: int | None) -> None:
    """Run the import engine from the menu and wire the out dir into catalog.pack_dirs."""
    from . import corpus
    from .corpus import ImportResult

    out_path = Path(out)
    try:
        paths = [Path(path)] if path else corpus.default_source_paths("garak")
        total = ImportResult()
        for p in paths:
            r = corpus.import_corpus("garak", p, out_path, limit=limit)
            total.seen += r.seen
            total.imported += r.imported
            total.duplicate += r.duplicate
            total.license_skipped += r.license_skipped
    except PackError as exc:
        typer.echo(f"  import error: {exc}")
        return
    typer.echo(
        f"  imported {total.imported} (seen {total.seen}, duplicate {total.duplicate}, "
        f"license-skipped {total.license_skipped}) -> {out_path}"
    )
    if total.imported:
        _add_pack_dir(cfg, out_path)  # wire it in; persisted on save
        typer.echo(f"  wired {out_path} into catalog.pack_dirs (save to persist)")


def _menu_import_letter(cfg):
    out = typer.prompt("catalog out dir", default="catalog").strip() or "catalog"
    path = typer.prompt("corpus --path (blank = auto-discover garak)", default="").strip()
    raw = typer.prompt("limit new packs (blank = all)", default="").strip()
    limit = int(raw) if raw.isdigit() else None
    _do_import(cfg, out, path or None, limit)
    return cfg


_ADHOC = "__adhoc__"  # sentinel: the "ad-hoc model (provider+model)" run choice, not a target name


def _run_target_label(cfg, tname: str) -> str:
    """A compact one-line description of a configured target for the run picker."""
    try:
        info = resolve_target_info(tname, cfg)
        return f"{tname}  ({info['provider']}/{info['model']})"
    except ConfigError:
        return tname


def _prompt_run_target(cfg) -> str | None:
    """Pick which target to run: a configured one or ad-hoc provider+model.

    Returns a target name, ``_ADHOC`` for the ad-hoc provider+model path, or ``None`` if cancelled.
    With no configured targets it goes straight to ad-hoc (no empty picker). On a TTY it's an
    arrow-key list; otherwise (tests/pipes) a numbered prompt.
    """
    import sys

    if not cfg.targets:
        return _ADHOC
    names = list(cfg.targets)
    if sys.stdin.isatty():
        try:
            import questionary
        except ImportError:
            pass
        else:
            choices = [questionary.Choice(_run_target_label(cfg, t), t) for t in names]
            choices.append(questionary.Separator())
            choices.append(questionary.Choice("ad-hoc model (provider + model)", _ADHOC))
            return questionary.select("which target?", choices=choices).ask()
    # numbered fallback (also the test path)
    typer.echo("  which target?")
    for i, t in enumerate(names, 1):
        typer.echo(f"    [{i}] {_run_target_label(cfg, t)}")
    typer.echo("    [0] ad-hoc model (provider + model)")
    raw = typer.prompt("target #", default="1").strip()
    if raw == "0":
        return _ADHOC
    if raw.isdigit() and 1 <= int(raw) <= len(names):
        return names[int(raw) - 1]
    if raw in cfg.targets:  # a name typed directly still works
        return raw
    typer.echo(f"  unknown choice {raw!r}")
    return None


def _pause_menu() -> None:
    """Wait for a keypress so run output stays readable before the menu clears (TTY only)."""
    click.pause("  ↵ press Enter to return to the menu")  # no-op when stdin/stdout isn't a TTY


def _print_report_card(record, path) -> bool:
    """Print the polished rich report card (TTY + rich only). Returns True if it printed, so the
    caller uses the plain-text fallback off-TTY / without rich (keeps pipes/tests identical)."""
    import sys

    if not sys.stdout.isatty():
        return False
    try:
        from rich.console import Console

        from .banner import stream_supports_unicode
        from .report_card import render_card
    except ImportError:
        return False
    uni = stream_supports_unicode(sys.stdout)
    Console(legacy_windows=False).print(render_card(record, path, unicode=uni))
    return True


def _attempts_by_outcome(record):
    """Bucket a record's attempts: got-through (non-control FAIL) / defended (PASS) / errors.

    Non-control only in every bucket, matching the card's metrics_summary tallies. Each list is
    sorted by (attack_id, attempt_id) for a stable browse order.
    """
    from .records import Verdict

    def bucket(v):
        rows = [a for a in record.attempts if not a.is_control and a.verdict == v]
        return sorted(rows, key=lambda a: (a.attack_id or "", a.attempt_id))

    return {"hits": bucket(Verdict.FAIL), "defended": bucket(Verdict.PASS),
            "errors": bucket(Verdict.ERROR)}


def _show_attempt(attempt) -> None:
    """Print one attempt's detail: rich card on a TTY, else a plain-text dump."""
    import sys

    if sys.stdout.isatty():
        try:
            from rich.console import Console

            from .banner import stream_supports_unicode
            from .report_card import render_attempt
        except ImportError:
            pass
        else:
            uni = stream_supports_unicode(sys.stdout)
            Console(legacy_windows=False).print(render_attempt(attempt, unicode=uni))
            return
    typer.echo(f"  {attempt.verdict.name}  {attempt.attack_id or '(no id)'}  ({attempt.category})")
    typer.echo(f"    prompt:   {(attempt.prompt or '')[:500]}")
    body = attempt.response_text or attempt.error or "(no response)"
    typer.echo(f"    response: {body[:500]}")
    if attempt.score_detail is not None and attempt.score_detail.reason:
        typer.echo(f"    why:      {attempt.score_detail.reason}")


def _menu_results(record) -> None:
    """Browse a run's per-attempt results: filter by outcome, drill into prompt/response/why.

    Read-only. On a TTY, arrow-key pickers; else numbered/letter fallbacks. Any unrecognised input
    (or blank) at the filter → back/return, so a scripted flow never drains stdin.
    """
    import sys

    buckets = _attempts_by_outcome(record)
    labels = [
        ("hits", "got through", "h"),
        ("defended", "defended", "d"),
        ("errors", "errors", "e"),
    ]
    while True:
        typer.echo(
            f"  results:  got through {len(buckets['hits'])}  ·  "
            f"defended {len(buckets['defended'])}  ·  errors {len(buckets['errors'])}"
        )
        key = None
        if sys.stdin.isatty():
            try:
                import questionary
            except ImportError:
                questionary = None
            if questionary is not None:
                choices = [
                    questionary.Choice(f"{name} ({len(buckets[b])})", b) for b, name, _ in labels
                ]
                choices.append(questionary.Separator())
                choices.append(questionary.Choice("back", "__back__"))
                sel = questionary.select("show which?", choices=choices).ask()
                if sel in (None, "__back__"):
                    return
                key = sel
        if key is None:  # letter fallback (also the test path)
            typer.echo("    [h] got through   [d] defended   [e] errors   [b] back")
            raw = typer.prompt("results filter", default="b").strip().lower()
            key = {"h": "hits", "d": "defended", "e": "errors"}.get(raw)
            if key is None:
                return  # blank / b / anything unrecognised → back (bounded, no re-prompt loop)
        rows = buckets[key]
        if not rows:
            typer.echo("    (none)")
            continue
        attempt = _pick_attempt(rows)
        if attempt is not None:
            _show_attempt(attempt)
            _pause_menu()


def _pick_attempt(rows):
    """Pick one attempt from a bucket (arrow-key on a TTY, numbered else); None on back."""
    import sys

    if sys.stdin.isatty():
        try:
            import questionary
        except ImportError:
            questionary = None
        if questionary is not None:
            choices = [
                questionary.Choice(f"{a.attack_id or '(no id)'}  ({a.category})", i)
                for i, a in enumerate(rows)
            ]
            choices.append(questionary.Separator())
            choices.append(questionary.Choice("back", None))
            idx = questionary.select("which attack?", choices=choices).ask()
            return None if idx is None else rows[idx]
    shown = rows[:30]
    for i, a in enumerate(shown, 1):
        typer.echo(f"    [{i}] {a.attack_id or '(no id)'}  ({a.category})")
    if len(rows) > len(shown):
        typer.echo(f"    … +{len(rows) - len(shown)} more (grendel report for the full list)")
    raw = typer.prompt("attack # (0 = back)", default="0").strip()
    if raw.isdigit() and 1 <= int(raw) <= len(shown):
        return shown[int(raw) - 1]
    return None  # 0 / blank / unrecognised → back


def _run_progress(total: int):
    """A live per-attempt counter for the menu run (TTY only; None off-TTY so pipes stay clean)."""
    import sys

    if not sys.stdout.isatty():
        return None
    state = {"n": 0, "hits": 0}

    def cb(attempt) -> None:
        state["n"] += 1
        # FAIL = attack got through; exclude benign controls (matches records._asr + the dashboard)
        if attempt.verdict.name == "FAIL" and not getattr(attempt, "is_control", False):
            state["hits"] += 1
        click.echo(f"\r  attacking… {state['n']}/{total}  ·  {state['hits']} hit(s)", nl=False)

    return cb


def _missing_run_key(target: str, cfg) -> str | None:
    """The API-key env var a real run needs but that is unset, or None if the key is present/N/A."""
    try:
        info = resolve_target_info(target, cfg)
        preset = resolve_provider(info["provider"], cfg)
    except ConfigError:
        return None
    if not preset.requires_key:
        return None
    tc = cfg.targets.get(target)
    key_env = getattr(tc, "api_key_env", None) or preset.api_key_env
    if key_env and not os.environ.get(key_env):
        return key_env
    return None


def _menu_run(cfg):
    """Pick a target and fire every attack at it via the existing engine (all packs, real run).

    Two ad-hoc outcomes for the returned cfg: a hosted provider+model target is synthesized on a
    throwaway copy (``run_cfg``) and NEVER leaks into the saved config; a '+ add a custom agent'
    choice PERSISTS the new agent into the returned cfg (the user configured it) and runs it.
    A configured-target pick returns the session cfg unchanged.
    """
    from .config import build_cli_target_config

    sel = _prompt_run_target(cfg)
    if sel is None:
        return cfg  # cancelled
    if sel != _ADHOC:
        target, run_cfg = sel, cfg
    else:
        provider = _prompt_provider(cfg)
        if provider is None:
            return cfg  # cancelled the provider picker
        if provider == _ADD_CUSTOM:
            new_cfg, name = _prompt_custom_agent(cfg)
            if name is None:
                return cfg  # nothing added (blank name / cancelled / bad input)
            cfg, run_cfg, target = new_cfg, new_cfg, name  # persist the configured agent
        else:
            model = _prompt_model(provider, cfg)
            if not model:
                return cfg  # cancelled the model picker (empty = Esc / no entry)
            try:
                tc = build_cli_target_config(provider=provider, model=model)
                run_cfg = cfg.with_cli_target(_CLI_TARGET_NAME, tc)  # throwaway; not session cfg
                target = _CLI_TARGET_NAME
            except ConfigError as exc:
                typer.echo(f"  error: {exc}")
                return cfg
    _fire_and_report(run_cfg, target)
    return cfg


def _offer_to_set_key(missing: str) -> bool:
    """When a run's provider key is unset, offer to set it now (TTY only). Returns True if saved.

    Off-TTY (tests / pipes) this is a no-op so the warning-then-confirm flow stays byte-identical;
    a newcomer on a real terminal gets to fix the key inline instead of dead-ending on a warning.
    """
    import sys

    from .secrets import LOCAL_SECRETS_FILE, save_local_secret

    if not sys.stdin.isatty():
        return False
    if not typer.confirm(f"  set {missing} now?", default=True):
        return False
    value = typer.prompt("  value", hide_input=True).strip()
    if not value:
        typer.echo("  (skipped — no value entered)")
        return False
    try:
        save_local_secret(missing, value, Path(LOCAL_SECRETS_FILE))
    except ConfigError as exc:
        typer.echo(f"  error: {exc}")
        return False
    os.environ.setdefault(missing, value)  # usable this run too
    typer.echo(f"  saved {missing} -> {LOCAL_SECRETS_FILE} (gitignored) [{_mask(value)}]")
    return True


def _fire_and_report(run_cfg, target) -> None:
    """Fire every attack at ``target`` in ``run_cfg``, then show the report card + results browser.

    Shared by the run menu and the guided setup so both take the identical run → report → browse
    path. Returns on any error / cancel / empty catalog (the caller just redraws its menu).
    """
    try:
        info = resolve_target_info(target, run_cfg)
        selected = _select_attacks(_menu_load_attacks(run_cfg), [])  # all packs — no prompt
    except (ConfigError, PackError) as exc:
        typer.echo(f"  error: {exc}")
        return
    if not selected:
        typer.echo("  no attacks available — import a corpus or add a pack dir first")
        _pause_menu()
        return
    label = f"{len(selected)} attack(s) vs {target} ({info['provider']}/{info['model']})"
    missing = _missing_run_key(target, run_cfg)  # a real run needs the provider's API key
    if missing:
        typer.echo(f"  ⚠ {missing} is not set — attacks will just error without it.")
        if _offer_to_set_key(missing):
            missing = None
    if not typer.confirm(f"  fire {label}?", default=not missing):
        typer.echo("  cancelled")
        return
    adapter = build_target(target, run_cfg, dry_run=False)
    # Wire scoring/judge from config, same as the `run` subcommand — else cfg.scoring and any
    # enabled judge are silently ignored on this menu path.
    if run_cfg.judge.enabled:
        scorer, judge_adapter = _build_judge_scorer(run_cfg, dry_run=False)
    else:
        scorer, judge_adapter = _build_scorer(run_cfg), None
    record = make_run_record(
        target_name=target,
        provider=info["provider"],
        model=info["model"],
        config=run_cfg,
        pack_ids=[a.id for a in selected],
    )
    from .live import make_live_run

    live = make_live_run(len(selected), f"{target} ({info['provider']}/{info['model']})")
    if live is not None:  # rich dashboard on a TTY
        click.clear()  # wipe the menu's wordmark so only the live panel's logo shows (no double)
        with live:
            asyncio.run(
                _execute(
                    adapter, run_cfg.run, selected, record,
                    scorer=scorer, judge_adapter=judge_adapter, on_attempt=live.on_attempt,
                )
            )
    else:  # plain one-line counter (off-TTY / no rich) or nothing (pipes)
        on_attempt = _run_progress(len(selected))
        asyncio.run(
            _execute(
                adapter, run_cfg.run, selected, record,
                scorer=scorer, judge_adapter=judge_adapter, on_attempt=on_attempt,
            )
        )
        if on_attempt is not None:
            typer.echo("")  # end the live progress line before the summary
    record_path = Runner(adapter, run_cfg.run).run_path(record)
    if not _print_report_card(record, record_path):  # TTY → polished card; else plain summary
        typer.echo("  " + _summary(record, record_path))
        typer.echo(f"  next: grendel report --run {record_path} --format md")
    _menu_results(record)  # browse which got through / were defended (returns on back)


def _menu_quickstart(cfg):
    """Guided first run for a newcomer: a plain-language intro, then the normal run flow.

    With no targets configured the run flow goes straight to provider → model → fire, so this is
    just the run path with an orientation preamble that says, in words, what is about to happen.
    """
    typer.echo("")
    typer.echo("  Guided setup — let's run your first test.")
    typer.echo("  Here's what happens next:")
    typer.echo("    1. pick a provider (openai / anthropic / ollama / your own agent)")
    typer.echo("    2. pick a model, and set its API key if needed")
    typer.echo("    3. Grendel fires every attack and shows a live scoreboard, then a report")
    typer.echo("  Note: a real run makes API calls to that provider (ollama is local + free).")
    typer.echo("  New to the words above? Quit this and open 'learn' first.")
    typer.echo("")
    return _menu_run(cfg)


def _list_run_records(cfg):
    """Recent run records under output_dir, newest first (capped): [(path, label), ...].

    Labels are built from the raw JSON scalars (json.loads, not RunRecord) so listing never
    materialises the full attempts list — a record may hold thousands of attempts.
    """
    d = Path(cfg.run.output_dir)
    if not d.is_dir():
        return []
    files = sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    out = []
    for p in files[:20]:
        try:  # a non-record .json (or a partial write) falls back to its filename as the label
            raw = json.loads(p.read_text(encoding="utf-8"))
            attempts = raw.get("attempts") or []
            non_ctrl = [a for a in attempts if not a.get("is_control")]
            scored = [a for a in non_ctrl if a.get("verdict") in ("pass", "fail")]
            hits = sum(1 for a in scored if a.get("verdict") == "fail")
            asr = hits / len(scored) if scored else 0.0
            label = (
                f"{raw.get('target_name')} ({raw.get('provider')}/{raw.get('model')}) · "
                f"{len(non_ctrl)} atk · ASR {asr:.0%} · {raw.get('status')}"
            )
        except Exception:  # noqa: BLE001 — listing must never crash on a bad file
            label = p.name
        out.append((p, label))
    return out


def _reports_letter_pick(records):
    """Numbered-fallback run picker: returns a Path, or None on blank/0/unknown (cancel)."""
    typer.echo("  which run?")
    for i, (_p, lbl) in enumerate(records, 1):
        typer.echo(f"    [{i}] {lbl}")
    raw = typer.prompt("run # (0 = back)", default="1").strip()
    if raw in ("", "0"):
        return None
    if raw.isdigit() and 1 <= int(raw) <= len(records):
        return records[int(raw) - 1][0]
    typer.echo(f"  unknown choice {raw!r}")
    return None


def _menu_reports(cfg):
    """List recent run records and print a text report for the chosen one (read-only)."""
    import sys

    from . import reports as reportsmod

    records = _list_run_records(cfg)
    if not records:
        typer.echo(f"  no run records in {cfg.run.output_dir} — fire a run first")
        _pause_menu()
        return cfg
    path = None
    if sys.stdin.isatty():
        try:
            import questionary
        except ImportError:
            questionary = None
        if questionary is not None:
            choices = [questionary.Choice(lbl, i) for i, (_p, lbl) in enumerate(records)]
            idx = questionary.select("which run?", choices=choices).ask()
            path = None if idx is None else records[idx][0]
        else:
            path = _reports_letter_pick(records)
    else:
        path = _reports_letter_pick(records)
    if path is None:
        return cfg  # cancelled
    try:
        rec = RunRecord.from_json(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 — a bad record must not crash the menu
        typer.echo(f"  error: {exc}")
        _pause_menu()
        return cfg
    if not _print_report_card(rec, path):  # TTY → polished card; else plain text
        typer.echo(reportsmod.render_text(rec))
        typer.echo(f"  full: grendel report --run {path} --format md")
    _menu_results(rec)  # browse which got through / were defended (returns on back)
    return cfg


# --- the home menu (bare `grendel` on a TTY) --------------------------------------------------
def _home_letter(cfg, path: Path, *, unicode: bool = True) -> None:
    import sys

    from .banner import config_header, render_welcome

    while True:
        _clear_and_logo(unicode)
        if not cfg.targets:  # fresh user → orient them before the menu
            typer.echo(render_welcome(color=sys.stdout.isatty(), unicode=unicode))
            typer.echo("")
        typer.echo(config_header(path, unicode=unicode))
        if not cfg.targets:  # newcomer → offer the guided path first
            typer.echo("  [1] guided setup · set up and run your first test (start here)")
        typer.echo(f"  [t] targets   · {len(cfg.targets)} configured")
        typer.echo("  [k] api keys  · set / check provider keys")
        typer.echo("  [p] packs     · browse the attack catalog")
        typer.echo(f"  [g] catalog   · {len(cfg.catalog.pack_dirs)} pack dir(s) (load sources)")
        typer.echo("  [x] run       · fire attacks at a target")
        typer.echo("  [r] reports   · view a past run's report")
        typer.echo("  [i] import    · grow the catalog from a corpus")
        typer.echo("  [o] doctor    · status & diagnostics")
        typer.echo("  [a] settings  · run / judge / proxy")
        typer.echo("  [?] learn     · what everything means (plain language)")
        typer.echo("  [s] save & quit    [q] quit without saving")
        choice = typer.prompt("select", default="q").strip().lower()
        if choice == "1" and not cfg.targets:  # gated like the [1] line above (hidden once set up)
            cfg = _menu_quickstart(cfg)
        elif choice == "?":
            _menu_learn(cfg)
        elif choice == "t":
            cfg = _targets_letter(cfg)
        elif choice == "k":
            cfg = _api_keys_letter(cfg)
        elif choice == "p":
            cfg = _menu_packs(cfg)
        elif choice == "g":
            cfg = _catalog_letter(cfg)
        elif choice == "x":
            cfg = _menu_run(cfg)
        elif choice == "r":
            cfg = _menu_reports(cfg)
        elif choice == "i":
            cfg = _menu_import_letter(cfg)
        elif choice == "o":
            _menu_doctor(cfg)
        elif choice == "a":
            cfg = _settings_letter(cfg)
        elif choice == "s":
            if _save_config_and_report(cfg, path):
                return
        elif choice in ("q", ""):
            typer.echo("no changes saved")
            return
        else:
            typer.echo(f"unknown option {choice!r}")


def _home_questionary(cfg, path: Path, *, unicode: bool = True) -> None:
    import sys

    import questionary

    from .banner import config_header, render_welcome

    while True:
        _clear_and_logo(unicode)
        if not cfg.targets:  # fresh user → orient them before the menu (same as the letter shell)
            typer.echo(render_welcome(color=sys.stdout.isatty(), unicode=unicode))
            typer.echo("")
        guided = (
            [questionary.Choice("guided setup · run your first test (start here)", "guided")]
            if not cfg.targets
            else []
        )
        choice = questionary.select(
            config_header(path, unicode=unicode),
            choices=[
                *guided,
                questionary.Choice(f"targets · {len(cfg.targets)} configured", "targets"),
                questionary.Choice("api keys · set / check provider keys", "apikeys"),
                questionary.Choice("packs · browse the attack catalog", "packs"),
                questionary.Choice(
                    f"catalog · {len(cfg.catalog.pack_dirs)} pack dir(s) (load sources)", "catalog"
                ),
                questionary.Choice("run · fire attacks at a target", "run"),
                questionary.Choice("reports · view a past run's report", "reports"),
                questionary.Choice("import · grow the catalog", "import"),
                questionary.Choice("doctor · status & diagnostics", "doctor"),
                questionary.Choice("settings · run / judge / proxy", "settings"),
                questionary.Choice("learn · what everything means (plain language)", "learn"),
                questionary.Separator(),
                questionary.Choice("save & quit", "save"),
                questionary.Choice("quit without saving", "quit"),
            ],
        ).ask()
        if choice is None or choice == "quit":
            typer.echo("no changes saved")
            return
        if choice == "guided":
            cfg = _menu_quickstart(cfg)
        elif choice == "learn":
            _menu_learn(cfg)
        elif choice == "targets":
            cfg = _targets_questionary(cfg)
        elif choice == "apikeys":
            cfg = _api_keys_questionary(cfg)
        elif choice == "packs":
            cfg = _menu_packs(cfg)
        elif choice == "catalog":
            cfg = _catalog_questionary(cfg)
        elif choice == "run":
            cfg = _menu_run(cfg)
        elif choice == "reports":
            cfg = _menu_reports(cfg)
        elif choice == "import":
            cfg = _menu_import_letter(cfg)
        elif choice == "doctor":
            _menu_doctor(cfg)
        elif choice == "settings":
            cfg = _settings_questionary(cfg)
        elif choice == "save":
            if _save_config_and_report(cfg, path):
                return


def _clear_and_logo(unicode: bool) -> None:
    """Clear the terminal (TTY only) + print the GRENDEL wordmark — one clean screen per redraw."""
    import sys

    from .banner import render_logo

    if sys.stdout.isatty():
        click.clear()
    typer.echo(render_logo(color=sys.stdout.isatty(), unicode=unicode))
    typer.echo("")


def _home_menu(cfg, path: Path) -> None:
    """Dispatch to the arrow-key home menu on a TTY, else the letter fallback (tests / pipes)."""
    import sys

    from .banner import stream_supports_unicode

    uni = stream_supports_unicode(sys.stdout)
    if sys.stdin.isatty():
        try:
            import questionary  # noqa: F401
        except ImportError:
            _home_letter(cfg, path, unicode=uni)
            return
        _home_questionary(cfg, path, unicode=uni)
    else:
        _home_letter(cfg, path, unicode=uni)


@app.command(
    epilog="Example: grendel config        (arrow-key menu; add targets, wire the catalog)",
)
def config(ctx: typer.Context, config: ConfigOpt = None) -> None:
    """Interactively browse and edit the configuration, then save (no config file needed)."""
    import sys

    from .banner import stream_supports_unicode

    cfg = _resolve_config(ctx, config)
    path = config or Path("grendel.yaml")
    uni = stream_supports_unicode(sys.stdout)
    if sys.stdin.isatty():
        try:
            import questionary  # noqa: F401
        except ImportError:
            _config_prompt_loop(cfg, path, unicode=uni)
            return
        _config_interactive(cfg, path, unicode=uni)
    else:
        _config_prompt_loop(cfg, path, unicode=uni)
