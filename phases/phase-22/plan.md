# Phase 22 — implementation plan

Derived from `phases/phase-22/spec.md`. One milestone (presentation-only, all in `live.py`), ending in
a checkpoint (`ruff` clean + `pytest` green + `reviewer`/`tester` `STATUS: PASS`).

---

## Milestone 1 — Branded, bordered live dashboard

**Intent:** a real "visual feast" — logo + bordered panel + progress bar + labelled sent count + a
tall verdict stream — without changing any run/count/ASR logic or the off-TTY fallback.

**Steps**
1. **`live.py` — state:** `LiveAttackRun.__init__` keeps the counters/ASR/`recent` as-is but (a) bumps
   `recent = deque(maxlen=200)` so more history is retained, (b) adds `self._visible = 12` (default row
   budget, overridden from the console height in `__enter__`). `on_attempt`/`_asr` unchanged (still
   exclude `is_control`).
2. **`live.py` — `_render()` rebuild** (all rich imports stay lazy/inside):
   - `u = self.unicode`. Glyphs ASCII-degrade as today (`_GLYPH` unicode/ascii pair).
   - **Logo:** `Text(render_logo(color=False, unicode=u), style="bold cyan")` (raw art, rich colors it).
   - **Progress:** unicode → `rich.progress_bar.ProgressBar(total, completed=n, width=40,
     complete_style="bright_cyan", finished_style="green")`; ascii → a manual `#`/`-` bar `Text`
     (ProgressBar/heavy chars aren't cp1254-safe). A `Table.grid` row: `ASR {asr:.0%}` (magenta) · bar ·
     `{n}/{total} sent` (bold) — the labelled sent count answers "how many went to the LLM".
   - **Stat row:** `Text` with `{hit_m} hits {hits}` (red) · `{def_m} defended {defended}` (green) ·
     `{err_m} errors {errors}` (yellow).
   - **Separator:** unicode → `Rule(style="cyan")`; ascii → a plain `Text("-"*width-ish)` (no `─`).
   - **Stream:** `list(self.recent)[:self._visible]`, each a colored `glyph + attack_id + (category)`.
   - **Frame:** wrap the `Group(logo, "", target line, progress row, stat row, sep, *stream)` in a
     `rich.panel.Panel(..., box=box.ROUNDED if u else box.ASCII, border_style="cyan",
     title="🐺 live attack run" if u else "GRENDEL - live attack run", title_align="left")`. ASCII box
     avoids `─│┌` on cp1254.
   - Guard `total = max(self.total, 1)` retained.
3. **`live.py` — `__enter__`:** create `Console(legacy_windows=False)` (as today), then set
   `self._visible = max(6, console.size.height - 16)` (logo + panel chrome overhead) so the stream
   fills a tall terminal; start `Live(self._render(), console=console, refresh_per_second=12,
   transient=False)`. A failure reading `size` falls back to the default 12 (wrapped in try/except).
4. **Tests** (`test_live_dashboard.py`, extend): existing counter/ASR/controls/total-guard tests
   unchanged. Update the render-smoke test for the new layout: assert the output contains the target
   label, `ASR`, `N/total sent` (the labelled count), a recent `attack_id`, and — NEW — the `GRENDEL`
   wordmark text (assert a distinctive logo fragment appears). Keep the ASCII-degrade test but broaden
   it: unicode=False output must contain none of `█ ░ ✗ ✓ ⚠ · ─ │` (bar, glyphs, AND box/rule chars),
   proving the whole frame is cp1254-safe; still contains `x hits`/`x HIT`. Add a test that `_visible`
   defaults to 12 without `__enter__` (render works headless).

**Checkpoint 1 (phase close):** full suite green + ruff clean; `reviewer` + `tester` `STATUS: PASS`;
append `phase 22: DONE …` to `PROGRESS.md`.

---

## Plan review — addressed
- (1) logo `Text(no_wrap=True, overflow="crop")`; the logo is shown only when console width ≥ 66
  (`self._show_logo`), else dropped — no mid-glyph wrap on narrow terminals.
- (2,3) `__enter__` computes height budget from the ACTUAL pieces: total = logo_part(7 if shown else 0)
  + 6 fixed (target+progress+stat+separator + 2 panel borders) + stream. `_visible = max(3, height -
  6 - logo_part)` so the WHOLE panel fits the terminal height (not just a lower bound); on a very short
  terminal the logo is dropped first (width/So-height gate), then the stream shrinks. Constants carry a
  comment with the arithmetic; a test feeds a fake height and asserts `_visible`.
- (4) exact label is `{n}/{total} sent` everywhere (spec wording reconciled); the checkpoint test
  asserts `f"{n}/{total} sent"`.
- (5) ascii separator width = the panel INNER width `self._width` (console width − 4 for border+pad),
  set in `__enter__` (default 60 headless): `Text("-" * self._width)`.
- (6) `ProgressBar` is INSTANTIATED only in the `unicode` branch (not merely styled) — the ascii branch
  builds a manual `#`/`-` bar; `self.unicode` (from `stream_supports_unicode`) is the single gate, not
  rich's own encoding detection.
- (7) tests add a width=80 render assertion; over-long `attack_id`/`(category)` may crop at the border
  (accepted — the full id is in the saved record).

## Risks & mitigations
- **cp1254 crash / garbage** → ASCII-degrade now covers glyphs AND box/bar/rule chars; `legacy_windows=
  False` + `install_console_fallback` remain; a broadened test asserts no fancy glyph leaks in ASCII mode.
- **Logo repaint cost** → the wordmark is static text inside a diffed `rich.Live`; repaint is cheap
  (rich only redraws changed cells). If height is tight, `_visible` shrinks so the frame still fits.
- **`console.size` unavailable (redirected / odd terminal)** → wrapped in try/except → default 12 rows.
- **Existing tests** → only the render-smoke + ASCII tests change (new layout strings); counter/ASR/gate
  tests untouched; off-TTY `make_live_run`→None path and `_menu_run` fallback unchanged.
- **True scrollback expectation** → explicitly out of scope; the stream fills the height and the full
  1517-row history is the saved record (`grendel report`), noted to the user.
