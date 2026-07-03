# Phase 17 — Completeness & UX polish: spec

> A close-the-gaps phase. grendel is a pure inline CLI (banner + interactive `grendel config`, no
> TUI) with 1500+ attacks in the catalog after the garak import. Real friction points remain for a
> newcomer. This phase fixes **every detected gap** so the tool is discoverable and complete, keeps
> the **488→current offline suite green**, and adds nothing that needs a key/network in the suite.
>
> **Detected gaps (all fixed here):**
> 1. **Banner missing `config`** — bare `grendel` lists run/list/report/diff/proxy/import/update but
>    NOT `config`. The command list must be complete (and stay in sync with the real commands).
> 2. **Provider/type not selectable** — `grendel config` → targets → add asks provider (and could ask
>    type) as **free text**; they must be **arrow-key selects** from the known providers / valid
>    types (with the letter-menu fallback listing valid choices).
> 3. **Catalog not editable from `config`** — you can't add/remove a **catalog pack directory** from
>    the menu, so the imported 1500-attack catalog can only be wired by hand-editing YAML.
> 4. **No cwd `grendel.yaml` auto-discovery** — `grendel list`/`run` with no `-c` show only the 21
>    bundled attacks even when a `grendel.yaml` sits in the working directory; the user must pass
>    `-c grendel.yaml` every time.
> 5. **No catalog filtering / status view** — `grendel list --packs` dumps all 1500+; there is no
>    `--category` filter, and no `grendel doctor`/status command (version, catalog counts, env keys,
>    targets) — the useful "welcome/status" view lost when the TUI was removed.
> 6. **Hygiene / docs** — the imported `catalog/` (~1500 files incl. toxicity prompts) isn't
>    gitignored; the garak auto-import test really pulls ~1500 each run (slow ~70s); `garak` isn't
>    documented as the optional dep `grendel import --source garak` needs; README doesn't cover
>    `config`/`import`/catalog/the scoring-tier caveat; PROGRESS/ROADMAP need the phase-16/17 entries.
> 7. **Un-gated recent work** — the post-phase-16 corpus/import changes (garak all-sets, line-`.txt`
>    handling, auto-discovery) landed after phase 16's gates; this phase's `reviewer` covers them.
>
> **Additive + safe.** No scoring/records/runner/proxy/catalog *engine* behaviour changes; exit codes
> unchanged; no new runtime dep (questionary already present; garak stays optional/example-only). The
> prior offline suite stays green; new offline unit tests cover each fix.

---

## 0. Overriding goal — the CLI must be FLAWLESSLY easy to use

The enumerated gaps below are a floor, **not the ceiling**. The real bar for this phase is: **the CLI
usage experience must be flawless — effortless for a complete newcomer and delightful for a power
user.** A person who has never seen grendel must, with zero docs, be able to: discover what it does,
run their first attack, read the result, configure a target, and grow the catalog — **without ever
feeling stuck, confused, or having to guess.**

Do **not** stop at the listed items. Perform a **usability sweep of every command and every
interactive flow** and fix *anything* that is friction — as if a first-time user were watching:
- Every command's `--help` is clear, with a copy-pasteable example.
- Every error message says exactly what to type next (never a bare traceback, a terse exit code, or a
  dead end); wrong input is caught with a helpful nudge, not a crash.
- Every success ends with a colored, human "next: …" hint; ✓-green / ✗-red used consistently.
- Interactive `grendel config` is obvious: labelled sections, arrow-key selects for anything with a
  fixed set of choices (provider, type, yes/no), sensible pre-filled defaults, and a visible way back
  / to save / to quit at every step.
- Discovery is trivial: bare `grendel` (banner) and `grendel doctor` tell you where you are and what
  to do next; long lists (1500+ packs) are filterable, not a wall of text.
- No dead ends: every place that shows "(none)" or a limitation also shows the one command that fixes
  it.

The **test of done** is a scripted first-run walkthrough (`run` → `report` → `config` → `import` →
`list`) that a newcomer could follow blind, plus a review pass whose explicit lens is "would a
first-time user ever be confused or stuck here?". If any flow is merely *adequate*, it is a defect to
fix — this phase is not done while the CLI UX is anything short of excellent.

## 1. Goals

1. **Complete, in-sync landing.** The bare-`grendel` banner lists **every** subcommand including
   `config` and `doctor`; the command list is derived so it can't drift from the real commands.
2. **Selectable provider + type + editable catalog in `grendel config`.** Adding a target picks
   `type` and `provider` from arrow-key lists (letter fallback lists the valid values); a new
   **catalog** section lets you **add/remove pack directories** (persisted to the YAML), so the
   imported catalog is wired from the menu.
3. **cwd `grendel.yaml` auto-discovery.** With no `-c` and no explicit config, if `./grendel.yaml`
   exists it is loaded automatically (so `grendel list --packs` / `run` see the configured catalog).
   A `--no-config` / env escape hatch and safe test isolation (the suite must not accidentally pick up
   a repo-root `grendel.yaml`).
4. **Catalog filtering + a status view.** `grendel list --packs [--category CAT] [--source SRC]` and
   a per-category count summary; a new `grendel doctor` prints an inline status report (version,
   catalog totals by category/source, provider env-keys present ✓/✗ — never values, configured
   targets, proxy) — the pure `doctor_report` idea, reborn as a plain CLI command.
5. **Hygiene + docs.** `.gitignore` the imported `catalog/`; make the garak auto-import test fast
   (bounded via `--limit`); document `garak` as an optional dep + the scoring-tier caveat; refresh
   README (config/import/catalog/doctor) and PROGRESS/ROADMAP.
6. Everything `pytest`-testable **offline** (no key/network in the suite); the prior suite stays green.

---

## 2. Scope

**In scope**
- `src/grendel/banner.py`: derive the banner command list from the actual Typer commands (or a single
  maintained list asserted against `app`), including `config` + `doctor`.
- `src/grendel/cli.py`:
  - `config` targets-add: `type` + `provider` as `questionary.select` (arrow-key) / letter-menu with
    an explicit valid-choice list; provider choices = `PRESETS` ∪ `cfg.providers`.
  - `config` new **catalog** section: list / add / remove `catalog.pack_dirs` entries, saved on save.
  - cwd `grendel.yaml` auto-discovery in the callback (only when no `-c`, guarded so tests don't pick
    up a stray file — e.g. honour an env flag the test harness sets, or only auto-load when running
    interactively / not under pytest).
  - `list`: `--category` and `--source` filters + a total/by-category count line.
  - new `doctor` command (a pure `build_doctor_report(cfg, env) -> str` in a small module, printed
    inline; env injected for tests, presence-only).
- `tests/`: extend `test_cli_config.py` (select-provider add via letter fallback; catalog add/remove),
  `test_banner.py` (banner lists config + doctor, matches the real command set), `test_cli.py`/new
  `test_cli_doctor.py` (doctor output; no secret), `test_cli_import.py` (fast bounded auto-import),
  a config-auto-discovery test.
- `.gitignore` (catalog/), `README.md`, `pyproject.toml` (a documented `[project.optional-dependencies]
  corpora = ["garak"]` extra), `PROGRESS.md`, `ROADMAP.md`.

**Out of scope (non-goals)**
- Re-introducing any full-screen TUI. Everything stays inline CLI.
- Changing scoring/records/runner/proxy/catalog engine behaviour, or exit codes.
- Bundling the imported `catalog/` into the package, or committing toxicity content (it is
  gitignored; the user regenerates it with one `grendel import`).
- A new judge/classifier — the scoring-tier caveat is *documented*, not changed.
- Editing every config field from the menu (custom providers / feeds stay file-only).

---

## 3. Details per gap

### 3.1 Banner completeness (gap 1)
`banner.py` should list every command. Implement as a `COMMANDS` list that a test asserts equals the
set of registered Typer command names (minus none), so a future command can't be forgotten. Add
`config` ("edit configuration interactively") and `doctor` ("status & diagnostics").

### 3.2 Selectable provider/type + editable catalog (gaps 2, 3)
- Add-target: `type` via `questionary.select(["http","python","agent"])`; `provider` via
  `questionary.select(sorted(PRESETS ∪ cfg.providers))`. Letter fallback: print the numbered/keyed
  valid choices and read a selection (reject an unknown value inline).
- New **catalog** menu entry: `list` current `pack_dirs`; `add` a directory (validated as a path);
  `remove` one (pick from the list). Mutates `cfg.catalog.pack_dirs`; saved on save. Pure helpers
  `_add_pack_dir(cfg, path)` / `_remove_pack_dir(cfg, path)`.

### 3.3 cwd `grendel.yaml` auto-discovery (gap 4)
In the callback, when `config is None`: if `Path("grendel.yaml").is_file()`, load it (log/announce
which config was auto-loaded). **Test isolation:** guard so the offline suite (which runs from the
repo root, where a `grendel.yaml` now exists) does NOT silently change behaviour — e.g. only
auto-load when `GRENDEL_NO_AUTOCONFIG` is unset AND set that env var in `conftest.py`, OR resolve the
existing tests to pass a config explicitly. The chosen mechanism must keep all prior tests green and
be covered by a dedicated test (auto-load happens in a tmp cwd with a grendel.yaml; does not happen
when suppressed).

### 3.4 list filter + doctor (gap 5)
- `list --packs --category jailbreak` filters; a header line `packs: N total` + per-category counts.
- `grendel doctor`: prints Install (version), Catalog (totals by category/source), Env keys
  (each preset `api_key_env` ✓/✗ from the environment, never the value), Targets, Proxy. Pure
  `build_doctor_report(cfg, *, env)`; a test asserts sections + no-secret-leak.

### 3.5 Hygiene + docs (gaps 6, 7)
- `.gitignore`: add `catalog/`.
- Import test: bound the auto-import with `--limit 5` (or drive `default_source_paths` + a tiny
  temp corpus) so the suite doesn't import 1500 each run; keep an `importorskip("garak")` guard.
- `pyproject.toml`: `[project.optional-dependencies] corpora = ["garak"]`; README documents
  `pip install -e ".[corpora]"` for `grendel import --source garak`.
- README: add `grendel config`, `grendel import` (+ auto-discovery + `--pack-dir`/catalog wiring),
  `grendel doctor`, and a one-line scoring-tier caveat (imported open-corpus attacks are scored by
  the T2 lexical classifier by default; enable the T3 judge for nuanced accuracy).
- PROGRESS.md: a `phase 17: DONE …` entry; ROADMAP already lists 16/17.

---

## 4. Testing strategy (offline + deterministic)

- **Banner** (`test_banner.py`): the banner lists `config` and `doctor`; `COMMANDS` names == the
  registered Typer command names (no drift).
- **Config** (`test_cli_config.py`): add a target choosing provider from the valid set (letter
  fallback) → saved YAML has it; an invalid provider selection → inline error, not added; catalog
  add/remove a pack dir → saved `catalog.pack_dirs` reflects it. `_add_pack_dir`/`_remove_pack_dir`
  pure-helper tests.
- **Auto-discovery** (`test_cli_autoconfig.py`): in a tmp cwd with a `grendel.yaml` pointing at a
  pack dir, `grendel list --packs` (no `-c`) shows the extra packs; with the suppression flag set, it
  does not. Prove the repo-root `grendel.yaml` doesn't leak into other tests.
- **Doctor** (`test_cli_doctor.py`): `grendel doctor` prints version/catalog/env-keys/targets;
  a set env key shows ✓ and its value never appears.
- **list filter** (`test_cli_packs.py`): `--category` narrows the output + the count line.
- **import speed** (`test_cli_import.py`): the auto-import test is bounded (`--limit`) and fast;
  `importorskip("garak")`.
- Prior offline suite stays green; only additive changes. No key/network in the suite.

---

## 5. Acceptance criteria

Phase 17 is done when:
0. **The CLI is flawlessly easy to use (§0).** A newcomer can go run → report → config → import →
   list with zero docs and never get stuck; every command's help/errors/next-steps are clear and
   actionable; a scripted first-run walkthrough passes and the reviewer confirms "a first-time user
   would not be confused anywhere". This is the primary bar; the items below are the concrete floor.
1. `ruff check .` + `ruff format --check .` clean; `pytest` green **offline** (prior suite + new
   tests); no key/network in the suite; the auto-import test is fast.
2. Bare `grendel` lists **every** command incl. `config` + `doctor` (asserted against the real set).
3. `grendel config` picks `type`/`provider` from **selects** and can **add/remove catalog pack
   dirs**, saved to the YAML.
4. `grendel` auto-loads a cwd `grendel.yaml` (so `list`/`run` see the configured catalog) with safe
   test isolation and an escape hatch.
5. `grendel list --packs --category …` filters + counts; `grendel doctor` prints an inline status
   report (version, catalog, env-keys ✓/✗ presence-only, targets, proxy).
6. Hygiene + docs: `catalog/` gitignored; garak documented as the optional `[corpora]` extra; README
   covers config/import/catalog/doctor + the scoring caveat; PROGRESS updated; the post-16 corpus
   changes are covered by the reviewer.
