# Phase 21 — implementation plan

Derived from `phases/phase-21/spec.md`. Two milestones, each ending in a checkpoint
(`ruff` clean + `pytest` green + `reviewer`/`tester` `STATUS: PASS`).

---

## Milestone 1 — Live model discovery (fetch + static fallback)

**Intent:** the model picker offers the provider's real, current models; static list is only a fallback.

**Steps**
1. **New `src/grendel/targets/model_list.py`** — `fetch_models(preset, api_key, *, client=None,
   timeout=4.0) -> list[str]`:
   - `api_style == "openai"`: `GET {base_url}/models`, `Authorization: Bearer {api_key}` when a key is
     present; parse `data[].id`.
   - `api_style == "anthropic"`: `GET {base_url}/models`, headers `x-api-key: {api_key}` +
     `preset.default_headers` (carries `anthropic-version`); parse `data[].id`.
   - `api_style == "ollama"`: `GET {base_url}/api/tags`; parse `models[].name`.
   - `custom` / no `base_url` / unknown: return `[]`.
   - Uses a sync `httpx.Client` (or the injected `client` for tests), short timeout. ANY failure
     (network, timeout, non-2xx, bad shape, missing key on a key-required style) → return `[]`, never
     raises. Results de-duped, order preserved (API order).
2. **`providers.py`** — broaden the static `models` fallbacks to a fuller current set per hosted preset
   (still suggestions, not closed): openai (gpt-4o family, o-series, gpt-4.1/4-turbo/3.5),
   anthropic (opus/sonnet/haiku current ids), openrouter (a handful of popular namespaced ids),
   ollama (llama3.x, mistral, qwen2.5, phi3, gemma2). `openai-compatible` stays empty.
3. **`cli.py` — `_prompt_model(provider, cfg)`**: on the TTY+questionary branch, before building
   choices: resolve the preset, read `api_key = os.environ.get(preset.api_key_env)` (None ok for
   ollama), call `fetch_models(preset, api_key)`; `live = that or _preset_models(...)`; use `live` for
   the choice list. The select prompt label shows the source/count, e.g. `model (openai · 63)` when
   fetched, `model (openai · suggestions)` when static. Non-TTY branch unchanged (typed, no fetch — so
   pipes/tests never hit the network). `_TYPE_ANOTHER` escape unchanged.
4. **Tests** (`test_model_list.py`): `fetch_models` for each style via `httpx.MockTransport` (openai
   `data[].id`, anthropic `data[].id` with x-api-key asserted, ollama `models[].name`); a non-2xx and
   a network error each → `[]`; `custom`/no-base_url → `[]`; missing key on openai still issues the
   request (mock returns list) but a 401 → `[]`. `providers.py` broadened lists asserted non-trivial
   (len >= 5 for openai/anthropic/ollama). The questionary integration stays offline-untestable
   (documented), consistent with the menu-test convention.

**Checkpoint 1:** ruff clean + pytest green; `reviewer` + `tester` `STATUS: PASS`.

---

## Milestone 2 — Rich live attack dashboard

**Intent:** a colorful real-time view of a menu run; plain counter remains the off-TTY/no-rich fallback.

**Steps**
1. **New `src/grendel/live.py`** (rich imported LAZILY inside functions so a missing rich never breaks
   module import):
   - `class LiveAttackRun`: `__init__(self, total, target_label)`; state counters `n, hits (FAIL),
     defended (PASS), errors (ERROR), skipped (SKIPPED)`, `recent = deque(maxlen=12)`.
   - `on_attempt(self, attempt)`: bump the counter for `attempt.verdict`, append `(verdict, attack_id,
     category)` to `recent`, `self._live.update(self._render())`. Wrapped so a render error can't
     crash a run.
   - `_render(self)`: a `rich.console.Group` of — a header (`GRENDEL · vs {target_label}`), a manual
     bar (`█`×filled + `░`×rest, width ~24) with `ASR {asr:.0%}` + `{n}/{total}` + colored counts
     (`[red]✗{hits}[/] [green]✓{defended}[/] [yellow]⚠{errors}[/]`), then the `recent` stream newest-
     first: per line a colored glyph+verdict+`attack_id` (`FAIL`→red `✗ HIT`, `PASS`→green `✓ def`,
     `ERROR`→yellow `⚠ err`, `SKIPPED`→dim `· skip`). ASR = `hits/(hits+defended)` (0 when none scored).
   - `__enter__`: create `Console()` + `Live(self._render(), refresh_per_second=12, transient=False)`,
     start it, return self. `__exit__`: stop the Live (leaves the final frame on screen).
   - `make_live_run(total, target_label) -> LiveAttackRun | None`: return `None` when
     `not sys.stdout.isatty()` OR `import rich` fails; else the instance.
2. **`cli.py` — `_menu_run`**: build `live = make_live_run(len(selected), f"{target} ({provider}/
   {model})")`. If `live` is not None: `with live: asyncio.run(_execute(..., on_attempt=live.on_attempt))`.
   Else keep the current path: `on_attempt = _run_progress(len(selected))`, run, and
   `if on_attempt is not None: typer.echo("")`. Summary + `_pause_menu()` afterward unchanged. (The
   plain `_run_progress` stays as the no-rich/off-TTY fallback.)
3. **`pyproject.toml`** — add `rich>=13` to `dependencies` (already present transitively via typer;
   made explicit because we now import it directly).
4. **Tests** (`test_live_dashboard.py`): `make_live_run` returns `None` off-TTY (CliRunner/pytest is
   non-TTY). `LiveAttackRun` counter math: feed fake attempts (objects with `.verdict.name`,
   `.attack_id`, `.category`) → assert `hits/defended/errors/n` and the computed ASR. `_render()`
   smoke: render the Group to text via a `rich.console.Console(file=StringIO, force_terminal=False)`
   and assert it contains the target label, the counts, and a recent `attack_id` (no exception, no
   color codes needed). The live-on-TTY wiring in `_menu_run` stays offline-untestable (documented),
   but the fallback path is already covered by the existing `test_cli_run_flow`/`test_cli_home` runs.

**Checkpoint 2 (phase close):** full suite green + ruff clean; `reviewer` + `tester` `STATUS: PASS`;
append `phase 21: DONE …` to `PROGRESS.md`.

---

## Plan review — addressed
- (1) `fetch_models` builds auth headers CONDITIONALLY — set `Authorization`/`x-api-key` only when
  `api_key` is truthy; `None` is never passed as a header value (would `TypeError`, uncaught). ollama
  sends no auth header. A key-required style with no key still issues the request; a 401/403 → `[]`.
- (2) live ASR excludes `is_control` attempts — `hits`/`defended` only bump when `not attempt.is_control`
  (controls may still appear in the `recent` stream), matching `records.py::_asr` so the live % equals
  the final summary/report ASR.
- (3) `_render()` guards `total = max(total, 1)` so the bar math can't ZeroDivisionError if the class is
  reused with `total == 0` elsewhere.
- (4) tests add the anthropic missing-key case (no `x-api-key` header sent; 401 → `[]`, no `TypeError`)
  alongside the openai one.
- (5) `live.py` carries a one-line comment: state mutation + `_render()` happen together on the asyncio
  thread before `Live.update()` (internally locked); the background refresh thread never calls
  `_render()` — don't move it off the mutating thread.

## Risks & mitigations
- **Network hang in the picker** → `fetch_models` uses a short timeout and swallows every error to
  `[]`; only called on the TTY branch, never in pipes/tests.
- **Stale static lists** → they're an explicit FALLBACK; live fetch is authoritative and always current;
  "✎ type another" guarantees any model is reachable.
- **rich missing / non-TTY** → `make_live_run` returns `None`; `_menu_run` keeps the plain `_run_progress`
  path; off-TTY output is byte-identical to today (tests unaffected).
- **Dashboard crashing a run** → `on_attempt` wraps its body; Runner already swallows a raising
  callback (logged, run continues); counters are plain ints mutated synchronously in the single asyncio
  thread (no lock needed).
- **New dependency** → rich is already installed transitively (typer); making it explicit is hygiene,
  not a real new install. Imported lazily so its absence degrades gracefully.
