# Phase 9 — Plugin system + open catalog + feeds (user packs · remote feed · OWASP/ATLAS in reports · authoring guide): spec

> Phase 9 of 10. Implements ROADMAP §8.9: *"Plugin system + open catalog + feeds — Make
> the catalog first-class: load user-authored packs from a directory, pull packs from a
> remote feed, and surface OWASP/ATLAS mappings in every report. Documented authoring guide
> so the community (and the user) can add attacks as pure data."* It builds **directly on the
> existing catalog machinery**: `packloader.load_packs` (the per-directory loader with its
> license-gate / coherence / assert-parse validation), `PackInfo`/`list_packs`, the `Attack`
> model (`owasp`/`atlas` fields already present), `RunRecord.metrics_summary` /
> `asr_by_category` (the ASR machinery), and the Phase-1 `httpx.MockTransport` offline-test
> pattern. Phase 9 **extends, not reinvents**: a new **multi-source catalog loader**
> (`load_catalog`) merges the bundled packs with user pack directories and a remote-feed cache,
> tagging each entry with its **source** (bundled/user/feed) and dedup-gating across sources;
> a new **`gauntlet update`** command pulls versioned packs from a remote **feed manifest** over
> `httpx` (license-gated + checksum-verified, fully offline-testable via `MockTransport`); the
> report and `list --packs` gain **OWASP/ATLAS breakdowns**; and a written **authoring guide**
> (`docs/authoring-packs.md`) documents adding an attack as pure YAML.
>
> **Catalog growth, not engine change.** This is the ROADMAP §4 "catalog grows without code
> changes" promise made real: **Vendored** (bundled, Phase 2/7/8) + **Feed** (remote pull, this
> phase) + a **minimal staged/approval** seam toward **Discover** (optional). License hygiene
> (ROADMAP §2/§4) is preserved at every source: the cross-source loader and the feed updater
> both run the same `ALLOWED_LICENSES` gate, and the feed **never auto-arms an ambiguous
> license** (§4 invariant).
>
> **Additive and default-safe.** `load_packs` (single-dir) is untouched; `load_catalog` with no
> configured user dirs and no feed cache returns **exactly** the bundled set — so existing
> `run`/`list`/scoring behavior is byte-identical out of the box. The prior **348** tests (1
> skipped) stay green; the only deliberate contract refinements are enumerated in §10 and the
> plan (the `list --packs` row gains a source tag; `AttemptRecord` gains additive
> `owasp`/`atlas` fields default `None`; `GauntletConfig` gains an additive default `catalog`
> block). Everything offline, deterministic, no new heavy deps (`httpx` is already a dependency).

---

## 1. Goals

1. **Multi-source catalog loader.** A new `load_catalog(config, *, allow_unlisted_licenses=False)`
   that loads the **bundled** packs plus every configured **user pack directory** plus the
   **feed cache directory**, runs the *same* per-file validation (license-gate + coherence +
   assert-parse) on **every** source, and merges them into one catalog with a defined
   cross-source dedup/precedence rule (§5). Each entry is tagged with its **source**
   (`bundled` / `user` / `feed`). `load_packs` (single-dir) stays as the leaf primitive
   `load_catalog` calls per source.
2. **Source tagging surfaced everywhere it matters.** `PackInfo` gains a `source: Source`
   field; `gauntlet list --packs` shows the source per row; the report and run path consume the
   merged catalog. A `CatalogEntry` (attack + source + path) is the unit the loader returns.
3. **Config additions for extra pack dirs + feed sources (additive).** A new `CatalogConfig`
   (`pack_dirs`, `feed_cache_dir`, `feeds`, `allow_override`, `allow_unlisted_licenses`) hung off
   `GauntletConfig.catalog`, defaulting to **empty** (bundled-only, unchanged behavior).
4. **Remote feed + `gauntlet update`.** A precisely-specified **feed manifest schema**
   (`FeedManifest` / `FeedPackEntry`) and a `gauntlet update` command that, per configured feed:
   fetches the manifest over `httpx`, **license-gates** each pack against `ALLOWED_LICENSES`
   (skip/refuse unlisted unless opted in — **never auto-arm** an ambiguous license),
   **verifies a SHA-256 checksum**, validates the pack content (same loader validation), and
   writes the YAML into the **feed cache dir** (which the §1.1 loader then merges as a `feed`
   source). It reports counts (pulled / updated / unchanged / skipped-for-license /
   checksum-failed). **Reproducible**: pinned pack versions + checksums → same manifest yields
   the same cache. **Fully offline-testable** by injecting an `httpx.AsyncClient` backed by
   `httpx.MockTransport`, exactly like the Phase-1 HTTP adapter tests.
5. **OWASP/ATLAS in every report.** `AttemptRecord` gains additive `owasp`/`atlas` fields (the
   runner populates them from the `Attack`, alongside `category`); `metrics_summary` gains
   `by_owasp` and `by_atlas` breakdowns (counts + ASR per code, reusing the existing `_asr`
   machinery); `gauntlet report` prints both breakdowns; `gauntlet list --packs` already shows
   each attack's `owasp`/`atlas` and now also its source.
6. **Authoring guide (deliverable artifact).** `docs/authoring-packs.md` — a real, written guide
   on adding an attack as pure YAML: the schema and every field, the `success_when` types, the
   license requirement, where to put the file (bundled vs user dir vs feed), and how to validate
   it with the loader (`gauntlet list --packs` / `load_catalog`).
7. **Minimal staged/approval seam (optional).** A `staged/` convention (config `staged_dir`) for
   feed/discovered candidates that require human approval before they arm: staged packs are
   **listed but never run** (loaded as `source=staged`, `armed=False`, excluded from `run`
   selection) until a human moves the file into a real pack dir. Kept minimal; the core is local
   packs + feed + reports + docs.
8. Everything `pytest`-testable, **offline and deterministic** (no network, no API keys, no real
   feed server). The prior **348** tests (1 skipped) stay green; the only contract updates are
   the additive ones enumerated in §10 and the plan.

---

## 2. Scope

**In scope**
- `src/gauntlet/packloader.py` (EXTEND): `Source` enum (`bundled`/`user`/`feed`/`staged`),
  `CatalogEntry` (`attack`, `source`, `path`), `load_catalog(config, *,
  allow_unlisted_licenses=False) -> list[CatalogEntry]` (merges bundled + user dirs + feed cache;
  cross-source dedup/precedence per §5; per-source validation reuses `load_packs`); `PackInfo`
  gains `source: Source`; `list_packs` gains an optional `config` arg to project the merged
  catalog with sources.
- `src/gauntlet/config.py` (EXTEND, additive): `FeedSource` (`name`, `url`), `CatalogConfig`
  (`pack_dirs`, `feed_cache_dir`, `feeds`, `allow_override`, `allow_unlisted_licenses`,
  `staged_dir`), `GauntletConfig.catalog: CatalogConfig = CatalogConfig()`.
- `src/gauntlet/feed.py` (NEW): `FeedPackEntry`, `FeedManifest` (Pydantic, `extra="forbid"`),
  `FeedUpdateResult` (a structured report), and `async def update_feeds(config, *, client=None,
  allow_unlisted_licenses=False) -> FeedUpdateResult` (the fetch → license-gate → checksum →
  validate → cache pipeline; takes an injectable `httpx.AsyncClient` for offline tests).
- `src/gauntlet/records.py` (EXTEND, additive): `AttemptRecord.owasp: str | None = None` and
  `AttemptRecord.atlas: str | None = None`; `metrics_summary` gains `by_owasp` / `by_atlas`;
  new `asr_by_owasp()` / `asr_by_atlas()` helpers mirroring `asr_by_category()`.
- `src/gauntlet/runner.py` (EXTEND): populate `owasp=attack.owasp`, `atlas=attack.atlas` on the
  scored `AttemptRecord` (and thread them through the error path for completeness).
- `src/gauntlet/cli.py` (EXTEND): new `gauntlet update` command; `run`/`list --packs` consume the
  merged catalog (`load_catalog`) and show the source column; `report` prints the OWASP/ATLAS
  breakdowns.
- `docs/authoring-packs.md` (NEW, deliverable): the authoring guide.
- Tests: multi-source loader (tmp-dir user packs + feed cache, dedup/precedence, source tags),
  config additions, the feed updater end-to-end via `httpx.MockTransport` (license-gate +
  checksum verify/mismatch + cache write + reproducibility), OWASP/ATLAS breakdowns, the
  `update`/`list`/`report` CLI surfaces, and the (optional) staged seam.

**Out of scope (explicitly deferred)**
- **The "Discover" living-sources pipeline** (arXiv/GitHub/HF auto-discovery, embedding-similarity
  dedup, auto-classification, auto-drafted `success_when`) — ROADMAP §4's most speculative tier.
  Phase 9 ships only the **minimal staged/approval seam** (§9) it would eventually feed; no
  network discovery, no ML.
- **A real hosted feed server / a published community feed** — Phase 9 defines the manifest
  schema and the *client* (`gauntlet update`); the suite uses a `MockTransport`-served fake feed.
  Authoring/operating a real feed repo is post-MVP (Phase 10 / community).
- **Signing / GPG / TUF-style trust** — checksum (SHA-256) integrity only. Cryptographic feed
  signing is noted as a future hardening, not built here.
- **New OWASP/ATLAS taxonomy work or auto-classification** — reuse the `owasp`/`atlas` fields the
  `Attack` model already carries and validates; the report just *aggregates* them.
- **Changing `load_packs`' single-dir contract** — it stays the leaf primitive; all multi-source
  behavior is new code in `load_catalog`.

---

## 3. Module layout

```
src/gauntlet/
├── packloader.py     # EXTEND: Source enum, CatalogEntry, load_catalog(); PackInfo.source; list_packs(config=)
├── config.py         # EXTEND: FeedSource, CatalogConfig; GauntletConfig.catalog (additive)
├── feed.py           # NEW: FeedPackEntry, FeedManifest, FeedUpdateResult, update_feeds() (httpx, offline-injectable)
├── records.py        # EXTEND: AttemptRecord.owasp/atlas (additive); by_owasp/by_atlas in metrics_summary; asr_by_owasp/atlas
├── runner.py         # EXTEND: populate owasp/atlas on AttemptRecord
└── cli.py            # EXTEND: `gauntlet update`; run/list --packs use load_catalog + source; report prints owasp/atlas
docs/
└── authoring-packs.md  # NEW: the written authoring guide (deliverable artifact)
tests/
├── test_catalog_loader.py   # M1: bundled+user+feed merge, dedup/precedence, source tags, license-gate per source
├── test_config.py           # M1: CatalogConfig additive cases (extend existing)
├── test_metrics_owasp.py    # M2: by_owasp/by_atlas breakdowns; asr_by_owasp/atlas; report output
├── test_feed_update.py      # M3: update_feeds via MockTransport — license-gate, checksum verify/mismatch, cache, reproducibility
├── test_cli_catalog.py      # M4: `gauntlet update` CLI; list --packs source column; report owasp/atlas; end-to-end
└── test_staged.py           # M4 (optional): staged packs listed-not-armed
```

---

## 4. The Attack data contract (unchanged) and source tagging

Phase 9 does **not** change the `Attack` schema (ROADMAP §4) — `owasp` (`LLM01..LLM10`) and
`atlas` (`AML.Tdddd[.ddd]`) are already required, validated fields. What is new is **where an
attack can come from** and the **source tag** the loader attaches:

```python
class Source(str, Enum):
    BUNDLED = "bundled"   # shipped in src/gauntlet/packs (Vendored tier)
    USER = "user"         # a config-listed user pack directory (Plugin/local tier)
    FEED = "feed"         # pulled by `gauntlet update` into the feed cache (Feed tier)
    STAGED = "staged"     # awaiting human approval — listed, NOT armed (optional §9)

class CatalogEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    attack: Attack
    source: Source
    path: Path
    armed: bool = True    # False only for STAGED (excluded from run selection)
```

`load_catalog` returns `list[CatalogEntry]` sorted by `attack.id`. The runner/`run` path uses
`[e.attack for e in load_catalog(cfg) if e.armed]`; `list --packs` shows `source` per row.

---

## 5. The multi-source catalog loader (`load_catalog`)

### 5.1 Sources, in precedence order

`load_catalog(config, *, allow_unlisted_licenses=False)` loads, in this fixed order:

1. **Bundled** — `default_packs_dir()` → `source=BUNDLED`.
2. **User dirs** — each path in `config.catalog.pack_dirs`, in listed order → `source=USER`.
3. **Feed cache** — `config.catalog.feed_cache_dir` (if set and a directory) → `source=FEED`.
4. **Staged** *(optional §9)* — `config.catalog.staged_dir` (if set) → `source=STAGED`,
   `armed=False`.

Each source directory is loaded with the **existing** `load_packs(dir,
allow_unlisted_licenses=...)` primitive, so **every** source gets the identical validation:
license-gate (`ALLOWED_LICENSES`), path/id coherence, side-effect/mcp assert-parse, single-doc
YAML, schema validation — all raising `PackError` naming the file. **A missing/absent configured
dir is not an error** (a user who hasn't created `./packs` yet, or hasn't run `gauntlet update`
yet, simply contributes zero packs); only a path that exists-but-is-malformed raises.
`allow_unlisted_licenses` (CLI flag or `config.catalog.allow_unlisted_licenses`) applies uniformly
to all sources.

### 5.2 Cross-source dedup / precedence rule (decided + justified)

**Default: a duplicate `id` across sources is a `PackError`** naming both paths and both sources
— mirroring the existing *in-directory* rule (`load_packs` already raises "duplicate attack id …
in A and B"). **Justification:** silently letting a `user`/`feed` pack shadow a vendored,
license-clean, reproducible attack is a supply-chain and reproducibility hazard (ROADMAP §2 "clean
licensing", §4 "reproducible by construction"). Failing loud forces the conflict to be resolved
deliberately.

**Opt-in override:** `config.catalog.allow_override = true` flips the duplicate to a **precedence
win** instead of an error, with the order **user > feed > bundled** (most-local wins — the user
deliberately patching/replacing a bundled or feed attack). The winning entry keeps its own source
tag; the shadowed one is dropped. Precedence is computed by source rank, then is **deterministic**
regardless of filesystem ordering. (Within a *single* directory a duplicate id is still always an
error — unchanged.)

### 5.3 What stays identical

With `config.catalog` at its default (empty `pack_dirs`, `feed_cache_dir=None`, no feeds),
`load_catalog(cfg)` returns the **same** attacks as `load_packs(default_packs_dir())` — same ids,
same order — each tagged `source=BUNDLED`. So `run` and scoring are byte-identical to Phase 8 out
of the box; the 21 bundled attacks and their tests are unaffected.

---

## 6. Config additions (`config.py`, additive)

```python
class FeedSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str                      # logical feed name (shown in `update` output)
    url: str                       # URL of the feed manifest (JSON or YAML)

class CatalogConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pack_dirs: list[Path] = []                 # extra user pack directories (USER source)
    feed_cache_dir: Path | None = None         # where `gauntlet update` writes pulled packs (FEED source)
    feeds: list[FeedSource] = []               # remote feed manifests to pull
    staged_dir: Path | None = None             # optional: staged-for-approval packs (§9)
    allow_override: bool = False               # cross-source dup id -> precedence vs error (§5.2)
    allow_unlisted_licenses: bool = False      # gate override applied to ALL sources + the feed

class GauntletConfig(BaseModel):
    ...
    catalog: CatalogConfig = CatalogConfig()   # ADDITIVE — default empty == bundled-only
```

- **Default is empty** → unchanged behavior, deterministic config snapshot (no machine-specific
  home paths injected). The recommended conventions `~/.gauntlet/packs` (user) and `./packs`
  (project) and `~/.gauntlet/feed-cache` are **documented in the authoring guide**, not
  auto-scanned — explicit config keeps runs reproducible and tests deterministic.
- `feed_cache_dir` defaulting to `None` means **`gauntlet update` errors with a clear message
  ("no catalog.feed_cache_dir configured") until the user sets it** — no surprise writes to the
  home directory.
- Validation: `FeedSource.url`/`name` non-empty; relative `pack_dirs`/`feed_cache_dir` resolved
  against the config-file directory (or cwd when config is `None`) so paths are stable.

---

## 7. The feed manifest schema + `gauntlet update` flow

### 7.1 Feed manifest schema (precise)

A feed is a single **manifest** document (JSON or YAML — parsed the same way) at `FeedSource.url`,
listing the packs the feed offers with pinned versions + checksums + licenses:

```yaml
# feed manifest (served at FeedSource.url)
feed: gauntlet-community           # str: feed identifier (must match nothing; informational)
manifest_version: 1                # int >= 1: manifest schema version (this phase understands 1)
generated_at: "2026-06-01T00:00:00Z"   # optional str (informational)
packs:
  - id: prompt-injection/new-trick-07     # str: must match the Attack.id pattern AND the pack content
    category: prompt-injection            # str: must match Attack.category and the cache subdir
    version: 2                            # int >= 1: pack content version (pin; drives "updated vs unchanged")
    license: Apache-2.0                   # str: license-gated against ALLOWED_LICENSES BEFORE download
    sha256: "9f86d0818...e8b2"            # str: lowercase hex SHA-256 of the pack YAML bytes
    url: "https://feed.test/packs/prompt-injection/new-trick-07.yaml"  # str: absolute, or relative to the manifest URL
    size: 1234                            # optional int (informational / sanity bound)
```

Pydantic models (`feed.py`, `extra="forbid"`):

```python
class FeedPackEntry(BaseModel):
    id: str                # validated against the Attack id pattern
    category: str
    version: int = Field(ge=1)
    license: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    url: str
    size: int | None = None

class FeedManifest(BaseModel):
    feed: str
    manifest_version: int = Field(ge=1)
    generated_at: str | None = None
    packs: list[FeedPackEntry] = []
```

An unknown `manifest_version` (> the one this build understands) is a clear `FeedError`
("unsupported manifest_version N; this gauntlet understands up to M") rather than a silent
misparse.

### 7.2 `gauntlet update` flow (fetch → license-gate → checksum → validate → cache → report)

`async def update_feeds(config, *, client=None, allow_unlisted_licenses=False) -> FeedUpdateResult`

For each `FeedSource` in `config.catalog.feeds` (or a single `--feed NAME`):

1. **Fetch manifest.** `GET FeedSource.url` via the injected `httpx.AsyncClient` (created with a
   real transport in production, a `MockTransport` in tests). Non-2xx → record a per-feed error,
   continue. Parse JSON/YAML → `FeedManifest.model_validate` (malformed → per-feed error).
2. **Per pack entry, in order:**
   1. **License gate (BEFORE download).** If `entry.license not in ALLOWED_LICENSES` and not
      `allow_unlisted_licenses` → **skip**, increment `skipped_license`, record the id+license.
      *This is the §4 invariant: the feed never auto-arms an ambiguous license.* Nothing is even
      downloaded for a refused license.
   2. **Resolve URL** (`entry.url` absolute, or joined against the manifest URL) and **download
      the pack bytes** (`GET`). Non-2xx → record an error for that entry, continue.
   3. **Checksum verify.** `hashlib.sha256(bytes).hexdigest() == entry.sha256` (case-insensitive)?
      No → **refuse**, increment `checksum_failed`, record the id (never written to cache).
   4. **Validate content.** Parse the YAML as an `Attack` (the same single-doc + schema +
      assert-parse validation as the loader) and check the content **coheres with the manifest
      claim**: `attack.id == entry.id`, `attack.category == entry.category`,
      `attack.license == entry.license`, `attack.version == entry.version`. Any mismatch → record
      an error, skip (the feed lied about what it served).
   5. **Cache write.** Write the bytes to
      `feed_cache_dir/<entry.category>/<stem>.yaml` (stem from the id), creating dirs. If a file
      with the same id already exists at the same `version` **and** same sha256 → **unchanged**
      (idempotent, no rewrite); a higher/different version → **updated**; new id → **pulled**.
3. **Report.** Return a `FeedUpdateResult` with totals + per-feed detail:
   `pulled`, `updated`, `unchanged`, `skipped_license`, `checksum_failed`, `errors`, and a list of
   `(feed, id, action, reason)` rows. The CLI prints a human summary; `--dry-run` runs steps 1–4
   (fetch + gate + checksum + validate) but **does not write** the cache.

**Reproducibility.** Pinned `version` + `sha256` mean the same manifest always produces the same
cache contents; re-running `update` on an unchanged manifest reports all `unchanged` and rewrites
nothing. The feed cache is then a normal `FEED` source for `load_catalog` (§5).

**`feed_cache_dir` not configured** → `gauntlet update` exits 2 with a clear message (no implicit
home-dir write).

### 7.3 Errors

`feed.py` defines `FeedError(GauntletError)` (in `errors.py`, alongside `PackError`) for manifest
parse / unsupported-version / unreachable-feed failures surfaced to the CLI as exit 2. Per-entry
problems (checksum, content mismatch, non-2xx pack download) are **collected into the result**
(not raised) so one bad pack doesn't abort the whole pull — the summary lists every skip/refusal.

---

## 8. OWASP/ATLAS in reports (`records.py` + `cli.py`)

### 8.1 The data seam — additive `AttemptRecord` fields

`metrics_summary` aggregates over `AttemptRecord`s, and `gauntlet report` loads **only** a
`RunRecord` JSON (no catalog at hand). So the OWASP/ATLAS codes must live **on the record**:

```python
class AttemptRecord(BaseModel):
    ...
    owasp: str | None = None    # ADDITIVE — populated by the runner from Attack.owasp
    atlas: str | None = None    # ADDITIVE — populated by the runner from Attack.atlas
```

Additive (default `None`): old run records deserialize unchanged; controls and error-path
attempts may carry `None`. The runner (§2) sets `owasp=attack.owasp, atlas=attack.atlas` on the
scored attempt (mirroring how `category` is already threaded).

### 8.2 The breakdown helpers + `metrics_summary`

Mirror the existing `asr_by_category` / `by_category` machinery exactly (reuse `_asr`, exclude
controls, exclude the reserved `control` category):

```python
def asr_by_owasp(self) -> dict[str, float]: ...   # group non-control attempts by owasp (None -> "unmapped")
def asr_by_atlas(self) -> dict[str, float]: ...    # group by atlas
```

`metrics_summary` gains two blocks, each `{code: {"asr", "scored", "succeeded"}}`:

```python
"by_owasp": { "LLM01": {"asr": 0.5, "scored": 4, "succeeded": 2}, ... },
"by_atlas": { "AML.T0051": {"asr": 0.33, "scored": 3, "succeeded": 1}, ... },
```

Attempts whose `owasp`/`atlas` is `None` (legacy records) group under `"unmapped"`; new runs
always carry codes (the fields are required on `Attack`). Controls are excluded (same as
`by_category`). This is **purely additive** to the dict — existing keys (`overall_asr`,
`by_category`, `controls`, …) are unchanged, so the `report --format json` consumers keep working.

### 8.3 CLI surfacing

- **`gauntlet report`** (text): after the existing "by category" block, print:
  ```
    by OWASP:
      LLM01: ASR 50.00% (succeeded 2/4)
      LLM06: ASR 0.00% (succeeded 0/3)
    by ATLAS:
      AML.T0051: ASR 33.33% (succeeded 1/3)
  ```
  `report --format json` already emits `metrics_summary()`, so `by_owasp`/`by_atlas` appear there
  automatically (additive — no key removed).
- **`gauntlet list --packs`** already prints each attack's `owasp` + `atlas`; Phase 9 adds the
  **source** tag to the row (e.g. trailing `[bundled]` / `[user]` / `[feed]`). This is the one
  `list --packs` output change (§10).

---

## 9. Minimal staged / approval seam (optional)

Toward ROADMAP §4's **Discover** tier (which "never auto-arms the catalog" — a human approves each
staged pack first), Phase 9 ships only the **landing zone**, no discovery pipeline:

- `config.catalog.staged_dir` — a directory of candidate packs (e.g. produced by a future
  Discover connector, or hand-dropped). `gauntlet update --stage` would write
  *unverified-but-license-clean* candidates here instead of the armed feed cache (kept minimal —
  the default `update` writes the armed cache).
- `load_catalog` loads `staged_dir` as `source=STAGED, armed=False`. **Staged packs are listed**
  (`gauntlet list --packs --staged` shows them, flagged) **but never selected for a `run`** (the
  run path filters `e.armed`).
- **Arming = a human moving the file** out of `staged/` into a real pack dir (then it loads as
  `user`/`feed` and runs). No automatic promotion.

If this does not land cleanly within the milestone budget it is **dropped without affecting the
core** (local packs + feed + reports + docs); the spec treats it as optional.

---

## 10. Deliberate contract updates (enumerated)

All additive; each is called out so the corresponding test is updated as a *deliberate* change:

1. **`AttemptRecord.owasp` / `.atlas`** — new optional fields default `None`. A test asserting the
   exact set of `AttemptRecord` fields or a serialized attempt JSON gains these two keys
   (default-`None` round-trips). No behavior change for existing records.
2. **`GauntletConfig.catalog`** — new field default `CatalogConfig()` (all-empty). Config
   round-trip / snapshot tests now include a `catalog` block (deterministic, no machine paths).
3. **`metrics_summary` gains `by_owasp` / `by_atlas`** — additive keys; tests asserting the exact
   key set of the metrics dict gain these two. `report --format json` output gains them.
4. **`gauntlet list --packs` row gains a source tag** — the bundled-pack list test that asserts
   exact `list` output (`test_cli` / `test_bundled_packs`) is updated to expect the `[bundled]`
   tag on the 21 bundled rows. The **counts are unchanged** (21 bundled attacks; Phase 9 adds no
   bundled packs).
5. **`PackInfo` gains `source`** — `list_packs` rows now carry a `source`; a test constructing or
   asserting `PackInfo` fields gains it (default/derived `BUNDLED` for the bundled dir).

No existing public function signature is removed; `load_packs` is untouched.

---

## 11. Testing strategy (offline + deterministic)

- **Multi-source loader** (`test_catalog_loader.py`): write attack YAMLs into tmp **user** and
  **feed-cache** dirs (valid coherent ids) + point a `GauntletConfig.catalog` at them →
  `load_catalog` returns bundled + user + feed entries with correct `source` tags, sorted by id;
  a **cross-source duplicate id** → `PackError` naming both paths/sources by default, and a
  **precedence win** (user > feed > bundled) when `allow_override=True`; an **unlisted-license**
  pack in a user dir → `PackError` unless `allow_unlisted_licenses`; an **absent** configured
  `pack_dir`/`feed_cache_dir` contributes zero (no error); default empty `catalog` →
  `load_catalog` == `load_packs(default_packs_dir())` (same 21 ids).
- **Config** (`test_config.py`, extend): `CatalogConfig` round-trips; `feeds`/`pack_dirs` parse;
  relative paths resolve against the config dir; default `catalog` is empty.
- **OWASP/ATLAS metrics** (`test_metrics_owasp.py`): a synthetic `RunRecord` with attempts
  carrying `owasp`/`atlas` → `by_owasp`/`by_atlas` give correct ASR/scored/succeeded per code;
  controls excluded; `None`-coded legacy attempts group as `"unmapped"`; existing
  `metrics_summary` keys unchanged.
- **Feed updater** (`test_feed_update.py`): an `httpx.MockTransport` handler serves a manifest +
  pack bytes (compute the real `sha256` in the fixture). Assert: a clean Apache-2.0 pack is
  pulled and written to the feed cache (then loadable by `load_catalog`); a **checksum mismatch**
  pack is refused (not written, `checksum_failed` counted); an **unlisted-license** pack is
  skipped **without being downloaded** (handler asserts its pack URL was never requested),
  unless `allow_unlisted_licenses`; a **content/manifest mismatch** (served id ≠ manifest id) is
  rejected; **`--dry-run` writes nothing**; re-running on the same manifest reports all
  `unchanged` and rewrites nothing (**reproducibility**); a non-2xx manifest → per-feed error,
  other feeds still processed; **no real network** (transport is mocked; a guard asserts the
  client used is the injected one).
- **CLI** (`test_cli_catalog.py`): `gauntlet update` against a `MockTransport`-injected client
  prints the summary and exit 0; `update` with no `feed_cache_dir` → exit 2 with the clear
  message; `list --packs` shows the source tag; `report` prints the OWASP/ATLAS blocks; an
  **end-to-end**: update → feed cache populated → `load_catalog` merges the feed pack → `run`
  (dry-run / fake adapter) selects it → `report` shows it under `by_owasp`/`by_atlas` with
  `source=feed` visible in `list`.
- **Staged (optional)** (`test_staged.py`): a `staged_dir` pack loads as `STAGED`/`armed=False`,
  appears in `list --packs --staged`, and is **excluded** from a `run` selection.
- **No network, no API keys, no real feed server, no real side effects anywhere.** The prior
  **348** tests (1 skipped) stay green except the enumerated §10 additive updates.

---

## 12. Acceptance criteria

A reviewer can confirm Phase 9 is done when:

1. `ruff check .` and `ruff format --check .` pass with zero findings; `pytest` is green
   **offline with no API keys / network / real feed server**; the prior **348** tests (1 skipped)
   pass, with only the additive §10 contract updates.
2. `load_catalog(config)` merges **bundled + user dirs + feed cache** into one catalog, running the
   existing license-gate + coherence + assert-parse validation on **every** source, tagging each
   `CatalogEntry` with its `source`; with the default empty `catalog` it returns exactly the
   bundled 21 attacks (unchanged), and `load_packs` is untouched.
3. The cross-source dedup rule holds: a duplicate id across sources is a `PackError` naming both
   paths/sources by default, or a deterministic precedence win (user > feed > bundled) when
   `catalog.allow_override` is set; in-directory duplicates still always error.
4. `GauntletConfig.catalog` (`pack_dirs`, `feed_cache_dir`, `feeds`, `allow_override`,
   `allow_unlisted_licenses`, `staged_dir`) is additive and defaults to empty (bundled-only).
5. The feed manifest schema (`FeedManifest`/`FeedPackEntry`) is precisely defined and validated;
   `gauntlet update` fetches the manifest over `httpx`, **license-gates each pack against
   `ALLOWED_LICENSES` before download** (never auto-arming an ambiguous license),
   **verifies the SHA-256 checksum**, validates pack content against the manifest claim, writes
   verified packs into the feed cache, and reports
   pulled/updated/unchanged/skipped-license/checksum-failed — all **offline-testable via
   `httpx.MockTransport`**, reproducible from pinned versions + checksums.
6. Every report surfaces OWASP/ATLAS: `AttemptRecord` carries `owasp`/`atlas`; `metrics_summary`
   has additive `by_owasp`/`by_atlas` breakdowns (ASR + counts per code, controls excluded);
   `gauntlet report` prints both; `gauntlet list --packs` shows owasp/atlas **and** the source.
7. `docs/authoring-packs.md` exists and documents adding an attack as pure YAML — the schema,
   every field, the `success_when` types, the license requirement, where to put the file
   (bundled / user dir / feed), and how to validate with the loader.
8. (If included) the staged seam loads `staged_dir` packs as `STAGED`/`armed=False` — listed but
   never run — and is otherwise inert; if dropped, the core (local packs + feed + reports + docs)
   is unaffected.
