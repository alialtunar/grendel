# Phase 13 — implementation plan

Derived from `phases/phase-13/spec.md`. Two milestones, each ending in a verifiable checkpoint
(`ruff` clean + `pytest` green + `reviewer`/`tester` `STATUS: PASS`). Milestone 1 is the pure/async
proxy core (routing, injection, forwarding, outcome extraction, scoring+recording via `handle`,
tested offline with an injected `MockTransport`); Milestone 2 is the stdlib HTTP server + the CLI
`proxy --serve` wiring + one localhost round-trip. **No scoring/records/config/runner/adapter
behaviour changes** — the proxy consumes `ProxyConfig` (Phase 12) and reuses `Scorer.score_async`.

---

## Milestone 1 — Proxy core (pure helpers + `ProxySession.handle`, offline)

**Intent:** implement the whole request lifecycle as a testable async unit with an injected httpx
client — no socket, no network.

**Steps**
1. **`proxy.py` — pure helpers:**
   - `select_route(path, proxy: ProxyConfig) -> str | None`: longest path-prefix in `proxy.routes`
     that `path` starts with → provider name; else None. (Deterministic; ties broken by longest.)
   - `inject_attack(body: dict, attack: Attack) -> dict`: deep-copy `body`; append a message per
     `attack.surface` (§3 of spec): `prompt`/default → `{"role":"user","content":payload}`;
     `tool-output` → `{"role":"tool","content":payload,"tool_call_id":"grendel-injected"}`. Never
     mutate the input. Missing/empty `messages` → create the list.
   - `build_upstream_request(preset, base_url, incoming_headers, body) -> (url, headers, body)`:
     compute the upstream URL for the preset's `api_style` (openai/openrouter/openai-compatible →
     `{base_url}/chat/completions`; anthropic → `{base_url}/messages`; ollama → `{base_url}/api/chat`)
     — reuse the endpoint suffixes from `http_adapter._build_request`. Headers: start from
     `preset.default_headers`, then **forward the agent's `Authorization`** (and, for anthropic,
     `x-api-key`/`anthropic-version` if the agent sent them) verbatim — Grendel injects **no** key.
     Body is passed through (already injected).
   - `extract_outcome(api_style, upstream_json) -> (text, tool_calls)`: openai → text =
     `choices[0].message.content or ""`, tool_calls from `choices[0].message.tool_calls` (each
     `{"function":{"name","arguments"(JSON str)}}` → `{name, args(parsed, {} on bad JSON), ordinal}`);
     anthropic → text = first `text` block, tool_calls from `tool_use` blocks (`{name, input}` →
     `{name, args, ordinal}`); ollama → text = `message.content`, tool_calls from
     `message.tool_calls` if present. No tool-calls key at all → `tool_calls=None` (tri-state,
     matching AdapterResponse); an empty tools list → `[]`.
2. **`proxy.py` — `ProxySession`:**
   - `__init__(self, config: GrendelConfig, attacks: list[Attack], *, client: httpx.AsyncClient,
     scorer: Scorer | None = None, record: RunRecord | None = None)`: stores config/attacks/client;
     `scorer = scorer or Scorer()`; builds/holds a `RunRecord` (target_name="proxy",
     provider/model set from the first route or "proxy"/"(various)"); `self._i = 0` attack cycler.
   - `def _next_attack(self) -> Attack`: **thread-safe** cycler — a `threading.Lock` guards
     `attacks[self._i % len(attacks)]; self._i += 1` (the threaded server can dispatch concurrent
     requests). A concurrency test asserts no duplicate/skipped index across parallel `handle` calls.
   - `async handle(self, path, headers, body_bytes) -> (status:int, resp_headers:dict, body:bytes)`:
     1. `provider = select_route(path, config.proxy)`; None → `(404, {...}, b'{"error":"no route ...}')`
        (no attack recorded).
     2. Parse `body_bytes` as JSON; not a chat request (no `messages`) → `(400, …)`.
     3. `attack = self._next_attack()`; `injected = inject_attack(body, attack)`.
     4. Resolve the provider preset (`resolve_provider(provider, config)`) + its base_url
        (`_resolve_base_url`-style; error → ERROR attempt + 502 to agent).
     5. `url, up_headers, up_body = build_upstream_request(preset, base_url, headers, injected)`.
     6. `resp = await self._client.post(url, json=up_body, headers=up_headers)`; on httpx error or
        non-2xx → record an ERROR `AttemptRecord` (error text) and return a clean error response
        (`resp.status_code` passthrough if we have one, else 502) — the agent never hangs.
     7. `text, tool_calls = extract_outcome(preset.api_style, resp.json())`; build
        `AdapterResponse(text, tool_calls, provider=preset.name, model=up_body.get("model",""),
        raw=json)`; `result = await scorer.score_async(attack, response_text=text, response=resp_ar)`.
     8. Append an `AttemptRecord` (attack_id, category, prompt=payload, response_text=text,
        tool_calls=tool_calls or [], tool_observed=(tool_calls is not None), verdict/score_tier/
        score_detail from `result`, latency) to `self.record`.
     9. Return `(resp.status_code, passthrough_headers, resp.content)` — the agent gets the upstream
        reply **unchanged**.
   - A small `_error_body(msg) -> bytes` helper (OpenAI-shaped `{"error": {"message": msg}}`).
3. **Tests** (`test_proxy_core.py`): every pure helper (§7 of spec) + `handle` end-to-end with an
   injected `httpx.AsyncClient(transport=httpx.MockTransport(handler))`:
   - `inject_attack` parametrized over `prompt`, `tool-output`, **and `rag`/`mcp-desc` (fallback →
     appended user message)**, asserting the input body is not mutated.
   - tool_calls completion + a side-effect attack → `AttemptRecord.tool_calls` normalized, verdict
     FAIL, tier T4; benign text + string attack → scored via T1; pass-through bytes equal upstream;
     upstream 500 → ERROR attempt + error response; **a route → provider with no resolvable
     `base_url` → ERROR attempt + clean 502**; **a body that fails `json.loads` → 400, no attempt
     recorded**; the agent `Authorization` reached upstream (assert inside the MockTransport handler)
     **and does NOT appear anywhere in `session.record.model_dump_json()`** (no key leakage); N calls
     → N attempts in cycle order; a **concurrency** case (`asyncio.gather` of several `handle` calls)
     → no duplicate/skipped attack index, N `AttemptRecord`s.

**Checkpoint 1:**
- `ruff` clean; `pytest` green: prior 465 (1 skipped) + `test_proxy_core.py`.
- `handle` scores + records correctly offline (MockTransport), pass-through verified, key forwarded.
- `reviewer` + `tester` → `STATUS: PASS`.

---

## Milestone 2 — Stdlib HTTP server + `grendel proxy --serve` + localhost round-trip

**Intent:** expose the core as a real OpenAI-compatible endpoint via stdlib `http.server`, wire the
CLI, and prove the socket path with one deterministic localhost test.

**Steps**
1. **`proxy.py` — server on a SINGLE persistent event loop (avoids cross-loop httpx reuse):**
   - `make_server(session, host, port) -> ThreadingHTTPServer`: create **one** `asyncio` event loop,
     run it in a daemon thread (`loop.run_forever()`), and build a `ThreadingHTTPServer` whose
     `BaseHTTPRequestHandler.do_POST` dispatches **every** request onto that one loop via
     `asyncio.run_coroutine_threadsafe(session.handle(path, headers, body), loop).result(timeout)`.
     Because all `handle` coroutines (and thus the session's single `httpx.AsyncClient`) run on the
     **one** loop, the client is never used across loops — the reviewer's cross-loop hazard is
     structurally avoided (NOT `asyncio.run` per request). Store `loop`/`thread` on the server for
     shutdown. `stop_server(httpd)`: `httpd.shutdown()`, `loop.call_soon_threadsafe(loop.stop)`,
     join both threads, then `run_coroutine_threadsafe(session.aclose(), …)` is not possible after
     stop — so close the client via a final scheduled coroutine *before* stopping the loop (or the
     CLI closes it after `serve` returns by running one last loop). Keep it simple: `stop_server`
     schedules `session.aclose()` on the loop, waits, then stops the loop.
   - `do_POST` is wrapped in a **try/except that always writes a well-formed response** (never lets an
     exception escape to the handler default): read `Content-Length` (missing/invalid → 400), read the
     body bytes, dispatch; any exception → a 500 with an OpenAI-shaped error body. JSON/chat-shape
     validation stays inside `handle` (testable without a socket). Non-POST methods → 405.
   - `serve(session, host, port)`: `make_server` + print the startup banner (bound `host:port`,
     routes, attack count, the agent `base_url` hint) + `serve_forever()`; returns after
     `stop_server`. The blocking `serve_forever` is only used by the CLI; tests use `make_server` +
     a background thread + `stop_server` so nothing blocks the suite.
2. **`cli.py` — extend `proxy`:** add `--serve` (bool), `--pack` (repeatable), `--out` (Path). When
   `--serve`:
   - after the Phase-12 merge/validate, require `merged.routes` non-empty (else exit 2);
   - load attacks (`_load_attacks(cfg)` + `_select_attacks(..., pack)`; empty → exit 2);
   - set `cfg.proxy = merged`; **wire the judge like `run` does** — if `cfg.judge.enabled` (or a
     `--judge/--no-judge` override), build the scorer via the existing `_build_judge_scorer(cfg,
     dry_run=False)` and pass it (+ remember the judge adapter to `aclose()` on shutdown); else
     `Scorer()`. This closes the reviewer's "T3 silently unreachable" gap — the proxy honors a
     configured judge exactly as `run` does; build `ProxySession(cfg, attacks,
     client=httpx.AsyncClient(), scorer=scorer)`;
   - `serve(session, merged.host, merged.port)`; on `KeyboardInterrupt`/return, write the record to
     `--out` or `cfg.run.output_dir`, print `_summary`, and `aclose()` the judge adapter if any.
   Without `--serve`: unchanged Phase-12 preview.
3. **Tests:**
   - `test_proxy_server.py`: `make_server` on `("127.0.0.1", 0)` with a `ProxySession` whose upstream
     is a `MockTransport`; the server runs its own loop thread + `serve_forever` in a
     `threading.Thread`; POST **two sequential** chat-completions requests to
     `http://127.0.0.1:{port}/openai/v1/chat/completions` via `httpx.Client` — the second request is
     the real regression guard for the single-loop client reuse (a broken per-request-loop design
     fails here). Assert each response body equals the mocked upstream and `session.record` has **2**
     attempts; then `stop_server(httpd)` + join in a `finally`. Deterministic; localhost only;
     upstream mocked; nothing blocks the suite.
   - `test_cli_proxy.py` (extend): `proxy --serve` with no route → exit 2; with a route but no
     selectable attacks → exit 2; `proxy --serve` happy path with `proxy.serve` **monkeypatched** to
     capture the `ProxySession` (assert host/port/routes/attack count + the startup banner) so no
     socket binds in the CLI unit test; the no-`--serve` preview path stays green.

**Checkpoint 2 (phase close):**
- `ruff` clean; `pytest` green: 465 prior (1 skipped) + core + server + CLI proxy tests; the
  localhost round-trip is deterministic (bind port 0, shutdown in-test); offline.
- `grendel proxy --serve` serves an OpenAI-compatible endpoint, injects+forwards+scores+records, and
  returns the upstream reply unchanged; multi-provider routing + key forwarding verified.
- `reviewer` + `tester` → `STATUS: PASS`; `review.md` + `test-report.md` end in `STATUS: PASS`.

---

## Risks & mitigations
- **Blocking `serve_forever` hangs the test suite.** Mitigate: `make_server` returns the
  `HTTPServer` (with its loop thread); tests run `serve_forever` in a daemon thread and call
  `stop_server(httpd)` in a `finally`; the CLI unit test monkeypatches `serve`. No test calls a
  blocking serve on the main thread.
- **Cross-event-loop `httpx.AsyncClient` reuse (reviewer item 1).** Mitigate structurally: the server
  runs **one** persistent asyncio loop in a background thread and dispatches every request onto it via
  `run_coroutine_threadsafe`, so the single client is always used on the one loop it was first used
  on — NOT `asyncio.run` per request. The two-sequential-request round-trip test is the regression
  guard.
- **Attack-cycler race (reviewer item 2).** Mitigate: a `threading.Lock` around `_next_attack`; a
  concurrency test asserts no duplicate/skipped index.
- **T3 judge silently unreachable (reviewer item 3).** Mitigate: the CLI `--serve` path reuses
  `_build_judge_scorer(cfg, dry_run=False)` when the judge is enabled (same as `run`), and closes the
  judge adapter on shutdown.
- **Ungraceful shutdown loses in-memory attempts (accepted non-goal).** The record is written only on
  clean shutdown (spec §2); a SIGKILL/crash loses attempts since start. Documented limitation for the
  MVP, not an oversight.
- **Anthropic request-shape mismatch.** The agent speaks OpenAI shape; an `anthropic` route forwards
  headers/url but not a body translation (spec §2 non-goal). Mitigate: `extract_outcome` supports
  the anthropic *response* shape; the spec documents that anthropic upstreams need an
  OpenAI-compatible gateway or a provider-shaped agent — the MVP focus is openai/openrouter/custom.
- **tool_calls arguments are a JSON string (OpenAI) vs dict (Anthropic).** Mitigate: `extract_outcome`
  parses the OpenAI `arguments` string with `json.loads` guarded by try/except → `{}` on failure;
  a unit test covers a malformed-arguments case.
- **Key leakage into logs/records.** Mitigate: the forwarded `Authorization` is never written to the
  `RunRecord` (only prompt/response/tool_calls are recorded); a test asserts no `Authorization`
  value appears in the serialized record.
