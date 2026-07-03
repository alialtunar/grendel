# Post-phase-24 review — catalog-load message/cache + polished report card

Scope: two user-feedback fixes on top of the completed phase-24 tree (no formal phase plan; all
phases are marked DONE). (A) `src/grendel/cli.py` `_menu_load_attacks`/`_catalog_sig`/
`_MENU_ATTACK_CACHE` — a loading message + session cache around the menu catalog load. (B) new
`src/grendel/report_card.py` + `_print_report_card` wiring in `cli.py` — a polished rich report
card after a menu run and in the reports viewer.

## Findings

1. **cp1254 / ascii safety — verified independently.** Rendered `render_card(record, path,
   unicode=False)` through a real `rich.console.Console` for both a populated record and an
   *empty* record (`attempts=[]`) and a record with a 200-char target name / 300-char path at
   width=40. In every case the output `.encode("cp1254")` succeeded with no `UnicodeEncodeError`,
   and none of `█ ░ ✗ ✓ ⚠ → … 🐺` leaked. The "→"/"·" degrade correctly (`"->"`, plain `"-"`
   separator in the title). `overflow=` is `"ellipsis"` only when `unicode=True`, `"crop"` in
   ascii mode (`report_card.py:48`), matching the pattern already proven safe in `live.py`. No
   crash on long ids/paths (single-line `Text(no_wrap=True, overflow=ov)` rows throughout,
   `report_card.py:53-54`). Confirmed by `tests/test_report_card.py::test_card_ascii_is_cp1254_safe`
   plus my own ad-hoc renders — matches.

2. **Cache correctness / no staleness / no cross-test leak.** `_catalog_sig` (`cli.py:177-186`)
   covers `pack_dirs`, `feed_cache_dir`, `staged_dir`, `allow_override`, `allow_unlisted_licenses`
   — the full set of inputs `load_catalog` depends on, so a pack-dir edit or import correctly
   invalidates the cache (new sig → miss → reload). `_menu_load_attacks` (`cli.py:189-202`) checks
   `cached is not None` (not truthiness), so an empty attack list is still cached correctly rather
   than being treated as a miss on every call. It still calls the module-level `_load_attacks`
   (`cli.py:200`), so existing `monkeypatch.setattr(cli, "_load_attacks", ...)` tests are
   unaffected. `tests/conftest.py` adds an autouse fixture clearing `cli._MENU_ATTACK_CACHE`
   before+after every test — confirmed this prevents inter-test leakage since the cache is a
   plain module-global dict with no other invalidation.

3. **Off-TTY byte-identical.** `_print_report_card` (`cli.py:2164-2180`) returns `False`
   immediately when `not sys.stdout.isatty()`, before importing rich/report_card — so under
   `CliRunner` (non-TTY) both `_menu_run` (`cli.py:2305-2307`) and `_menu_reports`
   (`cli.py:2388-2390`) fall through to the unchanged plain-text branches (`_summary`+`"next:
   grendel report"`, `reportsmod.render_text`+`"full:"`). This is exercised by the pre-existing
   `test_home_menu_run_full_writes_record`, `test_home_menu_run_picks_configured_target`,
   `test_home_menu_adhoc_run_does_not_leak_cli_target`, `test_home_menu_reports_lists_and_renders`
   in `tests/test_cli_home.py`, all of which pass unchanged.

4. **Empty/degenerate record.** `RunRecord.metrics_summary()` (`records.py:212-252`) always
   returns the full key set (`overall_asr`, `by_category={}`, `by_owasp={}`, etc.) even for
   `attempts=[]`, so `render_card` never hits a `KeyError`; `_duration_s` returns `None` when there
   are no timestamps and the duration line is simply omitted (`report_card.py:27-32,75-78`); empty
   `by_cat`/`owasp`/`hits` lists just skip their sections (`report_card.py:80-111`). Verified by
   rendering a zero-attempt record directly (no crash, cp1254-encodable) in addition to the
   existing `test_card_no_hits_omits_top_hits_section`.

5. **No dead code.** `_summary` and `reports.render_text` remain live (off-TTY fallback paths in
   `_menu_run`/`_menu_reports`), `_load_attacks` remains the single load point used by both `run`
   subcommand paths and (indirectly) by `_menu_load_attacks`. `pytest -q` → 613 passed, 1 skipped
   (matches the stated expectation); `ruff check src tests` → all checks passed.

6. **Minor, non-blocking gap.** There is no dedicated unit test that pins the cache's *external*
   behavior directly (e.g., asserting the "loading attack catalog…" message prints on a cold call
   and is absent on a warm one for the same signature, or that changing `pack_dirs` between two
   calls forces a reload). Current coverage is indirect: the two-ad-hoc-run test
   (`test_home_menu_adhoc_run_does_not_leak_cli_target`) exercises two `_menu_load_attacks` calls
   with the same signature but relies on a monkeypatched `_load_attacks`, so it can't distinguish
   a cache hit from a cache miss. Correctness was verified by code reading + the sig/`is not None`
   checks above, not by a targeted test. Suggest (non-blocking) adding a small unit test asserting
   the loading message prints once and is suppressed on the second call for the same `cfg`.

7. **Minor, non-blocking robustness note.** `_print_report_card` only catches `ImportError`
   around the rich/report_card import (`cli.py:2171-2177`); if `render_card` itself ever raised
   (e.g. a future regression producing a malformed `metrics_summary`), the menu run would crash
   instead of degrading to the plain-text fallback. Today this can't happen — `metrics_summary`'s
   keys are unconditionally populated — so this is a latent risk, not a current bug.

## Conclusion

Both changes match their described behavior, are cp1254-safe (independently verified beyond the
existing test), preserve off-TTY output byte-for-byte, don't introduce staleness or cross-test
cache leakage, and handle empty/degenerate records without crashing. Full suite green (613 passed,
1 skipped), ruff clean. Items 6-7 are suggestions, not blockers.

STATUS: PASS
