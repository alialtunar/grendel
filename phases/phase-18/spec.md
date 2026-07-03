# Phase 18 — Interactive home menu + self-explanatory target setup: spec

> Make grendel **manageable without memorising commands**. Today, bare `grendel` prints a static
> banner and management lives in `grendel config`; a newcomer found it hard ("zor geldi") and, when
> adding a target, couldn't tell **what** they were configuring (does it call a model's chat API? a
> local server? my own agent?). This phase turns bare `grendel` (on a terminal) into an **interactive
> home menu** that is the primary way to manage AND operate the tool, and makes **adding a target
> self-explanatory** — every choice says what it is and what request will be made, with a confirmation
> summary before saving. Scripts/CI keep the exact current behaviour.

---

## 0. Overriding goal — a newcomer manages everything from one screen, and always knows what they set

Typing `grendel` should feel like opening an app: an obvious menu to add a target, set a key, run an
attack, grow the catalog, and see status — **without reading docs or remembering subcommands**. And
while adding a target, the user must never be guessing: each field/choice explains itself and the
tool shows, in plain words, **what endpoint/behaviour** the target resolves to before it is saved.

This bar is not met if: the menu hides an operation the CLI can do; any add-target choice is opaque
(the user can't tell an HTTP chat endpoint from an in-process agent); or the resolved target isn't
shown back to the user before saving. Non-interactive use (pipe/CI/subcommands) must be byte-identical
to today.

---

## 1. Goals

1. **Interactive home menu on bare `grendel` (TTY only).** With a terminal attached and no subcommand,
   `grendel` opens an arrow-key home menu: **Targets · API keys · Run · Catalog/import · Doctor ·
   Save & quit · Quit**. It wraps the EXISTING engines (config editing, run, import, doctor) — no new
   engine, no full-screen TUI. When stdin/stdout is not a TTY (pipe, CI, tests), bare `grendel` prints
   the current banner and exits (unchanged). Every subcommand keeps working exactly as now; a
   `--no-menu`/env escape hatch forces the banner even on a TTY.
2. **Self-explanatory add-target.** In the add-target flow (both the arrow-key and letter-menu
   shells): the **type** choice is annotated with what it is and what request is made; the **provider**
   choice is annotated (e.g. `openai-compatible → needs base_url; for a local/self-hosted server`);
   fields (`base_url`, `api_key_env`, `entrypoint`) carry a one-line hint; and after entry a
   **confirmation summary** shows the resolved target in plain words (for http: the effective
   `METHOD URL` that will be called, e.g. `POST https://api.openai.com/v1/chat/completions`, model,
   and which API-key env it will read; for python/agent: `in-process call → module:attr`). The user
   confirms before it is added.
3. **API-key management from the menu.** An **API keys** section lists each provider with ✓/✗ for its
   key env var (presence only — never the value), tells you the exact `export NAME=…` to set a missing
   one, and offers an **opt-in** save into a **gitignored** local secrets file (`grendel.local.yaml`)
   that is merged into the environment at startup (process-only; never written to the committed
   `grendel.yaml`, never printed). Default remains env-var; local save is an explicit choice.
4. **Run from the menu.** A **Run** entry lets you pick a configured target + packs (+ a dry-run
   toggle) and executes via the existing `run` engine, printing the same summary + `next:` hint.
5. **Offline, deterministic, additive.** All logic is exercised by the letter-menu fallback (the
   questionary arrow-key path stays offline-untestable, per precedent). No engine/scoring/exit-code
   changes; the prior suite stays green; no key/network in tests; no new runtime dependency.

---

## 2. Scope

**In scope**
- `src/grendel/cli.py`: promote the interactive config loop into a broader **home menu** (add Run /
  Import / Doctor / API-keys entries alongside the existing run/judge/proxy/targets/catalog editing);
  bare `grendel` launches it on a TTY (else banner). Add-target flow gains per-choice annotations +
  a confirmation summary. New pure helpers for: resolving a target to a human description
  (`describe_target(tc, cfg) -> str`, including the effective endpoint URL for http), and secrets
  file load/save.
- `src/grendel/config.py` (or a small `secrets.py`): load/merge a gitignored local secrets file into
  `os.environ` at startup (only for keys not already set); a pure `save_local_secret(name, value,
  path)` writing `grendel.local.yaml`.
- `src/grendel/targets/…`: reuse `resolve_target_info` / PRESETS to compute the effective base_url +
  chat path for the confirmation summary (no behaviour change to request building).
- `.gitignore`: add `grendel.local.yaml`.
- `tests/`: home-menu navigation (letter fallback) reaches Run/Import/Doctor/API-keys; add-target
  shows the confirmation summary + resolved endpoint; unknown/opaque choices are explained; secrets
  file round-trips and is merged at startup but never written to `grendel.yaml`; bare `grendel`
  non-TTY still prints the banner; escape hatch works.
- README/PROGRESS/ROADMAP.

**Out of scope (non-goals)**
- Any full-screen/Textual TUI (stays inline).
- Changing request building, scoring, the runner, the proxy, or exit codes.
- Storing secrets in the committed `grendel.yaml`, or ever printing/logging a key value.
- New target *types* or providers (http/python/agent/mcp unchanged) — this phase clarifies and
  operates them, it doesn't add new ones.
- Auto-installing Ollama/garak or any network action in tests.

---

## 3. Details

### 3.1 Home menu (goal 1)
A top-level arrow-key menu (questionary) with a letter-menu fallback for non-TTY, mirroring the
current `config` shells. Entries: **Targets** (existing add/remove/list, now self-explanatory),
**API keys** (3.3), **Run** (3.4), **Catalog / import**, **Doctor** (prints `build_doctor_report`),
**Config (advanced: run/judge/proxy)**, **Save & quit**, **Quit**. Bare `grendel`:
`if sys.stdin.isatty() and sys.stdout.isatty() and not --no-menu/GRENDEL_NO_MENU: open home menu; else
print banner`. Every existing subcommand is unchanged and still directly runnable.

### 3.2 Self-explanatory add-target (goal 2)
- Type choices annotated, e.g.:
  - `http  — call a model's chat API (OpenAI-compatible POST /chat/completions)`
  - `python — call your own Python function in-process (module:attr)`
  - `agent — call your own agent callable in-process (module:attr)`
- Provider choices annotated (preset api_style + whether base_url is required; `openai-compatible →
  local/self-hosted server, needs base_url`).
- `describe_target(tc, cfg)` returns the plain-words resolution; for http it uses the same
  provider/base_url resolution the runner uses, surfacing `POST <base_url>/chat/completions`, the
  model, and the api-key env var that will be read (name only). Shown as a confirmation before adding;
  the user accepts or cancels.

### 3.3 API-key management (goal 3)
- **API keys** section: for each provider with an `api_key_env`, show ✓/✗ (presence only). For a
  missing one, print the exact `export NAME=value` (POSIX) / `setx`/`$env:` hint. Offer **"save a key
  to a local gitignored file"**: writes `grendel.local.yaml` (`secrets: {ENV_NAME: value}`), which is
  gitignored and, at CLI startup, merged into `os.environ` for any var not already set (process-only).
  Never written to `grendel.yaml`; never printed back; the value is masked in any confirmation.

### 3.4 Run from the menu (goal 4)
Pick a configured target (or a quick provider+model), choose packs (or all), toggle dry-run, and run
through the existing `run` path; show the standard summary + `next:` hint. No new run behaviour.

---

## 4. Testing strategy (offline + deterministic)
- Home-menu navigation via the **letter fallback** (`CliRunner` `input=`): reach Targets / API keys /
  Run (dry-run, monkeypatched adapter) / Import / Doctor; Quit without saving writes nothing.
- Add-target confirmation: the summary shows `POST …/chat/completions`, the model, and the api-key env
  name for an http target; `in-process call → module:attr` for python/agent; cancel doesn't add.
- `describe_target` pure-unit tests for http (with/without base_url, openai vs openai-compatible) and
  python/agent.
- Secrets: `save_local_secret` writes `grendel.local.yaml` (gitignored); startup merge sets an env var
  only when unset and never overrides an existing one; the value never appears in `grendel.yaml` nor in
  any echoed output (masked).
- Bare `grendel` **non-TTY** still prints the banner (existing tests stay green); `--no-menu`/env forces
  the banner even when a TTY is simulated.
- Prior suite stays green; no key/network; no new dependency.

---

## 5. Acceptance criteria

Phase 18 is done when:
0. **A newcomer manages everything from one screen and always knows what they configured (§0).**
1. `ruff` clean; `pytest` green **offline** (prior + new); no key/network; no new runtime dep.
2. Bare `grendel` on a TTY opens the home menu (Targets/API keys/Run/Import/Doctor/Config/Save/Quit);
   non-TTY prints the banner; a `--no-menu`/`GRENDEL_NO_MENU` escape hatch forces the banner.
3. Adding a target explains each type/provider/field and shows a **confirmation summary** with the
   resolved endpoint/behaviour (http: `POST <url>/chat/completions` + model + api-key env name;
   python/agent: in-process `module:attr`) before saving.
4. The **API keys** menu shows ✓/✗ per provider, tells you how to set a missing key, and can save a
   key to a **gitignored** `grendel.local.yaml` that is merged into the env at startup — never into
   `grendel.yaml`, never printed.
5. **Run** works from the menu (target + packs + dry-run) via the existing engine.
6. README/PROGRESS/ROADMAP updated; `grendel.local.yaml` gitignored.
