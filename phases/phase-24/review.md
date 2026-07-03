# Phase 24 re-review (second pass) — verifying the two prior BLOCKING issues on current code

## 1. Overflow bug (long attack_id/category wrapping past terminal height) — VERIFIED FIXED

`src/grendel/live.py` no longer builds nested `Table.grid` rows for stats/category/footer. Every row
is a single `rich.text.Text(no_wrap=True, overflow=ov)`:
- `_line(ov)` helper (`live.py:121-124`) is the single-line-row primitive.
- `_stats` headline/`fired`/stat/category rows (`live.py:134,140,142,156`) all use `_line(ov)` or a
  plain `Text(..., no_wrap=True)`.
- `_stream` rows (`live.py:175`) are single `Text(no_wrap=True, overflow=ov)`.
- `_footer` (`live.py:192`) is a single `_line(ov)`.
- Only the outer two-column layout (`live.py:213-216`) is a `Table.grid`, with both columns declared
  `no_wrap=True, overflow=ov`.

Reproduced the height-fit property independently (not just by trusting the new test): rendered
`LiveAttackRun._render()` through a real `rich.console.Console(force_terminal=True, width=W,
legacy_windows=False)` at (80,24), (100,30), (66,10), (36,8), (60,20), (30,7), (120,40), both
`unicode=True/False`, filled past `_visible` capacity with a long id
(`tool-abuse/indirect-injection-tool-output-01-very-long-wrapper-xyz`) and long category
(`tool-abuse-verylongcategoryname-that-keeps-going`) — rendered line count was `<= height` in every
case, 0 overflows. `test_long_ids_never_overflow_terminal_height`
(`tests/test_live_dashboard.py:143-167`) covers the same matrix as a permanent regression test.
**Confirmed fixed.**

## 2. ASCII ellipsis leak (`overflow="ellipsis"` inserting U+2026 in `unicode=False` mode) — VERIFIED FIXED

Every `ov` computation in the file is `"ellipsis" if u/self.unicode else "crop"` (`live.py:131, 168,
189, 206`), i.e. ascii mode always uses `overflow="crop"`, which has no marker character — so rich
never emits U+2026 when `unicode=False`. Verified independently: same 7-size x 2-mode sweep as above,
asserted `"…" not in out` for every ascii-mode render (0 leaks), and additionally asserted the ascii
output is fully encodable under `cp437`, `cp850`, and `cp1254` (the exact codepages the prior review
flagged as unable to encode U+2026) — 0 `UnicodeEncodeError`s across all cases.
`test_long_ids_never_overflow_terminal_height` also asserts `"…" not in out` in ascii mode
(`tests/test_live_dashboard.py:166-167`), and `test_ascii_degrade_uses_no_fancy_glyphs_or_box`
(`tests/test_live_dashboard.py:96-112`) forbids the full glyph/box/spinner/ellipsis set including
`"…"` and all of `_SPIN_U`. **Confirmed fixed.**

## Test suite / lint

- `python -m pytest -q` → **609 passed, 1 skipped** (matches expected count).
- `python -m ruff check src tests` → **All checks passed.**

## Non-regression spot checks (phase-24 spec properties)

- Controls excluded from counters/ASR: `on_attempt` only increments `hits`/`defended`/`_by_cat` when
  `not control` (`live.py:72-84`); `test_by_category_tracks_hits_and_scored`
  (`tests/test_live_dashboard.py:115-122`) explicitly asserts a control PASS is not counted. Confirmed
  by re-running that test plus the ASR-related tests directly.
- `_momentum` guards: `if self._start is None or self._clock is None: return "—"/"-"` and
  `if elapsed <= 0 or self.n == 0: return self._fmt_time(elapsed)` (`live.py:111-119`) — both
  div-by-zero paths guarded; `test_momentum_deterministic_with_injected_clock`
  (`tests/test_live_dashboard.py:125-132`) passes.
- Off-TTY / no-rich fallback: `make_live_run` (`live.py:265-277`) still returns `None` when
  `not sys.stdout.isatty()` or `import rich` fails — unchanged from prior phases.
- `on_attempt` can't crash a run: the whole body is wrapped in `try/except Exception: pass`
  (`live.py:67-93`), comment explains why `_render()` must stay on the caller's thread.
- No dead code: `_progress_row` no longer exists anywhere in `src`/`tests` (grep confirms zero
  matches); the `from rich.table import Table` import inside `_render` (`live.py:200`) is used for the
  still-legitimate outer `Table.grid` two-column layout — not unused.

## Conclusion

Both prior BLOCKING findings are fixed on the current tree, independently reproduced, and covered by
permanent regression tests. Full suite green, ruff clean, no regressions found in the surrounding
non-blocking properties (control-exclusion, momentum guards, off-TTY fallback, dead code).

STATUS: PASS
