# Phase 24 — implementation plan

Derived from `phases/phase-24/spec.md`. One milestone (presentation, all in `live.py`), ending in a
checkpoint (ruff clean + pytest green + reviewer/tester STATUS: PASS).

---

## Milestone 1 — two-column control-room dashboard

**Intent:** a two-column rich view (stats + per-category bars | attack stream) with momentum metrics
and a latest-hit spotlight — beautiful, cp1254-safe, height-fitting, off-TTY unchanged.

**Steps**
1. **`live.py` — new state in `__init__`:**
   - `self._by_cat: dict[str, list[int]]` — `{category: [hits, scored]}` for the per-category breakdown.
   - `self._start: float | None = None` and `self._clock` (defaults to `time.monotonic`, injectable for
     tests) — for elapsed/rate/ETA; `_start` is set in `__enter__` (None when rendered headless → the
     footer shows `—` for time, so tests stay deterministic).
   - keep counters/ASR/`recent` (maxlen bumped to 200 already).
2. **`on_attempt` — also fold per-category:** for a non-control PASS/FAIL, `bucket = _by_cat.setdefault(
   cat or "?", [0,0]); bucket[1]+=1; if FAIL: bucket[0]+=1`. (Controls still excluded, matching `_asr`.)
   Unchanged: n/hits/defended/errors/skipped, `recent.appendleft`, the try/except + Live.update note.
3. **`live.py` — small render helpers** (all honor `self.unicode`; ascii-degrade every glyph/bar/box):
   - `_bar(frac, width, style)` → a colored `rich.text.Text` bar (`█/░` unicode, `#/-` ascii) — the one
     bar primitive reused by the headline, category rows, and footer (replaces the ad-hoc bars).
   - `_stats(self)` → a `Group`: big `ASR NN%` headline + headline bar; `fired n/total`; colored
     `✗ hits / ✓ defended / ⚠ errors`; a `Rule("by category")`; then the top ≤6 categories by scored
     count, each `name  <mini-bar>  NN%` (bar colored red-ish by ASR). Empty state: `(warming up…)`.
   - `_stream(self, rows)` → a `Group` of the newest `rows` verdict lines (existing glyph+id+category
     styling); the single most-recent FAIL is spotlighted (`⚡`/`*` prefix + `bold reverse red`).
   - `_footer(self)` → full-width progress `_bar` + `n/total` + `elapsed Xs · Y.Z/s · ETA …` when
     `_start` is set (rate = n/elapsed, eta = remaining/rate; guard div-by-zero → `—`), a spinner char
     keyed to `self.n` (`⠋⠙⠹…` unicode / `|/-\\` ascii).
4. **`live.py` — `_render` rebuild:** compute a two-column body with `Table.grid`:
   `cols = Table.grid(expand=True); cols.add_column(ratio=…); cols.add_column(ratio=…);
   cols.add_row(Panel(_stats, title="stats"), Panel(_stream(rows), title="attacks"))`. Assemble
   `Group(logo?, target line, cols, _footer)` inside the outer `Panel(box=ROUNDED/ASCII,
   border_style="cyan", title …)`. `rows = list(self.recent)[:self._visible]` (unchanged budget).
   `_layout` reused as-is (logo drop + `_visible`); stream height stays bounded.
5. **`__enter__`:** set `self._start = self._clock()`; everything else (Console(legacy_windows=False),
   Live) unchanged.
6. **Tests** (`test_live_dashboard.py`, extend — keep all existing green):
   - `on_attempt` populates `_by_cat` correctly (hits/scored per category; controls excluded).
   - `_render` (headless, unicode + ascii width=100) contains: the target, `ASR`, `n/total`, a category
     name with its ASR, a recent id, and the `attacks`/`stats` panel titles; ascii mode still leaks NO
     `█ ░ ✗ ✓ ⚠ · ─ │ ━ ⚡ ⠋` chars (broaden the existing forbidden set with the new glyphs).
   - momentum: inject a fake clock (`run._clock = lambda: T`, `run._start = T0`) → footer shows a
     non-`—` rate/ETA; without `_start` (headless default) footer shows `—` (no crash, deterministic).
   - latest-hit spotlight: after a FAIL then a PASS, only the FAIL row carries the spotlight marker.
   - existing counter/ASR/controls/total-guard/_layout/logo-drop tests unchanged.

**Checkpoint 1 (phase close):** full suite green + ruff clean; a manual render of both unicode and
ascii frames eyeballed; reviewer + tester STATUS: PASS; append `phase 24: DONE …` to PROGRESS.md.

---

## Plan review — addressed
- (1) HEIGHT BUDGET redesigned. Columns are NOT nested Panels (no double borders). `_layout` now returns
  `(show_logo, visible, cats, inner)`: `_CHROME2 = 4` (target line + footer + 2 outer borders);
  `available = height - logo_part - _CHROME2`; `visible = max(1, available)` (stream rows);
  `cats = min(6, max(0, available - 4))` (stats needs 4 header lines) so `4+cats ≤ available` and the
  grid row height = `max(4+cats, visible) = available` → whole panel = `logo_part + 4 + available =
  height`. Fits exactly; on a short terminal `cats` degrades to 0, then the logo drops. New short-height
  `_layout` unit test asserts `cats==0` + total ≤ height.
- (2) footer keeps the `{n}/{total} sent` wording (full-width, not split), so the existing
  `"1/3 sent"`/`"2/3 sent"` literal tests still pass; noted as intentionally preserved.
- (3) ascii forbidden-glyph test forbids the FULL spinner charset (all braille frames) + `⚡`, not one
  frame; ascii spinner uses `|/-\`.
- (4) inside `_stats`, "by category" is a dim `Text` header (not a full-width `Rule`) and category rows
  let rich auto-size to the column — `self._width` (panel-level) is used ONLY for the footer bar.
- (5) rate/ETA guard `elapsed <= 0 or n == 0` (covers the live first-repaint zero, not just headless
  `_start is None`) → `—`.
- (6) spotlight = the newest FAIL WITHIN the rendered rows (scan newest→oldest of the visible slice);
  none present → no marker, no crash; an all-PASS edge test covers it.
- (7) delete the superseded `_progress_row`; update the module docstring to the two-column design.
- (8) category bucket key = `attempt.category or "uncategorized"` (matches records.by_category).
- (9) top categories = `sorted(items, key=lambda kv: -kv[1][1])` — stable, insertion-order tie-break
  (deterministic); stated for the test.
- (10) keep the width=80 render test; footer `sent` is full-width so it can't wrap; mini-bars are short.

## Risks & mitigations
- **Layout overflow / scroll** → reuse `_layout` (drops logo on short/narrow, floors `visible`); the
  two columns share the same `_visible` stream budget; footer/stats are fixed small height. Eyeball a
  short-terminal render.
- **cp1254 crash/garbage** → one `_bar` primitive + `_GLYPH` ascii column + box.ASCII + ascii spinner;
  a broadened test asserts no fancy glyph leaks in ascii mode; `legacy_windows=False` kept.
- **Non-determinism from time** → clock injected; `_start=None` headless → `—`; no `time` call in
  `_render` except via `self._clock`/`self._start`. (Real CLI uses `time.monotonic`, fine outside a
  workflow.)
- **Perf (12 repaints/s)** → helpers build small Texts; logo can be cached (optional, from the review's
  F3 note) but not required. Category loop is ≤6 rows. No I/O in `_render`.
- **Divide-by-zero** (ASR, rate, ETA, category frac) → every ratio guards an empty denominator → `0`/`—`.
