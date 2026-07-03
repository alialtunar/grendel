# Phase 15 — Control-center TUI (the whole tool from one terminal screen): spec

> Phase 15 — a follow-on UX phase. Implements ROADMAP §8.15: *"`grendel tui` opens a Textual control
> center: a home menu that drives every operation without memorizing commands — launch a run (pick
> target + packs → the live scoreboard), configure everything (targets, proxy routes, judge, run
> options) and save to the config file, browse the catalog and import corpora, configure + start the
> proxy, and open past-run reports/diff, plus a doctor status view. It wraps the existing engines —
> no new engine."*
>
> **The deliverable:** a new `grendel tui` command that opens a **Textual control center** — a home
> menu whose entries push dedicated screens: **Doctor** (a boxed status report: version, env keys,
> targets/providers, catalog counts, proxy — the "welcome" panel), **Config** (view + edit targets /
> proxy routes / judge / run options and **save** to the config YAML), **Run** (pick a target + packs
> → the live Phase-5/11 scoreboard), **Packs** (browse the catalog + **import** a garak corpus), and
> **Proxy** (configure routes + **serve** the zero-touch endpoint). Every screen is a thin driver over
> code that **already exists** (`build_scoreboard`/`ScoreboardApp`, `load_catalog`/`list_packs`,
> `corpus.import_corpus`, `proxy.ProxySession`/`serve`, the config models) — this phase adds **no new
> engine**, only the terminal front door.
>
> **Additive + CLI-preserving.** The plain `grendel run/list/report/diff/update/proxy/import`
> commands keep working **byte-for-byte**; `grendel` with no args still prints help. `grendel tui` is
> a new command. Reused engines are unchanged in behaviour; the scoreboard is refactored into a
> reusable `ScoreboardScreen` **without changing what `run --tui` does**. **Offline + deterministic:**
> every screen is exercised by Textual `run_test` pilot tests with fakes (a fake run engine, the
> garak fixture, a `MockTransport` proxy upstream) — **no network, no API keys, no real serve loop in
> the suite**; pure helpers (`doctor_report`, `save_config`, the menu model) are unit-tested. No new
> runtime dependency (Textual is already a dep). The prior **508** tests (1 skipped) stay green.

---

## 1. Goals

1. **`grendel tui` — one screen to drive everything.** A `ControlApp` (Textual) whose **home menu**
   lists Run / Config / Packs / Proxy / Doctor; `enter` pushes that screen, `escape`/`q` returns to
   the menu (or quits from the menu). No command memorization: the TUI is the front door.
2. **Doctor status view (the "welcome" panel).** A boxed, sectioned report — grendel version,
   provider presets + configured targets, catalog counts (bundled/user/feed), proxy host/port/routes,
   which provider **env keys are set** (name + ✓/✗, never the value), and the judge on/off — computed
   by a **pure** `doctor_report(config) -> DoctorReport` and rendered as framed panels (the OpenClaw
   look). Read-only.
3. **Config editor + save.** A screen to view/edit the config: **run options** (output_dir,
   concurrency, max_tokens, temperature), **judge** (enabled, target), **proxy** (host, port, routes
   add/remove), and **targets** (list; add an HTTP target from provider+model). Edits update an
   in-memory `GrendelConfig`; **Save** writes it to the config path via a new pure
   `save_config(cfg, path)` (round-trips through `load_config`). Validation errors surface inline (no
   crash).
4. **Run from the TUI.** A **Run setup** screen: choose a target (a configured target **or** an
   ad-hoc provider+model, reusing the Phase-12 flag-target synthesis) and select packs (from the
   catalog), then launch the **live scoreboard** — the existing Phase-5/11 view, refactored into a
   reusable `ScoreboardScreen` the control center pushes and `run --tui` also uses. The run drives the
   real `Runner` via the same `on_attempt` engine hook.
5. **Packs browse + import.** A screen listing the catalog (id / category / OWASP / source, reusing
   `list_packs`) and an **import** action that runs `corpus.import_corpus("garak", path, out)` and
   reports the result — the Phase-14 pipeline, from the UI.
6. **Proxy configure + serve.** A screen to edit proxy host/port/routes (reusing the `ProxyConfig`
   validation) and **start serving** (the Phase-13 `ProxySession`/`serve`) in a background worker,
   with a live status line + a stop action — the zero-touch endpoint, launched from the UI.
7. Everything `pytest`-testable, **offline + deterministic**. Prior 508 tests (1 skipped) stay green;
   `run --tui` behaviour is unchanged.

---

## 2. Scope

**In scope**
- `src/grendel/tui/app.py` (REFACTOR, behaviour-preserving): extract the scoreboard's compose +
  `update_widgets` + actions into a **`ScoreboardScreen(Screen)`**; `ScoreboardApp(App)` becomes a
  thin wrapper that pushes `ScoreboardScreen` and **forwards `.state`, `.last_repro`, the action
  methods, and the widget query targets** so the existing `test_tui_app.py` pilot tests keep passing
  (any unavoidable test adjustment is enumerated in §7). `run --tui` is unchanged.
- `src/grendel/tui/doctor.py` (NEW): `DoctorReport` (frozen dataclass of sections) +
  `doctor_report(config: GrendelConfig, *, env: Mapping[str,str] | None = None) -> DoctorReport` —
  pure (env injected for tests; never reads real secrets, only presence of the named vars).
- `src/grendel/tui/control.py` (NEW): `ControlApp(App)` + the screens (`HomeScreen`, `DoctorScreen`,
  `ConfigScreen`, `RunSetupScreen`, `PacksScreen`, `ProxyScreen`). Each screen is a thin driver;
  cross-screen state (the working `GrendelConfig`, the config path) lives on the `ControlApp`.
- `src/grendel/config.py` (EXTEND): `save_config(config: GrendelConfig, path: Path) -> None` — pure,
  `yaml.safe_dump(config.model_dump(by_alias=True, mode="json"))` (round-trips through `load_config`).
- `src/grendel/cli.py` (EXTEND): a `tui` command — `grendel tui [--config C]` builds the working
  config and runs `ControlApp`. (A thin launch; the heavy logic is in `control.py`.)
- Tests: `tests/test_tui_doctor.py` (pure `doctor_report`), `tests/test_config_save.py`
  (`save_config` round-trip), `tests/test_tui_control.py` (`run_test` pilot: home menu navigation;
  each screen mounts + its key action works with fakes — Config edit+save, Packs import via the
  fixture, Proxy config validate, Run setup → a **fake** engine drives the scoreboard screen; Doctor
  renders), and the existing `test_tui_app.py` kept green (with any enumerated adjustment).

**Out of scope (deferred / non-goals)**
- **A reports/diff *screen*.** ROADMAP §15 lists reports/diff; to keep the phase bounded, the MVP
  ships Run/Config/Packs/Proxy/Doctor. Reports browsing is a **documented follow-on** (the `report`/
  `diff` CLI commands already cover it). *(If it lands, it is a thin `ReportsScreen` over the existing
  `reports`/`diff` renderers — no new engine.)*
- **A mouse-driven / themed redesign.** Keyboard navigation + the existing TCSS palette; framed
  panels for Doctor. No web, no charts.
- **Editing every config field.** The editor covers the high-value fields (run options, judge, proxy
  routes, add-HTTP-target); exotic fields (custom providers, catalog feeds, retry tuning) stay
  file-only for now (documented). No schema change.
- **Changing `run --tui`, the CLI commands, or any engine.** The TUI wraps them; it does not alter
  scoring/records/runner/proxy/catalog behaviour. Bare `grendel` still prints help (no auto-launch).
- **Running the blocking proxy `serve_forever` on the UI thread or in the test suite.** Serve runs in
  a Textual worker/thread with a stop action; tests never bind a real long-lived loop (the proxy
  screen's serve is monkeypatched / driven with the make_server+stop_server seam offline).

---

## 3. Navigation model (pure + testable)

- `ControlApp` holds `self.config: GrendelConfig`, `self.config_path: Path | None`, and pushes
  screens. The **home menu** is a `ListView`/`OptionList` of `(key, label, screen)` entries; `enter`
  pushes, `escape` pops back to home, `q` quits from home. The menu entries are a module constant
  (`MENU: list[MenuItem]`) so the set + order is unit-testable without Textual.
- Each screen has a `BINDINGS` footer (its actions + `escape` back). No global mutable singletons;
  screens read/update `self.app.config`.

---

## 4. Doctor report (§2 `doctor.py`) — the welcome panel

`doctor_report(config, *, env=None)` returns a `DoctorReport` with sections (each a title + a list of
`(label, value, ok: bool|None)` rows), covering: **Install** (version, `grendel` importable),
**Targets & providers** (preset names; configured target names + provider/model), **Env keys**
(each preset's `api_key_env` → ✓ set / ✗ missing, from the injected `env`; **values never shown**),
**Catalog** (bundled count via `load_catalog`/`list_packs`; user pack_dirs; feeds), **Proxy**
(host:port + routes or "none"), **Judge** (enabled + target). Pure and deterministic (env + config
injected). `DoctorScreen` renders each section as a Textual `Static`/panel with a border (the framed
OpenClaw look); a small renderer maps `ok=True/False/None` → ✓/✗/·. Unit-tested on a synthetic config
+ env (no real environment read in the assertion).

## 5. Config editor + `save_config`

- `save_config(cfg, path)`: `path.write_text(yaml.safe_dump(cfg.model_dump(by_alias=True,
  mode="json"), sort_keys=False))`. A round-trip test asserts `load_config(path)` reproduces the
  config (targets, proxy, judge, run). Pure; no I/O beyond the one write.
- `ConfigScreen`: `Input` widgets for run options + judge + proxy host/port bound to
  `self.app.config`; an "add route" (`PATH=PROVIDER`, validated like the CLI) and "add target"
  (provider+model → `with_cli_target`-style, but persisted under a user-named key) row; a **Save**
  action (`ctrl+s`) → `save_config(self.app.config, path)` with an inline "saved → PATH" / error
  message. A bad value (e.g. port out of range) shows the validation error inline; the screen never
  crashes.

## 6. Run / Packs / Proxy screens (thin drivers over existing engines)

- **RunSetupScreen:** a target selector (configured targets + an "ad-hoc" provider/model form reusing
  the Phase-12 `_cli_target` synthesis) + a pack multi-select (from `_load_attacks`); "Start" builds
  the record + the `Runner` engine (the same closure `cli.run --tui` builds) and pushes the
  `ScoreboardScreen` with that engine. Offline test: a **fake engine** (scripted `AttemptRecord`s,
  the existing `test_tui_app` pattern) drives the pushed scoreboard; assert the grid/stream fill.
- **PacksScreen:** a table from `list_packs(config)`; an "import" form (source=garak, path, out) →
  `corpus.import_corpus(...)` → a result line; after import the table refreshes. Offline test: import
  the bundled `tests/fixtures/garak` into a tmp dir → the result line shows `imported 5`.
- **ProxyScreen:** host/port/route inputs (validated via `ProxyConfig` + the known-provider check);
  "Serve" → a worker thread runs `proxy.make_server(session, host, port)` then `httpd.serve_forever()`
  + a status line + "Stop" → `proxy.stop_server`. Offline test: drive the config + validation and the
  serve/stop seam by **monkeypatching** `make_server`/`stop_server`/the serve-worker (asserting the
  captured session + a clean stop) — never a real socket bind or long-lived loop in the pilot suite
  (real-socket coverage lives in `test_proxy_server.py`).

## 7. Deliberate contract updates (enumerated)

1. **New `grendel tui` command** and new modules `tui/control.py`, `tui/doctor.py`; `config.py` gains
   `save_config`. Additive.
2. **`tui/app.py` refactor:** the scoreboard becomes `ScoreboardScreen` (owns view state + render +
   actions + `record` + `state`); `ScoreboardApp` is a thin wrapper that pushes it and exposes
   read-through `@property` `state`/`record` (→ the screen) while **keeping `_clipboard_write` and
   `last_repro` App-owned** (the screen's copy action delegates to `self.app._clipboard_write` and
   sets `self.app.last_repro`). No App-level `action_*` wrappers are added — `pilot.press` resolves
   actions on the active screen. `App.query_one` already searches the active screen. Goal +
   expectation: `test_tui_app.py` is **untouched** and `run --tui` behaves identically.
3. No change to CLI command behaviour, scoring, records, runner, proxy, catalog, or config schema.
   Bare `grendel` still prints help. No new runtime dependency.

## 8. Testing strategy (offline + deterministic)

- **Pure** (`test_tui_doctor.py`, `test_config_save.py`): `doctor_report` sections/rows on a
  synthetic config + injected env (env keys ✓/✗ correct, no value leaked); `save_config` →
  `load_config` round-trip equality; the `MENU` model (entries/order).
- **Pilot** (`test_tui_control.py`, Textual `run_test`, offline): launch `ControlApp`; navigate the
  home menu (enter pushes each screen, escape returns); **Config** edits a run option + saves →
  asserts the file loads back with the change; **Packs** imports the garak fixture → the result line;
  **Proxy** validates a route + a bad port (inline error, no crash); **Run** setup → a fake engine
  fills the pushed `ScoreboardScreen`. Deterministic across repeated runs (the Phase-5/11 pattern).
- **Regression:** `test_tui_app.py` (scoreboard) stays green — `run --tui` unchanged; the full CLI
  suite unchanged.
- **No network, no API keys, no real serve loop, no real corpus download.** Prior 508 tests (1
  skipped) pass; only the additive §7 items.

## 9. Acceptance criteria

Phase 15 is done when:
1. `ruff check .` + `ruff format --check .` clean; `pytest` green **offline, no keys/network**; the
   prior 508 tests (1 skipped) pass plus the new doctor/config-save/control tests; `run --tui` and all
   CLI commands behave identically.
2. **`grendel tui` opens a control center:** a home menu drives Run / Config / Packs / Proxy / Doctor;
   every screen is a thin driver over the existing engines (scoreboard, import_corpus, ProxySession,
   config), asserted by `run_test` pilot tests.
3. **Configurable from the screen:** the Config editor edits run/judge/proxy/targets and **saves** to
   the config YAML (round-trips through `load_config`); Doctor shows the framed status (version, env
   keys ✓/✗, catalog, proxy, judge).
4. **Operable from the screen:** a run launches the live scoreboard; a garak import runs from Packs;
   the proxy configures + serves from Proxy — all offline-testable, no engine changed.
5. Additive + CLI-preserving; no new dependency; `run --tui` and bare-`grendel`-help unchanged.
