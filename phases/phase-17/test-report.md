# Phase 17 Test Report — Output-boundary Unicode fix

Date: 2026-07-02
Scope: full repo test gate after codec-fallback / stdout-stderr reconfigure fix
and new `tests/test_cli_encoding.py` subprocess regression test.

## Commands run

1. `python -m ruff check src tests` → **All checks passed!**
2. `python -m ruff format --check src tests` → **100 files already formatted**
3. `python -m pytest -q` → **524 passed, 1 skipped in 22.49s**

## Targeted verification

`python -m pytest -q tests/test_cli_encoding.py tests/test_banner.py tests/test_cli_doctor.py -v`
→ **24 passed in 10.54s**

Confirmed individual tests present and green:
- `tests/test_cli_encoding.py::test_console_fallback_downgrades_glyphs_instead_of_raising`
- `tests/test_cli_encoding.py::test_commands_never_crash_on_legacy_console` (parametrized,
  8 cases: bare `grendel` / `doctor` / `list` / `config` × `iso-8859-5` / `iso-8859-9`,
  subprocess-based)
- `tests/test_banner.py` — 10 prior ASCII-fallback tests, all pass
- `tests/test_cli_doctor.py` — 5 prior ASCII-fallback tests, all pass

## Notes

- 1 skip in full suite is the known/expected mcp test skip (pre-existing, not related to this fix).
- Full suite ran fully offline; garak auto-import bounded via `--limit` as expected, no network calls observed.
- No failures, no flakes across two full runs of the encoding/fallback subset.

## Result

- ruff check: PASS
- ruff format --check: PASS
- pytest full suite: 524 passed, 1 skipped (expected)
- New encoding regression tests: all 9 green
- Prior ASCII-fallback tests (banner, doctor): all 15 green

STATUS: PASS
