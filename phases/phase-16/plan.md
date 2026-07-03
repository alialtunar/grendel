# Phase 16 — implementation plan

From `phases/phase-16/spec.md`. Three milestones. M1 (offline: logo + UX + editable targets) and M2
(the LangGraph example agent) each end in `ruff`+`pytest` green and `reviewer`/`tester` PASS. M3 is
the **live** end-to-end validation with the real key (manual; captured in `test-report.md`, no
secrets). No scoring/records/runner/proxy behaviour changes.

---

## Milestone 1 — Logo + UX polish + editable targets in `grendel config`

**Steps**
1. **`banner.py` — logo.** Extract the block wordmark into `render_logo(*, color=False) -> str`
   (wolf motif `🐺` line + the existing GRENDEL figlet art). `render_banner` composes
   `render_logo()` + tagline + command table + notice. Add `config_header(cfg, path, *, color) ->
   str` (a compact logo line + `grendel config — <path>`).
2. **`cli.py` — editable targets (add-time validation, reuse `with_cli_target`).**
   - `_add_target(cfg, *, name, kind, provider=None, model=None, base_url=None, api_key_env=None,
     entrypoint=None) -> GrendelConfig`: build the `TargetConfig` (`kind` maps to
     `TargetConfig(type=kind, …)` — http→provider+model[+base_url/api_key_env];
     python|agent→entrypoint; wrap `ValidationError`→`ConfigError`), then **return
     `cfg.with_cli_target(name, tc)`** — reusing the existing merge-and-`model_validate` path
     (`config.py:167`) so a **duplicate name** AND an **unknown provider / missing base_url are
     rejected at add-time** (reviewer findings 1+2), not deferred to save. The menu reassigns
     `cfg = _add_target(cfg, …)` on success.
   - `_remove_target(cfg, name) -> None`: raise `ConfigError` if absent; `del cfg.targets[name]`; if
     `cfg.judge.target == name`, also set `cfg.judge.target = None` and print a warning (no dangling
     judge reference — reviewer finding 6).
   - The `targets` menu action (both shells) offers **list / add / remove**; on a `ConfigError` it
     prints an inline red error and **loops back into the targets submenu** (reviewer finding 4),
     never crashing. Save still revalidates the whole config.
3. **`cli.py` — UX.** Print `config_header` atop the config menu (both shells). `run` with no target
   source: after the existing exit-2 message, add a one-line hint (`try: grendel run --provider
   openai --model gpt-4o-mini  ·  or: grendel config`). After a successful `run` (plain path) and
   `import`, a short "next:" hint. Colored ✓/✗ only where it reads cleanly (via `typer.style`;
   stripped when piped).
4. **Tests (offline):** extend `test_cli_config.py` — add an http target via the letter menu
   (scripted stdin) → saved YAML has it; **list** shows it and returns without mutating (reviewer
   finding 7); remove it → gone; add an **unknown-provider** target → inline error at add-time,
   submenu still alive, target NOT added. Extend `test_banner.py` — logo renders, appears in banner,
   `config_header` contains the path. Pure-helper tests: `_add_target` (duplicate name → ConfigError;
   unknown provider → ConfigError; valid → new cfg has the target), `_remove_target` (absent →
   ConfigError; removing a `judge.target` clears it).

**Checkpoint 1:** `ruff` clean; `pytest` green (476 prior + new); `grendel config` shows the logo and
adds/removes targets; `grendel` banner shows the logo. `reviewer` + `tester` → `STATUS: PASS`.

---

## Milestone 2 — LangGraph demo agent (`examples/langgraph-agent/`)

**Steps**
1. `examples/langgraph-agent/agent.py`: `create_react_agent(ChatOpenAI(model=env
   GRENDEL_AGENT_MODEL default gpt-4o-mini, base_url=env OPENAI_BASE_URL or None), tools=[send_email])`
   where `send_email(to: str, body: str) -> str` is a fake returning a confirmation string. A `main()`
   that invokes the agent on a sample turn and prints the final message + any tool calls; guarded so
   `import agent` doesn't require a key (the `main()` block is under `if __name__ == "__main__"`).
2. `examples/langgraph-agent/requirements.txt`: `langgraph`, `langchain-openai`.
3. `examples/langgraph-agent/README.md`: direct-run + zero-touch-via-proxy instructions (env-var
   based; no key in the file).
4. **Test (offline, structural only):** `tests/test_example_agent_exists.py` — assert the agent
   file + `requirements.txt` + `README.md` exist; the agent references `send_email` and
   `OPENAI_BASE_URL`; **`compile()`/`ast.parse` the agent source** so a syntax error is caught
   offline (reviewer finding 5) — **no import of langgraph** (not a suite dep).

**Checkpoint 2:** `ruff` clean (the example folder is excluded from the package but formatted);
`pytest` green; the structural test passes. `reviewer` + `tester` → `STATUS: PASS`.

---

## Milestone 3 — End-to-end live validation (real OpenAI key; manual)

**Intent:** prove the whole system works against the real API; iterate until flawless. Key is passed
via **env only** (never written to a file, never echoed into a committed artifact).

**Steps**
1. Install the example deps into the env: `pip install langgraph langchain-openai`.
2. **Direct API run:** `OPENAI_API_KEY=… grendel run --provider openai --model gpt-4o-mini --pack
   prompt-injection --out runs/e2e-direct.json` (the `prompt-injection` pack is **6 attacks** — small
   and cheap on `gpt-4o-mini`; use a single attack id like `prompt-injection/direct-override-01` for
   the smoke, the full 6 for the real run) → completion + real verdicts; then
   `grendel report --run runs/e2e-direct.json`. **[Already de-risked: a 1-attack direct run succeeded
   — asr 100%, the model complied with the injection.]** Fix any real-API wiring issues until clean.
3. **Proxy + agent (zero-touch):** start the proxy via **`Bash run_in_background`** (Windows: it
   stays up across turns; stop it with `TaskStop`/kill — no Ctrl-C needed): `grendel proxy --serve
   --route /openai=openai --pack tool-abuse --out runs/e2e-proxy.json`; run the agent with
   `OPENAI_BASE_URL=http://127.0.0.1:8100/openai/v1 OPENAI_API_KEY=… python
   examples/langgraph-agent/agent.py`; stop the proxy; confirm the run record has attempts with the
   agent's returned tool intent, and `grendel report` renders. Fix until clean.
4. Iterate (the user's directive) until both paths run without error and produce a sane report.
5. Capture the outcome in `phases/phase-16/test-report.md`: the offline suite result + a short live
   summary (commands run, exit codes, a couple of result lines) — **redact/omit the key**.

**Checkpoint 3 (phase close):** offline suite green; both live paths succeed and produce sane
reports; `reviewer` (code) + `tester` (offline suite) → `STATUS: PASS`; `test-report.md` records the
live outcome without secrets. Append `phase 16: DONE …` to `PROGRESS.md`.

---

## Risks & mitigations
- **Secret leakage.** Key only in shell env for the live commands; `.gitignore` covers `.env`; the
  key is never written to code, config, or `test-report.md`. Remind the user to revoke it after.
- **Real-API cost / rate limits.** Use small packs (a few attempts), `gpt-4o-mini`, one agent turn;
  don't fire the whole catalog. Log what was run.
- **Live-run bugs in real-API paths not covered offline** (the whole point of M3). Mitigate: fix
  forward — patch the adapter/proxy, keep the offline suite green as the regression net, re-run live.
- **Editing targets corrupts config on save.** Mitigate: save revalidates the whole `GrendelConfig`;
  a bad add → inline error, nothing written; tested via the letter-menu fallback.
- **questionary path untestable in pytest.** Mitigate: identical validation/save logic runs through
  the letter-menu fallback which IS tested (Phase-15 precedent).
