# Phase 2 — Attack-pack format + core packs: implementation plan

> Build order is dependency-ordered: schema models → loader + validation + license gating
> → bundled YAML data + data tests → CLI `list --packs` wiring + integration. Every
> milestone ends in a **Checkpoint** with exact commands. The phase quality gate is
> `ruff check .` (zero findings), `ruff format --check .` (clean), and `pytest` (green,
> offline, no API keys). New code reuses Phase-1 patterns: Pydantic v2 with
> `ConfigDict(extra="forbid")` (`config.py`), `str, Enum` enums (`records.py`), and the
> `GauntletError` hierarchy (`errors.py`). No new third-party dependencies — `pyyaml` and
> `pydantic` are already in `pyproject.toml`.

---

## Milestone 1 — Attack schema models

**Build**
- `src/gauntlet/errors.py`: add `PackError(GauntletError)` — raised for every pack/loader
  failure (malformed YAML, validation, path/id mismatch, license gating, duplicate id).
- `src/gauntlet/attacks.py`:
  - `Surface(str, Enum)` (`prompt`/`tool-output`/`rag`/`mcp-desc`) and
    `Severity(str, Enum)` (`low`/`medium`/`high`/`critical`).
  - The four `success_when` variants — `StringCheck`, `SideEffectCheck`,
    `ClassifierCheck`, `JudgeCheck` — each `extra="forbid"`, each with a `type` Literal
    discriminator. `StringCheck` carries a `model_validator(mode="after")` requiring at
    least one of `contains`/`pattern` and compiling `pattern` with `re.compile` (invalid
    regex → raise, surfaced as `PackError` by the loader). `SideEffectCheck.assert_` uses
    `Field(alias="assert")` + `model_config` `populate_by_name=True`.
  - `SuccessWhen = Annotated[Union[StringCheck, SideEffectCheck, ClassifierCheck,
    JudgeCheck], Field(discriminator="type")]`.
  - `Attack(BaseModel)` per spec §4 with field patterns (`id`, `category`, `owasp`,
    `atlas`), `version: int = Field(ge=1)`, non-empty `payload`/`name`, `references:
    list[str] = []`, and `extra="forbid"`.
  - `ALLOWED_LICENSES: frozenset[str]` per spec §6.
  - **[Review fixes applied]**
    - **#1 error-type contract:** ALL field/model validators in `attacks.py` raise plain
      `ValueError` (standard Pydantic idiom) so they surface as `ValidationError`; the
      loader (M2) converts to `PackError`. Validators do NOT raise `PackError` directly.
    - **#2 `contains: []`:** `StringCheck` "at least one of" guard uses a **falsy** check:
      `if not self.contains and self.pattern is None: raise ValueError(...)` — so
      `contains=[]` with no `pattern` is rejected. Add that test case.
    - **#3 whitespace payload:** `payload` and `name` use a `field_validator` that
      `.strip()`s and rejects empty-after-strip (`min_length=1` alone is insufficient).
      Test `payload="   "` → `ValidationError`.
    - **#4 empty reference:** `references: list[Annotated[str, Field(min_length=1)]]`;
      test `references=[""]` rejected.
    - **#6 `assert` alias:** `SideEffectCheck` sets `populate_by_name=True`; test that YAML
      key `assert: foo` validates and maps to `assert_`.
    - **#11 OWASP revision:** owasp mappings follow the **OWASP LLM Top 10 2025** revision
      (LLM07 = System Prompt Leakage); cite the revision year in the bundled YAML refs.
- `tests/test_attacks.py`: well-formed attack validates; rejects unknown top-level key,
  unknown `success_when.type`, `string` check with neither `contains` nor `pattern`,
  `string` check with `contains=[]` and no `pattern` (#2), invalid `owasp`/`atlas`,
  `version=0`, invalid regex `pattern`, whitespace-only `payload` (#3), `references=[""]`
  (#4); `assert` YAML key maps to `assert_` (#6).

**Files**: `src/gauntlet/errors.py`, `src/gauntlet/attacks.py`, `tests/test_attacks.py`.

**Checkpoint**
```
ruff check .
ruff format --check .
pytest tests/test_attacks.py -q
```
Passing: ruff clean, format clean; the schema test asserts every accept/reject case in
spec §11 #2 plus the discriminated-union and `assert` alias behavior.

---

## Milestone 2 — Loader + validation + license gating

**Build**
- `src/gauntlet/packloader.py`:
  - `default_packs_dir() -> Path` = `Path(__file__).parent / "packs"`.
  - `PackInfo(BaseModel)` per spec §7 (`license_ok`, `success_type`, `path`), with
    `ConfigDict(extra="forbid")` (#8 — match the rest of the codebase).
  - `load_packs(packs_dir=None, *, allow_unlisted_licenses=False) -> list[Attack]`:
    glob `*/*.yaml`, deterministic **sort by `attack.id`** (#9 — `category` is a prefix of
    `id`, so the two-key sort was redundant); per-file rules 1–4 of spec §7
    (single-mapping YAML — reject empty/non-mapping/multi-doc via
    `docs = list(yaml.safe_load_all(content))` then `len(docs) != 1` (#10 — must
    materialize the generator, `len()` on the lazy generator raises `TypeError`);
    `Attack.model_validate`; path/id coherence; license gating), cross-file rule 5
    (duplicate id). Every failure → `PackError`.
    - **#1 + #7 catch order:** the loader does `except PackError: raise` (re-raise its own)
      then `except ValidationError as exc: raise PackError(f"invalid attack in {path}: {exc}")
      from exc` — so the message always **names the file path** (and id where known). The
      test asserts `PackError.args[0]` contains the offending file name.
  - `list_packs(...) -> list[PackInfo]`: project each `Attack` to a `PackInfo`.
  - Missing/non-directory `packs_dir` → `PackError`.
- `tests/test_packloader.py` using `tmp_path` to author throwaway YAML files (no
  dependency on the bundled packs yet): valid load; unknown license rejected by default and
  accepted+flagged with opt-in; duplicate id across two files; id/path mismatch; empty,
  non-mapping, multi-doc, and syntactically-broken YAML; missing dir. Assert `PackError`
  messages name the offending file/id.

**Files**: `src/gauntlet/packloader.py`, `tests/test_packloader.py`.

**Checkpoint**
```
ruff check .
ruff format --check .
pytest tests/test_packloader.py -q
```
Passing: every spec §11 #4 and #5 case is covered against temp fixtures; loader is pure
and offline; `PackError` messages are specific.

---

## Milestone 3 — Bundled packs + data-integrity tests

**Build**
- Author 12 static YAML files under `src/gauntlet/packs/prompt-injection/` and
  `src/gauntlet/packs/jailbreak/` exactly as tabulated in spec §9 — original, short,
  benign, authorized-testing-framed payloads; `license: Apache-2.0`; `success_when` type
  `string` (canary `GAUNTLET-PWNED` / `GAUNTLET-JAILBROKEN`, plus the `pattern` marker for
  `system-prompt-leak-04`); plausible OWASP/ATLAS mappings; `references` citing corpus
  families by URL only.
- `tests/test_bundled_packs.py`: **first assert `default_packs_dir().is_dir()` and each
  category subdir is non-empty (#5 — distinguishes a packaging/`hatchling` file-inclusion
  problem from a validation failure; verify `src/gauntlet/packs/*/` is populated after
  `pip install -e .`)**; then `load_packs(default_packs_dir())` returns exactly 12
  attacks; ids are unique and equal `<category>/<stem>`; every `license` is in
  `ALLOWED_LICENSES`; every `success_when.type == "string"`; every `owasp` matches the
  `LLM\d\d` pattern and `atlas` the `AML.T....` pattern; the two category counts are 6 and
  6; `list_packs` returns 12 rows all with `license_ok=True`.

**Files**: `src/gauntlet/packs/prompt-injection/*.yaml` (6),
`src/gauntlet/packs/jailbreak/*.yaml` (6), `tests/test_bundled_packs.py`.

**Checkpoint**
```
ruff check .
ruff format --check .
pytest tests/test_bundled_packs.py -q
```
Passing: the 12 bundled files load cleanly through the real loader (spec §11 #3, #6, #8);
the data-integrity test is green; ruff/format clean (YAML isn't linted, but the test file
is).

---

## Milestone 4 — CLI `list --packs` wiring + integration test

**Build**
- `src/gauntlet/cli.py`: in `list_`, replace the Phase-1
  `"no attack packs available until Phase 2."` block with a call to
  `list_packs(default_packs_dir())`, printing per spec §10 (grouped by category, one line
  per attack: id, owasp, atlas, severity, success_type, `[license]`, ` (unlisted license)`
  suffix when `license_ok` is False). Wrap discovery in `try/except PackError` → echo to
  stderr + `raise typer.Exit(code=2)`, mirroring the existing `ConfigError` handling.
- `tests/test_cli_packs.py` using `typer.testing.CliRunner`: `gauntlet list --packs` exits
  0, prints both category headers and all 12 ids, and **explicitly** asserts
  `"no attack packs available until Phase 2" not in result.output` (#12); the bare
  `gauntlet list` "show all" path also lists packs.

**Files**: `src/gauntlet/cli.py`, `tests/test_cli_packs.py`.

**Checkpoint**
```
ruff check .
ruff format --check .
pytest -q
gauntlet list --packs
```
Passing: the **entire** suite is green offline with no API keys; `gauntlet list --packs`
prints the 12 bundled attacks grouped by category with the Phase-1 placeholder gone (spec
§11 #1, #7). This satisfies all acceptance criteria in spec §11.

---

## Plan review

1. **[BLOCKING] Validator error-type contract / loader catch order unspecified.** Fixed: all `attacks.py` validators raise plain `ValueError` (→ `ValidationError`); the loader converts to `PackError` (M1 + M2 notes).
2. **[BLOCKING] `contains: []` slips past the "at least one of" guard with an `is None` check.** Fixed: falsy check `if not self.contains and self.pattern is None` + test (M1).
3. **[BLOCKING] Whitespace-only `payload` passes `min_length=1`.** Fixed: strip-and-reject `field_validator` on `payload`/`name` + test (M1).
4. **Empty string in `references` untested.** Fixed: `list[Annotated[str, Field(min_length=1)]]` + test (M1).
5. **`default_packs_dir()` existence not asserted (packaging vs validation failure ambiguity).** Fixed: M3 asserts `is_dir()` + non-empty subdirs first.
6. **`assert` alias behavior untested.** Fixed: `populate_by_name=True` + test (M1).
7. **Loader `PackError` must name the file/id.** Fixed: explicit message `invalid attack in {path}: {exc}` (M2).
8. **`PackInfo` missing `extra="forbid"`.** Fixed (M2).
9. **Redundant `(category, id)` sort.** Fixed: sort by `attack.id` (M2).
10. **[BLOCKING] `len(yaml.safe_load_all(...))` crashes (lazy generator).** Fixed: `docs = list(yaml.safe_load_all(content))` then `len(docs)` (M2).
11. **OWASP revision unspecified (LLM07 differs 2023 vs 2025).** Fixed: pin OWASP LLM Top 10 2025; cite year in YAML refs (M1/M3).
12. **CLI test must assert Phase-1 placeholder absent.** Fixed: explicit `not in result.output` assertion (M4).

**Resolution:** all four BLOCKING items (1, 2, 3, 10) and the eight non-blocking items
(4–9, 11–12) folded into the milestone build descriptions and checkpoints above. Ready to
implement.

STATUS: PASS
