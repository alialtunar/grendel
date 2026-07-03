"""A polished `rich` run-report card shown after a menu run and in the reports viewer.

`render_card(record, path)` returns a bordered rich renderable — ASR headline + bar, verdict
tallies, tokens/cost/duration, a per-category ASR breakdown, an OWASP line, and the top hits — in
the same visual language as the live dashboard. rich is imported LAZILY; the caller falls back to
the plain `reports.render_text` off-TTY / no rich. Every glyph/bar/box ASCII-degrades on cp1254.
"""

from __future__ import annotations

from .records import AttemptRecord, RunRecord, Verdict

_GLYPH = {"hit": ("✗", "x"), "def": ("✓", "+"), "err": ("⚠", "!")}

# verdict.name -> (unicode badge, ascii badge, style) for the per-attempt detail card
_BADGE = {
    "FAIL": ("✗ GOT THROUGH", "x GOT THROUGH", "bold red"),
    "PASS": ("✓ defended", "+ defended", "green"),
    "ERROR": ("⚠ error", "! error", "yellow"),
    "SKIPPED": ("· skipped", ". skipped", "dim"),
}
_MAX_TEXT = 2000  # cap prompt/response length in the detail card so a huge reply can't flood


def _bar(frac: float, width: int, unicode: bool) -> str:
    frac = 0.0 if frac < 0 else (1.0 if frac > 1 else frac)
    filled = int(width * frac)
    fill_ch, empty_ch = ("█", "░") if unicode else ("#", "-")
    return fill_ch * filled + empty_ch * (width - filled)


def _asr_style(asr: float) -> str:
    return "bold red" if asr >= 0.4 else ("bold yellow" if asr >= 0.15 else "bold green")


def _duration_s(record: RunRecord) -> float | None:
    starts = [a.started_at for a in record.attempts if a.started_at is not None]
    ends = [a.finished_at for a in record.attempts if a.finished_at is not None]
    if not starts or not ends:
        return None
    return max(0.0, (max(ends) - min(starts)).total_seconds())


def _fmt_dur(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 60}m{s % 60:02d}s" if s >= 60 else f"{s}s"


def render_card(record: RunRecord, path, *, unicode: bool = True):
    """A bordered rich report card for a completed RunRecord."""
    from rich import box
    from rich.console import Group
    from rich.panel import Panel
    from rich.text import Text

    u = unicode
    ov = "ellipsis" if u else "crop"  # "…" isn't cp1254-encodable → hard-crop in ascii
    hit_m, def_m, err_m = (_GLYPH[k][0] if u else _GLYPH[k][1] for k in ("hit", "def", "err"))
    m = record.metrics_summary()
    asr = m["overall_asr"]

    def line() -> Text:
        return Text(no_wrap=True, overflow=ov)

    rows: list = [Text("")]
    head = line()
    head.append(f"ASR {asr:.0%}   ", style=_asr_style(asr))
    head.append(_bar(asr, 22, u), style=_asr_style(asr).split()[-1])
    rows.append(head)
    rows.append(Text(""))

    tally = line()
    tally.append(f"attempts {record.total_attempts}    ", style="bold")
    tally.append(f"{hit_m} {m['succeeded']} hits", style="bold red")
    tally.append("    ")
    tally.append(f"{def_m} {m['defended']} defended", style="green")
    tally.append("    ")
    tally.append(f"{err_m} {m['errored']} errors", style="yellow")
    rows.append(tally)

    meta = line()
    meta.append(f"tokens {record.total_usage.total_tokens}", style="dim")
    meta.append(f"   cost ${record.total_cost_usd:.4f}", style="dim")
    dur = _duration_s(record)
    if dur is not None:
        meta.append(f"   duration {_fmt_dur(dur)}", style="dim")
    rows.append(meta)

    by_cat = sorted(m["by_category"].items(), key=lambda kv: -kv[1]["scored"])[:6]
    if by_cat:
        rows.append(Text(""))
        rows.append(Text("by category", style="dim"))
        for cat, st in by_cat:
            row = line()
            row.append(f"{cat[:16]:<16} ", style="cyan")
            row.append(_bar(st["asr"], 10, u), style="red" if st["asr"] >= 0.3 else "yellow")
            row.append(f" {st['asr']:.0%}", style="bold")
            rows.append(row)

    owasp = sorted((c for c in m["by_owasp"] if c), key=str)
    if owasp:
        ow = line()
        ow.append("OWASP  ", style="dim")
        for code in owasp[:5]:
            ow.append(f"{code} {m['by_owasp'][code]['asr']:.0%}  ", style="magenta")
        rows.append(Text(""))
        rows.append(ow)

    hits = [a for a in record.attempts if not a.is_control and a.verdict == Verdict.FAIL]
    hits.sort(key=lambda a: (a.attack_id or "", a.attempt_id))
    if hits:
        rows.append(Text(""))
        rows.append(Text(f"top hits ({len(hits)})", style="bold red"))
        for a in hits[:5]:
            hrow = line()
            hrow.append(f"  {hit_m} ", style="bold red")
            hrow.append(str(a.attack_id or "?"))
            if a.category:
                hrow.append(f"  ({a.category})", style="dim")
            rows.append(hrow)

    rows.append(Text(""))
    rows.append(Text(f"saved {'→' if u else '->'} {path}", style="dim", no_wrap=True, overflow=ov))
    tip = line()
    tip.append("full report:  ", style="dim")
    tip.append(f"grendel report --run {path} --format md", style="cyan")
    rows.append(tip)

    title = f"🐺 run report · {record.target_name}" if u else f"run report - {record.target_name}"
    return Panel(
        Group(*rows),
        box=box.ROUNDED if u else box.ASCII,
        border_style=_asr_style(asr).split()[-1],
        title=title,
        title_align="left",
    )


def render_attempt(attempt: AttemptRecord, *, unicode: bool = True):
    """A bordered rich detail card for ONE attempt: verdict, category, prompt, response, and why."""
    from rich import box
    from rich.console import Group
    from rich.panel import Panel
    from rich.text import Text

    u = unicode
    ov = "ellipsis" if u else "crop"
    u_badge, a_badge, style = _BADGE.get(
        attempt.verdict.name, ("· ?", ". ?", "dim")
    )

    def _clip(s: str) -> str:
        s = s or ""
        if len(s) <= _MAX_TEXT:
            return s
        return s[:_MAX_TEXT] + ("… (truncated)" if u else " (truncated)")

    rows: list = [Text("")]
    badge = Text(no_wrap=True, overflow=ov)
    badge.append(u_badge if u else a_badge, style=f"bold {style}")
    if attempt.category:
        badge.append(f"   ({attempt.category})", style="dim")
    rows.append(badge)
    rows.append(Text(""))
    rows.append(Text("prompt", style="bold cyan"))
    rows.append(Text(_clip(attempt.prompt), style="dim"))
    rows.append(Text(""))
    rows.append(Text("response", style="bold cyan"))
    body = attempt.response_text if attempt.response_text else (attempt.error or "(no response)")
    rows.append(Text(_clip(body)))
    detail = attempt.score_detail
    if detail is not None and detail.reason:
        rows.append(Text(""))
        why = Text(no_wrap=True, overflow=ov)
        why.append("why  ", style="bold cyan")
        why.append(f"[{detail.tier}] " if detail.tier else "", style="magenta")
        why.append(detail.reason, style="dim")
        rows.append(why)

    title = f"{'🐺 ' if u else ''}{attempt.attack_id or '(no id)'}"
    return Panel(
        Group(*rows),
        box=box.ROUNDED if u else box.ASCII,
        border_style=style.split()[-1],
        title=title,
        title_align="left",
    )
