# Phase 15 — implementation plan

Derived from `phases/phase-15/spec.md`. Three milestones, each ending in a verifiable checkpoint
(`ruff` clean + `pytest` green + `reviewer`/`tester` `STATUS: PASS`). M1 delivers the control-center
shell + the configurable interface (Doctor + Config), M2 adds Run (scoreboard refactor) + Packs, M3
adds Proxy. **No engine/CLI/scoring/records/config-schema behaviour changes** — every screen wraps
existing code; `run --tui` and the plain CLI stay identical.

---

## Milestone 1 — Control-center shell + Doctor + Config (the configurable interface)

**Intent:** `grendel tui` opens a navigable control center; Doctor shows the framed status, Config
edits + **saves** the config YAML — the OpenClaw-style configurable UI, with zero scoreboard-refactor
risk (this milestone doesn't touch `app.py`).

**Steps**
1. **`config.py` — `save_config`.** `def save_config(config: GrendelConfig, path: Path) -> None:
   path.write_text(yaml.safe_dump(config.model_dump(by_alias=True, mode="json"), sort_keys=False),
   encoding="utf-8")`. Pure. (Round-trips through `load_config` — `mode="json"` for enum/Path
   scalars; verified pattern from Phase 14.)
2. **`tui/doctor.py` (NEW).** `@dataclass(frozen=True) DoctorSection(title, rows: list[tuple[str,str,
   bool|None]])`; `DoctorReport(sections: tuple[DoctorSection,...])`; `doctor_report(config, *,
   env=None) -> DoctorReport` — pure, `env = env if env is not None else os.environ` (only reads
   **presence** of each preset's `api_key_env`, never the value). Sections: Install (version from
   `importlib.metadata.version("grendel")` guarded, importable), Targets & providers (PRESETS names;
   configured targets), Env keys (each preset api_key_env → set?), Catalog (counts via
   `list_packs(config=config)` grouped by source; user pack_dirs; feeds), Proxy (host:port + routes),
   Judge (enabled + target). A `render_section(section) -> str` maps ok True/False/None → ✓/✗/·.
3. **`tui/control.py` (NEW) — shell + Home + Doctor + Config.**
   - `MENU: list[MenuItem]` module constant (`MenuItem(key, label, screen_factory_name)`) — unit
     tested for entries/order without Textual.
   - `ControlApp(App)`: holds `config: GrendelConfig`, `config_path: Path | None`; `on_mount` pushes
     `HomeScreen`; a `CSS_PATH` (small tcss, or reuse inline). Bindings: `q` quit (from home).
   - `HomeScreen(Screen)`: an `OptionList`/`ListView` of `MENU` labels; `enter` → `app.push_screen`
     of the chosen screen; footer shows keys.
   - `DoctorScreen(Screen)`: on mount, `doctor_report(app.config)` → render each section into a
     bordered `Static`; `escape` back.
   - `ConfigScreen(Screen)`: `Input`s for `run.output_dir/concurrency/max_tokens/temperature`,
     `judge.enabled`(a `Switch`)/`judge.target`, `proxy.host/port`; an "add route" input
     (`PATH=PROVIDER`, validated like the CLI proxy) and "add target" (provider+model → a
     `TargetConfig` stored under a user key via `config.with_cli_target(name, tc)` reused, or a small
     inline add); a `ctrl+s` **Save** action → validate into the working `GrendelConfig` (catch
     `ValidationError`/`ConfigError` → inline error `Static`, no crash) then `save_config(app.config,
     app.config_path)` (default path `grendel.yaml` in cwd when `config_path` is None) → inline
     "saved -> PATH".
4. **`cli.py` — `tui` command.** `grendel tui [--config C]`: `cfg = _resolve_config(ctx, config)`;
   `ControlApp(config=cfg, config_path=config).run()`. (Thin; heavy logic in `control.py`. A lazy
   `from .tui.control import ControlApp` so importing cli/plain paths never require the control app.)
5. **Tests:** `test_config_save.py` — **two** round-trips (reviewer item 8): (a) *loaded-then-saved*:
   a config with a target + proxy routes + judge, `save_config` → `load_config` reproduces it; (b)
   *never-loaded, default-path save*: a fresh `GrendelConfig()` (config_path `None`) with a Config-
   screen-added **relative** `catalog.pack_dir` saved to `grendel.yaml` in a tmp cwd → `load_config`
   of that file resolves the pack_dir relative to the file dir without error (the one place path
   resolution could diverge). Plus: `test_tui_doctor.py` (`doctor_report` on a synthetic
   config + injected env: env-key ✓/✗ rows correct, **no secret value in any row**, catalog count ==
   bundled 21, proxy/judge rows; `MENU` entries/order); `test_tui_control.py` M1 part (`run_test`:
   home menu lists the 5 entries; `enter` on Doctor pushes it and a version row renders; navigate to
   Config, set a run option Input, `ctrl+s`, then `load_config(path)` shows the change; a bad port →
   inline error, screen still alive).

**Checkpoint 1:**
- `ruff` clean; `pytest` green: prior 508 (1 skipped) + the new pure + control(M1) tests.
- `grendel tui` opens; Doctor renders framed status; Config edits + saves a loadable YAML; menu nav
  works — all via `run_test`, offline.
- `reviewer` + `tester` → `STATUS: PASS`.

---

## Milestone 2 — Run (scoreboard refactor) + Packs

**Intent:** launch the live scoreboard from the TUI, and browse+import the catalog — reusing the
Phase-5/11 scoreboard and the Phase-14 importer.

**Steps**
1. **`tui/app.py` — behaviour-preserving refactor to `ScoreboardScreen`.** Move `compose` +
   `update_widgets` + `_detail_text` + all `action_*` + `BINDINGS` + the live-engine plumbing
   (`on_mount`/`_run_engine`/`_post_attempt`/`on_attempt_recorded`) into a new
   `ScoreboardScreen(Screen)` (constructed with `attacks, record, target_name, engine`).
   `ScoreboardApp(App)` becomes a thin wrapper: `on_mount` → `push_screen(self._board)` where
   `self._board = ScoreboardScreen(...)` is built in `__init__`. **Exact forwarding contract** (from a
   `grep` of `tests/test_tui_app.py` — the only surface the suite touches on the app):
   - **Screen owns** the view state + render + actions + `record` (it mutates `record.attempts` on
     rerun) + `state`.
   - **App owns** `_clipboard_write` (wraps the App-only `copy_to_clipboard`; tests monkeypatch
     `app._clipboard_write` — it MUST stay an App method) and `last_repro` (a plain attribute).
     `ScoreboardScreen.action_copy_repro` delegates to `self.app._clipboard_write(text)` and sets
     `self.app.last_repro = text` (reviewer items 1–2).
   - **App read-through `@property`**: `state` → `self._board.state`; `record` → `self._board.record`
     (reviewer item 1 — `test_rerun_*` reads `app.record.attempts`).
   - **Do NOT add App-level `action_*` wrappers** — Textual resolves key-bound `action_<name>` on the
     active `Screen`; `pilot.press(...)` never calls `app.action_*` in this suite, so wrappers would
     be dead code (reviewer item 3). Only the four items above are functionally required.
   - **CRITICAL (empirically confirmed in Textual 8.2.7, M1 finding):** `App.query_one` searches only
     the App's **own** composed widgets (its default screen), **NOT** a pushed screen. So the naive
     "push a `ScoreboardScreen`" would break `test_tui_app.py`'s `app.query_one("#header")`. **Use a
     shared mixin, not a pushed screen for `ScoreboardApp`:** factor compose + `update_widgets` +
     `_detail_text` + actions + the engine plumbing into a `_ScoreboardUI` mixin that uses
     `self.query_one(...)`/`self.run_worker(...)`/`self.app` (all valid on both App and Screen).
     `ScoreboardApp(_ScoreboardUI, App)` **keeps composing the widgets on itself** (its default
     screen) so `app.query_one`, `app._clipboard_write`, `app.state`, `app.record`, `pilot.press` all
     resolve exactly as today → `test_tui_app.py` **untouched**. `ScoreboardScreen(_ScoreboardUI,
     Screen)` composes the same widgets on the screen for the control center (queried via
     `screen.query_one`). The mixin's copy action calls `self.app.copy_to_clipboard` via a
     `_clipboard_write` that exists on both hosts (App defines it; the Screen inherits a version that
     delegates to `self.app`). No `.state`/`.record` forwarding *properties* are needed on
     `ScoreboardApp` anymore (the widgets + state live on the app itself, as today) — the forwarding
     discussion above applies only if a push were used; the mixin avoids it entirely.
2. **Extract `build_cli_target_config` (pure) from `_cli_target`.** Factor the whole flag→
   `TargetConfig` synthesis out of the `typer`-coupled `_cli_target` into a plain helper that raises
   `ConfigError` (not `typer.Exit`). **All five usage-error branches** currently calling `_die`
   (→ `typer.Exit(2)`) must become `ConfigError` in the pure helper (reviewer item 5): (a)
   `--target` + flags both given, (b) more-than-one group, (c) `--provider`/`--model` not paired,
   (d) malformed `--header` (no `=`), (e) more-than-one mcp source — plus the trailing
   `with_cli_target` `ConfigError`. `_cli_target` becomes a thin wrapper: call
   `build_cli_target_config(...)`, translating `ConfigError` → `_die(...)` (exit-2 contract
   unchanged). A test asserts each of the five conditions raises `ConfigError` from the pure helper.
3. **`tui/control.py` — `RunSetupScreen`.** A target chooser (configured targets from `app.config`
   **or** an ad-hoc provider+model form) + a pack `SelectionList` from `_load_attacks(app.config)`;
   "Start" resolves the target via `build_cli_target_config(...)` for the ad-hoc case (catching
   `ConfigError` → inline error, no crash), builds the record + the `Runner` engine closure (the same
   one `cli.run --tui` builds), and `app.push_screen(ScoreboardScreen(selected, record,
   target_name=..., engine=engine))`.
4. **`tui/control.py` — `PacksScreen`.** A `DataTable` from `list_packs(config=app.config)` (id /
   category / owasp / source); an "import" form (path, out; source garak) → `corpus.import_corpus(...)`
   in a worker (or inline for a local path) → a result `Static` (`imported N …`); refresh the table
   after (append `out` to `app.config.catalog.pack_dirs` — an **in-place** append to the Pydantic
   list field; harmless here since `pack_dirs` has no cross-field validation, but noted so no one
   assumes the `with_cli_target` rebuild/revalidate applies here — reviewer item 10).
5. **Tests:** extend `test_tui_control.py`: RunSetup with a **fake engine** (the `test_tui_app`
   scripted-attempts pattern) → pushing the scoreboard screen fills the grid/stream (assert
   `screen.state.done`); Packs import of `tests/fixtures/garak` into a tmp `out` → result line
   `imported 5` and the table grows. Keep `test_tui_app.py` green.

**Internal gate (before step 3):** immediately after step 1 (the `app.py`→`ScoreboardScreen`
refactor), run **`pytest tests/test_tui_app.py`** alone and confirm green *before* writing
`RunSetupScreen`/`PacksScreen` — isolates a refactor regression from the new-feature work (reviewer
item 9).

**Checkpoint 2:**
- `ruff` clean; `pytest` green: 508 prior (1 skipped) + M1 + M2 tests; `test_tui_app.py` unchanged in
  behaviour (`run --tui` identical).
- From the TUI: a run launches the live scoreboard (fake-engine test); a garak import runs from
  Packs. Offline, deterministic.
- `reviewer` + `tester` → `STATUS: PASS`.

---

## Milestone 3 — Proxy screen (configure + serve) + phase close

**Intent:** configure and start the zero-touch proxy from the TUI, reusing Phase-13.

**Steps**
1. **`tui/control.py` — `ProxyScreen`.** Inputs for host/port + an "add route" (`PATH=PROVIDER`,
   validated via `ProxyConfig` + the known-provider check, reusing the CLI logic factored into a
   plain helper); a pack selector for what to inject; "Serve" → build a `ProxySession(app.config,
   attacks, client=httpx.AsyncClient())`, then in a **Textual worker thread**: `httpd =
   proxy.make_server(session, host, port)` **followed by `httpd.serve_forever()`** (reviewer item 6 —
   `make_server` only binds + starts the asyncio-loop thread; it does NOT accept connections, so the
   worker must call `serve_forever`). A live status `Static` (bound address + attempt count) and a
   "Stop" action → `proxy.stop_server(httpd)`. Never a blocking `serve_forever` on the UI thread.
2. **Tests:** extend `test_tui_control.py`: Proxy screen validates a good route + rejects a bad port
   / unknown provider (inline error, no crash); the serve/stop seam is exercised **offline by
   monkeypatching** `proxy.make_server`/`stop_server` (and the serve-worker) to capture the built
   session (assert host/port/routes/attack count) and confirm stop is called — **no real socket bind
   inside the Textual pilot test** (reviewer item 7 — spec §2/§8 forbid a real serve loop in the
   suite; a real port-0 bind + a second loop thread concurrent with Textual's loop risks Windows-CI
   flakiness). Real-socket serve/stop coverage stays in the existing `test_proxy_server.py`.
3. **Docs (light):** a short README/SETUP line: `grendel tui` opens the control center. Only touch a
   doc if a doc-marker test requires it; else skip.

**Checkpoint 3 (phase close):**
- `ruff` clean; `pytest` green: 508 prior (1 skipped) + all Phase-15 tests; deterministic; offline
  (no network, no API keys, no real long-lived serve loop, no corpus download).
- `grendel tui` drives Run / Config / Packs / Proxy / Doctor end-to-end over the existing engines.
- `reviewer` + `tester` → `STATUS: PASS`; `review.md` + `test-report.md` end in `STATUS: PASS`.
- Append `phase 15: DONE …` to `PROGRESS.md` (after the phase-14 line; keep `ALL PHASES COMPLETE` at
  the end, updated to include 15).

---

## Risks & mitigations
- **Scoreboard refactor breaks `test_tui_app.py` / `run --tui` (highest risk).** Mitigate: M2 keeps
  `ScoreboardApp`'s public surface identical by forwarding `.state`/`.last_repro`/`action_*` to the
  pushed `ScoreboardScreen`; `App.query_one` already searches the active screen; `pilot.press` routes
  to the active screen's bindings. Run `test_tui_app.py` as the guard after the refactor; enumerate
  any one-line adjustment. If forwarding is clean, that suite is untouched.
- **`_cli_target` is `typer`-coupled (calls `typer.Exit`).** Mitigate: extract the pure synthesis
  (`build_cli_target_config(...) -> TargetConfig`, raising `ConfigError`) so both the CLI wrapper and
  the TUI RunSetup use it; the CLI keeps its exit-2 behaviour, the TUI catches `ConfigError` inline.
  A test asserts the extracted helper's errors.
- **Blocking `serve_forever` / import hangs the UI or the suite.** Mitigate: serve via a worker
  thread that runs `make_server` then `serve_forever` (the Phase-13 seam), stopped with
  `stop_server`; the Textual pilot tests **monkeypatch** that seam (no real socket bind — real-socket
  coverage stays in `test_proxy_server.py`); imports run on a local fixture path. No test starts a
  real long-lived loop.
- **Secret leakage in Doctor.** Mitigate: `doctor_report` records only env-var **presence** (✓/✗),
  never the value; a test asserts no secret string appears in any rendered row.
- **Scope creep (Reports screen, full config coverage).** Mitigate: explicitly deferred in spec §2;
  MVP is Run/Config/Packs/Proxy/Doctor; the `report`/`diff` CLI already covers reports.
