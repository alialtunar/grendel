# Phase 9 Review

Reviewed: `git diff HEAD~1 HEAD` — 21 files, 2535 insertions.
Test run result: **385 passed, 1 skipped** (matches expected count).
Lint: `ruff check .` — all checks passed.

---

## Findings

### 1. Security — path traversal (HIGH, plan Fix #2): CLEAR

`FeedPackEntry.category` uses `Field(pattern=r"^[a-z0-9-]+$")` and `id` uses
`Field(pattern=r"^[a-z0-9-]+/[a-z0-9-]+$")`. Both patterns exclude `.`, `/`, and
every other traversal character. A manifest with `category: "../../etc"` is rejected
inside `FeedManifest.model_validate()` at parse time, before any download or write
occurs. The cache path is built from the VALIDATED `attack.category` and
`attack.id.split("/",1)[1]` (not from `entry.category` or any URL-derived stem); the
`Attack` model re-validates `category` with the same pattern, providing defense-in-depth.

`test_traversal_manifest_rejected_at_parse` confirms: `result.errors == 1`,
`/packs/evil.yaml` not in `srv.requested`, nothing written to `cache`.

### 2. Atomic write (plan Fix #4): CLEAR

`_atomic_write_bytes` in `feed.py` mirrors the runner pattern exactly: `dest.with_name(f"{dest.name}.{os.getpid()}.tmp")` → `tmp.write_bytes(content)` → `os.replace(tmp, dest)`. `test_interrupted_write_leaves_prior_file_intact` monkeypatches `feedmod.os.replace` to raise and asserts the prior v1 file is intact and `result.errors == 1`.

Minor observation: when `os.replace` fails, the `.{pid}.tmp` file is left behind in the cache directory (not cleaned up). This is a minor cleanup gap, not a correctness or security issue — the next successful run overwrites via `os.replace`.

### 3. License gate before download (HARD constraint): CLEAR

In `_process_entry`, the license check at lines 151-155 returns unconditionally before the HTTP GET for the pack body. `test_unlisted_license_skipped_without_download` asserts `result.skipped_license == 1`, `result.pulled == 0`, and `/packs/gpl-01.yaml` not in `srv.requested`. The subsequent opt-in run confirms the gate is the only blocker.

### 4. sha256 compare (plan Fix #8): CLEAR

`hashlib.sha256(content).hexdigest()` produces lowercase hex. `entry.sha256` is pattern-validated as `^[0-9a-f]{64}$` (also lowercase). Direct `==` compare is correct and unambiguous.

### 5. 1 MiB size cap (plan Fix #10): CLEAR

`MAX_PACK_BYTES = 1024 * 1024`. Check: `if len(content) > MAX_PACK_BYTES`. `test_oversize_pack_refused` sends 1 MiB + 1 byte; asserts `result.errors == 1`, `result.pulled == 0`, and the detail reason contains `"cap"`.

Note: the cap is applied to the downloaded response body (`resp.content`), not to `Content-Length`. This means an attacker serving a body without a `Content-Length` header that exceeds 1 MiB will still be caught, but only after all bytes are received (no streaming abort). httpx buffers the full body before returning `resp.content`. For a 1 MiB ceiling this is acceptable.

### 6. Fix #1 — single `_load_attacks` patch point: CLEAR

`cli._load_attacks(cfg)` is a module-level function; both TUI and non-TUI `run` paths call it. Both `test_cli_run.py` and `test_cli_tui.py` monkeypatch `cli._load_attacks` (not `cli.load_packs`), and the lambda returns the fake attack list directly. Verified the tests inject 2 fake attacks (not the real 21).

### 7. Fix #3 — runner error-path owasp/atlas threading: CLEAR

`_perform_send` signature: `owasp: str | None = None, atlas: str | None = None`.
Error-path `AttemptRecord` in `_perform_send` sets `owasp=owasp, atlas=atlas`.
`_run_attempt` passes `owasp=attack.owasp, atlas=attack.atlas`.
`_run_control` passes no owasp/atlas kwargs (defaults to `None`, correct per plan).
The success-path `AttemptRecord` in `_run_attempt` also sets `owasp=attack.owasp, atlas=attack.atlas`.

### 8. OWASP/ATLAS metrics_summary: CLEAR

`_breakdown("owasp")` and `_breakdown("atlas")` both use `_group_by_code` which skips `is_control` attempts and maps `None` to `"unmapped"`. `_asr` handles the zero-scored-attempts case (`return 0.0`). `metrics_summary` adds `"by_owasp"` and `"by_atlas"` without removing any prior key. `test_existing_keys_unchanged` enumerates all prior keys and asserts they remain.

### 9. Multi-source loader dedup and precedence: CLEAR

`_SOURCE_RANK`: `STAGED=0, BUNDLED=1, FEED=2, USER=3`. Cross-source override:
- `allow_override=False` → `PackError` naming both paths and sources.
- `allow_override=True`, equal rank → `PackError` with `"same-rank"` (Fix #7).
- `allow_override=True`, different rank → higher rank wins deterministically.

Tests cover: default duplicate error, user-beats-bundled, user-beats-feed, same-rank error.

### 10. `FeedUpdateResult` is a Pydantic BaseModel (Fix #5): CLEAR

`class FeedUpdateResult(BaseModel): model_config = ConfigDict(extra="forbid")` with typed fields. Correct.

### 11. Owned httpx.AsyncClient lifecycle (Fix #6): CLEAR

`async with httpx.AsyncClient() as owned:` when `client is None`. Injected client is used as-is (caller owns lifecycle). `test_clean_pull_caches_and_loadable` asserts the injected client was actually used.

### 12. Fix #9 — `--feed NAME` no-match exit 2: CLEAR

CLI checks `feed not in {f.name for f in cfg.catalog.feeds}` before calling `update_feeds`. `test_update_unknown_feed_exits_2` asserts `exit_code == 2` and `"no feed named"` in output.

### 13. Fix #11 — relative path resolution in `load_config`: CLEAR

`load_config` resolves `pack_dirs`, `feed_cache_dir`, and `staged_dir` against `path.resolve().parent`. Dedicated test `test_catalog_relative_paths_resolve_against_config_dir` asserts both `pack_dirs[0]` and `feed_cache_dir` resolve to absolute paths based on the config file's directory.

### 14. Authoring guide (Fix #12): CLEAR

`docs/authoring-packs.md` exists with all 6 required section headers. `test_authoring_guide_exists_with_required_sections` asserts each header and all 5 `success_when` types and the `list --packs` validation command.

### 15. `yaml.safe_load` used throughout: CLEAR

Manifest parsing: `yaml.safe_load(resp.text)`. Pack body parsing in `_parse_attack_bytes`: `yaml.safe_load_all(content.decode("utf-8"))`. No `yaml.load` with untrusted `Loader` anywhere in new code.

### 16. Manifest version gate: CLEAR

`if manifest.manifest_version > SUPPORTED_MANIFEST_VERSION: raise FeedError(...)`. Pattern also enforces `ge=1`.

### 17. `FeedSource` non-empty validation: CLEAR

`@field_validator("name", "url")` with `if not v.strip(): raise ValueError(...)`. `test_feed_source_empty_name_rejected` covers the `name` field. No test for `url=""` specifically, but the validator covers both fields identically — minor coverage gap, non-blocking.

### 18. Content-manifest coherence check: CLEAR

After parsing the pack body as an `Attack`, all four fields (`id`, `category`, `license`, `version`) are compared against the manifest claim. Mismatch → error collected, nothing written. `test_content_manifest_mismatch_rejected` confirms.

### 19. Prior 348 tests inert: CLEAR

All 385 tests pass (1 skipped). The enumerated contract updates (source tag in list output, `owasp`/`atlas` fields on `AttemptRecord`, `by_owasp`/`by_atlas` in `metrics_summary`) are correctly reflected in existing tests.

---

STATUS: PASS
