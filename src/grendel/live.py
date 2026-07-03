"""A rich two-column live dashboard for the interactive menu run (phases 21-24).

A per-attempt callback drives a bordered `rich.Live` control-room view: the GRENDEL wordmark, a LEFT
column with the headline ASR + a per-category breakdown of live attack-success bars, a RIGHT column
with the newest attacks streaming in (red = hit, green = defended, yellow = error) with the latest
hit spotlighted, and a footer with a progress bar + elapsed/throughput/ETA. rich is imported LAZILY
so its absence never breaks module import; `make_live_run` returns None off-TTY or without rich, and
the caller falls back to the plain one-line counter. Every glyph/bar/box/rule ASCII-degrades on a
non-UTF-8 console (Windows cp1254, etc.), and `_layout` keeps the whole panel within the terminal.
"""

from __future__ import annotations

from collections import deque

# verdict.name -> (unicode label, ascii label, rich style)
_GLYPH = {
    "FAIL": ("✗ HIT ", "x HIT ", "bold red"),
    "PASS": ("✓ def ", "+ def ", "green"),
    "ERROR": ("⚠ err ", "! err ", "yellow"),
    "SKIPPED": ("· skip", ". skip", "dim"),
}
_SPIN_U = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
_SPIN_A = "|/-\\"

# Panel chrome outside the two columns: target line + footer + 2 border lines.
_CHROME = 4
# left column's fixed lines above the category list: ASR, fired, stat, "by category"
_STATS_HEAD = 4
_LOGO_LINES_U = 7  # unicode wordmark: 6 art rows + 1 blank spacer
_LOGO_LINES_A = 6  # ascii wordmark: 5 art rows + 1 blank spacer
_MIN_LOGO_WIDTH = 66  # below this the wordmark would wrap mid-glyph → drop it


def _layout(height: int, width: int, *, unicode: bool = True) -> tuple[bool, int, int, int]:
    """(show_logo, visible_stream_rows, category_rows, panel_inner_width) that keep the WHOLE panel
    within the terminal. Column-row height = max(stats, stream); both are bounded by `available` so
    the panel is exactly `logo_part + _CHROME + available` lines. The logo drops on a narrow/short
    terminal, then categories degrade to 0, so a small terminal never overflows (→ Live scroll)."""
    logo_h = _LOGO_LINES_U if unicode else _LOGO_LINES_A
    show_logo = width >= _MIN_LOGO_WIDTH and height >= _CHROME + logo_h + _STATS_HEAD + 2
    logo_part = logo_h if show_logo else 0
    available = max(1, height - logo_part - _CHROME)
    cats = min(6, max(0, available - _STATS_HEAD))
    return show_logo, available, cats, max(20, width - 4)


class LiveAttackRun:
    """Accumulates per-attempt state and repaints a rich dashboard. Usable as a context manager."""

    def __init__(self, total: int, target_label: str, *, unicode: bool = True) -> None:
        self.total = max(int(total), 1)  # guard: bar math must never divide by zero
        self.target_label = target_label
        self.unicode = unicode  # ASCII-degrade glyphs/box/bar on a non-UTF-8 console (cp1254, etc.)
        self.n = self.hits = self.defended = self.errors = self.skipped = 0
        self.recent: deque = deque(maxlen=200)  # retain history; only _visible rows are shown
        self._by_cat: dict[str, list[int]] = {}  # category -> [hits, scored] (controls excluded)
        self._visible = 12  # stream rows to show (overridden from console height in __enter__)
        self._cats = 6  # category rows to show
        self._show_logo = True
        self._width = 60  # panel inner width (footer bar; set in __enter__)
        self._start = None  # monotonic run-start (set in __enter__; None headless → no momentum)
        self._clock = None
        self._live = None

    def on_attempt(self, attempt) -> None:
        try:
            self.n += 1
            name = attempt.verdict.name
            control = getattr(attempt, "is_control", False)
            cat = getattr(attempt, "category", None) or "uncategorized"
            if name == "FAIL" and not control:  # exclude controls from ASR (matches records._asr)
                self.hits += 1
            elif name == "PASS" and not control:
                self.defended += 1
            elif name == "ERROR":
                self.errors += 1
            elif name == "SKIPPED":
                self.skipped += 1
            if name in ("FAIL", "PASS") and not control:  # per-category ASR (scored, non-control)
                bucket = self._by_cat.setdefault(cat, [0, 0])
                bucket[1] += 1
                if name == "FAIL":
                    bucket[0] += 1
            aid = getattr(attempt, "attack_id", None) or "?"
            self.recent.appendleft((name, aid, getattr(attempt, "category", "")))
            # NOTE: state mutation + _render() run together HERE on the asyncio-loop thread, before
            # Live.update() (internally locked). rich's background refresh thread never calls
            # _render() itself — do not move _render() off this thread or the race reappears.
            if self._live is not None:
                self._live.update(self._render())
        except Exception:  # noqa: BLE001 — a UI callback must never abort a run
            pass

    def _asr(self) -> float:
        scored = self.hits + self.defended
        return self.hits / scored if scored else 0.0

    def _bar(self, frac: float, width: int) -> str:
        frac = 0.0 if frac < 0 else (1.0 if frac > 1 else frac)
        filled = int(width * frac)
        fill_ch, empty_ch = ("█", "░") if self.unicode else ("#", "-")
        return fill_ch * filled + empty_ch * (width - filled)

    @staticmethod
    def _fmt_time(seconds: float) -> str:
        s = int(max(0, seconds))
        return f"{s // 60}m{s % 60:02d}s" if s >= 60 else f"{s}s"

    def _momentum(self) -> str:
        if self._start is None or self._clock is None:
            return "—" if self.unicode else "-"
        elapsed = self._clock() - self._start
        sep = "·" if self.unicode else "-"
        if elapsed <= 0 or self.n == 0:
            return self._fmt_time(elapsed)
        rate = self.n / elapsed
        eta = max(0, self.total - self.n) / rate if rate > 0 else 0
        return f"{self._fmt_time(elapsed)} {sep} {rate:.1f}/s {sep} ETA {self._fmt_time(eta)}"

    def _line(self, ov):
        from rich.text import Text

        return Text(no_wrap=True, overflow=ov)  # single-line row (no nested-table width haggling)

    def _stats(self):
        from rich.console import Group
        from rich.text import Text

        u = self.unicode
        ov = "ellipsis" if u else "crop"
        hit_m, def_m, err_m = ("✗", "✓", "⚠") if u else ("x", "+", "!")
        asr = self._asr()
        head = self._line(ov)
        head.append(f"ASR {asr:.0%}  ", style="bold magenta")
        head.append(self._bar(asr, 12), style="magenta")
        budget = self._visible
        rows: list = [head]
        if budget >= 2:
            rows.append(Text(f"fired  {self.n}/{self.total}", style="bold", no_wrap=True))
        if budget >= 3:
            stat = self._line(ov)
            stat.append(f"{hit_m} {self.hits}", style="bold red")
            stat.append("   ")
            stat.append(f"{def_m} {self.defended}", style="green")
            stat.append("   ")
            stat.append(f"{err_m} {self.errors}", style="yellow")
            rows.append(stat)
        if self._cats > 0 and budget >= _STATS_HEAD + 1:
            rows.append(Text("by category", style="dim"))
            items = sorted(self._by_cat.items(), key=lambda kv: -kv[1][1])[: self._cats]
            if not items:
                rows.append(Text("(warming up…)" if u else "(warming up...)", style="dim"))
            for cat, (h, sc) in items:
                cat_asr = h / sc if sc else 0.0
                line = self._line(ov)  # ONE Text → guaranteed one physical line, no width haggling
                line.append(f"{cat[:12]:<12} ", style="cyan")
                line.append(self._bar(cat_asr, 6), style="red" if cat_asr >= 0.3 else "yellow")
                line.append(f" {cat_asr:.0%}", style="bold")
                rows.append(line)
        return Group(*rows)

    def _stream(self, rows):
        from rich.console import Group
        from rich.text import Text

        u = self.unicode
        ov = "ellipsis" if u else "crop"  # "…" isn't cp1254-encodable → hard-crop in ascii mode
        spot = next((i for i, (name, _a, _c) in enumerate(rows) if name == "FAIL"), None)
        out: list = []
        for i, (name, aid, cat) in enumerate(rows):
            u_lbl, a_lbl, style = _GLYPH.get(name, ("· ?", ". ?", "dim"))
            # no_wrap + crop/ellipsis: a long attack_id/category stays ONE physical line, else it
            # wraps and the panel grows past the terminal height that _layout budgeted.
            line = Text(no_wrap=True, overflow=ov)
            if i == spot:  # spotlight the newest hit in view
                line.append("⚡ " if u else "* ", style="bold yellow")
                style = "bold reverse red"
            line.append((u_lbl if u else a_lbl) + " ", style=style)
            line.append(str(aid))
            if cat:
                line.append(f"  ({cat})", style="dim")
            out.append(line)
        if not out:
            return Text("(warming up…)" if u else "(warming up...)", style="dim")
        return Group(*out)

    def _footer(self):
        ov = "ellipsis" if self.unicode else "crop"
        spin = (_SPIN_U if self.unicode else _SPIN_A)[self.n % (10 if self.unicode else 4)]
        bar_w = max(8, self._width - 42)
        foot = self._line(ov)  # ONE Text → one physical line at any width
        foot.append(f"{spin} ", style="bold cyan")
        foot.append(self._bar(self.n / self.total, bar_w), style="cyan")
        foot.append(f"  {self.n}/{self.total} sent  ", style="bold")
        foot.append(self._momentum(), style="dim")
        return foot

    def _render(self):
        from rich.table import Table
        from rich.text import Text

        from .banner import render_logo

        u = self.unicode
        ov = "ellipsis" if u else "crop"  # "…" isn't cp1254-encodable → hard-crop in ascii mode
        body: list = []
        if self._show_logo:
            body.append(Text(render_logo(color=False, unicode=u), style="bold cyan",
                        no_wrap=True, overflow="crop"))
            body.append(Text(""))
        body.append(Text(f"target  {self.target_label}", style="dim", no_wrap=True, overflow=ov))
        cols = Table.grid(expand=True, padding=(0, 2))
        cols.add_column(ratio=2, no_wrap=True, overflow=ov)
        cols.add_column(ratio=3, no_wrap=True, overflow=ov)
        cols.add_row(self._stats(), self._stream(list(self.recent)[: self._visible]))
        body.append(cols)
        body.append(self._footer())
        title = "🐺 live attack run" if u else "GRENDEL - live attack run"
        return _panel(body, u, title)

    def __enter__(self) -> LiveAttackRun:
        import time

        from rich.console import Console
        from rich.live import Live

        # legacy_windows=False → rich writes ANSI via stdout.write (respecting the CLI's console
        # fallback handler) instead of the win32 API that crashes on a cp1254 console.
        console = Console(legacy_windows=False)
        try:
            height, width = console.size.height, console.size.width
        except Exception:  # noqa: BLE001 — odd/redirected terminal → safe defaults
            height, width = 24, 80
        self._show_logo, self._visible, self._cats, self._width = _layout(
            height, width, unicode=self.unicode
        )
        self._clock = time.monotonic
        self._start = self._clock()
        self._live = Live(self._render(), console=console, refresh_per_second=12, transient=False)
        self._live.start()
        return self

    def __exit__(self, *exc) -> bool:
        if self._live is not None:
            self._live.update(self._render())  # paint the final frame
            self._live.stop()
        return False


def _panel(rows: list, unicode: bool, title: str):
    from rich import box
    from rich.console import Group
    from rich.panel import Panel

    return Panel(
        Group(*rows),
        box=box.ROUNDED if unicode else box.ASCII,
        border_style="cyan",
        title=title,
        title_align="left",
    )


def make_live_run(total: int, target_label: str):
    """A LiveAttackRun on a TTY with rich available, else None (caller uses the plain counter)."""
    import sys

    if not sys.stdout.isatty():
        return None
    try:
        import rich  # noqa: F401
    except ImportError:
        return None
    from .banner import stream_supports_unicode

    return LiveAttackRun(total, target_label, unicode=stream_supports_unicode(sys.stdout))
