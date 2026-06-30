# Phase 10 Test Report

Date: 2026-06-30

## Test Suite Results

### Full Suite (run twice for flakiness)

Both runs: **419 passed, 1 skipped** in ~8.85s — no flakiness observed.

The 1 skip is the MCP-absent guard (expected).

### Import and Dependency Checks

- `python -c "import gauntlet; print('ok')"` → `ok`
- `jinja2` in `sys.modules` after importing gauntlet → `False`
- `pyproject.toml` dependencies list: no jinja2 present

### Lint / Format

- `ruff check .` → All checks passed
- `ruff format --check .` → 87 files already formatted (clean)

## Specific Feature Verification

### CI Gate Tests (tests/test_cli_run.py — 11 tests, all pass)

- `test_fail_under_trips_exit_3` — PASS: `--fail-under` exits 3 when ASR > threshold; record artifact still written
- `test_fail_under_pass_when_asr_at_or_below` — PASS: exits 0 when ASR ≤ threshold
- `test_fail_under_out_of_range_exits_2` — PASS: exits 2 for out-of-range threshold
- `test_dry_run_fail_under_is_noop` — PASS: dry-run ignores fail-under

### HTML Report Tests (tests/test_reports.py)

- `test_html_escapes_adversarial_payload` — PASS: `<script>` payload is HTML-escaped to `&lt;script&gt;`
- `test_html_self_contained` — PASS: output is self-contained, no CDN/external URLs

### Markdown Report Tests (tests/test_reports.py)

- `test_markdown_backtick_safe_fence` — PASS: triple-backtick payloads don't break fences

### Diff Tests (tests/test_diff.py + tests/test_cli_diff.py — 11 tests, all pass)

- `test_self_diff_is_zero` — PASS: self-diff produces zero delta
- attack_id=None exclusion covered in diff axis union tests — PASS

### README Tests (tests/test_docs_readme.py — 3 tests, all pass)

- `test_readme_exists_with_authorized_use_framing` — PASS: authorized-use/defensive-only wording present
- `test_demo_tape_exists_with_commands_and_output` — PASS: demo/gauntlet.tape exists

## Summary

All 419 tests pass across two consecutive runs with no flakiness. Ruff lint and format checks are clean. No new third-party dependencies (no jinja2). All Phase 10 feature areas verified: CI gate exit codes, HTML XSS escaping, Markdown fence safety, self-diff zero delta, and README authorized-use framing.

STATUS: PASS
