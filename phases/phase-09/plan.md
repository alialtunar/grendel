# Phase 9 — Plugin system + open catalog + feeds (multi-source loader · OWASP/ATLAS reports · remote feed · authoring guide): implementation plan

> Dependency-ordered and **scoring-untouched**, so the prior **348** tests (1 skipped) stay green
> at every checkpoint: (1) the **multi-source catalog loader** (`load_catalog` merging bundled +
> user dirs + feed cache, source-tagged, dedup/precedence) + the additive `CatalogConfig` — a
> read-only loading change, no scoring; (2) the **OWASP/ATLAS report breakdown** — additive
> `AttemptRecord.owasp/atlas`, `by_owasp`/`by_atlas` in `metrics_summary`, report/list surfacing;
> (3) the **remote feed** — manifest schema + `gauntlet update` (offline via `httpx.MockTransport`,
> license-gate + checksum + content-coherence), whose cache the M1 loader already merges as a
> `feed` source; (4) the **authoring guide** doc + the optional **staged/approval** seam +
> end-to-end integration. Every milestone ends in a **Checkpoint** with exact commands. Quality
> gate: `ruff check .` (zero findings), `ruff format --check .` (clean), `pytest` (green,
> **offline, no API keys, no network, no real feed server**). New code reuses existing patterns:
> Pydantic v2 `ConfigDict(extra="forbid")`; the `load_packs` license-gate + coherence + assert-parse
> primitive (called per source); the Phase-1 `httpx.MockTransport` injectable-client pattern for the
> feed pull; the `_asr` / `by_category` machinery for the new breakdowns; the existing `errors.py`
> hierarchy (`PackError`, new `FeedError`). **No new deps** (`httpx` is already a dependency).
> `load_packs` stays untouched; everything else is additive — the only contract updates are the
> enumerated additive ones (spec §10), noted per milestone.

---

## Milestone 1 — Multi-source catalog loader (bundled + user dirs + feed cache) + source tagging + `CatalogConfig`

**Build**
- `src/gauntlet/packloader.py` (EXTEND):
  - `Source(str, Enum)`: `BUNDLED`/`USER`/`FEED`/`STAGED`.
  - `CatalogEntry(BaseModel)` (`extra="forbid"`): `attack: Attack`, `source: Source`, `path: Path`,
    `armed: bool = True`.
  - `load_catalog(config, *, allow_unlisted_licenses=False) -> list[CatalogEntry]`: load the
    bundled dir, then each `config.catalog.pack_dirs`, then `config.catalog.feed_cache_dir` (if set
    & a dir), then `config.catalog.staged_dir` (if set; `armed=False`) — **each via the existing
    `load_packs(dir, allow_unlisted_licenses=...)`** so every source gets the same validation. An
    **absent** configured dir contributes zero (no error); a malformed one raises `PackError`
    (unchanged). `allow_unlisted_licenses` = the arg OR `config.catalog.allow_unlisted_licenses`.
  - **Cross-source dedup (spec §5.2):** build by source order; on a duplicate `id` across sources,
    default → `PackError` naming both paths + both sources; if `config.catalog.allow_override` →
    precedence win **user > feed > bundled** (deterministic by source rank, not filesystem order),
    drop the loser. (In-dir duplicates still error inside `load_packs` — unchanged.)
    **[Fix #7 — same-source rank tie]** two dirs of the SAME source rank (e.g. two `pack_dirs`)
    with the same id always → `PackError` even when `allow_override=True` (override only resolves
    DIFFERENT ranks; equal ranks have no winner). Test this.
  - `PackInfo` gains `source: Source`. `list_packs(packs_dir=None, *, config=None,
    allow_unlisted_licenses=False)`: when `config` is given, project the **merged** `load_catalog`
    (each row tagged with its source); when not, keep the single-dir behavior (default
    `source=BUNDLED`) so existing callers/tests are unchanged.
- `src/gauntlet/config.py` (EXTEND, additive): `FeedSource` (`name`, `url`, non-empty validated),
  `CatalogConfig` (`pack_dirs`, `feed_cache_dir`, `feeds`, `staged_dir`, `allow_override`,
  `allow_unlisted_licenses`), and `GauntletConfig.catalog: CatalogConfig = CatalogConfig()`.
  Resolve relative `pack_dirs`/`feed_cache_dir`/`staged_dir` against the config-file dir (cwd when
  config is `None`) in `load_config` so paths are stable. **No change** to existing validators.
  **[Fix #11]** this is a real modification to `load_config` (not just new models) — list
  `config.py::load_config` explicitly in Files and add a dedicated round-trip test asserting a
  relative `pack_dirs` entry resolves against the config-file's directory.
- `src/gauntlet/cli.py` (EXTEND): `gauntlet list --packs` calls `list_packs(config=cfg)` and adds
  the source tag to each row (trailing `[{source}]`). **[Fix #1 — CRITICAL single patch point]**
  introduce a thin module-level helper `_load_attacks(cfg) -> list[Attack]` = `[e.attack for e in
  load_catalog(cfg) if e.armed]`, and have `gauntlet run` (both plain + TUI paths) call
  `_load_attacks(cfg)` instead of `load_packs(default_packs_dir())` (identical set when `catalog`
  is empty). The existing `test_cli_run.py` (6 sites) and `test_cli_tui.py` (2 sites)
  monkeypatch `cli.load_packs` — those become inert after this change; UPDATE them to monkeypatch
  `cli._load_attacks` (return the fake `list[Attack]` directly). List both files in Files +
  contract updates. Keep `PackError`/`ConfigError` → exit 2.
- Tests: `tests/test_catalog_loader.py` (spec §11 loader cases — merge, source tags, default ==
  bundled-21, cross-source dup error + override precedence, unlisted-license gate per source,
  absent dir = zero). Extend `tests/test_config.py` (CatalogConfig round-trip, relative-path
  resolution, empty default).
- **[Enumerated contract updates — deliberate, additive]:**
  - `tests/test_bundled_packs.py` / the `list --packs` output test: the 21 bundled rows now end in
    `[bundled]`; update the exact-output assertion. **Counts unchanged (21).**
  - Any test constructing/asserting `PackInfo` fields gains `source` (default `BUNDLED`).

**Files**: `packloader.py`, `config.py`, `cli.py`, `tests/test_catalog_loader.py`,
`tests/test_config.py` (extend), `tests/test_bundled_packs.py` (source-tag assertion).

**Checkpoint**
```
ruff check .
ruff format --check .
pytest -q   # FULL suite — packloader/config/cli are shared paths; confirm the 348 prior tests (1 skipped) stay green
```
Passing: `load_catalog` merges bundled + user + feed-cache + staged sources with correct source
tags and the §5.2 dedup rule; default empty `catalog` is byte-identical to the bundled set; no
scoring change. Prior 348 tests green (only the source-tag list assertion updated).

---

## Milestone 2 — OWASP/ATLAS metrics breakdown + report/list surfacing

**Build**
- `src/gauntlet/records.py` (EXTEND, additive):
  - `AttemptRecord.owasp: str | None = None`, `AttemptRecord.atlas: str | None = None` (default
    `None` → old records deserialize unchanged; controls/error rows may be `None`).
  - `asr_by_owasp()` / `asr_by_atlas()` mirroring `asr_by_category()` (group non-control attempts
    by code, `None` → `"unmapped"`, reuse `_asr`, exclude the reserved `control` category).
  - `metrics_summary` gains `"by_owasp"` and `"by_atlas"` blocks — each
    `{code: {"asr", "scored", "succeeded"}}`, controls excluded — **without removing or changing
    any existing key** (`overall_asr`, `by_category`, `controls`, … intact).
- `src/gauntlet/runner.py` (EXTEND): set `owasp=attack.owasp, atlas=attack.atlas` on the scored
  `AttemptRecord`, mirroring `category`. **[Fix #3 — error-path threading]** the shared
  `_perform_send` helper builds the AttemptRecord from `attack_id`/`category` only; add
  `owasp: str | None = None` and `atlas: str | None = None` kwargs to its signature, have
  `_run_attempt` pass `owasp=attack.owasp, atlas=attack.atlas`, and `_run_control` pass `None`
  for both. Without this the error-path attempt can't carry the codes. (Error/control rows are
  excluded from the ASR breakdowns regardless; controls carry `owasp=atlas=None`.)
- `src/gauntlet/cli.py` (EXTEND): `gauntlet report` (text) prints a `by OWASP:` block and a
  `by ATLAS:` block after `by category:`, formatted like the category rows
  (`{code}: ASR {asr:.2%} (succeeded {succeeded}/{scored})`). `report --format json` already emits
  `metrics_summary()` → the new blocks appear automatically (additive).
- Tests: `tests/test_metrics_owasp.py` (synthetic `RunRecord` → `by_owasp`/`by_atlas` correctness,
  controls excluded, `None` → `"unmapped"`, existing keys unchanged). Extend a report test with an
  additive assertion that the OWASP/ATLAS blocks render.
- **[Enumerated contract updates — deliberate, additive]:** a test asserting the exact
  `AttemptRecord` field set or a serialized-attempt JSON gains `owasp`/`atlas` (default `None`); a
  test asserting the exact `metrics_summary` key set gains `by_owasp`/`by_atlas`.

**Files**: `records.py`, `runner.py`, `cli.py`, `tests/test_metrics_owasp.py`, a report test
(extend).

**Checkpoint**
```
ruff check .
ruff format --check .
pytest tests/test_metrics_owasp.py tests/test_records.py -q
```
Then full suite:
```
pytest -q
```
Passing: every report surfaces OWASP/ATLAS (record fields populated by the runner, `by_owasp`/
`by_atlas` in `metrics_summary`, both printed by `report` and present in JSON, source+codes shown
by `list --packs`). Prior 348 tests green with the enumerated additive updates.

---

## Milestone 3 — Remote feed: manifest schema + `gauntlet update` (offline via MockTransport, license-gate + checksum)

**Build**
- `src/gauntlet/errors.py` (EXTEND): add `FeedError(GauntletError)` (manifest parse / unsupported
  version / unreachable feed).
- `src/gauntlet/feed.py` (NEW, spec §7):
  - `FeedPackEntry` (`id`, `category`, `version>=1`, `license`, `sha256` pattern `^[0-9a-f]{64}$`,
    `url`, `size?`) and `FeedManifest` (`feed`, `manifest_version>=1`, `generated_at?`, `packs`),
    both `extra="forbid"`. Reject `manifest_version` greater than this build understands (`FeedError`).
    **[Fix #2 — path-traversal: enforce patterns]** `FeedPackEntry.category` MUST be
    `Field(pattern=r"^[a-z0-9-]+$")` and `id` MUST be `Field(pattern=r"^[a-z0-9-]+/[a-z0-9-]+$")`,
    so a manifest with `"category": "../../etc"` is rejected at PARSE time (step 1).
  - `FeedUpdateResult` **[Fix #5]** is a Pydantic `BaseModel` (`extra="forbid"`, like every other
    structured type): `pulled`, `updated`, `unchanged`, `skipped_license`, `checksum_failed`,
    `errors`, `details: list[...]` of `(feed, id, action, reason)`.
  - `async def update_feeds(config, *, client=None, allow_unlisted_licenses=False) ->
    FeedUpdateResult`: per `FeedSource`, `GET` the manifest via the injected `httpx.AsyncClient`
    (**[Fix #6]** when `client is None`, own it via `async with httpx.AsyncClient(...) as client:`
    so connections/fds are released — mirror the Phase-1 adapter), validate it, then per entry run
    the spec §7.2 pipeline:
    **license-gate BEFORE download** (unlisted + not opted-in → skip, never fetched) →
    download bytes (**[Fix #10]** enforce a hard size cap, e.g. 1 MiB — refuse + count as error if
    `Content-Length` or the streamed bytes exceed it; `size` in the manifest is the declared bound)
    → **sha256 verify** (**[Fix #8]** direct lowercase compare `sha256(content).hexdigest() ==
    entry.sha256`; the field pattern guarantees both lowercase; mismatch → refuse, not written) →
    parse+validate as `Attack` and check content **coheres with the manifest claim**
    (id/category/license/version) →
    **[Fix #2 — write path from VALIDATED attack, atomically]** build the cache path from the
    parsed `attack.category` and `attack.id.split('/',1)[1]` (NEVER from `entry.category` or a
    url-derived stem), and **[Fix #4]** write atomically (temp file in the dest dir + `os.replace`,
    like the runner's `_atomic_write`) to `feed_cache_dir/<category>/<stem>.yaml`
    (pulled/updated/unchanged by version+sha).
    Per-entry problems are collected into the result (not raised); manifest-level failures are
    per-feed errors so one bad feed doesn't abort the rest. Honor a `dry_run` flag (fetch+verify,
    no write). `feed_cache_dir is None` → `FeedError` ("no catalog.feed_cache_dir configured").
- `src/gauntlet/cli.py` (EXTEND): `gauntlet update [--feed NAME] [--allow-unlisted-licenses]
  [--dry-run]` → `asyncio.run(update_feeds(cfg, ...))`, print the summary
  (pulled/updated/unchanged/skipped-license/checksum-failed + per-skip reasons), exit 0 on success,
  exit 2 on `FeedError` (e.g. no `feed_cache_dir`). **[Fix #9]** `--feed NAME` that matches no
  configured feed → exit 2 with a clear "no feed named NAME" message (don't silently process zero).
- Tests: `tests/test_feed_update.py` (spec §11 feed cases via `httpx.MockTransport`): clean pack
  pulled + cached + then loadable by `load_catalog`; checksum mismatch refused (not written);
  unlisted-license skipped **without download** (handler asserts the pack URL was never requested)
  unless opted in; content/manifest mismatch rejected; `--dry-run` writes nothing; re-run on the
  same manifest → all `unchanged`, no rewrite (reproducibility); non-2xx manifest → per-feed error,
  other feeds still processed. Compute real `sha256` in fixtures; assert the injected client is used
  (no real network). **[Fix #2]** a manifest with `category: "../../etc"` or a traversal `id` is
  rejected at parse (FeedManifest validation) and nothing is written outside `feed_cache_dir`.
  **[Fix #10]** an over-cap pack body is refused and counted as an error. **[Fix #4]** an
  interrupted/partial write leaves the prior cached file intact (atomic).

**Files**: `errors.py`, `feed.py`, `cli.py`, `tests/test_feed_update.py`.

**Checkpoint**
```
ruff check .
ruff format --check .
pytest tests/test_feed_update.py -q
```
Then full suite:
```
pytest -q
```
Passing: `gauntlet update` pulls versioned packs from a `MockTransport`-served feed, license-gates
(never auto-arming ambiguous licenses) and checksum-verifies before caching, is reproducible from
pins, and the cached packs merge as a `feed` source (M1). Fully offline. Prior 348 tests green.

---

## Milestone 4 — Authoring guide doc + (optional) staged/approval seam + end-to-end integration

**Build**
- `docs/authoring-packs.md` (NEW, deliverable — spec §6 item 6): a written guide covering the
  `Attack` YAML schema and **every field** (`id` & the `category/stem` coherence rule, `name`,
  `category`, `owasp` `LLM01..LLM10`, `atlas` `AML.Tdddd[.ddd]`, `surface`, `severity`, `license` &
  the `ALLOWED_LICENSES` requirement, `version`, `payload`, `references`); the **`success_when`
  types** (`string` / `side-effect` / `mcp-assert` / `classifier` / `judge`) with a worked example
  each; **where to put the file** (bundled `src/gauntlet/packs/<category>/`, a user `pack_dirs`
  entry, or a feed); **how to validate** (`gauntlet list --packs` / `load_catalog` surfacing the
  PackError on bad license/coherence/assert); and the **feed manifest** format (§7.1) for pack
  publishers. Use a real, copy-pasteable example pack.
- **(Optional) staged/approval seam** (spec §9): wire `config.catalog.staged_dir` into M1's
  `load_catalog` as `source=STAGED, armed=False`; `gauntlet run` already filters `e.armed` (M1);
  add `gauntlet list --packs --staged` to show staged rows flagged. `tests/test_staged.py`: a
  staged pack is listed-not-armed and excluded from a run selection. (If the milestone budget is
  tight, drop this without touching the core.)
- **End-to-end integration test** (`tests/test_cli_catalog.py`): `gauntlet update` (MockTransport)
  → feed cache populated → `gauntlet list --packs` shows the feed pack tagged `[feed]` → a
  `run --dry-run` (or fake adapter) selects it → `gauntlet report` shows it under
  `by_owasp`/`by_atlas`. Plus CLI surface tests: `update` with no `feed_cache_dir` → exit 2 clear
  message; `list --packs` source column; `report` OWASP/ATLAS blocks.
- **[Fix #12 — guide content verifiability]** add a lightweight `tests/test_docs_authoring.py`
  asserting `docs/authoring-packs.md` exists and contains the required section headers (schema /
  every field, success_when types, license requirement, where to put the file, feed manifest
  format, validation command) — so the deliverable can't ship empty.

**Files**: `docs/authoring-packs.md`, `packloader.py`/`cli.py` (staged wiring, optional),
`tests/test_cli_catalog.py`, `tests/test_staged.py` (optional).

**Checkpoint**
```
ruff check .
ruff format --check .
pytest -q   # entire suite, offline (no keys/network/feed server)
```
Passing: the authoring guide documents adding an attack as pure YAML end-to-end; (optionally)
staged packs are listed-not-armed; the full update → cache → merge → run → report flow works
offline. The entire suite is green — the prior 348 tests (1 skipped) plus the new Phase-9 tests,
with only the enumerated additive contract updates. Satisfies spec §12 items 1–8.

---

## Plan review

1. **[CRITICAL] `cli.run` switching to `load_catalog` makes the existing `test_cli_run.py`/`test_cli_tui.py` `_patch_packs` monkeypatches inert.** Fixed (M1): single `_load_attacks(cfg)` patch point; update both test files to patch it; enumerated as contract updates.
2. **[HIGH] Path traversal on feed cache write.** Fixed (M3): `FeedPackEntry.category`/`id` pattern-validated at parse; cache path built from the VALIDATED `attack.category`/`attack.id`, never `entry.category`/url; traversal test.
3. **[HIGH] Runner error-path owasp/atlas threading unspecified.** Fixed (M2): `_perform_send` gains `owasp`/`atlas` kwargs; `_run_attempt` passes attack codes, `_run_control` passes None.
4. **Feed cache write not atomic.** Fixed (M3): temp + `os.replace`; interrupted-write test.
5. **`FeedUpdateResult` type unspecified.** Fixed (M3): Pydantic BaseModel, extra="forbid".
6. **Owned `httpx.AsyncClient` lifecycle.** Fixed (M3): `async with` for the owned path.
7. **Same-source cross-dir duplicate id unaddressed.** Fixed (M1): equal-rank duplicate → PackError even with allow_override; test.
8. **sha256 "case-insensitive" wording.** Fixed (M3): direct lowercase compare.
9. **`--feed NAME` no-match unspecified.** Fixed (M3): exit 2 clear message.
10. **`size` cap not enforced.** Fixed (M3): hard 1 MiB cap, refuse+count oversize; test.
11. **`load_config` path-resolution change buried.** Fixed (M1): listed explicitly + dedicated test.
12. **Authoring guide content not verified.** Fixed (M4): section-header test.

**Resolution:** the critical item (1), both HIGH items (2, 3), and the nine others (4–12) are
folded into the milestone build descriptions, test lists, and checkpoints above. Ready to
implement.

STATUS: PASS
