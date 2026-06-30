# Phase 10 — Polish & ship (CI/headless mode · score-diff · HTML+Markdown reports · README · VHS demo tape): spec

> Phase 10 of 10 — **the final phase, the release-ready cut.** Implements ROADMAP §8.10:
> *"Polish & ship — CI/headless mode (exit code on an ASR threshold), score-diff over time
> (regression tracking), HTML + Markdown reports, a VHS-recorded demo GIF, and a strong README
> with the authorized-use framing. The release-ready cut."* It builds **directly on the existing
> reporting + run machinery** and adds no engine behaviour: `RunRecord.metrics_summary()` (the
> overall/by-category/by-OWASP/by-ATLAS ASR + controls + utility-under-attack block — the single
> source of truth every renderer consumes), `RunRecord.total_usage` / `total_cost_usd`,
> `AttemptRecord` (the `prompt` / `response_text` / `tool_calls` / `verdict` / `score_detail`
> failure-detail fields the HTML/MD failure list renders), the existing `gauntlet report`
> (text/json) command, the `gauntlet run` summary path (`_summary`), and the Phase-1
> `RunRecord.from_json` / `to_json` durable format. Phase 10 **extends, not reinvents**.
>
> **Five shippable deliverables, all OFFLINE and deterministic-testable:**
> 1. **CI/headless mode** on `gauntlet run` — a `--fail-under` ASR threshold that makes the run
>    exit **non-zero** when overall ASR exceeds it (a CI regression gate). No TUI, machine-readable
>    summary (the plain path already prints it). Precise exit-code contract.
> 2. **Score-diff** — a new `gauntlet diff RUN_A RUN_B` command + a structured `RunDiff` model:
>    overall + per-category/OWASP/ATLAS ASR deltas, newly-failing vs newly-fixed attacks, and
>    cost/latency deltas, rendered as text / json / markdown.
> 3. **HTML + Markdown reports** — `gauntlet report --format html|md` renders `metrics_summary`
>    (overall ASR, by category/OWASP/ATLAS, utility-under-attack, cost, latency, the failure list
>    with payloads + what the target did) to a **self-contained** HTML file and a Markdown file.
> 4. **A strong `README.md`** — vision, install, quickstart, the attack-pack data model, scoring
>    tiers, agent mode, and a **PROMINENT authorized-use / defensive-only framing** (ROADMAP §7).
> 5. **A VHS demo tape** — `demo/gauntlet.tape` (a VHS script that types the gauntlet commands and
>    shows the TUI scoreboard) + a short doc on generating the gif. **The `.gif` binary is produced
>    out-of-band** (VHS + a terminal); it is NOT recorded in tests.
>
> **Additive and default-safe.** No scoring/runner behaviour changes. `gauntlet run` with no
> `--fail-under` exits exactly as today (0 on success). `gauntlet report` defaults to `text`. The
> prior **385** tests (1 skipped) stay green; the only deliberate contract updates are the additive
> ones enumerated in §9 (mainly: `report --format` accepts two new values; `run` gains one option).
> **Minimize new deps:** renderers use **stdlib string templating** (f-strings + `html.escape`) —
> **no Jinja2** (justified in §5). Everything deterministic + unit-testable by asserting on the
> rendered string; **no browser, no VHS, no network in the suite.**

---

## 1. Goals

1. **CI/headless mode (regression gate).** `gauntlet run` gains `--fail-under FLOAT` (an overall-ASR
   threshold). After a normal run, if `overall_asr > threshold` the process exits with a defined
   **non-zero gate code (3)**; otherwise it exits 0. Headless = the existing plain (non-`--tui`)
   path, which already prints a one-line machine-readable summary and writes the JSON record. The
   exit-code contract is precisely specified (§4) and testable via `CliRunner` + a fake adapter.
2. **Score-diff over time.** A new `gauntlet diff RUN_A RUN_B` command + a structured `RunDiff`
   model (in a new `diff.py`) that compares two `RunRecord`s: overall ASR delta, per-category /
   per-OWASP / per-ATLAS ASR deltas, the set of **newly-failing** (defended→succeeded) and
   **newly-fixed** (succeeded→defended) attacks keyed by `attack_id`, and cost/latency deltas.
   Deterministic; rendered as text (default), json, or markdown. Testable on two hand-built records.
3. **HTML + Markdown reports.** `gauntlet report --format html|md` renders the **same**
   `metrics_summary` the text report shows — overall ASR, by category/OWASP/ATLAS, utility-under-
   attack, controls, cost, latency, and a **failure list** (each succeeded attack's id, category,
   OWASP/ATLAS, payload, and what the target did: response text / observed tool calls) — to a
   self-contained `.html` (inline CSS, no CDN/JS/external assets) and a `.md` file. A new
   `reports.py` holds `render_markdown(record) -> str` and `render_html(record) -> str`; `report`
   gains `--out PATH` to write the rendered artifact (else prints to stdout).
4. **A strong README.** A real, written `README.md` at the repo root: vision (ROADMAP §1), install,
   quickstart (`run` / `list` / `report` / `diff` / `update`), the attack-pack data model (ROADMAP
   §4), the scoring tiers (ROADMAP §5), agent mode (ROADMAP §7-phase), and a **prominent
   authorized-use / defensive-only section** (ROADMAP §7) near the top. This is a written deliverable.
5. **VHS demo tape.** `demo/gauntlet.tape` — a committed VHS script that types a representative
   gauntlet session (`list --packs`, a `run --tui` scoreboard, `report`, `diff`) — plus
   `demo/README.md` documenting how to install VHS and run `vhs demo/gauntlet.tape` to produce
   `demo/gauntlet.gif`. **The gif itself is generated out-of-band and is NOT committed/produced by
   the test suite** (binary, needs VHS + a real terminal).
6. Everything `pytest`-testable, **offline and deterministic** (no browser, no VHS, no network, no
   API keys). The prior **385** tests (1 skipped) stay green; the only contract updates are the
   additive ones enumerated in §9.

---

## 2. Scope

**In scope**
- `src/gauntlet/reports.py` (NEW): `render_markdown(record: RunRecord) -> str` and
  `render_html(record: RunRecord) -> str` — pure functions, stdlib templating, deterministic,
  self-contained output. A small shared `_failures(record) -> list[AttemptRecord]` helper (the
  succeeded, non-control attempts, sorted by `attack_id`).
- `src/gauntlet/diff.py` (NEW): `RunDiff` (Pydantic, `extra="forbid"`) + `diff_runs(a: RunRecord,
  b: RunRecord) -> RunDiff` + `render_text(diff)` / `render_markdown(diff)` (and the json rendering
  is `RunDiff.model_dump`). `RunDiff` carries `overall_asr_delta`, per-axis delta maps,
  `newly_failing` / `newly_fixed` (`list[str]` of attack ids, sorted), and cost/latency deltas.
- `src/gauntlet/cli.py` (EXTEND):
  - `run` gains `--fail-under FLOAT | None` (default `None` = no gate); after the run, if set and
    `overall_asr > threshold`, raise `typer.Exit(code=3)` (the **gate** code) — after the record is
    written and the summary printed (§4).
  - `report` gains `--format html|md` (in addition to `text`/`json`) and `--out PATH` (write the
    rendered report to a file; default stdout). Unknown `--format` → exit 2.
  - new `diff` command: `gauntlet diff RUN_A RUN_B [--format text|json|md] [--out PATH]`.
- `README.md` (NEW, repo root, deliverable): the written README (§7).
- `demo/gauntlet.tape` (NEW, deliverable) + `demo/README.md` (NEW): the VHS tape + how-to (§8).
- Tests: `tests/test_reports.py` (markdown + html renderers — assert key strings/structure on the
  rendered output, escaping, self-containment, determinism), `tests/test_diff.py` (the `RunDiff`
  model on two hand-built records — deltas, newly-failing/fixed, renderings), `tests/test_cli_diff.py`
  (the `diff` CLI surface), extend `tests/test_cli_run.py` (the `--fail-under` gate exit codes),
  extend `tests/test_cli_report.py` (the `--format html|md` + `--out` paths), and
  `tests/test_docs_readme.py` (assert `README.md` + `demo/gauntlet.tape` exist and contain the
  required sections/markers — so the written deliverables can't ship empty).

**Out of scope (explicitly deferred / non-goals)**
- **An actually-recorded `demo/gauntlet.gif`.** Phase 10 ships the **tape script + instructions**;
  the gif is rendered out-of-band with VHS (an external tool not installable/runnable in CI tests).
  No binary asset is produced or asserted by the suite.
- **Jinja2 (or any templating dep).** Decided against (§5): stdlib f-strings + `html.escape` keep
  the dep set minimal and the rendered output trivially string-assertable. (ROADMAP §6 *names*
  Jinja2 as the candidate; this phase makes the lighter-weight, zero-dep choice and justifies it.)
- **A PDF / browser-rendered / interactive report.** HTML is a single self-contained file asserted
  as a *string*; no headless browser, no screenshot, no JS charting.
- **Multi-run trend dashboards / a time-series store.** `diff` compares exactly **two** records;
  N-way trend aggregation is post-MVP.
- **Publishing to PyPI / a release pipeline / CI YAML.** Phase 10 makes the tool *CI-ready* (the
  exit-code contract); wiring a specific GitHub Actions workflow is the user's to add (the README
  documents the contract and gives an example invocation).
- **Any scoring/runner/metrics behaviour change.** `metrics_summary` is consumed as-is; the
  renderers and diff are pure read-side projections.

---

## 3. Module layout

```
src/gauntlet/
├── reports.py   # NEW: render_markdown(record) / render_html(record); _failures() helper (stdlib templating, deterministic, self-contained)
├── diff.py      # NEW: RunDiff (pydantic), diff_runs(a, b), render_text(diff) / render_markdown(diff)
└── cli.py       # EXTEND: run --fail-under (gate exit 3); report --format html|md + --out; new `diff` command
README.md        # NEW (repo root): the strong README with the authorized-use framing (deliverable)
demo/
├── gauntlet.tape   # NEW: VHS script (types the gauntlet session, shows the TUI) — deliverable
└── README.md       # NEW: how to install VHS + run the tape to produce gauntlet.gif (gif is out-of-band)
tests/
├── test_reports.py      # M3+M4: markdown + html renderers — key strings, escaping, self-containment, determinism
├── test_diff.py         # M2: RunDiff on two hand-built records — deltas, newly-failing/fixed, renderings
├── test_cli_diff.py     # M2: `gauntlet diff` CLI (text/json/md, --out, missing file -> exit 2)
├── test_cli_run.py      # M1 (extend): --fail-under gate exit codes (0 vs 3)
├── test_cli_report.py   # M3/M4 (extend): report --format html|md + --out; bad --format -> exit 2
└── test_docs_readme.py  # M5: README.md + demo/gauntlet.tape exist with required sections/markers
```

---

## 4. CI / headless mode — the exit-code contract (precise)

**Flag.** `gauntlet run` gains one option:

```
--fail-under FLOAT   # overall-ASR gate threshold in [0.0, 1.0]; default None (no gate). CI regression gate.
```

`--fail-under 0.0` means *"any successful attack fails the gate"*; `--fail-under 0.2` means
*"fail if overall ASR strictly exceeds 20%"*. The threshold is the **overall** ASR
(`metrics_summary()["overall_asr"]`, == `record.asr`) — controls and ERROR/SKIPPED are already
excluded by that metric (ROADMAP §5). Validation: a value outside `[0.0, 1.0]` → **exit 2** (usage
error) before the run starts.

**Threshold semantics.** The gate trips when **`overall_asr > threshold`** (strictly greater).
Rationale: `--fail-under 0.0` should pass a clean run (ASR exactly 0.0) and fail any non-zero ASR;
strict-greater gives that boundary. (Documented in `--help` and the README as "fail if overall ASR
exceeds the threshold".)

**Exit codes (the contract):**

| Code | Meaning | When |
|------|---------|------|
| **0** | success, gate passed (or no gate) | run completed; `--fail-under` unset, or `overall_asr <= threshold` |
| **2** | usage / config error | bad `--target`, bad `--pack`, bad config, `--fail-under` out of `[0,1]`, mutually-exclusive flags — Typer's existing convention, raised **before** results matter |
| **3** | **gate tripped** (regression) | run completed normally **but** `overall_asr > --fail-under` |

- **The gate is evaluated last.** The run executes, the record is **persisted** (and `--out`
  written), and the one-line summary is **printed** — *then* the gate exit is raised. A CI job that
  fails the gate still gets the artifact + summary. (Implementation: compute the gate after the
  existing `typer.echo(_summary(...))`, then `raise typer.Exit(code=3)`.)
- **Exit 3 is distinct from 2** so CI can tell *"a regression"* (3, expected/actionable) from
  *"the tool was mis-invoked"* (2). It is also distinct from any uncaught-exception exit.
- **`--dry-run` + `--fail-under`** → the gate is a no-op (dry-run sends nothing and writes no
  record; it returns before the run). Documented; not an error.
- **Headless.** "CI/headless mode" = the existing **plain path** (no `--tui`): it already emits the
  machine-readable one-line summary (`run <id>: … asr=… …`) and writes the JSON record. No new
  "headless" flag is needed; `--fail-under` is the only addition. (`--tui` + `--fail-under` is
  permitted — the gate still applies after the TUI run — but the README recommends the plain path
  for CI.)

Testable: `CliRunner().invoke(app, ["run", "--target", "fake", "--fail-under", "0.0", …])` with a
fake adapter whose attempts yield a known ASR → assert `result.exit_code` is 0 or 3 as specified,
and that the summary line + record were still produced on the 3 path.

---

## 5. HTML + Markdown report renderers (`reports.py`) — templating + dep decision + determinism

### 5.1 Dependency decision — **stdlib templating, no Jinja2** (justified)

ROADMAP §6 lists Jinja2 as the candidate for HTML/MD. **This phase deliberately uses stdlib
f-string templating instead**, because:

- **Minimize deps (project rule).** The reports are a handful of small, fixed templates over one
  dict (`metrics_summary`) + a flat failure list — no loops/conditionals complex enough to need a
  template engine. Adding Jinja2 (and its `MarkupSafe` transitive dep) for this is unjustified
  weight on an Apache-licensed CLI.
- **Determinism + testability.** Pure f-strings produce byte-identical output for the same record,
  with no template-autoescape surprises, and the unit tests assert on the **exact rendered string**.
- **Self-containment.** HTML is one file with a small inline `<style>` block — no CDN, no JS, no
  external assets (ROADMAP/offline requirement). A template engine adds nothing here.

So: no new runtime dependency. (If a future phase needs richer templating it can add Jinja2 then;
this is explicitly the lighter choice for the release cut.) HTML escaping uses **`html.escape`**
(stdlib) on every record-derived string (payloads, response text, tool-call reprs, ids) to prevent
attack payloads — which are adversarial by construction — from breaking or injecting into the HTML.

### 5.2 What both renderers show (from `metrics_summary` + the record)

Driven entirely by `record.metrics_summary()` + record-level fields (single source of truth, same
as the text report):

- **Header:** run id, target (`provider/model`), status, created-at, pack ids.
- **Headline metrics:** overall ASR, scored / succeeded / defended / errored / skipped, total.
- **Utility-under-attack + controls** (answered / total / refused / errored) — shown only when
  `controls.total > 0` (mirror the text report's conditional).
- **Cost + latency:** `record.total_cost_usd`, `record.total_usage.total_tokens`, and a latency
  summary (e.g. mean/median of non-`None` `attempt.latency_ms`) — a small helper in `reports.py`.
- **Breakdowns:** `by_category`, `by_owasp`, `by_atlas` — each a table of `code | ASR | succeeded/
  scored`, rows sorted by code (deterministic).
- **Failure list:** every succeeded (`verdict == FAIL`), non-control attempt, sorted by `attack_id`,
  showing `attack_id`, category, OWASP/ATLAS, the **payload** (`prompt`), and **what the target did**
  (`response_text` and, if `tool_calls`, the observed tool calls) plus the `score_detail.reason`
  (why the scorer ruled it a success). This is the "exact payloads that broke it" of ROADMAP §1.

### 5.3 Markdown (`render_markdown`)

A GitHub-flavoured Markdown document: `#`/`##` headings, the metrics as a small table, the three
breakdowns as Markdown tables, and the failure list as a `###` per attack with the payload/response
in fenced code blocks. Pure f-strings; deterministic ordering (sorted keys). Returns a `str`.

### 5.4 HTML (`render_html`)

A single self-contained `<!DOCTYPE html>` document: `<head>` with an inline `<style>` (a compact,
readable theme — pass/fail color accents echoing the TUI scoreboard's red/green), `<body>` with the
header, a metrics summary, three `<table>` breakdowns, and the failure list (`<section>` per
failure, payload/response in `<pre>`). **No `<script>`, no external `<link>`/CDN, no remote images.**
Every interpolated record value is `html.escape`-d. Returns a `str`.

### 5.5 CLI wiring

`gauntlet report --run REC --format {text|json|html|md} [--out PATH]`:
- `text` / `json` — unchanged (existing behaviour).
- `html` → `reports.render_html(record)`; `md` → `reports.render_markdown(record)`.
- `--out PATH` set → write the rendered string to `PATH` (utf-8), echo a one-line confirmation
  (`wrote <format> report -> PATH`); unset → print the rendered string to stdout.
- Unknown `--format` → exit 2 with a clear message (covers all four valid values).

### 5.6 Determinism

Same record → byte-identical output (no timestamps-of-now, no dict-iteration-order dependence —
all breakdowns sorted by key, the failure list sorted by `attack_id` then `attempt_id` as a stable
tiebreak). The record's own `created_at` is rendered (a property of the input, deterministic), not
`datetime.now()`. Tests assert exact substrings/structure and that two calls return identical strings.

---

## 6. Score-diff (`diff.py` + `gauntlet diff`)

### 6.1 The `RunDiff` model

```python
class AsrDelta(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    asr_a: float
    asr_b: float
    delta: float          # asr_b - asr_a (positive = regression: more attacks succeeded in B)

class RunDiff(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_a: str            # run_id of A (the baseline)
    run_b: str            # run_id of B (the new run)
    overall_asr_a: float
    overall_asr_b: float
    overall_asr_delta: float
    by_category: list[AsrDelta]      # sorted by code; union of A/B categories (missing side -> 0.0)
    by_owasp: list[AsrDelta]
    by_atlas: list[AsrDelta]
    newly_failing: list[str]         # attack_ids defended in A but succeeded in B, sorted
    newly_fixed: list[str]           # attack_ids succeeded in A but defended in B, sorted
    cost_delta_usd: float            # total_cost_usd(B) - total_cost_usd(A)
    latency_delta_ms: float | None   # mean-latency(B) - mean-latency(A); None if either side has no latencies
```

### 6.2 `diff_runs(a, b) -> RunDiff`

- Overall + per-axis deltas computed from each record's `metrics_summary()` (reusing the existing
  ASR machinery — no recomputation logic duplicated). Each breakdown is the **union** of codes
  present in A or B; a code missing on one side contributes ASR `0.0` for that side (and is noted).
- **newly-failing / newly-fixed** are computed by joining attempts on **`attack_id`** (the stable
  identifier): for ids scored (PASS/FAIL, non-control) in **both** runs, compare verdicts —
  `defended(A) & succeeded(B)` → newly-failing; `succeeded(A) & defended(B)` → newly-fixed. Ids only
  in one run, or ERROR/SKIPPED on a side, are excluded from these two sets (they aren't a
  fixed↔broke transition). Both lists sorted.
- `cost_delta_usd` from `total_cost_usd`; `latency_delta_ms` from a mean over non-`None`
  `latency_ms` per run (None if either run has no measured latency — diffing nothing is `None`, not 0).
- **Deterministic**: pure functions of the two records, sorted outputs, no clock/network.

### 6.3 `gauntlet diff RUN_A RUN_B`

```
gauntlet diff RUN_A RUN_B [--format text|json|md] [--out PATH]
```

- `RUN_A` / `RUN_B` are positional paths to `RunRecord` JSON files; a missing/unparseable file →
  **exit 2** (same convention as `report`). A is the baseline, B the new run.
- `--format text` (default) → `diff.render_text(d)` (a human summary: overall delta with a
  ▲/▼/= sign, the per-category/OWASP/ATLAS deltas, the newly-failing/newly-fixed id lists, cost/
  latency deltas). `json` → `d.model_dump()` via `json.dumps`. `md` → `diff.render_markdown(d)`
  (tables + lists, for pasting into a PR/CI comment — the "regression tracking" use).
- `--out PATH` → write the rendered string (else stdout), mirroring `report`.
- Exit 0 on a successful diff regardless of the delta sign (`diff` *reports* regressions; it does
  not itself gate — gating is `run --fail-under`). (A future `--fail-on-regression` could trip exit
  3 here too, but that's out of scope for this cut.)

Testable on two hand-built `RunRecord`s (no run needed): assert the deltas, the newly-failing/fixed
sets, and that the three renderings contain the expected markers.

---

## 7. README deliverable (outline) — with the authorized-use framing requirement

`README.md` at the repo root, a real written deliverable (not a stub), covering at minimum:

1. **Title + one-line pitch** (ROADMAP §1: "a CLI tool that red-teams your AI agents").
2. **⚠ Authorized-use / defensive-only framing — PROMINENT, near the top (a HARD requirement,
   ROADMAP §7).** A clearly-set-off section stating: gauntlet is for **authorized testing of agents
   you own or are explicitly authorized to test**; it is **not** an offensive tool, has **no
   evasion-for-malice features**, and is **not** a general LLM benchmark — it is defensive security
   red-teaming. This framing is non-negotiable and must be visually prominent (heading + callout),
   not buried.
3. **What it does** — the differentiator: tests the **agent**, not just the model; outcome/side-effect
   judging; the live TUI scoreboard; attacks-as-data catalog (ROADMAP §1-2).
4. **Install** — Python 3.11+, `pip install -e .` (and the `[mcp]` / `[dev]` extras), the
   provider-key-in-`.env` note (ROADMAP §9), Ollama for free local runs.
5. **Quickstart** — copy-pasteable: `gauntlet list --packs`, `gauntlet run --target … [--tui]`,
   `gauntlet report --run … --format html|md`, `gauntlet diff RUN_A RUN_B`, `gauntlet update`. Show
   the **CI usage** of `run --fail-under` + the exit-code contract (§4).
6. **The attack-pack data model** — the YAML schema (ROADMAP §4), `success_when` types, license
   gating; link to `docs/authoring-packs.md`.
7. **Scoring tiers** — T1–T4, ASR / utility-under-attack / cost / latency (ROADMAP §5).
8. **Agent mode** — Python-callable / MCP / sandbox targets and side-effect assertions (ROADMAP §7-phase).
9. **Reports & regression tracking** — text/json/html/md reports + `diff`; the demo gif (link to
   `demo/`).
10. **License** (Apache-2.0) + a pointer to the ROADMAP and per-phase docs.

A lightweight test (`test_docs_readme.py`) asserts the README exists and contains the required
section markers — crucially the **authorized-use** wording — so the deliverable can't ship empty or
without the safety framing.

---

## 8. VHS demo tape deliverable (script + docs; gif out-of-band)

- **`demo/gauntlet.tape`** — a [VHS](https://github.com/charmbracelet/vhs) script (`.tape`) that:
  sets a sensible terminal size/theme, `Type`s a representative session — `gauntlet list --packs`,
  a `gauntlet run --target … --tui` (the live scoreboard filling red/green — the hero asset of
  ROADMAP §5), `gauntlet report --run … --format md`, and a `gauntlet diff` — with `Sleep`s for
  readability, and an `Output demo/gauntlet.gif` directive. It uses a **demo-safe** target (a local/
  Ollama or fake target so the recording needs no paid key) and is committed as **text**.
- **`demo/README.md`** — documents: install VHS (`go install` / `brew install vhs`), run
  `vhs demo/gauntlet.tape` to render `demo/gauntlet.gif`, the demo-target prerequisites, and that
  **the `.gif` is generated out-of-band and intentionally not committed** (regenerate from the tape).
- **Explicitly NOT in the suite:** no test runs VHS or asserts on a gif. The deliverable here is the
  **tape script + the how-to doc**; a test only asserts `demo/gauntlet.tape` exists and contains the
  expected commands/`Output` directive (so the script can't rot to empty), never that a gif was made.

---

## 9. Deliberate contract updates (enumerated)

All additive; each is called out so the corresponding test is updated as a *deliberate* change:

1. **`gauntlet run` gains `--fail-under`** — new optional flag, default `None` (no gate). With it
   unset, `run` exits exactly as before (0 on success). New tests cover the 0/3 gate boundary; no
   existing `run` test changes behaviour (they pass no `--fail-under`).
2. **`gauntlet report --format` accepts `html` and `md`** (in addition to `text`/`json`) and gains
   `--out PATH`. Existing `text`/`json` behaviour is unchanged; the unknown-format error message
   now lists four valid values. A report test may assert the new help/values, but the existing
   text/json assertions are untouched.
3. **New `gauntlet diff` command** — purely additive; no existing command affected.
4. **New modules `reports.py` / `diff.py`** — new code only; no existing public signature removed.
5. **New deliverable files** — `README.md` (repo root), `demo/gauntlet.tape`, `demo/README.md`. Note:
   `pyproject.toml` currently sets `readme = "PROGRESS.md"`; Phase 10 **may** repoint it to
   `README.md` — if so, that one-line change is called out and the build still succeeds (additive,
   `README.md` exists). (Optional; only if it doesn't disturb the wheel build.)

No new runtime dependency is added (stdlib templating — §5.1). `metrics_summary`, the runner, and
scoring are untouched.

---

## 10. Testing strategy (offline + deterministic)

- **Markdown/HTML renderers** (`test_reports.py`): build a synthetic `RunRecord` with a mix of
  FAIL/PASS/ERROR/SKIPPED attempts, controls, OWASP/ATLAS codes, tool-calls, and an adversarial
  payload containing HTML metacharacters (`<script>`, `&`, `"`). Assert: the overall ASR string, the
  by-category/OWASP/ATLAS rows, the utility/controls block (present with controls, absent without),
  cost/latency, and the failure list (each succeeded attack's id + payload + response). Assert HTML
  is **self-contained** (`<!DOCTYPE html>`, an inline `<style>`, **no** `http://`/`https://` asset
  URLs, **no** `<script>`) and that the metacharacter payload is **escaped** (`&lt;script&gt;`).
  Assert **determinism** (two calls → identical strings). No browser.
- **Score-diff** (`test_diff.py`): two hand-built `RunRecord`s sharing some `attack_id`s with
  changed verdicts → assert `overall_asr_delta`, the per-axis `AsrDelta` lists (union of codes,
  missing side = 0.0), the exact `newly_failing` / `newly_fixed` id sets (defended↔succeeded
  transitions only; ERROR/SKIPPED/one-sided ids excluded), `cost_delta_usd`, `latency_delta_ms`
  (None when a side has no latencies), and that text/json/md renderings contain the expected markers.
- **CI gate** (`test_cli_run.py`, extend): a fake adapter producing a known ASR → `run --fail-under
  0.0` on a run with ASR>0 → **exit 3** and the summary/record still produced; `--fail-under 1.0` (or
  ASR≤threshold) → **exit 0**; `--fail-under 1.5` → **exit 2** (out of range); `--dry-run
  --fail-under 0.0` → exit 0 (no gate). Reuse the existing fake-adapter / `_load_attacks`
  monkeypatch pattern from the current run tests.
- **`report` html/md + diff CLI** (`test_cli_report.py` extend, `test_cli_diff.py`): `report
  --format html` / `md` prints (or `--out` writes) the rendered string; bad `--format` → exit 2;
  `diff A B --format text|json|md` on two written records → exit 0 with the expected output; a
  missing record path → exit 2.
- **Written deliverables** (`test_docs_readme.py`): `README.md` exists and contains the required
  section markers — including the **authorized-use / defensive-only** wording (the §7 hard
  requirement) and the quickstart commands; `demo/gauntlet.tape` exists and contains the gauntlet
  commands + an `Output` directive. No VHS invoked.
- **No browser, no VHS, no network, no API keys, no real side effects.** The prior **385** tests (1
  skipped) stay green except the enumerated §9 additive updates.

---

## 11. Acceptance criteria

A reviewer can confirm Phase 10 (the **release-ready cut**) is done when:

1. `ruff check .` and `ruff format --check .` pass with zero findings; `pytest` is green **offline
   with no API keys / network / browser / VHS**; the prior **385** tests (1 skipped) pass, with only
   the additive §9 contract updates.
2. **CI/headless mode:** `gauntlet run --fail-under T` exits **0** when overall ASR ≤ T (or the flag
   is unset), **3** when overall ASR > T (gate tripped, *after* the record is written and summary
   printed), and **2** for an out-of-range threshold — the exit-code contract of §4, testable via
   `CliRunner` + a fake adapter.
3. **Score-diff:** `gauntlet diff RUN_A RUN_B` produces a deterministic `RunDiff` (overall +
   per-category/OWASP/ATLAS ASR deltas, newly-failing/newly-fixed attack ids, cost/latency deltas),
   rendered as text/json/md; missing record → exit 2; tested on two hand-built records.
4. **HTML + Markdown reports:** `gauntlet report --format html|md [--out PATH]` renders
   `metrics_summary` (overall ASR, by category/OWASP/ATLAS, utility-under-attack, controls, cost,
   latency, and the failure list with payloads + what the target did) to a **self-contained** HTML
   file (inline CSS, no CDN/JS/external assets, payloads HTML-escaped) and a Markdown file, both
   **deterministic** and unit-tested by asserting on the rendered string — **no new dependency**
   (stdlib templating; the no-Jinja2 decision is justified in §5.1).
5. **README:** `README.md` exists and is a real, strong README — vision, install, quickstart
   (run/list/report/diff/update incl. the CI exit-code usage), the attack-pack data model, scoring
   tiers, agent mode, and a **PROMINENT authorized-use / defensive-only framing** (ROADMAP §7),
   verified by `test_docs_readme.py`.
6. **VHS demo:** `demo/gauntlet.tape` (a VHS script typing the gauntlet session + showing the TUI
   scoreboard) and `demo/README.md` (how to render the gif with VHS) exist; the `.gif` is documented
   as **out-of-band** and is neither committed nor produced by the suite.
7. No scoring/runner/metrics behaviour changed; `metrics_summary` is the single source of truth all
   renderers and the diff consume; everything offline and deterministic. **This is the release-ready
   cut — the final phase of the ROADMAP.**
