# Phase 16 — Easy-to-use CLI + logo + editable targets + LangGraph end-to-end: spec

> A follow-on UX + validation phase (post-TUI-removal). The tool is now a pure inline CLI with a
> branded banner and an interactive `grendel config` (arrow-key `questionary` menu, letter-menu
> fallback for non-TTY). This phase makes it **easy for anyone to use**, gives it a proper **logo**,
> makes **targets editable from `grendel config`** (add / remove, not just view), ships a **LangGraph
> demo agent in a separate folder**, and proves the whole system **end-to-end against the real
> OpenAI API** — iterating until it runs flawlessly.
>
> **Deliverables:**
> 1. **Logo + UX polish.** A reusable `grendel` logo (the wolf + wordmark) shown on the bare-`grendel`
>    banner **and** atop the `grendel config` menu; friendlier guidance (helpful next-step hints,
>    clearer errors, colored summaries), so a first-time user can run and configure without reading
>    docs.
> 2. **Editable targets in `grendel config`.** The `targets` section becomes **add / remove**, not
>    read-only: add an HTTP target (name + provider + model [+ base_url/api_key_env]) or a
>    python/agent target (name + entrypoint), and remove a target — validated, saved to the YAML.
> 3. **LangGraph demo agent** (`examples/langgraph-agent/`): a small, self-contained agent built with
>    LangGraph + `langchain-openai`, with a tool (a fake `send_email`), whose `base_url` is
>    configurable so it can be pointed at **`grendel proxy`** (zero-touch) — the canonical thing
>    Grendel tests. Its own `requirements.txt` + `README.md`; **not** part of the grendel package or
>    its offline test suite.
> 4. **End-to-end validation (live).** With the user's OpenAI key (env only, never written to disk):
>    (a) a direct `grendel run --provider openai --model gpt-4o-mini` against the real API records
>    real verdicts; (b) `grendel proxy --serve` in front of the LangGraph agent injects attacks and
>    records the agent's returned tool intent. Iterate until both work cleanly.
>
> **Offline suite stays green.** All new *unit* tests are offline (the config-target editing via the
> letter-menu fallback + the logo render + any pure helpers); the LangGraph agent + the real-API runs
> are **live, manual** validation, not pytest. No secret is written to any file. The prior **476**
> tests (1 skipped) stay green; `questionary` is already a dep, `langgraph`/`langchain-openai` are
> **example-only** deps (in the agent folder's `requirements.txt`, not `pyproject.toml`).

---

## 1. Goals

1. **A logo the app wears.** One reusable ASCII logo (wolf + `GRENDEL` wordmark) in `banner.py`,
   rendered on the bare-`grendel` landing **and** as the header of the `grendel config` menu, with
   color in a TTY.
2. **First-run-friendly — the UX bar is EXCELLENCE, not "adequate".** A first-time user, with zero
   docs, must be able to discover what to do, pick a target, run, and read the result **without ever
   feeling lost**. Concretely: bare `grendel` is an inviting branded landing; every error is
   actionable (says exactly what to type next, never a bare stack trace or a terse code); the config
   menu is self-explanatory with a branded header and sensible defaults pre-filled; every command
   ends with a colored, human "next: …" hint; success is ✓-green, failure ✗-red, consistently. The
   test is: *could someone who has never seen grendel run their first attack in under a minute?* If
   any path is confusing, it is a defect to fix — this phase is not done while the UX is merely
   "okay". No behaviour change to exit codes; the polish is all additive.
3. **Editable targets from the config menu.** `grendel config` → `targets` offers: **list**, **add**
   (http: name/provider/model[/base_url/api_key_env]; python|agent: name/entrypoint), **remove**
   (pick a name). Adds go through the existing `TargetConfig`/`GrendelConfig` validation (unknown
   provider etc. → inline error, not a crash) and are saved to the YAML. Works with arrow-keys
   (questionary) and via the letter-menu fallback (tested).
4. **A real LangGraph agent to test.** `examples/langgraph-agent/agent.py`: a LangGraph
   `create_react_agent` (or a minimal graph) with a `send_email(to, body)` tool, using
   `ChatOpenAI(base_url=…)` read from env so it can target OpenAI directly **or** the grendel proxy.
   A `requirements.txt` (langgraph, langchain-openai) + `README.md` showing both the direct run and
   the "point at `grendel proxy`" zero-touch run.
5. **End-to-end proof (live).** Using the provided key (env only): a direct real-API `grendel run`
   and a proxy-in-front-of-the-agent run both complete, record real verdicts/tool-intent, and the
   report renders. Fix whatever breaks until clean.
6. Prior 476 offline tests (1 skipped) stay green; new offline unit tests cover the editable-targets
   letter-menu path + the logo; no secret on disk.

---

## 2. Scope

**In scope**
- `src/grendel/banner.py` (EXTEND): a `LOGO` constant (wolf + wordmark) + `render_logo(color)`;
  `render_banner` uses it; export a compact header form for the config menu.
- `src/grendel/cli.py` (EXTEND): the `config` command's `targets` section becomes an add/remove
  sub-menu (both the questionary path and the letter-menu fallback); the logo prints atop the config
  menu; friendlier `run`-no-target and post-action hints. New pure helpers `_add_target(cfg, …)` /
  `_remove_target(cfg, name)` that mutate + rely on save-time revalidation.
- `examples/langgraph-agent/` (NEW): `agent.py`, `requirements.txt`, `README.md` — a runnable
  LangGraph agent with a `send_email` tool and a configurable `base_url`/model via env.
- A demo tool-abuse pack is already bundled (`packs/tool-abuse/*`) — reused to inject at the agent.
- Tests (offline): extend `tests/test_cli_config.py` (add/remove a target via the letter-menu
  fallback → the saved YAML has/omits it; adding an unknown-provider target → inline error, no
  crash); extend `tests/test_banner.py` (the logo renders; appears in the banner). `test_docs_*`
  updated only if a marker changes.

**Out of scope (deferred / non-goals)**
- **Bundling `langgraph`/`langchain-openai` into `pyproject.toml`.** They are heavy, example-only
  deps; they live in the agent folder's `requirements.txt` and are installed for the live test only.
- **Unit-testing the live OpenAI calls or the LangGraph agent in pytest.** Those need a real key +
  network; they are manual, live validation (this phase's §5), never in the offline suite.
- **Unit-testing the questionary arrow-key interaction.** It needs a PTY; the config logic is tested
  through the letter-menu fallback (same code paths for validation/save), as established in Phase 15.
- **Editing every config field / custom providers / feeds from the menu.** Targets + run/judge/proxy
  (already present) are the high-value set; the rest stay file-only.
- **Writing the API key to any file** (`.env`, config, or code). Env-var only, per the user's note;
  the key is used for the live test and then revoked by the user.
- **Changing scoring/records/runner/proxy/packloader behaviour.** All additive UX + an example agent.

---

## 3. Logo + UX (banner.py + cli.py)

- `render_logo(color)` returns the wolf + `GRENDEL` wordmark (the existing figlet block art, with a
  small wolf motif). `render_banner` composes logo + tagline + command table + notice.
- A compact `config_header(cfg, path, color)` (logo line + `grendel config — <path>`) prints atop the
  config menu so it feels branded and consistent.
- Friendlier guidance (all additive, exit codes unchanged): `run` with neither `--target` nor a
  target-flag group prints the existing exit-2 error **plus** a one-line "try: `grendel run
  --provider openai --model gpt-4o-mini`, or `grendel config` to add a target"; after a successful
  `run`/`import`, a short "next: `grendel report --run …`" hint. Colored ✓/✗ where it helps.

## 4. Editable targets in `grendel config`

The `targets` action opens a sub-menu (arrow-key or letter):
- **list** — show configured targets (name → type provider/model | entrypoint).
- **add** — prompt for `name`, then `type` (http/python/agent); for http: `provider`, `model`, and
  optional `base_url`/`api_key_env`; for python/agent: `entrypoint`. Build a `TargetConfig` (its
  field validators run) and insert into `cfg.targets[name]`. A duplicate name or an invalid field →
  inline error, no crash (the target isn't added).
- **remove** — pick an existing name (or type it in the fallback) → delete from `cfg.targets`.
- On **save**, the whole `GrendelConfig` is revalidated (unknown provider, missing base_url for
  `openai-compatible`, etc. → inline error, nothing written), exactly as today.

Pure helpers `_add_target(cfg, *, name, type, provider, model, base_url, api_key_env, entrypoint)`
(raises `ConfigError` on a bad/duplicate spec) and `_remove_target(cfg, name)` are unit-tested; the
questionary/letter shells just gather inputs and call them.

## 5. LangGraph demo agent (`examples/langgraph-agent/`)

- `agent.py`: builds a LangGraph agent (`langgraph.prebuilt.create_react_agent`) with one tool
  `send_email(to: str, body: str)` (a fake that just returns a confirmation string — no real email),
  and `ChatOpenAI(model=os.getenv("GRENDEL_AGENT_MODEL","gpt-4o-mini"),
  base_url=os.getenv("OPENAI_BASE_URL"))` so it talks to OpenAI directly **or** to
  `grendel proxy` when `OPENAI_BASE_URL` points at it. A `main()` that runs one user turn
  (`"summarize my inbox"`) and prints the result + any tool calls.
- `requirements.txt`: `langgraph`, `langchain-openai`.
- `README.md`: (a) direct run: `OPENAI_API_KEY=… python agent.py`; (b) zero-touch:
  `grendel proxy --serve --route /openai=openai --pack tool-abuse` then
  `OPENAI_BASE_URL=http://127.0.0.1:8100/openai/v1 OPENAI_API_KEY=… python agent.py` — Grendel
  injects attacks into the agent's LLM calls and records the tool intent.

## 6. End-to-end validation (live, manual — the "flawless" bar)

With the key in env only:
1. **Direct API:** `grendel run --provider openai --model gpt-4o-mini --pack prompt-injection`
   (a small pack) → completes, records real verdicts, `grendel report` renders. Fix any real-API
   wiring bugs (auth header, response parse, cost) until clean.
2. **Proxy + agent (zero-touch):** start `grendel proxy --serve --route /openai=openai --pack
   tool-abuse`; run the LangGraph agent against the proxy `base_url` (its own key forwarded); confirm
   Grendel injects, forwards, reads returned `tool_calls`, and writes a run record. Fix until clean.
3. Keep iterating (the user's directive) until both paths run without error and produce a sane
   report. Record the outcome in `phases/phase-16/test-report.md` (offline suite + a live-run
   transcript summary — **no key in the report**).

## 7. Deliberate contract updates (enumerated)

1. `banner.py` gains the logo helpers; `render_banner` output changes cosmetically (tests assert
   stable markers: `grendel`, command names, the notice — not exact art).
2. `grendel config` `targets` becomes add/remove; new pure `_add_target`/`_remove_target`. Additive.
3. New `examples/langgraph-agent/` (example code + its own requirements). Not in `pyproject.toml`, not
   in the offline suite.
4. No scoring/records/runner/proxy/packloader change; exit codes unchanged; no secret written to
   disk. `questionary` already a dep; no new *package* runtime dep.

## 8. Testing strategy

- **Offline unit (pytest):** editable-targets add/remove via the letter-menu fallback (scripted stdin
  → saved YAML reflects the change; unknown-provider add → inline error, screen alive, nothing saved);
  logo renders and appears in the banner; `_add_target`/`_remove_target` pure-helper errors. Prior
  476 tests (1 skipped) stay green.
- **Live manual (this phase's bar):** the two §6 end-to-end runs against the real OpenAI API succeed;
  captured as a summary (no secrets) in `test-report.md`.
- No network / no key in the offline suite; the live runs are explicitly out-of-suite.

## 9. Acceptance criteria

Phase 16 is done when:
1. `ruff check .` + `ruff format --check .` clean; `pytest` green offline (476 prior + new
   editable-targets/logo tests), no key/network in the suite.
2. The app has a **logo** (bare `grendel` + `grendel config` header) and is noticeably **easier to
   use** (helpful hints, editable targets from the menu).
3. **Targets are add/remove-editable** from `grendel config` (validated, saved), via arrow-keys and
   the letter fallback.
4. A **LangGraph agent** exists in `examples/langgraph-agent/` with a tool and a configurable
   base_url, runnable directly and behind `grendel proxy`.
5. **End-to-end works flawlessly (live):** a direct real-API `grendel run` and a proxy-fronted agent
   run both complete and produce a sane report; summarized (no secrets) in `test-report.md`.
