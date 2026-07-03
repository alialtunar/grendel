# Phase 17 — implementation plan

From `phases/phase-17/spec.md`. Three milestones, each ending in a verifiable checkpoint (`ruff`
clean + `pytest` green offline + `reviewer`/`tester` `STATUS: PASS`). No scoring/records/runner/proxy/
catalog engine behaviour changes; exit codes unchanged; no key/network in the suite.

---

## Milestone 1 — Landing & discovery (banner, auto-config, list filter, doctor)

**Steps**
1. **Banner completeness (gap 1).** In `banner.py`, add `config` + `doctor` to `COMMANDS`. Add a
   test that `{name for name,_ in COMMANDS}` equals the set of registered Typer command names
   (`{c.name for c in app.registered_commands}` incl. the callback-less commands), so the list can't
   drift. Keep the descriptions short.
2. **cwd `grendel.yaml` auto-discovery (gap 4).** In the callback `main`, when `config is None` and
   `os.environ.get("GRENDEL_NO_AUTOCONFIG")` is unset and `Path("grendel.yaml").is_file()`: load it
   and `typer.echo` a one-line "(using ./grendel.yaml)" note to stderr. **Test isolation:** set
   `GRENDEL_NO_AUTOCONFIG=1` in `tests/conftest.py` (autouse fixture / env) so the repo-root
   `grendel.yaml` never leaks into the existing suite. A dedicated `test_cli_autoconfig.py` unsets it
   in a tmp cwd to prove auto-load works, and asserts suppression works.
3. **`list` filter + counts (gap 5a).** `list` gains `--category TEXT` and `--source TEXT`; filter
   the pack rows; print `packs: N total` and keep the per-category grouping. Existing `list --packs`
   output stays a superset (tests that assert specific packs still pass).
4. **`grendel doctor` (gap 5b).** New `src/grendel/doctor.py` (pure): `build_doctor_report(cfg, *,
   env=None) -> str` — Install (version via importlib.metadata, guarded), Catalog (totals by
   category + by source via `list_packs(config=cfg)`), Env keys (each preset `api_key_env` → ✓/✗ from
   `env`, **never the value**), Targets, Proxy. A `doctor` CLI command prints it (colored in a TTY).
   Presence-only; deterministic (env injected for tests).
5. **Tests:** `test_banner.py` (config+doctor present; names match app), `test_cli_autoconfig.py`
   (auto-load in tmp cwd; suppressed under the flag), `test_cli_packs.py` (`--category` narrows +
   count line), `test_cli_doctor.py` (sections present; a set env key ✓ and its value absent).

**Checkpoint 1:** ruff clean; pytest green (prior + new); bare `grendel` lists all commands; `grendel
doctor` prints status; cwd grendel.yaml auto-loads (isolated). `reviewer` + `tester` → `STATUS: PASS`.

---

## Milestone 2 — Config editor completeness (selects + catalog editing)

**Steps**
1. **Selectable type + provider (gap 2).** In `_targets_questionary`, `provider` becomes
   `questionary.select(sorted(set(PRESETS) | set(cfg.providers)))` (type already a select). In
   `_targets_letter`, print the numbered valid providers and read a choice (an unknown value → inline
   error, not added). `_add_target` already validates via `with_cli_target` (unknown provider still
   rejected as a backstop).
2. **Editable catalog pack dirs (gap 3).** Pure helpers `_add_pack_dir(cfg, path)` (append a
   `Path` to `cfg.catalog.pack_dirs` if not already present) / `_remove_pack_dir(cfg, path)` (remove;
   `ConfigError` if absent). A new **catalog** entry in the config menu (both shells): list / add /
   remove pack dirs; saved on save (the whole config revalidates, unchanged).
3. **Tests (`test_cli_config.py`):** add a target selecting a valid provider via the letter fallback
   → saved YAML has it; an invalid provider choice → inline error, nothing added; add a catalog pack
   dir → saved `catalog.pack_dirs` contains it; remove it → gone; `_add_pack_dir`/`_remove_pack_dir`
   pure-helper edge cases (duplicate ignored, absent → ConfigError).

**Checkpoint 2:** ruff clean; pytest green; `grendel config` picks provider/type from lists and
add/removes catalog dirs, saved. `reviewer` + `tester` → `STATUS: PASS`.

---

## Milestone 3 — Usability sweep (flawless CLI) + hygiene, docs, and gating recent work

**Usability sweep (spec §0 — the primary bar; do this BEFORE the hygiene items):**
- Walk **every** command as a first-time user: `run` (incl. no-target, dry-run, real-ish), `list`
  (all flags + the new filters), `report`, `diff`, `proxy` (preview + serve help), `import` (auto +
  `--path`), `config` (every section), `doctor`, and bare `grendel`. For each: is the `--help` clear
  with a copy-paste example? Is every error actionable (says what to type next, no bare traceback/exit
  code)? Does success end with a colored "next: …" hint? Fix every friction found — not just the
  enumerated gaps.
- Make `<command> --help` examples consistent (add `epilog`/help text with a concrete example where
  missing). Ensure every "(none)" / limitation line names the command that fixes it.
- Add a **scripted first-run walkthrough test** (`test_cli_walkthrough.py`, offline, monkeypatched
  target/packs): a newcomer sequence `grendel` → `run --provider … --dry-run` → `config` (add target
  + catalog) → `import --limit` → `list --packs --category` → `doctor` → `report`, asserting each step
  exits 0 (or a clear 2) and prints a helpful next-step — so the smooth first-run can't regress.
- The M3 `reviewer` runs with the explicit lens "would a first-time user be confused or stuck at any
  step?" and must confirm no such spot remains (in addition to correctness).

**Hygiene / docs / gating:**

**Steps**
1. **gitignore the imported catalog (gap 6a).** Add `catalog/` to `.gitignore` (the ~1500 imported
   files incl. toxicity prompts are regenerated with one `grendel import`; not committed).
2. **Fast import test (gap 6b).** Rewrite the auto-import test to bound the run: `grendel import
   --source garak --out tmp --limit 5` (or drive `default_source_paths` and import a single small
   path) so it no longer pulls ~1500 each run; keep `importorskip("garak")`. Suite time returns to
   ~20-25s.
3. **garak optional dep (gap 6c).** `pyproject.toml`: `[project.optional-dependencies] corpora =
   ["garak"]`. `grendel import --source garak` (auto path) already errors clearly if garak is absent.
4. **README + docs (gap 6d).** Add `grendel config` (interactive, arrow-key), `grendel import`
   (auto-discovery + `--pack-dir`/`catalog.pack_dirs` wiring + `pip install -e ".[corpora]"`),
   `grendel doctor`, and a one-line scoring-tier caveat (open-corpus imports scored by the T2 lexical
   classifier by default; enable the T3 judge for nuance). Keep the authorized-use framing intact
   (its markers are asserted by `test_docs_readme`).
5. **PROGRESS.md.** Append a `phase 17: DONE …` entry (ROADMAP already lists 16/17).
6. **Gate the post-16 corpus changes (gap 7).** The `reviewer` at this checkpoint explicitly reviews
   `corpus.py` (garak all-sets `GARAK_CURATED`, line-vs-paragraph `.txt` handling, `_category_for`
   harmbench/toxicity, `default_source_paths`/`garak_data_dir`) and the `cli.py` `import` auto-loop —
   the changes that landed after phase 16's gates.

**Checkpoint 3 (phase close):** ruff clean; pytest green offline + **fast**; README/PROGRESS updated;
`catalog/` gitignored; garak documented. `reviewer` + `tester` → `STATUS: PASS`; `review.md` +
`test-report.md` end in `STATUS: PASS`; append `phase 17: DONE …` to `PROGRESS.md`.

---

## Risks & mitigations
- **Auto-config breaks the existing suite** (repo-root `grendel.yaml`). Mitigate: `conftest.py` sets
  `GRENDEL_NO_AUTOCONFIG=1` for the whole suite; a dedicated test exercises the auto-load path in a
  tmp cwd. Verify all prior tests stay green.
- **Banner-names-match-commands test is brittle** to Typer internals. Mitigate: derive the registered
  names defensively (handle `command.name` being None → use the function name) and assert set
  equality with a clear message.
- **questionary select paths are untestable (no PTY).** Mitigate: the letter-menu fallback exercises
  the same validation/save logic and IS tested (established precedent).
- **catalog.pack_dirs Path round-trip on save.** Mitigate: `save_config` uses `mode="json"` (Paths →
  strings) and `load_config` re-resolves relative catalog paths; a test round-trips an added pack dir.
- **Doctor catalog scan slow / errors on a huge catalog.** Mitigate: `build_doctor_report` counts via
  `list_packs` and guards exceptions (a broken catalog → an error row, never a crash), like the old
  doctor did.

---

## Plan review — resolutions (STATUS: REVISE → addressed)

The plan-reviewer flagged nine items; the four blocking fixes and their resolutions:
1. **Auto-config isolation must be module-level** (a live `grendel.yaml` + ~1500-file `catalog/`
   already sit at the repo root). Resolved: `tests/conftest.py` sets `os.environ["GRENDEL_NO_AUTOCONFIG"]
   = "1"` at import time (active during collection, for every module), not a per-test fixture.
   `test_cli_autoconfig.py` does `monkeypatch.delenv(..., raising=False)` **and** `monkeypatch.chdir`.
2. **`--no-config` must be a discoverable CLI flag** (§0 newcomer bar), not only an env var. Resolved:
   added `--no-config` on the root callback (shows in `grendel --help`); the env var is kept solely as
   the test-isolation mechanism.
3. **`catalog.pack_dirs` save is relative→absolute, not a clean round-trip.** Acknowledged as existing
   behavior (`load_config` resolves relative catalog paths to absolute): the M2 catalog-add test asserts
   against the **resolved absolute** path; documented in the README ("saved paths become absolute").
4. **doctor/list-filter tests use a minimal catalog**, not the repo-root one: tests build `cfg` from
   `GrendelConfig()` (bundled-only, ~21 packs) or a tiny tmp pack dir — fast + isolated.
Non-blocking items also folded in: `--source`/`--category` reject an unknown value with a nudge listing
the valid set (no silent-empty dead-end); the M1 checkpoint locks the command count at **9**
(run/list/report/diff/proxy/import/update/config/doctor); the M3 walkthrough exercises the non-TTY
letter-menu path (questionary arrow-key paths stay offline-untested, per precedent); M3 verifies
`git status` shows `catalog/` untracked (never accidentally added).
