# Phase 10 -- Polish & ship: Review

Reviewed: `git diff HEAD~1 HEAD` (commit `f09b54a`), all touched files, full test suite run.

---

## 1. CI exit-code contract (--fail-under / _apply_gate)

PASS. `_apply_gate(record, fail_under)` is a thin helper that raises `typer.Exit(code=3)` only when `overall_asr > fail_under` (strictly greater, per spec sec 4). It is called at the END of both the plain path (line 317 in cli.py) and the TUI path (line 294), after the record is persisted and `_summary` is printed. The gate is never reached on `--dry-run` because that path returns at line 242 before any record is created. Out-of-range validation runs before any adapter is built (lines 201-203), giving exit 2. Tests cover all five required cases: exit 3 tripped, exit 0 at boundary (ASR == threshold), exit 2 out-of-range, dry-run noop, zero-scored exit 0.

Record persistence and summary print happen before the gate on both paths -- CI still gets the artifact on a gate trip. Confirmed by `test_fail_under_trips_exit_3` which asserts `out.exists()` and `"asr=" in result.output` alongside `exit_code == 3`.

## 2. Score-diff determinism and correctness (diff.py)

PASS. `diff_runs` is pure and deterministic:
- `_axis_deltas` uses `sorted(set(a) | set(b))` -- union of codes, sorted, missing side 0.0.
- `newly_failing`/`newly_fixed` are computed from `sorted(...)` comprehensions over the intersection of `_scored_verdicts` maps.
- Fix #2 (attack_id=None exclusion): `_scored_verdicts` skips attempts where `a.attack_id is None`, preventing two None-id attempts from different runs colliding in the join. Test record includes a None-id attempt to exercise this.
- Fix #6 (self-diff): `diff_runs(a, a)` yields `overall_asr_delta == 0.0`, empty `newly_failing`, empty `newly_fixed` -- confirmed by `test_self_diff_is_zero`.
- Fix #8 (div-by-zero): per-axis ASRs are read from `metrics_summary()["by_*"][code]["asr"]`, which delegates to the existing `_asr` helper (already div-by-zero-safe). No re-implementation.
- Fix #9 (latency None): `_mean_latency` returns None when no attempts have measured latency; `latency_delta_ms` is None when either side is None; both `render_text` and `render_markdown` render `"latency: n/a"` -- asserted in `test_latency_none_when_a_side_lacks_latency`.
- Fix #3-text (Windows console): `_sign` uses ASCII +/-/=, no unicode.

## 3. HTML report -- security (escaping, self-containment)

PASS. Every record-derived string in `render_html` is passed through `_e()` which calls `html.escape(str(value))`. Covered values: run_id, target_name, provider, model, status.value, created_at.isoformat(), joined pack_ids, axis code values, failure attack_id, category, owasp, atlas, score_detail.reason, prompt, response_text, and tool-call repr() output. Numeric fields (total_cost_usd, total_tokens, overall_asr, scored/succeeded counts) are format-string floats/ints and cannot carry injection payloads.

The _STYLE CSS constant and style tag are hardcoded; there is no script tag in the template, no CDN or external URL (confirmed: "http://" and "https://" absent). Manual verification with a `<script>alert(1)</script>` payload confirms `&lt;script&gt;` appears in output and the raw tag does not. Tests `test_html_self_contained` and `test_html_escapes_adversarial_payload` cover both properties.

## 4. Markdown backtick safety (Fix #3)

PASS. `_fence(content)` computes `max(3, longest_backtick_run + 1)` where the longest run is found via `re.compile(r"`+").finditer`. A payload with triple-backticks gets a 4-backtick fence; an empty payload gets a 3-backtick fence. Verified with direct calls in review. Test `test_markdown_backtick_safe_fence` uses a NASTY payload containing triple-backticks and asserts "````" in md and the raw NASTY payload verbatim inside the longer fence.

## 5. Null guards (Fix #1)

PASS. Both `render_markdown` and `render_html`:
- Render `score_detail.reason` only inside `if f.score_detail is not None:` -- a succeeded attempt with score_detail=None does not crash.
- Render `f.response_text or "(no response)"` -- a None response renders the sentinel.

Test record in test_reports.py includes an AttemptRecord with response_text=None, verdict=Verdict.FAIL, score_detail=None to exercise both branches. Tests `test_markdown_null_guards` and `test_html_null_guards` assert "(no response)" in output.

## 6. Unknown --format => exit 2

PASS. `report` command restructured from silent fall-through to explicit if/elif/return chain; the final `if format != "text"` branch emits an error and raises `typer.Exit(code=2)`. Same for the `diff` command with an explicit else branch. Tests `test_report_bad_format_exit_2` and `test_diff_bad_format_exit_2` confirm exit 2 on format "xml".

## 7. No new dependencies

PASS. `diff.py` imports only pydantic (already a project dependency) and `.records`. `reports.py` imports only stdlib `html` and `re`. No Jinja2 or any other new library. `pyproject.toml` diff shows only the readme field change.

## 8. pyproject.toml readme repoint

PASS. `readme = "README.md"` (was PROGRESS.md). `pip install -e .` succeeds without errors -- verified during review. The plan required explicit verification; no revert was needed.

## 9. README authorized-use framing (ROADMAP sec 7 hard requirement)

PASS. Section "Authorized use only -- defensive security, not an offensive tool" appears prominently near the top of README.md (line 16), before the install or quickstart sections. The block contains all four strings the test asserts: "authorized", "defensive", "not an offensive tool", "not a general llm benchmark" (case-insensitive). Test `test_readme_exists_with_authorized_use_framing` in tests/test_docs_readme.py asserts all four. The quickstart section documents --fail-under and "exit code" -- also asserted by test.

## 10. VHS tape committed, not run in tests

PASS. demo/gauntlet.tape is committed as a text file. It contains Output, "gauntlet list --packs", "gauntlet run", and "--tui" -- all required markers. No test invokes VHS; `test_demo_tape_exists_with_commands_and_output` only reads and asserts string contents. The .gif is explicitly out-of-band (demo/README.md documents how to generate it).

## 11. Test count / regression

PASS. Full suite: 419 passed, 1 skipped (matching the plan target). `ruff check .` zero findings. `ruff format --check .` 87 files clean. Prior 385 tests remain green; Phase 10 adds 34 new tests across test_diff.py, test_cli_diff.py, test_reports.py (new), test_cli_report.py (extended), test_cli_run.py (extended), test_docs_readme.py (new), and test_integration.py (extended).

## 12. Minor observations (non-blocking)

- The `report --format text` path does not route through `_emit`, so `--out PATH` is silently ignored when using the text format. This is consistent with the plan ("Keep text/json unchanged" for Milestone 3); JSON does gain --out support via _emit. No test exercises `--format text --out FILE`, so no test failure. The asymmetry is cosmetically odd but explicitly allowed by the plan.
- `_record` in test_diff.py uses `datetime.now(UTC)` (non-fixed timestamp). This does not affect determinism since created_at is not part of RunDiff.
- The `render_markdown` diff renderer wraps `_latency_text(d)` in bold markers (`**latency: n/a**`), correctly producing the asserted substring "latency: n/a" inside the bold wrapper. Both assertions pass.

---

STATUS: PASS
