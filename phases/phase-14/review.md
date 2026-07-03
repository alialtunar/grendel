# Phase 14 Review — open-corpus import (`grendel import`)

Scope reviewed: `src/grendel/corpus.py` (new), `src/grendel/cli.py` (`import` command),
`tests/test_corpus_import.py`, `tests/test_cli_import.py`, `tests/fixtures/garak/*`, and the
phase-14 doc/ROADMAP touch-points, against `phases/phase-14/{spec,plan}.md`.

## Verification performed

1. Ran `python -m ruff check .` and `python -m ruff format --check .` — both clean.
2. Ran the full suite: `507 passed, 1 skipped` (prior 489 + 1 skipped + 18 new corpus/CLI tests).
3. Traced the id/coherence chain by hand against `packloader.py`:
   - `Attack.id` pattern `^[a-z0-9-]+/[a-z0-9-]+$`; `to_attack` builds
     `f"{entry.category}/{_slugify(entry.source_name)}-{h}"` where `category` ∈
     `{jailbreak, dan}`, `_slugify` guarantees `[a-z0-9-]+` (empty → `"import"`, verified via
     `_slugify("")`/`_slugify("...")` → `"import"`), and `h` is 8 lowercase hex chars — the
     id can never contain `..` or an extra `/`.
   - Write path `out_dir/attack.category/f"{stem}.yaml"` with `stem = attack.id.split("/",1)[1]`
     reproduces exactly the `expected_id = f"{attack.category}/{path.stem}"` check in
     `packloader._check_coherence`, and `attack.category` (written into the dumped YAML)
     always equals the parent directory name — verified end-to-end via
     `test_import_converts_and_writes_loadable_packs` (`load_packs(out)` succeeds, 5/5).
   - `model_dump(by_alias=True, mode="json")` confirmed to emit plain scalars: read a written
     fixture output file and independently confirmed `"surface: prompt"` / `"severity: medium"`
     appear as scalars (also asserted by `test_written_yaml_has_scalar_enums`).
4. Confirmed `to_attack` wraps `ValidationError` as `PackError`
   (`tests/test_corpus_import.py::test_invalid_entry_raises_packerror_after_earlier_writes`), and
   that the CLI's `except PackError: exit 2` branch is exercised (via the unknown-source path,
   `test_import_cli_unknown_source_exit_2`). Manually confirmed (via a scratch `CliRunner`
   invocation) that malformed/empty prompts never reach `to_attack` through the real
   `GarakSource` (`.txt`/`.json` readers already skip empty/whitespace-only text), so a
   CLI-level "conversion error → exit 2" case is not reachable through the shipped source and its
   absence from `test_cli_import.py` is not a functional gap — see item 1 below for the residual
   documentation nit.
5. Dedup ordering: read `import_entries` — dedup check (`h in existing or h in seen_hashes`)
   runs strictly before the license-gate check, confirmed by
   `test_dedup_runs_before_license_gate`. `--limit` breaks immediately after the Nth write with
   `seen`/`duplicate`/`license_skipped` reflecting only entries processed up to the stop
   (`test_limit_stops_after_n_and_reports_counts`). `--dry-run` performs the full pipeline but
   skips `_atomic_write` (`test_dry_run_writes_nothing_but_reports`).
6. `_payload_hashes` swallows `ValueError`/`yaml.YAMLError`/`OSError` only (best-effort scan of a
   possibly-dirty `out_dir`) — matches the spec's "malformed existing files are ignored" mitigation.
7. Re-ran the CLI end-to-end fixture import twice via a scratch script and via
   `test_rerun_is_idempotent` / `test_imported_dir_loads_via_pack_dir`: second run → `imported=0`,
   and the imported dir loads through a real `run --pack-dir --dry-run` invocation, listing
   `dan/dan-*` in the plan.
8. Checked `ROADMAP.md` §8 phase-14 entry — the diff added matches spec's framing verbatim
   (no drift).
9. Confirmed no new runtime dependency (only `pyyaml`, `hashlib`, `json`, `re`, `os` — all
   already used/stdlib) and no touch to `scoring.py`/`records.py`/`runner.py`/`proxy.py`/
   `packloader.py` (`git diff` shows those files untouched by this phase).

## Findings

1. **(Non-blocking, documentation nit)** The plan's Milestone-2 test list calls for a
   `test_cli_import.py` case covering "a corpus that converts to an invalid Attack → exit 2"
   (reviewer item 2 in the plan). That test is not present. In practice it is not reachable via
   the shipped `GarakSource` (both the `.txt` paragraph splitter and the `.json` reader already
   drop empty/whitespace-only entries before they ever reach `to_attack`, and every other
   `Attack` field is fixed/valid by construction), so the scenario can only be exercised by
   feeding a hand-built `RawEntry` directly to `import_entries` — which
   `test_corpus_import.py::test_invalid_entry_raises_packerror_after_earlier_writes` already does,
   and the CLI's generic `except PackError: exit 2` wrapping is independently proven by the
   unknown-source CLI test. Functionally there is no gap; only the plan's specific test
   enumeration wasn't literally satisfied. Suggest either dropping that line from the plan's
   test list or adding a one-line comment in `test_cli_import.py` noting why it's not
   separately covered, so a future reader doesn't go looking for it.
2. **(Non-blocking, optional)** No mention of `grendel import` was added to
   `docs/authoring-packs.md` or `README.md`. The plan explicitly permits skipping this ("only
   touch docs if an existing doc test requires the new command; otherwise skip to avoid scope
   creep") and no doc test broke, so this is acceptable as shipped, but since this is the final
   phase of the roadmap, a short discoverability note (one command block) would help users find
   the feature.

No correctness, security, path-traversal, license-gating, dedup-ordering, or schema-validity
issues found. `ruff` and the full test suite (507 passed, 1 skipped) are clean and match the
phase-14 acceptance criteria; the corpus engine and CLI match the spec/plan in every load-bearing
detail (id pattern, coherence check, enum-scalar YAML dump, dedup-before-license ordering,
`--limit`/`--dry-run` semantics, path-safety, offline/no-network/no-`garak`-install operation, and
`--pack-dir` consumability).

STATUS: PASS
