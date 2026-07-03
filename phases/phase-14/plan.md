# Phase 14 — implementation plan

Derived from `phases/phase-14/spec.md`. Two milestones, each ending in a verifiable checkpoint
(`ruff` clean + `pytest` green + `reviewer`/`tester` `STATUS: PASS`). Milestone 1 is the corpus
engine (garak source + convert + `import_corpus`, tested against a bundled fixture and the real
`load_packs`); Milestone 2 is the `grendel import` CLI + end-to-end. **No scoring/records/config/
runner/proxy/packloader behaviour changes** — the importer produces ordinary `Attack` YAMLs.

---

## Milestone 1 — Corpus engine (`corpus.py`): garak source → validated Attack YAML

**Intent:** read a garak corpus from a local path, convert each prompt to a schema-valid `Attack`,
license-gate, dedup (existing + in-run), and write path-safe YAMLs — all pure/offline, proven by
loading the output through the real `packloader`.

**Steps**
1. **`corpus.py` — data types + helpers:**
   - `@dataclass(frozen=True) class RawEntry`: `text: str`, `category: str`, `source_name: str`,
     `license: str`.
   - `class ImportResult(BaseModel)` (`extra="forbid"`): `seen`, `imported`, `duplicate`,
     `license_skipped` (ints), `written: list[str]`.
   - `_norm(payload) -> str`: strip + collapse internal whitespace + casefold.
   - `_norm_hash(payload) -> str`: `sha256(_norm(payload).encode()).hexdigest()`.
   - `_slugify(name) -> str`: lowercase, `[^a-z0-9]+`→`-`, strip/collapse dashes; `""` → `"import"`.
2. **`corpus.py` — garak source:**
   - `class GarakSource` with `read(path: Path) -> Iterator[RawEntry]`: if `path` is a file, read it;
     if a dir, walk `sorted(path.rglob("*"))` for `.txt`/`.json`. `.txt` → split on blank lines into
     paragraphs (`re.split(r"\n\s*\n")`), strip, skip empties. `.json` → `json.loads`; accept a list
     of strings or of dicts with `prompt`/`text`. Category from the file stem (`dan*`→`dan` else
     `jailbreak`); `license="Apache-2.0"`; `source_name=stem`. Deterministic order.
   - `SOURCES = {"garak": GarakSource()}`; `get_source(name)` → the source or raise `PackError`
     (unknown source, naming known ones).
3. **`corpus.py` — conversion:**
   - `to_attack(entry, *, seq) -> Attack`: build id `f"{entry.category}/{_slugify(entry.source_name)}
     -{_norm_hash(entry.text)[:8]}"`; construct the `Attack` (owasp LLM01, atlas AML.T0054, surface
     prompt, severity medium, license entry.license, version 1, payload=text, success_when the
     classifier check, references garak). **Wrap pydantic `ValidationError` as `PackError`**
     (`raise PackError(f"invalid converted attack from {entry.source_name!r}: {exc}")`) — mirrors
     `packloader._parse_and_validate`, so the CLI's exit-2-on-conversion-error contract holds
     (reviewer item 2). (`seq` available for a tie-break; the hash-based id is the primary key.)
   - **YAML dump uses `attack.model_dump(by_alias=True, mode="json")`** — `mode="json"` is REQUIRED
     so `surface`/`severity` enums serialize to plain scalars (a plain `model_dump` leaves enum
     objects that `yaml.safe_dump` cannot represent → `RepresenterError`; reviewer item 1).
4. **`corpus.py` — pipeline (split for testability):**
   - `import_entries(entries: Iterable[RawEntry], out_dir, *, limit=None,
     allow_unlisted_licenses=False, dry_run=False) -> ImportResult` — the core, so tests can feed
     hand-built `RawEntry`s (bad license, duplicates, an invalid entry) without going through a
     source. `import_corpus(source_name, src_path, out_dir, **kw)` = `get_source(source_name)` +
     `import_entries(src.read(src_path), out_dir, **kw)`.
   - `existing = _payload_hashes(out_dir)` (scan `out_dir/*/*.yaml` for `payload`, hash; ignore
     unparseable files); `seen_hashes = set()`.
   - For each `entry`: `seen += 1`; `h = _norm_hash(entry.text)`; **dedup FIRST** — `if h in existing
     or h in seen_hashes` → `duplicate += 1`, continue (a duplicate-AND-bad-license entry counts as a
     duplicate; reviewer item 4, dedup-first, cheaper); then license — `if entry.license not in
     ALLOWED_LICENSES and not allow_unlisted_licenses` → `license_skipped += 1`, continue; then
     `attack = to_attack(entry, seq=imported)` (may raise `PackError` → propagates, aborting the run
     after any earlier atomic writes — the incremental design converges on re-run; reviewer item 5);
     `seen_hashes.add(h)`; unless `dry_run`, atomic-write `out_dir/attack.category/f"{stem}.yaml"`;
     `imported += 1`; record the rel path; **`--limit`: `if limit is not None and imported == limit:
     break`** (stop the whole run — `seen`/`duplicate`/`license_skipped` reflect entries processed up
     to the stop; reviewer item 3, break-after-N-writes, pinned + tested).
   - Return `ImportResult(...)`. **Path-safety:** category+stem come from the pattern-validated
     `Attack`, so the join can never traverse.
5. **`_payload_hashes(out_dir)`** and a small `_atomic_write(dest, text)` (tmp + `os.replace`),
   mirroring Phase-9's atomic-write.
6. **Fixture:** `tests/fixtures/garak/` — `dan.txt` (2 DAN-style paragraphs), `inthewild.txt`
   (2 jailbreak paragraphs incl. one whitespace-variant duplicate of another), `prompts.json`
   (a list mixing strings + `{"prompt": …}`), for deterministic counts.
7. **Tests** (`test_corpus_import.py`):
   - convert+write via `import_corpus("garak", fixture, out)`: count matches distinct prompts;
     `load_packs(out)` accepts the output; ids pattern-safe; `success_when.type == "classifier"`;
     **the raw written YAML text contains `surface: prompt` / `severity: medium` as plain scalars**
     (regression guard for the `mode="json"` dump; reviewer item 1).
   - dedup/incremental: re-run → `imported == 0`, `duplicate == seen`; whitespace-variant duplicate
     collapses to one; two genuinely different prompts stay two.
   - license gate via `import_entries` with hand-built `RawEntry`s: a bad-license entry →
     `license_skipped` (not written) unless `allow_unlisted_licenses=True`; a **duplicate-AND-bad-
     license** entry → counted as `duplicate` (dedup-first ordering; reviewer item 4).
   - `--limit`: `limit=1` over a multi-prompt fixture → `imported == 1` and assert
     `seen`/`duplicate`/`license_skipped` reflect entries processed up to the stop (semantics pinned;
     reviewer item 3). `dry_run=True` → zero files written, counts still reported.
   - conversion error: `import_entries` with an invalid `RawEntry` (empty/whitespace text) → raises
     `PackError` after any earlier good writes; a re-run with the bad entry removed adds only the
     remainder, no duplicates (partial-failure convergence; reviewer item 5).
   - determinism: same payload → same id across two out dirs.

**Checkpoint 1:**
- `ruff` clean; `pytest` green: prior 489 (1 skipped) + `test_corpus_import.py`.
- `import_corpus("garak", fixture, out)` writes valid packs that `load_packs(out)` loads; re-run is a
  no-op; license/limit/dry-run correct.
- `reviewer` + `tester` → `STATUS: PASS`.

---

## Milestone 2 — `grendel import` CLI + end-to-end

**Intent:** expose the engine as a terminal command and prove the output feeds `run`/`list` via
`--pack-dir`.

**Steps**
1. **`cli.py` — `import` command** (function `import_`, `@app.command(name="import")`):
   options `--source` (default `garak`), `--path PATH` (required), `--out DIR` (required), `--limit
   INT`, `--dry-run`, `--allow-unlisted-licenses`. Validate `--path` exists (else exit 2). Call
   `corpus.import_corpus(...)` inside `try/except PackError → exit 2` (covers unknown source). Print
   `"[dry-run] " if dry_run else "" + f"imported {r.imported} (seen {r.seen}, duplicate
   {r.duplicate}, license-skipped {r.license_skipped}) -> {out}"`; unless dry-run, add a hint that
   the dir is usable via `--pack-dir`.
2. **Tests** (`test_cli_import.py`): `import --source garak --path FIX --out DIR` → exit 0, summary
   substring, files on disk; unknown `--source` → exit 2; missing `--path` → exit 2; a corpus that
   converts to an invalid Attack → exit 2 with a clear message (not a traceback; the
   `PackError`-wrapped conversion error, reviewer item 2); `run --pack-dir DIR --provider openai
   --model m --dry-run` (real catalog load of the imported dir via a real `--pack-dir`) lists the
   imported packs in the plan.
3. **Docs (light):** a short note in `docs/authoring-packs.md` (or README) that `grendel import`
   enriches a catalog dir from garak — additive prose; update the doc marker test if it asserts a
   command list. (Keep minimal; only if an existing doc test needs it — otherwise skip to avoid
   scope creep.)

**Checkpoint 2 (phase close):**
- `ruff` clean; `pytest` green: 489 prior (1 skipped) + corpus + CLI import tests; deterministic;
  offline (fixture, no garak install, no network).
- `grendel import` converts + gates + dedupes + writes; the dir loads via `--pack-dir`; incremental
  re-run adds nothing.
- `reviewer` + `tester` → `STATUS: PASS`; `review.md` + `test-report.md` end in `STATUS: PASS`.
- After both PASS: append `phase 14: DONE …` and a fresh `ALL PHASES COMPLETE` line to `PROGRESS.md`.

---

## Risks & mitigations
- **Generated id violates the `Attack.id` pattern (write fails / traversal).** Mitigate: `_slugify`
  guarantees `[a-z0-9-]+`, the hash is hex, category is `jailbreak`/`dan`; `to_attack` constructs the
  `Attack` (pattern-validated) BEFORE any write, and the write path is derived from the validated
  id — a test asserts every written id matches the pattern and the file lands under `out/<category>/`.
- **Dedup misses near-duplicates / over-merges.** Mitigate: normalized-hash (strip/collapse-ws/
  casefold) is exact-after-normalization by design (semantic dedup is an explicit non-goal §2); a
  test covers a whitespace-variant duplicate collapsing to one and two genuinely different prompts
  staying two.
- **A garak `.txt` with no blank-line separation yields one giant prompt.** Mitigate: documented that
  paragraphs are blank-line-delimited; the fixture uses blank-line separation (garak's actual
  format). Single-prompt files still import as one attack (valid).
- **Existing out-dir has unrelated/broken YAML → import crashes on the hash scan.** Mitigate:
  `_payload_hashes` ignores files it can't parse (best-effort hash set); import never fails because
  of pre-existing dir content; the `load_packs` validity proof runs on the freshly-written packs.
- **`import` is a Python keyword.** Mitigate: the function is `import_`, registered via
  `@app.command(name="import")`; a CLI test invokes `["import", …]`.
- **Doc-test coupling.** Mitigate: only touch docs if an existing doc test requires the new command;
  otherwise leave docs to avoid unrelated churn.
