# Phase 18 — implementation plan

From `phases/phase-18/spec.md`. Three milestones, each ending in a verifiable checkpoint (`ruff`
clean + `pytest` green offline + `reviewer`/`tester` `STATUS: PASS`). No engine/scoring/runner/proxy/
exit-code changes; non-interactive behaviour (pipe/CI/subcommands) stays byte-identical; no key/
network in the suite; no new runtime dependency. All new interactive logic is reachable through the
**letter-menu fallback** so it is offline-testable (the questionary arrow-key path stays untestable,
per precedent). A known non-CliRunner regression seam already exists (`test_cli_encoding.py`) if a
real-TTY check is ever needed.

---

## Milestone 1 — The home menu (bare `grendel` → manage & operate)

**Steps**
1. **Promote the config loop into a home menu.** Rename/extend the current interactive shells: a new
   `_home_questionary(cfg, path, *, unicode)` and `_home_letter(cfg, path, *, unicode)` whose top-level
   entries are **Targets · API keys · Run · Catalog/import · Doctor · Config (advanced: run/judge/
   proxy) · Save & quit · Quit**. The existing `_targets_*`, `_catalog_*`, run/judge/proxy editors,
   `build_doctor_report`, and `import_corpus`/`default_source_paths` are reused verbatim — the menu is a
   dispatcher, not a new engine. Keep `save_config` semantics unchanged.
2. **Bare `grendel` opens it on a TTY.** In `main`, when `ctx.invoked_subcommand is None`: if
   `sys.stdin.isatty() and sys.stdout.isatty()` and neither `--no-menu` nor `GRENDEL_NO_MENU` is set,
   launch the home menu (loading cfg via the same path as `config`); otherwise print the banner and
   exit (today's behaviour — keeps all bare-grendel tests + pipes/CI green). Add a `--no-menu` flag on
   the callback (shown in `--help`).
3. **Doctor / Import / Run entries.** Doctor prints `build_doctor_report(...)`. Import prompts for an
   out dir (default `catalog`) + optional `--path`/`--limit` and calls the import loop, printing the
   same summary. Run is fleshed out in M-note below (kept minimal here: dispatch to the shared run
   helper added in M2's sibling step) — for M1, Run may be a stub entry that says "coming next" ONLY
   if needed to keep the milestone small; prefer to land a working dry-run Run here if low-risk.
4. **Tests** (`test_cli_home.py`): letter-fallback navigation reaches Targets, API-keys (placeholder in
   M1 → real in M3), Doctor (prints "Install"/"Catalog"), Import (dry-run/limit, no network via the
   bundled fixture), Config-advanced (edit run concurrency, save). `Quit` writes nothing. Bare
   `grendel` under a **simulated non-TTY** (CliRunner, the default) still prints the banner; assert the
   escape hatch: with a monkeypatched `isatty()→True` + `--no-menu`, the banner prints (not the menu).

**Checkpoint 1:** ruff clean; pytest green (prior + new); bare `grendel` opens the home menu on a TTY
and still banners off-TTY; menu reaches Targets/Doctor/Import/Config; `--no-menu`/env forces the
banner. `reviewer` + `tester` → `STATUS: PASS`.

---

## Milestone 2 — Self-explanatory add-target (know what you're configuring)

**Steps**
1. **Annotated choices.** In the add-target flow (both shells), the **type** select shows what each
   type is + what request is made (`http — call a model's chat API (OpenAI-compatible POST
   /chat/completions)`; `python`/`agent — call your own function/agent in-process (module:attr)`). The
   **provider** select shows each preset's `api_style` and whether `base_url` is required
   (`openai-compatible → local/self-hosted server; needs base_url`). Field prompts (`base_url`,
   `api_key_env`, `entrypoint`) gain a one-line hint.
2. **`describe_target(tc, cfg) -> str` (pure).** Returns the plain-words resolution used for the
   confirmation. For `http`: resolve provider/base_url the SAME way the runner does (reuse
   `resolve_target_info`/PRESETS — read-only) and surface `POST <base_url>/chat/completions`, the
   `model`, and the api-key **env var name** it will read (never a value). For `python`/`agent`:
   `in-process call → <module:attr>`. For `mcp`: the command/url. Add unit tests for each branch
   (openai vs openai-compatible w/ base_url; python/agent).
3. **Confirmation before add.** After collecting fields, print the `describe_target` summary and ask
   to confirm (letter: `y`/`n`; questionary: `confirm`). On confirm → `_add_target` (unchanged
   validation). On cancel → nothing added, return to the menu. Wire into both shells.
4. **Tests** (`test_cli_home.py` / extend `test_cli_config.py`): adding an http target shows
   `POST …/chat/completions`, the model, and the api-key env name, then saves on confirm; cancel adds
   nothing; a python/agent target shows the in-process line; `describe_target` pure-unit cases.

**Checkpoint 2:** ruff clean; pytest green; add-target explains every choice and shows the resolved
endpoint/behaviour before saving; cancel is a no-op. `reviewer` + `tester` → `STATUS: PASS`.

---

## Milestone 3 — API-key management + Run + hygiene/docs

**Steps**
1. **Local secrets file (gitignored).** New `src/grendel/secrets.py` (small, pure-ish):
   `load_local_secrets(path) -> dict[str,str]` (reads `grendel.local.yaml`'s `secrets:` map; missing
   file → `{}`), `merge_secrets_into_env(secrets, env)` (sets a var **only if unset** — never
   overrides a real env var), `save_local_secret(name, value, path)` (atomic write, `extra="forbid"`
   schema, 0600 where supported). In `main`, after config load, merge `grendel.local.yaml` from the cwd
   (guarded by the same isolation approach as auto-config: a `GRENDEL_NO_LOCAL_SECRETS` env the suite
   sets, so a stray file never leaks into tests). `.gitignore`: add `grendel.local.yaml`.
2. **API-keys menu.** For each provider with an `api_key_env`: show ✓/✗ (presence only, reusing the
   doctor logic). For a missing key, print the exact `export NAME=value` (and a Windows `$env:NAME`
   line). Offer **save to local file** → prompts for the value (masked in any echo), writes via
   `save_local_secret`, confirms with the value **masked** (`sk-…last4`). Never write to `grendel.yaml`,
   never print the full value.
3. **Run from the menu.** A shared `_run_from_menu(cfg)` (or reuse the `run` command internals): pick a
   configured target (or provider+model), pick packs (or all), toggle dry-run, execute via the existing
   run path, print the standard summary + `next:` hint. Offline test monkeypatches the adapter
   (FakeAdapter) + `_load_attacks`, same seam as `test_cli_flag_target.py`/`test_cli_walkthrough.py`.
4. **Docs + hygiene.** README: a short "Just run `grendel`" section (the home menu) + the local-secrets
   note (gitignored, opt-in, env still wins). PROGRESS phase-18 entry; ROADMAP already lists 18.
5. **Tests** (`test_cli_secrets.py` + `test_cli_home.py`): `save_local_secret` round-trip; merge sets a
   var only when unset and never overrides; the value never appears in `grendel.yaml` or echoed output
   (masked); API-keys menu shows ✓/✗ and the export hint; Run-from-menu dry-run + a full run
   (FakeAdapter) writes a record and prints the summary.

**Checkpoint 3 (phase close):** ruff clean; pytest green offline; API-keys menu status + guided set +
opt-in gitignored local save (merged at startup, never in `grendel.yaml`, never printed); Run works
from the menu; README/PROGRESS updated; `grendel.local.yaml` gitignored. `reviewer` (lens: "can a
newcomer add a target/key and run, always knowing what they set, without docs?") + `tester` →
`STATUS: PASS`; append `phase 18: DONE …` to `PROGRESS.md`.

---

## Risks & mitigations
- **Bare `grendel` menu breaks scripts/tests that expect the banner.** Mitigate: strictly TTY-gate
  (both stdin+stdout isatty) + `--no-menu`/`GRENDEL_NO_MENU`; CliRunner is non-TTY so every existing
  bare-grendel test stays on the banner path unchanged. Add an explicit escape-hatch test.
- **A secret leaking to disk/log/committed config.** Mitigate: secrets ONLY in the gitignored
  `grendel.local.yaml`; never merged into `grendel.yaml`; values masked in all output; a test asserts
  the value never appears in the saved config or echoed text; `.gitignore` entry + a test that the file
  is ignored.
- **Local-secrets file leaking into the test suite** (like the phase-17 auto-config risk). Mitigate: a
  `GRENDEL_NO_LOCAL_SECRETS` env set module-level in `conftest.py`; a dedicated test exercises the
  merge in a tmp cwd with the flag unset.
- **`describe_target` drifting from real request building.** Mitigate: it REUSES `resolve_target_info`/
  PRESETS (the same resolution the runner uses) rather than re-deriving the URL; a unit test pins the
  openai and openai-compatible outputs.
- **questionary arrow-key paths untestable.** Mitigate: the letter-menu fallback carries the same
  dispatch/validation/summary logic and IS tested (established precedent).
- **Menu hides an operation (fails §0).** Mitigate: the M3 reviewer checks every CLI operation is
  reachable from the menu OR intentionally out of scope (proxy-serve stays a subcommand — long-running).

---

## Plan review — resolutions (STATUS: REVISE → addressed)

1. **main() cfg-loading shared, banner path unchanged.** Extract `_autodiscover_config(config,
   no_config)` (the `GRENDEL_NO_AUTOCONFIG`-guarded `./grendel.yaml` pickup). Both the subcommand path
   and the new TTY-home-menu path call it then `load_config`; the **non-TTY banner path loads NO
   config** (byte-identical to today). A `_wants_home_menu(no_menu)` helper decides menu-vs-banner.
2/3. **`describe_target(tc, cfg)` reuses the REAL resolution and branches on api_style.** It inserts the
   not-yet-saved `tc` under a temp key into a copied cfg and calls `resolve_target_info` (so base_url +
   api_style come from the same code the runner uses — no drift), then picks the path suffix by
   api_style (`openai → /chat/completions`, `anthropic → /messages`, `ollama → /api/chat`); it does NOT
   hardcode `/chat/completions`. It surfaces the api-key **env var name** only (never a value).
4. **Test seam: `GRENDEL_FORCE_MENU`.** `_wants_home_menu` precedence: `--no-menu`/`GRENDEL_NO_MENU` →
   banner; else `GRENDEL_FORCE_MENU` → menu; else `stdin.isatty() and stdout.isatty()`. Tests set
   `GRENDEL_FORCE_MENU=1` and invoke bare `grendel` via `CliRunner` (non-TTY stdin → the **letter**
   home menu, exercising `main()`'s gating for real). An escape-hatch test asserts `--no-menu` wins.
5. **`grendel.local.yaml` is read from the process cwd** (like `./grendel.yaml` auto-discovery),
   independent of `-c` — a stated decision, documented in the README.
6. **conftest:** add `os.environ["GRENDEL_NO_LOCAL_SECRETS"] = "1"` at module import (beside the
   existing `GRENDEL_NO_AUTOCONFIG` line); the dedicated secrets test `delenv`s it in a tmp cwd, using
   `test_cli_autoconfig.py` as the template.
7. **Drop the 0600 claim** (a no-op on Windows NTFS). Security rests on `.gitignore` + the value never
   being written to the committed `grendel.yaml` and never printed — asserted by tests, not file mode.
8. **Run decision (M1):** land a **functional Run** (dry-run + a real run via the existing
   `build_target`/`_load_attacks`/`_execute`/`_summary` helpers, FakeAdapter test seam) in M1 — no
   "coming next" stub ships to main.
9. **API-keys is net-new**, introduced by this phase (not a pre-existing CLI op being hidden), so it
   lands in **M3**; the M1 menu simply doesn't list it yet — §0's "menu hides an operation the CLI can
   do" is not violated (there is no `grendel api-keys` command today).
10. **Add-target confirmation catches `ConfigError`** from `describe_target`/validation (e.g.
    unresolvable base_url, unknown provider) → prints the error and returns to the prompt; never crashes
    the menu loop. Explicit M2 test.
11. **Malformed `grendel.local.yaml`** (non-mapping `secrets:`, unknown top-level keys under
    `extra="forbid"`) surfaces a clear `ConfigError`, not a raw pydantic traceback — mirrors
    `load_config`; explicit M3 test.
