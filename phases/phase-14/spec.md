# Phase 14 — Open-corpus import (catalog enrichment): spec

> Phase 14 of 14 — **the final phase.** Implements ROADMAP §8.14: *"Open-corpus import — catalog
> enrichment — one terminal command that pulls attacks from public red-team corpora (garak first,
> Apache-2.0: ~666 in-the-wild + 14 DAN ≈ ~680), converts each to a validated `Attack` YAML,
> license-gates + de-duplicates, writes them into a catalog dir. Re-runnable/incremental (only new
> payloads added). (Proven feasible: real garak jailbreaks converted + loaded through the real
> packloader.)"*
>
> **The deliverable:** `grendel import --source garak --path <garak-corpus> --out <catalog-dir>` — a
> re-runnable command that reads a public red-team corpus (garak's Apache-2.0 in-the-wild jailbreak +
> DAN prompt lists) from a local path, **converts each prompt to a schema-valid `Attack` YAML**
> (validated by the real `Attack` model), **license-gates** (only allow-listed licenses are written),
> **de-duplicates** by normalized payload (against the target catalog dir *and* within the run so the
> import is **incremental** — a second run adds nothing), and writes each as
> `<out>/<category>/<id>.yaml` (path-traversal-safe). The written packs load cleanly through the
> existing `packloader` (`load_packs`) — the proof the pipeline produces real, armable attacks. The
> new catalog dir is consumable by `run`/`list` via Phase-12's `--pack-dir` (or `catalog.pack_dirs`).
>
> **Offline + deterministic.** The garak *source* is a pluggable connector that reads from a **local
> path** (a garak data dir/file the user supplies — or a small bundled test fixture in the same
> format); no network, no requirement that the `garak` package be installed. Conversion is pure and
> hash-deterministic. No new runtime dependency. Scoring/records/config/runner/proxy are untouched;
> the prior **489** tests (1 skipped) stay green.

---

## 1. Goals

1. **One import command.** `grendel import --source garak --path PATH --out DIR [--limit N]
   [--dry-run] [--allow-unlisted-licenses]` reads a corpus from `PATH`, converts + gates + dedupes,
   and writes new `Attack` YAML packs under `DIR`. Prints a summary (seen / imported / duplicate /
   license-skipped).
2. **Garak source connector (pluggable).** A `garak` source that reads garak's Apache-2.0 prompt
   corpora from a local path: `.txt` files (one prompt per paragraph, blank-line separated — the
   in-the-wild / DAN format) and `.json` files (a list of strings or `{"prompt": …}` objects).
   Category is inferred from the filename (`dan*` → `dan`; else `jailbreak`). The source registry is
   keyed by name so future corpora slot in without changing the command.
3. **Convert to a validated `Attack`.** Each raw prompt becomes a schema-valid `Attack`: a
   deterministic `id = <category>/<slug>-<8hex>` (slug from the source file, `8hex` from the payload
   hash — both matching the `id` pattern), `name`, `category` (`jailbreak`/`dan`), `owasp: LLM01`,
   `atlas: AML.T0054`, `surface: prompt`, `severity: medium`, `license` (from the source, default
   `Apache-2.0`), `version: 1`, `payload` (the prompt verbatim), `success_when` a **classifier**
   check (`classifier: lexical, label: attack_succeeded` — an open jailbreak has no planted canary,
   so T2 refusal/harm classification is the right scorer), and a `references` link to garak.
4. **License-gate.** Only licenses in `ALLOWED_LICENSES` (Apache-2.0/MIT/BSD/CC0) are written;
   others are skipped (counted) unless `--allow-unlisted-licenses`. Garak is Apache-2.0 → written.
5. **De-duplicate + incremental.** Dedup by a normalized-payload hash against (a) the existing packs
   already in `--out` (loaded/scanned at start) and (b) prompts already emitted this run. A re-run
   over the same corpus writes **0** new packs (idempotent enrichment). `--limit N` caps the number
   of *new* packs written.
6. **Proven-valid output.** The written YAMLs load through the real `packloader.load_packs(out_dir)`
   without error (a test asserts this), and the dir is usable as a `--pack-dir` catalog source.
7. Everything `pytest`-testable, **offline + deterministic** (a bundled garak-format fixture; no
   network, no `garak` install). Prior 489 tests (1 skipped) stay green.

---

## 2. Scope

**In scope**
- `src/grendel/corpus.py` (NEW):
  - `RawEntry` (a small dataclass: `text`, `category`, `source_name`, `license`).
  - `GarakSource.read(path: Path) -> Iterator[RawEntry]` — walk `path` (a file or dir) for
    `.txt`/`.json`, extract prompts, infer category from filename, tag `license="Apache-2.0"`,
    `source_name` from the file stem. Skips empty prompts; deterministic ordering (sorted files,
    file order within).
  - `SOURCES: dict[str, Source]` registry (`{"garak": GarakSource()}`); `get_source(name)` → raises
    a clear error on unknown source.
  - `to_attack(entry: RawEntry, *, seq: int) -> Attack` — pure conversion to a validated `Attack`
    (raises the model's `ValidationError`/our error on a bad entry; deterministic id).
  - `_norm_hash(payload: str) -> str` — normalized (strip/collapse-whitespace/casefold) sha256 for
    dedup; `_payload_hashes(dir) -> set[str]` — hashes of payloads already in the out dir.
  - `import_corpus(source_name, src_path, out_dir, *, limit=None, allow_unlisted_licenses=False,
    dry_run=False) -> ImportResult` — the pipeline: read → convert → license-gate → dedup
    (existing + in-run) → write `<out>/<category>/<id>.yaml` (atomic; path-safe: category/id come
    from the *validated* Attack, both pattern-constrained). `ImportResult` carries `seen`,
    `imported`, `duplicate`, `license_skipped`, and the list of written relative paths.
- `src/grendel/cli.py` (EXTEND): a new `import` command (function `import_` — `import` is a keyword)
  wiring the flags → `import_corpus`, printing the summary. Unknown source / missing path → exit 2.
- Tests: `tests/test_corpus_import.py` (garak fixture → converts/writes valid packs that
  `load_packs` accepts; dedup/incremental re-run → 0 new; license gate; `--limit`; `--dry-run` writes
  nothing; path-safety of ids), `tests/test_cli_import.py` (the `import` CLI surface + exit codes).
  A tiny garak-format fixture under `tests/fixtures/garak/`.

**Out of scope (deferred / non-goals)**
- **Bundling the full ~680-prompt garak corpus into the repo.** The importer *reads* garak's data
  from a user-supplied `--path` (documented: point at a checked-out garak data dir); the repo ships
  only a small representative fixture for tests. (Vendoring the whole corpus is a data-distribution
  decision, not this phase's mechanism.)
- **Network fetching / auto-download of garak.** The source reads a **local** path. A remote fetch
  is the Phase-9 `feed`/`update` mechanism's job; this phase is a local corpus converter. (No httpx,
  no `garak` import.)
- **The full ingest pipeline's embedding-dedup / auto-classify / human-approval staging** (ROADMAP
  §4 "Discover" tier). This phase does **exact/normalized** payload dedup + a fixed category/OWASP
  mapping; semantic dedup and LLM auto-classification are future. Imported packs are written **armed**
  into a catalog dir (not `staged/`), since garak is a curated, license-clean source.
- **Other corpora (HarmBench/AdvBench/JailbreakBench connectors).** The registry is built to accept
  them; only `garak` ships here ("garak first").
- **Modifying scoring/records/config/runner/proxy.** Import is a pure catalog producer; nothing
  downstream changes. The classifier `success_when` reuses the existing Phase-4 T2 path.

---

## 3. Garak source format (what `GarakSource.read` accepts)

Garak ships prompt corpora as plain lists. The connector accepts, from a file or a directory tree:
- **`.txt`** — prompts separated by blank lines (a paragraph = one prompt); leading/trailing
  whitespace stripped; empty paragraphs skipped. (Single-line-per-prompt files are the degenerate
  case — each non-empty line a prompt when no blank-line separation exists is handled by treating the
  whole file as blank-line-delimited paragraphs.)
- **`.json`** — a top-level list of strings, or a list of objects with a `"prompt"` (or `"text"`)
  key. Non-string/empty entries skipped.
- **Category inference:** filename stem starting `dan` (case-insensitive) → category `dan`; anything
  else → `jailbreak`. (Both are valid `category` patterns; both map to OWASP `LLM01` / ATLAS
  `AML.T0054`.)
- **License:** garak corpora are Apache-2.0 → every `RawEntry.license = "Apache-2.0"`.

The test fixture mirrors this exactly (a `dan.txt`, an `inthewild.txt`, and a `prompts.json`).

---

## 4. Conversion → `Attack` (deterministic, schema-valid)

`to_attack(entry, seq)`:
- `payload = entry.text` (verbatim; validated non-empty by the model).
- `h = sha256(_norm(payload))[:8]` (lowercase hex → matches the id pattern).
- `slug = _slugify(entry.source_name)` (lowercase, non-`[a-z0-9]`→`-`, collapse/trim dashes; empty →
  `"import"`).
- `id = f"{entry.category}/{slug}-{h}"` — both segments match `^[a-z0-9-]+$` (category is
  `jailbreak`/`dan`; the slug is sanitized; `h` is hex) → **path-traversal-safe by construction**.
- `name = f"garak {entry.category} import {h}"`; `owasp="LLM01"`, `atlas="AML.T0054"`,
  `surface="prompt"`, `severity="medium"`, `license=entry.license`, `version=1`.
- `success_when = {"type": "classifier", "classifier": "lexical", "label": "attack_succeeded",
  "threshold": 0.5}` — T2 refusal/harm classification (no planted canary in an open jailbreak).
- `references = ["https://github.com/NVIDIA/garak"]`.
- Returns an `Attack` (constructed via the model, so any schema violation raises before a file is
  written). The YAML is `yaml.safe_dump(attack.model_dump(by_alias=True, mode="json"), sort_keys=
  False)` — **`mode="json"` is required** so enum fields (`surface`/`severity`) serialize to their
  string values (a plain `model_dump` leaves enum objects that `yaml.safe_dump` cannot represent).
  Verified to round-trip through `load_packs` (classifier `success_when` validates; `id ==
  category/stem` so the loader's path/id check passes).

Two identical payloads → the **same id** (same hash) → dedup catches them (and the id-collision is
consistent, never a traversal).

---

## 5. Dedup + incremental + writing

- **Existing hashes:** at start, `_payload_hashes(out_dir)` scans `out_dir/*/*.yaml` (if present),
  parses each `payload`, and collects `_norm_hash`. (Malformed existing files are ignored for the
  hash set — the import doesn't fail because the dir has unrelated content; the final `load_packs`
  proof runs on the freshly-written set in tests.)
- **In-run dedup:** a `set` of hashes seen this run; a prompt whose hash is already in
  existing∪in-run is a `duplicate` (counted, not written).
- **License gate:** `entry.license not in ALLOWED_LICENSES and not allow_unlisted_licenses` →
  `license_skipped` (counted, not written).
- **Write:** `dest = out_dir/attack.category/f"{stem}.yaml"` where `stem = attack.id.split('/',1)[1]`
  (from the *validated* Attack), created with `mkdir(parents=True)` + an atomic write (tmp + replace,
  mirroring Phase-9 `_atomic_write_bytes`). `--dry-run` performs read/convert/gate/dedup but writes
  nothing (counts still reported). `--limit N` stops after `N` new packs are written.
- **Incremental:** re-running over the same corpus finds every hash already present → `imported=0`.

`ImportResult` (a small dataclass / BaseModel): `seen`, `imported`, `duplicate`, `license_skipped`,
`written: list[str]` (relative paths). The CLI prints a one-line summary + the written count.

---

## 6. CLI

```
grendel import --source garak --path PATH --out DIR [--limit N] [--dry-run]
               [--allow-unlisted-licenses]
```
- `--source` unknown → exit 2 (naming known sources). `--path` missing → exit 2. `--out` is created
  if absent.
- Prints: `[dry-run] imported N (seen S, duplicate D, license-skipped L) -> DIR` and, unless
  dry-run, that the packs are loadable via `--pack-dir DIR`.
- Exit 0 on success; exit 2 on a usage error (unknown source, missing path, or a conversion error
  surfaced as a clear message).

---

## 7. Deliberate contract updates (enumerated)

1. **New `grendel import` command** — purely additive.
2. **New module `src/grendel/corpus.py`** — the source registry + converter + `import_corpus`. New
   code only; reuses `Attack`/`ALLOWED_LICENSES`/`load_packs`.
3. **A small `tests/fixtures/garak/` corpus fixture** — test data only.
4. No change to scoring/records/config/runner/proxy/packloader behaviour. The written packs are
   ordinary `Attack` YAMLs the existing loader already understands (Phase-12 `--pack-dir` /
   `catalog.pack_dirs` consume the new dir). No new runtime dependency (`pyyaml` already a dep).

---

## 8. Testing strategy (offline + deterministic)

- **Conversion + write** (`test_corpus_import.py`): run `import_corpus("garak", fixture_dir,
  tmp_out)` → assert the written count matches the fixture's distinct prompts; every written file is
  a valid `Attack` (assert `load_packs(tmp_out)` returns them, ids match the pattern, category ∈
  {jailbreak,dan}, `success_when.type == "classifier"`); ids are path-safe (no `..`, no separators
  beyond the single `/`). Determinism: two imports into two dirs → identical ids for identical
  payloads.
- **Dedup / incremental** (`test_corpus_import.py`): a second `import_corpus` into the same
  `tmp_out` → `imported == 0`, `duplicate == seen`; a fixture containing an exact-duplicate prompt
  (and a whitespace-only variant) → counted once.
- **License gate** (`test_corpus_import.py`): a `RawEntry`/fixture with a non-allowlisted license →
  `license_skipped`, not written, unless `allow_unlisted_licenses=True`.
- **`--limit` / `--dry-run`** (`test_corpus_import.py`): `limit=1` writes exactly one; `dry_run=True`
  writes zero files but reports the would-import counts.
- **CLI** (`test_cli_import.py`): `import --source garak --path FIX --out DIR` exit 0 + summary +
  files on disk; unknown `--source` → exit 2; missing `--path` → exit 2; the written dir works as
  `run --pack-dir DIR --dry-run` (loads the imported packs).
- **No behaviour drift:** the prior 489 tests (1 skipped) stay green; only the additive §7 items. No
  network, no `garak` install, no API keys.

---

## 9. Acceptance criteria

Phase 14 (the final phase) is done when:
1. `ruff check .` + `ruff format --check .` clean; `pytest` green **offline, no keys/network/garak**;
   the prior 489 tests (1 skipped) pass plus the new corpus/CLI import tests.
2. **One import command:** `grendel import --source garak --path PATH --out DIR` converts a garak
   corpus to schema-valid `Attack` YAMLs, license-gates, de-duplicates, and writes them under `DIR`;
   the written packs **load through the real `packloader`** and are usable via `--pack-dir`.
3. **Incremental / re-runnable:** a second run over the same corpus writes 0 new packs; `--limit`
   and `--dry-run` behave as specified; dedup is by normalized payload.
4. **License-clean + path-safe:** only allow-listed licenses are written (garak = Apache-2.0);
   every generated id is pattern-constrained so the write path can never traverse.
5. Everything offline + deterministic; no new dependency; scoring/records/config/runner/proxy
   unchanged. **This completes the ROADMAP (phases 1–14).**
