"""The branded landing banner printed by a bare ``grendel`` invocation.

A GRENDEL wordmark logo + tagline + a colored command table + the authorized-use notice,
rendered inline like a normal CLI (no full-screen TUI). ``render_banner`` is pure and testable;
the CLI applies color. On a console whose encoding can't represent the block-art / emoji glyphs
(e.g. a legacy Windows cp1254 code page), pass ``unicode=False`` for a plain-ASCII fallback so the
first command a newcomer runs never dies with a UnicodeEncodeError.
"""

from __future__ import annotations

import codecs
import sys

import typer

# ASCII stand-ins for the handful of non-ASCII glyphs grendel prints, applied at the OUTPUT
# boundary (see install_console_fallback) so no console write can ever crash — including strings
# the pretty-vs-ASCII `unicode` flag doesn't reach (config labels, em-dashes, a report piped to
# stdout). Anything not listed degrades to '?' rather than raising.
_GLYPH_FALLBACKS = {
    "—": "-",
    "–": "-",
    "―": "-",
    "·": ".",
    "•": "*",
    "→": "->",
    "←": "<-",
    "↑": "^",
    "↓": "v",
    "…": "...",
    "✓": "+",
    "✗": "x",
    "⚠": "!",
    "🐺": "",
    "“": '"',
    "”": '"',
    "‘": "'",
    "’": "'",
}
_HANDLER_NAME = "grendel_console_fallback"


def _console_fallback(err):
    bad = err.object[err.start : err.end]
    return ("".join(_GLYPH_FALLBACKS.get(ch, "?") for ch in bad), err.end)


def install_console_fallback() -> None:
    """Make stdout/stderr downgrade un-encodable glyphs to ASCII instead of crashing.

    Registers a codec error handler and switches stdout/stderr to it, so ANY terminal write is
    crash-proof on a non-UTF-8 console (Windows cp1254, iso-8859-*, ascii). Files are written with
    explicit utf-8 elsewhere, so this only affects the console. Idempotent; a no-op where the
    stream can't be reconfigured (e.g. a test capture buffer).
    """
    codecs.register_error(_HANDLER_NAME, _console_fallback)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors=_HANDLER_NAME)
        except (AttributeError, ValueError):
            pass


_LOGO = r"""
 ██████╗ ██████╗ ███████╗███╗   ██╗██████╗ ███████╗██╗
██╔════╝ ██╔══██╗██╔════╝████╗  ██║██╔══██╗██╔════╝██║
██║  ███╗██████╔╝█████╗  ██╔██╗ ██║██║  ██║█████╗  ██║
██║   ██║██╔══██╗██╔══╝  ██║╚██╗██║██║  ██║██╔══╝  ██║
╚██████╔╝██║  ██║███████╗██║ ╚████║██████╔╝███████╗███████╗
 ╚═════╝ ╚═╝  ╚═╝╚══════╝╚═╝  ╚═══╝╚═════╝ ╚══════╝╚══════╝
"""

_LOGO_ASCII = r"""
  ____ ____  _____ _   _ ____  _____ _
 / ___|  _ \| ____| \ | |  _ \| ____| |
| |  _| |_) |  _| |  \| | | | |  _| | |
| |_| |  _ <| |___| |\  | |_| | |___| |___
 \____|_| \_\_____|_| \_|____/|_____|_____|
"""

_TAGLINE = "🐺  grendel — red-team your AI agents with authorized attack packs"
_TAGLINE_ASCII = "grendel - red-team your AI agents with authorized attack packs"

# (command, one-line description) — the whole surface, driven inline. A test asserts these
# names stay in sync with the actually-registered Typer commands (so none can be forgotten).
COMMANDS: list[tuple[str, str]] = [
    ("run", "fire attack packs at a target (LLM / agent / MCP)"),
    ("list", "list configured targets, providers, and attack packs"),
    ("report", "render a run record (text / json / md / html)"),
    ("diff", "compare two run records (ASR deltas, regressions)"),
    ("proxy", "zero-touch OpenAI-compatible LLM proxy (--serve)"),
    ("import", "import attacks from public corpora (garak)"),
    ("update", "pull attack packs from configured feeds"),
    ("config", "edit configuration interactively (arrow-key menu)"),
    ("doctor", "status & diagnostics (version, catalog, env keys)"),
]

_NOTICE = "authorized testing of agents you own or may test — defensive use only"
_NOTICE_ASCII = "authorized testing of agents you own or may test - defensive use only"


def stream_supports_unicode(stream) -> bool:
    """True if ``stream``'s encoding can represent the fancy glyphs (block art, emoji, ✓/✗)."""
    enc = getattr(stream, "encoding", None) or "ascii"
    try:
        "█▀✓✗🐺⚠—·".encode(enc)
        return True
    except (LookupError, UnicodeEncodeError):
        return False


def _c(text: str, color: bool, **style) -> str:
    return typer.style(text, **style) if color else text


def render_logo(*, color: bool = False, unicode: bool = True) -> str:
    """The GRENDEL wordmark (block art, or ASCII when ``unicode=False``); optionally colored."""
    art = _LOGO if unicode else _LOGO_ASCII
    return _c(art.strip("\n"), color, fg=typer.colors.BRIGHT_CYAN, bold=True)


def render_welcome(*, color: bool = False, unicode: bool = True) -> str:
    """A first-run orientation block for the home menu when nothing is configured yet.

    Says what Grendel is + the 3 steps, referencing the menu ITEM names (targets / run / doctor) so
    it reads correctly in both the letter shell ([t] targets) and the arrow-key one. ASCII-degrades.
    """
    dash = "—" if unicode else "-"
    b = lambda t: _c(t, color, bold=True)  # noqa: E731 — tiny local styler
    g = lambda t: _c(t, color, fg=typer.colors.GREEN, bold=True)  # noqa: E731
    dim = lambda t: _c(t, color, dim=True)  # noqa: E731
    lines = [
        f"{b('New here?')}  Grendel red-teams your AI {dash} it fires authorized attack packs",
        "           at a target and shows you which ones got through.",
        "",
        b("Get started:"),
        f"  1. {g('add a target')}   (targets)  a hosted model + key, or your own agent's URL",
        f"  2. {g('fire attacks')}   (run)",
        f"  3. {g('read results')}   the live dashboard, then browse which attacks got through",
        "",
        f"  {b('First time?')}  Pick {g('guided setup')} to do this step by step,",
        f"  or {g('learn')} to see what every word here means.",
        dim("  tip: 'doctor' is a health check & next steps any time."),
    ]
    return "\n".join(lines)


def render_concepts(*, color: bool = False, unicode: bool = True) -> str:
    """A plain-language glossary of every term a newcomer meets, shown by the 'learn' menu item.

    The app's own explainer so someone who has never seen Grendel understands what a target, a
    pack, ASR, and 'got through vs defended' mean — no external docs needed. ASCII-degrades so it
    never crashes a legacy console; ``color`` adds ANSI headers/terms for a TTY.
    """
    dash = "—" if unicode else "-"
    arrow = "→" if unicode else "->"
    b = lambda t: _c(t, color, bold=True)  # noqa: E731 — tiny local stylers
    g = lambda t: _c(t, color, fg=typer.colors.GREEN, bold=True)  # noqa: E731
    cy = lambda t: _c(t, color, fg=typer.colors.BRIGHT_CYAN, bold=True)  # noqa: E731
    dim = lambda t: _c(t, color, dim=True)  # noqa: E731
    ok = _c("PASS", color, fg=typer.colors.GREEN, bold=True)
    bad = _c("FAIL", color, fg=typer.colors.RED, bold=True)
    lines = [
        cy(f"What is Grendel?  {dash}  a red-team range for your AI"),
        f"  You point it at an AI you own, it fires hundreds of {b('authorized')} attacks",
        "  (jailbreaks, prompt injection, tool abuse), and grades each reply. You learn",
        "  which attacks got through so you can fix them before a real attacker finds them.",
        "",
        b("The words you'll see"),
        f"  {g('target')}    the AI under test {dash} a hosted model, or your own agent's URL.",
        f"  {g('provider')}  who hosts the model: openai / anthropic / openrouter / ollama,",
        f"            or a custom one. {dim('(ollama runs locally and is free.)')}",
        f"  {g('api key')}   the secret used to call a hosted provider. It lives in an env",
        f"            variable {dash} never written into the shared config file.",
        f"  {g('pack')}      one attack, a small YAML file. {g('category')} groups them:",
        "            jailbreak, prompt-injection, tool-abuse, ...",
        f"  {g('run')}       fire every attack at your target and grade every reply.",
        "",
        b("Reading the result"),
        f"  {bad} / {b('got through')}   the attack worked {dash} your AI did the unsafe thing.",
        f"  {ok} / {b('defended')}      your AI refused or stayed safe. Good.",
        f"  {g('ASR')}   Attack Success Rate {dash} % that got through. {b('Lower is better.')}",
        f"  {g('judge')} an optional LLM that grades borderline replies (tier T3).",
        "",
        b("After a run"),
        f"  Saved automatically. Browse {b('got through')} vs {b('defended')} right here,",
        "  or export a Markdown / HTML report and compare runs over time.",
        "",
        dim(f"  Golden rule: only test what you own or may test {arrow} defensive use only."),
    ]
    return "\n".join(lines)


def config_header(path, *, color: bool = False, unicode: bool = True) -> str:
    """A compact branded header for the interactive `grendel config` menu."""
    label = "🐺 GRENDEL" if unicode else "GRENDEL"
    sep = "·" if unicode else "-"
    dash = "—" if unicode else "-"
    brand = _c(label, color, fg=typer.colors.BRIGHT_CYAN, bold=True)
    return f"{brand}  {sep}  config {dash} {path}"


def render_banner(*, color: bool = False, unicode: bool = True) -> str:
    """Return the landing banner. ``color`` adds ANSI; ``unicode=False`` gives an ASCII fallback."""

    def c(text: str, **style) -> str:
        return typer.style(text, **style) if color else text

    lines: list[str] = []
    lines.append(render_logo(color=color, unicode=unicode))
    lines.append(_TAGLINE if unicode else _TAGLINE_ASCII)
    lines.append("")
    lines.append(c("Usage:", bold=True) + "  grendel <command> [options]")
    lines.append("        grendel <command> --help   " + c("# help for any command", dim=True))
    lines.append("")
    lines.append(c("Commands:", bold=True))
    width = max(len(name) for name, _ in COMMANDS)
    for name, desc in COMMANDS:
        lines.append(f"  {c(name.ljust(width), fg=typer.colors.GREEN, bold=True)}  {desc}")
    lines.append("")
    lines.append(
        c("New here?", bold=True) + "  grendel doctor   " + c("# status & next steps", dim=True)
    )
    lines.append(
        "           grendel run --provider openai --model gpt-4o-mini --pack jailbreak --dry-run"
    )
    lines.append("")
    warn = "⚠ " if unicode else "! "
    lines.append(c(warn + (_NOTICE if unicode else _NOTICE_ASCII), fg=typer.colors.YELLOW))
    return "\n".join(lines)
