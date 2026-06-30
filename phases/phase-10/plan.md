# Phase 10 — Polish & ship (CI/headless mode · score-diff · HTML+Markdown reports · README · VHS tape): implementation plan

> Dependency-ordered and **engine-untouched**, so the prior **385** tests (1 skipped) stay green at
> every checkpoint. Phase 10 adds only **read-side** projections + CLI surface + written
> deliverables — no scoring/runner/metrics behaviour changes. Order: (1) the **CI/headless gate**
> (`run --fail-under`, the smallest self-contained change, exit-code contract); (2) the **score-diff**
> model + `gauntlet diff` (pure functions over two records); (3) the **Markdown** report renderer +
> `report --format md`; (4) the **HTML** report renderer + `report --format html` (reuses M3's
> `_failures`/latency helpers); (5) the **README** + **VHS tape** + docs + final end-to-end
> integration. Every milestone ends in a **Checkpoint** with exact commands. Quality gate:
> `ruff check .` (zero findings), `ruff format --check .` (clean), `pytest` (green, **offline — no
> API keys, network, browser, or VHS**). New code reuses existing patterns: `metrics_summary()` as
> the single metrics source; the `RunRecord.from_json` durable format; the `CliRunner` + fake-adapter
> / `cli._load_attacks` monkeypatch pattern from `test_cli_run.py`; the `report` command's
> load-or-exit-2 convention; Pydantic v2 `ConfigDict(extra="forbid")`. **No new dependency**
> (stdlib f-string templating + `html.escape`, justified in spec §5.1). The only contract updates are
> the enumerated additive ones (spec §9), noted per milestone.

---

## Milestone 1 — CI/headless mode: `gauntlet run --fail-under` (the ASR regression gate + exit-code contract)

**Build**
- `src/gauntlet/cli.py` (EXTEND, `run`): add
  `fail_under: Annotated[float | None, typer.Option("--fail-under", help="Fail (exit 3) if overall
  ASR exceeds this threshold [0.0-1.0]; CI regression gate.")] = None`.
  - **Validate early:** if `fail_under is not None and not (0.0 <= fail_under <= 1.0)` → `typer.echo`
    a clear message + `raise typer.Exit(code=2)` **before** building the target/running (a usage error).
  - **Gate last (spec §4):** in BOTH the plain path and the TUI path, *after* the record is persisted
    and `typer.echo(_summary(...))` has printed, if `fail_under is not None` and
    `record.metrics_summary()["overall_asr"] > fail_under` → `raise typer.Exit(code=3)`. The record +
    summary are produced regardless (CI still gets the artifact). **[Single gate helper]** add a thin
    module-level `_apply_gate(record, fail_under)` that raises `typer.Exit(code=3)` when tripped, and
    call it at the end of both paths to avoid duplicating the comparison.
  - **`--dry-run`** returns before the run (no record) → the gate is never reached (a no-op for
    dry-run, per spec §4); no special-casing needed since dry-run `return`s above the gate.
- Tests: `tests/test_cli_run.py` (EXTEND) — using the existing fake-adapter + `cli._load_attacks`
  monkeypatch pattern, build a run whose attempts yield a known overall ASR and assert:
  - **[Fix #4/#14 — produce a FAIL]** the default `FakeAdapter` text `"ok"` scores `PASS`
    (defended → ASR 0). To get ASR > 0, set the FakeAdapter text to MATCH the attack's
    `success_when.contains` (the default `make_attack` uses `contains:["x"]`, so text `"x"` →
    `Verdict.FAIL`). Then `--fail-under 0.0` → `exit_code == 3`.
  - **[Fix #5]** that exit-3 test passes `--out tmp_path/rec.json` for a stable path, and asserts
    BOTH the summary substring in output AND that `rec.json` exists on disk (record produced
    despite the gate trip).
  - ASR ≤ threshold (e.g. `--fail-under 1.0`, or a clean PASS run) → `exit_code == 0`.
  - `--fail-under 1.5` (out of range) → `exit_code == 2` before any run.
  - `--dry-run --fail-under 0.0` → `exit_code == 0` (gate is a no-op).
  - **[Fix #7]** a run with only ERROR/SKIPPED attempts (0 scored → `overall_asr == 0.0`) +
    `--fail-under 0.0` → `0.0 > 0.0` is False → `exit_code == 0` (boundary).
- **[Enumerated contract update — additive]:** `run` gains `--fail-under`; existing `run` tests pass
  no such flag and are unchanged (default `None` = no gate, exit 0 on success as before).

**Files**: `cli.py`, `tests/test_cli_run.py` (extend).

**Checkpoint**
```
ruff check .
ruff format --check .
pytest tests/test_cli_run.py -q
```
Then full suite:
```
pytest -q
```
Passing: `run --fail-under` implements the §4 exit-code contract (0 pass / 3 gate-tripped /
2 out-of-range), gate evaluated after the record+summary are produced; default-unset `run` is
byte-identical to before. Prior 385 tests (1 skipped) green (only the additive flag added).

---

## Milestone 2 — Score-diff: `RunDiff` model + `diff_runs()` + `gauntlet diff` command

**Build**
- `src/gauntlet/diff.py` (NEW, spec §6):
  - `AsrDelta(BaseModel, extra="forbid")`: `code`, `asr_a`, `asr_b`, `delta` (`asr_b - asr_a`).
  - `RunDiff(BaseModel, extra="forbid")`: `run_a`, `run_b`, `overall_asr_a/b/delta`,
    `by_category`/`by_owasp`/`by_atlas: list[AsrDelta]`, `newly_failing`/`newly_fixed: list[str]`,
    `cost_delta_usd: float`, `latency_delta_ms: float | None`.
  - `diff_runs(a: RunRecord, b: RunRecord) -> RunDiff`: compute overall + per-axis deltas from each
    record's `metrics_summary()` (reuse the existing ASR machinery; **union** of codes per axis,
    a code absent on one side → ASR `0.0` that side), `AsrDelta` lists **sorted by code**.
    newly-failing/fixed by joining attempts on `attack_id` over ids scored (PASS/FAIL, non-control)
    in **both** runs: `defended(A)&succeeded(B)` → `newly_failing`; `succeeded(A)&defended(B)` →
    `newly_fixed`; both **sorted**; one-sided/ERROR/SKIPPED ids excluded.
    **[Fix #2 — `attack_id=None`]** attempts with `attack_id is None` are EXCLUDED from the join
    (else two `None`-id attempts from different runs would collide as "the same attack"); treat
    them like one-sided/ERROR. The `test_diff.py` records include a `None`-id attempt to cover it.
    **[Fix #8]** per-axis ASRs are read from each record's `metrics_summary()[axis][code]["asr"]`
    (already div-by-zero-guarded by `_asr` → 0.0) — do NOT re-implement the ASR computation.
    `cost_delta_usd` from `total_cost_usd`; `latency_delta_ms` = mean(non-None `latency_ms`, B) −
    mean(…, A), **`None`** if either side has no measured latency. **[Helper]** a small
    `_mean_latency(record) -> float | None`.
  - `render_text(d: RunDiff) -> str` (human summary: overall delta with an **ASCII** sign per
    **[Fix #3-text/Windows]** `+`/`-`/`=` — NOT unicode ▲/▼ which raise UnicodeEncodeError on
    cp1252 Windows consoles — per-axis deltas, the newly-failing/newly-fixed id lists, cost/latency
    deltas) and `render_markdown(d) -> str` (tables + lists, for a PR/CI comment). JSON rendering is
    `d.model_dump()` (no separate fn). **[Fix #9]** when `latency_delta_ms is None` both renderers
    print a defined sentinel `latency: n/a` (asserted exactly in tests). Pure f-strings,
    deterministic (sorted), no clock/network.
- `src/gauntlet/cli.py` (EXTEND): new `diff` command —
  `gauntlet diff RUN_A RUN_B [--format text|json|md] [--out PATH]`. `RUN_A`/`RUN_B` are positional
  `Path` args; load each via `RunRecord.from_json`, reusing `report`'s **not-found / parse-error →
  exit 2** convention. `text` (default) → `render_text`; `json` → `json.dumps(d.model_dump())`;
  `md` → `render_markdown`; unknown `--format` → exit 2. `--out PATH` → write the rendered string
  (utf-8) + echo `wrote diff -> PATH`; else print to stdout. Exit 0 regardless of delta sign (diff
  reports, doesn't gate).
- Tests:
  - `tests/test_diff.py` (NEW): two hand-built `RunRecord`s sharing `attack_id`s with changed
    verdicts → assert `overall_asr_delta`, the per-axis `AsrDelta` lists (union, missing side 0.0),
    the exact `newly_failing`/`newly_fixed` sets (transitions only; ERROR/SKIPPED/one-sided/`None`-id
    excluded), `cost_delta_usd`, `latency_delta_ms` (and `None`→`n/a` when a side lacks latencies),
    and that text/json/md renderings contain the expected markers + are deterministic.
    **[Fix #6]** a diff of a record against ITSELF → `overall_asr_delta == 0.0`, empty
    `newly_failing`, empty `newly_fixed` (simplest determinism/sign-error check).
  - `tests/test_cli_diff.py` (NEW): write two records to tmp files → `diff A B --format text|json|md`
    → exit 0 + expected output; `--out` writes the file; a missing record path → exit 2; bad
    `--format` → exit 2.

**Files**: `diff.py` (new), `cli.py` (extend), `tests/test_diff.py` (new), `tests/test_cli_diff.py`
(new).

**Checkpoint**
```
ruff check .
ruff format --check .
pytest tests/test_diff.py tests/test_cli_diff.py -q
```
Then full suite:
```
pytest -q
```
Passing: `gauntlet diff` produces a deterministic `RunDiff` (overall + per-axis ASR deltas,
newly-failing/fixed attack ids, cost/latency deltas) rendered text/json/md; missing record → exit 2.
Prior 385 tests green (purely additive new command + modules).

---

## Milestone 3 — Markdown report renderer + `report --format md`

**Build**
- `src/gauntlet/reports.py` (NEW, spec §5):
  - `_failures(record) -> list[AttemptRecord]`: the succeeded (`verdict == Verdict.FAIL`),
    non-control attempts, sorted by `(attack_id or "", attempt_id)` (stable, deterministic).
  - `_latency_summary(record) -> tuple[float | None, float | None]` (mean, median over non-`None`
    `attempt.latency_ms`; `(None, None)` when none) — shared with M4's HTML.
  - `render_markdown(record: RunRecord) -> str`: a GFM document from `record.metrics_summary()` +
    record fields — header (run id, `provider/model`, status, `record.created_at`, pack ids), a
    headline-metrics table (overall ASR, scored/succeeded/defended/errored/skipped/total), the
    utility/controls block **only when `controls.total > 0`**, cost (`total_cost_usd`,
    `total_usage.total_tokens`) + latency, the three breakdown tables (`by_category`/`by_owasp`/
    `by_atlas`, rows **sorted by code**: `code | ASR | succeeded/scored`), and the failure list (a
    `###` per `_failures()` entry with id/category/OWASP/ATLAS + payload (`prompt`) and what the
    target did (`response_text`, observed `tool_calls`) + `score_detail.reason`, payload/response in
    fenced code blocks). Pure f-strings; deterministic ordering. Returns `str`.
    **[Fix #1 — null guards]** `response_text` is `str | None` and `score_detail` is
    `ScoreDetail | None`; render `score_detail.reason` ONLY when `score_detail is not None`, and
    render `response_text or "(no response)"`. The test record includes a succeeded attempt with
    `score_detail=None` and `response_text=None` to cover the branch.
    **[Fix #3 — backtick-safe fences]** payloads/responses are adversarial and may contain ```` ``` ````;
    a 3-backtick fence would close early. Compute the fence as a run of backticks ONE LONGER than the
    longest backtick run in the content (min 3) — or use indented code blocks. The test record
    includes a payload containing ```` ``` ````.
- `src/gauntlet/cli.py` (EXTEND, `report`): accept `--format md` → `reports.render_markdown(record)`;
  add `--out PATH` (write the rendered string utf-8 + echo `wrote md report -> PATH`; else stdout).
  Keep `text`/`json` unchanged. **[Fix #10]** the existing code SILENTLY falls through to text on an
  unknown format — restructure to explicit `if/elif` per format with a final `else: echo error +
  raise typer.Exit(2)` listing the valid values (`text|json|md|html`). This is a controlled
  behavioural fix (no existing bad-format test, so nothing breaks); add a bad-`--format` → exit 2 test.
- Tests: `tests/test_reports.py` (NEW, markdown half): a synthetic `RunRecord` (mixed
  FAIL/PASS/ERROR/SKIPPED, controls, OWASP/ATLAS codes, tool-calls) → assert the overall-ASR string,
  the breakdown rows, the controls/utility block present-with-controls (and a no-controls variant
  omits it), cost/latency, and the failure list (each succeeded id + payload + response); assert two
  calls return identical strings (determinism). `tests/test_cli_report.py` (EXTEND): `report
  --format md` prints the rendered markdown; **[Fix #13]** `--out FILE` writes it and the test reads
  the file back (utf-8) and asserts its content equals the stdout-rendered string; bad `--format` →
  exit 2.
- **[Enumerated contract update — additive]:** `report --format` now accepts `md`; `--out` added.
  Existing text/json assertions unchanged.

**Files**: `reports.py` (new), `cli.py` (extend), `tests/test_reports.py` (new),
`tests/test_cli_report.py` (extend).

**Checkpoint**
```
ruff check .
ruff format --check .
pytest tests/test_reports.py tests/test_cli_report.py -q
```
Then full suite:
```
pytest -q
```
Passing: `report --format md` renders `metrics_summary` (all blocks + failure list) to deterministic
Markdown, written to `--out` or stdout. Prior 385 tests green (additive `--format md` + `--out`).

---

## Milestone 4 — HTML report renderer + `report --format html` (self-contained, escaped)

**Build**
- `src/gauntlet/reports.py` (EXTEND): `render_html(record: RunRecord) -> str` — a single
  self-contained `<!DOCTYPE html>` document reusing `_failures()` / `_latency_summary()` from M3:
  `<head>` with an **inline `<style>`** (compact theme, red/green pass/fail accents echoing the TUI),
  `<body>` with header, the metrics summary, three `<table>` breakdowns (rows sorted by code), and a
  `<section>` per failure (payload/response in `<pre>`). **No `<script>`, no external `<link>`/CDN,
  no remote images.** Every record-derived string is wrapped in **`html.escape`** (payloads are
  adversarial). **[Fix #1]** same null-guards as MD: `score_detail.reason` only when
  `score_detail is not None`; `response_text or "(no response)"`. (HTML needs no backtick handling —
  `<pre>` + `html.escape` is already safe.) Deterministic. Returns `str`.
- `src/gauntlet/cli.py` (EXTEND, `report`): accept `--format html` → `reports.render_html(record)`
  (reusing the M3 `--out`/stdout plumbing).
- Tests: `tests/test_reports.py` (EXTEND, html half): on a record whose payload contains
  `<script>`/`&`/`"`, assert the HTML is **self-contained** (`<!DOCTYPE html>`, an inline `<style>`,
  **no** `http://`/`https://` asset URL, **no** `<script>` from our template) and the payload is
  **escaped** (`&lt;script&gt;`, no raw `<script>` from the payload); assert the headline ASR, the
  breakdown tables, the controls/utility block conditionality, and the failure list render; assert
  determinism (two calls identical). `tests/test_cli_report.py` (EXTEND): `report --format html`
  prints/`--out`-writes the document. **No browser.**

**Files**: `reports.py` (extend), `cli.py` (extend), `tests/test_reports.py` (extend),
`tests/test_cli_report.py` (extend).

**Checkpoint**
```
ruff check .
ruff format --check .
pytest tests/test_reports.py tests/test_cli_report.py -q
```
Then full suite:
```
pytest -q
```
Passing: `report --format html` renders a self-contained, HTML-escaped, deterministic document
(no CDN/JS/external assets), asserted as a string with no browser. Prior 385 tests green.

---

## Milestone 5 — README + VHS demo tape + docs + final end-to-end integration

**Build**
- `README.md` (NEW, repo root — spec §7 deliverable): the strong README — title + pitch; a
  **PROMINENT authorized-use / defensive-only callout near the top** (ROADMAP §7: authorized testing
  of your own agents only, not an offensive tool, no evasion-for-malice, not a general LLM benchmark);
  what it does (agent-not-model, outcome judging, TUI scoreboard, attacks-as-data); install
  (3.11+, `pip install -e .`, `[mcp]`/`[dev]` extras, provider key in `.env`, Ollama); quickstart
  (`list --packs`, `run --target … [--tui]`, `report --format html|md`, `diff RUN_A RUN_B`, `update`)
  **including the CI usage of `run --fail-under` + the §4 exit-code contract**; the attack-pack data
  model (link `docs/authoring-packs.md`); scoring tiers (T1–T4, ASR/utility/cost/latency); agent
  mode; reports & regression tracking (+ the demo gif link); license (Apache-2.0).
- `demo/gauntlet.tape` (NEW — spec §8): a VHS script (terminal size/theme, `Type` a session —
  `gauntlet list --packs`, `gauntlet run --target … --tui` showing the scoreboard, `gauntlet report
  --run … --format md`, `gauntlet diff …` — with `Sleep`s and an `Output demo/gauntlet.gif`
  directive), using a demo-safe (Ollama/fake) target so no paid key is needed; committed as text.
- `demo/README.md` (NEW — spec §8): how to install VHS, run `vhs demo/gauntlet.tape` to render the
  gif, the demo-target prerequisites, and that **the `.gif` is out-of-band / not committed**.
- Optional one-liner (spec §9.5): repoint `pyproject.toml` `readme = "README.md"` (currently
  `PROGRESS.md`). **[Fix #12]** if done, VERIFY concretely with `python -m pip install -e . ` (the
  editable re-install must still succeed) — do NOT just assume; if the build complains, revert the
  repoint. Call it out explicitly in the final report whether done + verified or skipped.
- Tests:
  - `tests/test_docs_readme.py` (NEW — spec §10): **[Fix #11]** locate files repo-relative via
    `Path(__file__).resolve().parents[1] / "README.md"` (match the existing `parents[1]` convention,
    NOT cwd). Assert `README.md` exists and contains the required section markers — crucially the
    **authorized-use / defensive-only** wording (the ROADMAP §7 hard requirement) — plus the
    quickstart commands; assert `demo/gauntlet.tape` exists and contains the gauntlet commands + an
    `Output` directive. **No VHS invoked.**
  - **End-to-end integration** (extend `tests/test_integration.py` or `test_cli_diff.py`): a fake
    run → write the record → `report --format html` and `--format md` both render → `diff` the record
    against a second hand-built record → all offline, asserting the pieces connect (run → report
    html/md → diff).
- Final full-suite pass.

**Files**: `README.md`, `demo/gauntlet.tape`, `demo/README.md`, `pyproject.toml` (optional readme
repoint), `tests/test_docs_readme.py` (new), `tests/test_integration.py` (extend, optional).

**Checkpoint**
```
ruff check .
ruff format --check .
pytest -q   # entire suite, offline (no keys/network/browser/VHS)
```
Passing: the README documents the tool end-to-end with the prominent authorized-use framing; the VHS
tape + how-to ship (gif out-of-band, not in the suite); the full `run → report html/md → diff` flow
works offline. The entire suite is green — the prior 385 tests (1 skipped) plus the new Phase-10
tests, with only the enumerated additive contract updates (spec §9). This is the **release-ready
cut** — the final phase of the ROADMAP. Satisfies spec §11 items 1–7.

---

## Plan review

1. **[BLOCKING] `score_detail`/`response_text` are nullable → renderers crash.** Fixed (M3/M4): guard `score_detail.reason` (only when not None), `response_text or "(no response)"`; test record includes a `score_detail=None`/`response_text=None` succeeded attempt.
2. **[BLOCKING] `attack_id=None` corrupts diff join.** Fixed (M2): excluded from newly_failing/fixed; test includes a None-id attempt.
3. **[BLOCKING] Markdown triple-backtick payload breaks fences.** Fixed (M3): fence = backtick run one longer than the longest run in content (min 3); test payload contains ```` ``` ````. (Also #3-text: ASCII +/-/= signs, not unicode, for Windows consoles — M2.)
4. **[BLOCKING] Gate test won't trip exit 3 with default FakeAdapter text.** Fixed (M1): FakeAdapter text set to match the attack's `contains` (`"x"`) → Verdict.FAIL → ASR>0 → exit 3.
5. **Gate test needs `--out` for a stable record path.** Fixed (M1).
6. **Diff-against-self edge case.** Fixed (M2): zero-delta test.
7. **`--fail-under` with 0 scored.** Fixed (M1): ASR 0.0, `0.0>0.0` False → exit 0 boundary test.
8. **Div-by-zero in per-axis diff.** Fixed (M2): reads `_asr`-guarded metrics_summary, no re-impl.
9. **`latency_delta_ms=None` rendering.** Fixed (M2): `latency: n/a` sentinel, asserted.
10. **`report` unknown-format silent fall-through.** Fixed (M3): explicit if/elif/else exit 2 + test.
11. **`test_docs_readme.py` path.** Fixed (M5): `Path(__file__).parents[1]`.
12. **pyproject readme repoint verification.** Fixed (M5): concrete `pip install -e .` verify or revert.
13. **`--out` file content/encoding untested.** Fixed (M3): read-back equals stdout render.
14. **(=#4) FakeAdapter FAIL verdict for the gate.** Fixed (M1).

**Resolution:** all four BLOCKING items (1–4) and the ten others (5–14) are folded into the
milestone build descriptions, test lists, and checkpoints above. Ready to implement.

STATUS: PASS
