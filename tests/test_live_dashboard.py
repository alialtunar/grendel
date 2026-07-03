"""Phase 21 M2: the rich live attack dashboard — counter math + render smoke, offline.

The on-TTY rich.Live wiring is offline-untestable (CliRunner/pytest is non-TTY), matching the
project's menu-test convention; the pure state/render logic and the TTY gate are unit-tested here.
"""

from __future__ import annotations

from io import StringIO

from grendel.live import LiveAttackRun, _layout, make_live_run


class _V:
    def __init__(self, name: str) -> None:
        self.name = name


class _A:
    def __init__(
        self, verdict: str, attack_id="jb/x", category="jailbreak", is_control=False
    ) -> None:
        self.verdict = _V(verdict)
        self.attack_id = attack_id
        self.category = category
        self.is_control = is_control


def test_make_live_run_none_off_tty(monkeypatch) -> None:
    import sys

    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    assert make_live_run(10, "t") is None  # pipes/tests get no dashboard


def test_counter_math_and_asr() -> None:
    run = LiveAttackRun(4, "gpt (openai/gpt-4o)")
    run.on_attempt(_A("FAIL"))  # hit
    run.on_attempt(_A("PASS"))  # defended
    run.on_attempt(_A("FAIL"))  # hit
    run.on_attempt(_A("ERROR"))  # error, not scored
    assert (run.n, run.hits, run.defended, run.errors) == (4, 2, 1, 1)
    assert run._asr() == 2 / 3  # hits / (hits+defended), errors excluded


def test_controls_excluded_from_asr() -> None:
    run = LiveAttackRun(2, "t")
    run.on_attempt(_A("PASS", is_control=True))  # a benign control — must not count toward ASR
    run.on_attempt(_A("FAIL"))
    assert run.defended == 0 and run.hits == 1
    assert run._asr() == 1.0  # only the real attack scored


def test_total_zero_guard_no_zero_division() -> None:
    run = LiveAttackRun(0, "t")  # guarded to max(total, 1)
    run.on_attempt(_A("FAIL"))
    from rich.console import Console

    Console(file=StringIO(), force_terminal=False).print(run._render())  # must not raise


def _render_text(run, *, width: int) -> str:
    from rich.console import Console

    buf = StringIO()
    Console(file=buf, force_terminal=False, width=width).print(run._render())
    return buf.getvalue()


def test_render_has_logo_panel_target_sent_and_recent() -> None:
    run = LiveAttackRun(3, "myagent (openai/gpt-4o)")
    run.on_attempt(_A("FAIL", attack_id="jailbreak/dan-01"))
    run.on_attempt(_A("PASS", attack_id="prompt-injection/sys-leak"))
    out = _render_text(run, width=100)
    assert "myagent (openai/gpt-4o)" in out  # target line
    assert "ASR" in out and "2/3 sent" in out  # labelled sent count (answers "how many went")
    assert "live attack run" in out  # bordered panel title
    assert "█" in out  # GRENDEL wordmark block-art rendered
    assert "jailbreak/dan-01" in out  # a stream entry


def test_render_at_80_cols_still_shows_core() -> None:
    run = LiveAttackRun(3, "gpt (openai/gpt-4o)")
    run.on_attempt(_A("PASS", attack_id="jailbreak/dan-01"))
    out = _render_text(run, width=80)
    assert "ASR" in out and "1/3 sent" in out and "jailbreak/dan-01" in out


def test_logo_dropped_leaves_no_block_art() -> None:
    run = LiveAttackRun(3, "t")
    run._show_logo = False  # what _layout does on a narrow terminal
    out = _render_text(run, width=100)
    assert "█" not in out and "live attack run" in out


def test_ascii_degrade_uses_no_fancy_glyphs_or_box() -> None:
    # On a non-UTF-8 console (cp1254) glyphs AND box/bar/rule/spinner chars degrade to ASCII.
    from grendel.live import _SPIN_U

    run = LiveAttackRun(4, "t", unicode=False)
    run._show_logo, run._visible, run._cats = False, 6, 3
    # a long id would crop — assert the crop uses no "…" (not cp1254-encodable), just a hard cut
    long_id = "tool-abuse/indirect-injection-tool-output-01-very-long"
    for v, aid, cat in [("FAIL", long_id, "jailbreak"), ("PASS", "pi/x", "prompt-injection")]:
        run.on_attempt(_A(v, attack_id=aid, category=cat))
    out = _render_text(run, width=72)  # narrow enough to force a crop of the long id
    assert long_id not in out  # the long id was cropped (not shown in full)
    assert "x HIT" in out and "jailbreak" in out  # stream + category
    assert "GRENDEL - live attack run" in out  # ascii panel title
    forbidden = ("█", "░", "✗", "✓", "⚠", "·", "─", "│", "━", "⚡", "…", *_SPIN_U)
    for fancy in forbidden:
        assert fancy not in out


def test_by_category_tracks_hits_and_scored() -> None:
    run = LiveAttackRun(5, "t")
    run.on_attempt(_A("FAIL", category="jailbreak"))
    run.on_attempt(_A("PASS", category="jailbreak"))
    run.on_attempt(_A("FAIL", category="prompt-injection"))
    run.on_attempt(_A("PASS", category="jailbreak", is_control=True))  # control excluded
    assert run._by_cat["jailbreak"] == [1, 2]  # 1 hit / 2 scored (control not counted)
    assert run._by_cat["prompt-injection"] == [1, 1]


def test_momentum_deterministic_with_injected_clock() -> None:
    run = LiveAttackRun(100, "t")
    assert run._momentum() == "—"  # no clock (headless) → em-dash, no crash
    run._start = 0.0
    run._clock = lambda: 20.0  # 20s elapsed
    run.n = 40  # 40 done of 100 → 2.0/s → 60 left → ETA 30s
    mom = run._momentum()
    assert "2.0/s" in mom and "ETA" in mom and "20s" in mom


def test_spotlight_marks_newest_hit_only() -> None:
    run = LiveAttackRun(4, "t")
    run.on_attempt(_A("FAIL", attack_id="jb/first-hit"))
    run.on_attempt(_A("PASS", attack_id="pi/defended"))  # newest row, not a hit
    out = _render_text(run, width=100)
    assert "⚡" in out and "jb/first-hit" in out  # the hit is spotlighted, the PASS is not


def test_long_ids_never_overflow_terminal_height() -> None:
    # Regression: long attack_id/category/target must be cropped (no_wrap+ellipsis), not wrapped —
    # a wrapped row would push the panel past the height _layout budgeted (Live scroll/flicker).
    from rich.console import Console

    long_id = "tool-abuse/indirect-injection-tool-output-01-very-long-id-that-would-wrap"
    long_cat = "tool-abuse-verylongcategoryname-that-keeps-going"
    for width, height in [(36, 8), (66, 10), (80, 24), (100, 24), (100, 30), (120, 40)]:
        for uni in (True, False):
            show_logo, visible, cats, _ = _layout(height, width, unicode=uni)
            run = LiveAttackRun(1517, "cli (openai/a-very-long-target-label-here)", unicode=uni)
            run._show_logo, run._visible, run._cats = show_logo, visible, cats
            run._start, run._clock = 0.0, lambda: 41.0  # exercise the momentum footer too
            for k in range(visible + 6):  # fill past capacity with long strings
                run.on_attempt(_A(("FAIL" if k % 2 else "PASS"),
                                  attack_id=long_id + str(k), category=long_cat))
            run.n = 482
            c = Console(file=StringIO(), force_terminal=True, width=width, legacy_windows=False)
            with c.capture() as cap:
                c.print(run._render())
            out = cap.get()
            lines = out.rstrip("\n").count("\n") + 1
            assert lines <= height, f"{width}x{height} uni={uni}: {lines} > {height} lines"
            if not uni:  # the ellipsis char "…" isn't cp1254-encodable — ascii must hard-crop
                assert "…" not in out, f"{width}x{height} ascii leaked an ellipsis"


def test_layout_fits_terminal_height() -> None:
    # tall + wide → logo shown; column-row height = available = height - logo(7) - chrome(4)
    show_logo, visible, cats, inner = _layout(height=40, width=100)
    assert show_logo and visible == 40 - 7 - 4 and cats == 6 and inner == 96
    # narrow → logo dropped, stream grows by the freed rows
    show_logo, visible, _cats, _ = _layout(height=40, width=50)
    assert show_logo is False and visible == 40 - 4
    # SHORT height → logo dropped AND categories degrade to 0, whole panel still fits
    show_logo, visible, cats, _ = _layout(height=8, width=100)
    assert show_logo is False and cats == 0 and visible + 4 == 8  # 0 logo + chrome 4 + stream == 8
    # ascii logo is 5 art rows (6 with spacer), so it frees one more row than unicode's 7
    show_logo, visible, _cats, _ = _layout(height=40, width=100, unicode=False)
    assert show_logo and visible == 40 - 6 - 4
