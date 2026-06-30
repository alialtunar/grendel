# Phase 2 Review

Reviewed: `src/gauntlet/attacks.py`, `src/gauntlet/packloader.py`, `src/gauntlet/errors.py`,
`src/gauntlet/cli.py`, all 12 bundled YAML packs under `src/gauntlet/packs/`, and the four
new test modules. Commands run: `ruff check .`, `ruff format --check .`, `pytest -q` (full
suite), manual Python invocations to probe edge-case behavior.

---

## Findings

1. **`_non_empty_after_strip` does not strip — it only validates.** `attacks.py` lines 112–116:
   the validator calls `v.strip()` in the condition but `return v` returns the raw unstripped
   value. The plan says "a `field_validator` that `.strip()`s and rejects empty-after-strip",
   implying the stored value should be stripped. In practice this is harmless for the bundled
   YAML packs (YAML block scalars don't inject invisible leading whitespace into the payload
   string), and the rejection test (`payload="   "`) still passes. A field name or payload with
   leading/trailing spaces would be stored verbatim rather than cleaned. Non-blocking: no
   bundled data is affected and the spec acceptance criteria are met, but the behavior diverges
   from the plan's wording.

2. **`except PackError: raise` guard in `_parse_and_validate` is unreachable dead code.**
   `packloader.py` lines 87–88: the inner `try` block only calls `Attack.model_validate(data)`,
   which raises `ValidationError` (a Pydantic exception), never `PackError`. None of the
   `attacks.py` validators raise `PackError` directly (correct per review fix #1). The guard
   is therefore never triggered. It is defensive and harmless but could mislead a future
   contributor into thinking validators may raise `PackError`. Non-blocking.

3. **`ClassifierCheck.classifier` and `.label` accept empty strings.** `attacks.py` lines
   72–73: neither field has `min_length=1`. An empty `classifier: ""` or `label: ""` would
   validate. No bundled pack uses these fields (they are all `type: string`), and the spec does
   not explicitly require non-empty for these sub-fields. Non-blocking, but inconsistent with
   how `SideEffectCheck.assert_` and `JudgeCheck.rubric` are guarded.

4. **Hatchling `artifacts` entry is redundant but harmless.** `pyproject.toml`: `artifacts =
   ["src/gauntlet/packs/**/*.yaml"]` was added. Hatchling's `packages = ["src/gauntlet"]` with
   git-tracked files already includes the YAML files in the wheel. The `artifacts` key is for
   non-VCS files; adding it for VCS-tracked files is a no-op. No functional impact.

5. **All 12 blocking and non-blocking review fixes verified implemented:**
   - Fix #1 (ValueError contract): all validators in `attacks.py` raise `ValueError`; loader
     converts `ValidationError` → `PackError` with file path in message. Confirmed.
   - Fix #2 (`contains=[]` falsy guard): `if not self.contains and self.pattern is None`
     correctly rejects empty list. Test `test_string_check_empty_contains_no_pattern_rejected`
     passes.
   - Fix #3 (strip-reject payload/name): whitespace-only `payload` and `name` raise
     `ValidationError`. Tests pass.
   - Fix #10 (`list(yaml.safe_load_all(...))`): generator materialized before `len()`. Correct.

6. **Attack schema matches ROADMAP §4 / spec §4 exactly.** All fields present, correct types,
   correct patterns (`^LLM(0[1-9]|10)$`, `^AML\.T\d{4}(\.\d{3})?$`), `extra="forbid"` on all
   models, discriminated union with four variants.

7. **License allowlist is airtight.** `ALLOWED_LICENSES = frozenset({"Apache-2.0", "MIT",
   "BSD-2-Clause", "BSD-3-Clause", "CC0-1.0"})` matches spec §6. Default behavior rejects
   unlisted licenses; opt-in path sets `license_ok=False` on the `PackInfo`. All bundled packs
   carry `Apache-2.0`. Tests cover both paths.

8. **All 12 bundled YAML packs are structurally correct and match the spec §9 table exactly:**
   surface/severity/owasp/atlas/license all match; `system-prompt-leak-04` uses
   `pattern: SYSTEM-SECRET-[0-9]+` (not `contains`); all others use `contains`; all are
   `Apache-2.0`; all are `success_when.type: string`; OWASP revision is 2025 (LLM07 = System
   Prompt Leakage), cited in references.

9. **Security: `yaml.safe_load_all` used throughout.** No arbitrary code execution risk from
   untrusted YAML files.

10. **Duplicate-id check fires before coherence check.** `packloader.py` lines 60–63: correct
    order per spec §7 rule 5. The test `test_duplicate_id_across_files` confirms the error
    message names the second (offending) file.

11. **CLI Phase-1 placeholder removed from `list --packs` path.** The `list_` command now
    calls `list_packs(default_packs_dir())` and prints grouped output. The `run` command still
    contains a "until Phase 2" notice (line 108), which is correct per spec §10 ("gauntlet run
    --pack ID still prints the Phase-1 nothing to run notice"). Test `test_phase1_placeholder_absent`
    confirms the placeholder is absent from `list --packs` output.

12. **Test suite: 79 tests total, all pass.** Phase-1's 41 tests remain green. The 38 new Phase-2
    tests cover every acceptance criterion in spec §11. `ruff check .` and `ruff format --check .`
    both pass with zero findings.

---

STATUS: PASS
