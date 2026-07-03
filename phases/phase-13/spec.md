# Phase 13 — LLM-proxy: zero-touch agent testing: spec

> Phase 13 of 14 — **the core "test a real agent without any development" capability** (the primary
> zero-touch mechanism; the MCP-proxy idea was dropped). Implements ROADMAP §8.13: *"LLM-proxy —
> zero-touch agent testing — an OpenAI-compatible endpoint the user's agent points its `base_url`
> at (one setting, no code, no extra API). Grendel injects the attack into the passing prompt and
> reads the model's returned `tool_calls` (tool intent). Multi-provider routing (openai/anthropic/
> openrouter) by path; forwards the agent's own key."*
>
> **The deliverable:** a `grendel proxy --serve` mode — an **OpenAI-compatible HTTP endpoint** the
> user points their agent's `base_url` at (the *only* change they make). For each chat/completions
> call the agent makes, Grendel **injects an attack** into the outgoing prompt, **forwards** the call
> to the real upstream provider (routed by URL-path prefix, carrying the agent's *own*
> `Authorization` key), reads back the model's **`tool_calls`** (the tool *intent* the attack
> provoked) and text, **scores** the exchange with the existing Scorer (reusing T4 side-effect on the
> returned tool_calls, T1 string on the text), records an `AttemptRecord`, and returns the upstream
> response to the agent **unchanged** — the agent runs normally, unaware.
>
> **Built on Phase 12's `ProxyConfig`** (host/port/routes) — this phase makes `grendel proxy`
> actually serve using it. **Offline + deterministic:** the proxy core is a pure/async unit driven
> directly in tests with an injected httpx client (`MockTransport` upstream — no network); one
> localhost round-trip test binds an ephemeral port to prove the socket wiring, still with a mocked
> upstream. No new runtime dependency (stdlib `http.server` + the existing `httpx`). Scoring/records/
> config semantics are unchanged; the prior **465** tests (1 skipped) stay green.

---

## 1. Goals

1. **OpenAI-compatible proxy endpoint.** `grendel proxy --serve` binds `ProxyConfig.host:port` and
   accepts `POST` chat-completions requests exactly as an OpenAI-compatible server would, so an agent
   only changes its `base_url` (e.g. `http://127.0.0.1:8100/openai/v1`) — no code, no extra API.
2. **Attack injection into the passing prompt.** Each incoming request's messages are augmented with
   the current attack's payload (default: an appended `user` message carrying the payload; the
   attack `surface` selects the injected role — `prompt`→user, `tool-output`→a synthesized `tool`
   message), producing the modified body actually forwarded upstream. Pure + deterministic.
3. **Multi-provider routing by path + key forwarding.** The URL path prefix selects the provider via
   `ProxyConfig.routes` (`/openai`→openai, `/anthropic`→anthropic, `/openrouter`→openrouter, or any
   custom provider). The request is rewritten to the provider's `base_url` and the **agent's own
   `Authorization`** header is forwarded (Grendel adds no key of its own).
4. **Read the returned `tool_calls` (tool intent) + text; score + record.** The upstream response is
   parsed for `tool_calls` (OpenAI `choices[].message.tool_calls`; Anthropic `tool_use` content
   blocks) → normalized to the sandbox shape `[{name, args, ordinal}]` — and text. An
   `AdapterResponse(tool_calls=…, text=…)` is scored by the **existing** `Scorer.score_async` (T4
   side-effect asserts on the returned tool intent; T1 string on the text), and an `AttemptRecord` is
   appended to a `RunRecord`. On shutdown the record is written + a summary printed (same artifact
   the TUI/report/diff already consume).
5. **Zero-touch, transparent pass-through.** The agent receives the upstream response **unchanged**
   (Grendel is a transparent middlebox for the reply); it keeps working. Injection + scoring are
   side-band. Errors forwarding upstream are surfaced as an `AttemptRecord` ERROR, and the agent gets
   a well-formed error response (never a hang).
6. Everything `pytest`-testable, **offline + deterministic** (injected httpx `MockTransport`
   upstream; one localhost bind on port 0). Prior 465 tests (1 skipped) stay green.

---

## 2. Scope

**In scope**
- `src/grendel/proxy.py` (NEW): the proxy engine, split into **pure** helpers + an **async session**:
  - `select_route(path: str, proxy: ProxyConfig) -> str | None` — longest-matching path-prefix →
    provider name (None if no route matches).
  - `inject_attack(body: dict, attack: Attack) -> dict` — return a new body with the payload injected
    per `attack.surface` (pure; original untouched).
  - `build_upstream_request(preset, base_url, incoming_headers, body) -> tuple[str, dict, dict]` —
    upstream URL (provider endpoint for the api_style), forwarded headers (agent `Authorization`
    passed through; provider default headers merged), body (unchanged messages already injected).
  - `extract_outcome(api_style: str, upstream_json: dict) -> tuple[str, list[dict]]` — (text,
    normalized tool_calls) from an OpenAI/Anthropic/ollama response.
  - `ProxySession` — holds the `GrendelConfig`, the selected `list[Attack]` (an index cycler), the
    `Scorer`, an injected `httpx.AsyncClient` (real or `MockTransport`), and the growing `RunRecord`.
    `async handle(path, headers, body_bytes) -> tuple[int, dict, bytes]`: route → pick next attack →
    inject → forward upstream (agent key) → parse → score (`score_async`) → append `AttemptRecord`
    → return the **upstream** status/headers/body to the caller. A routeless path or a
    non-chat-completions POST → a clean 404/400 (no attack recorded).
  - `serve(session, host, port)` — a stdlib `http.server.ThreadingHTTPServer` +
    `BaseHTTPRequestHandler` that reads the POST body, runs `session.handle` (via `asyncio.run` per
    request or a shared loop), and writes the response. Graceful shutdown (SIGINT/`shutdown()`)
    writes the record + prints the summary.
- `src/grendel/cli.py` (EXTEND `proxy`): add `--serve` (bind + serve; default stays preview),
  `--pack` (repeatable; the attacks to inject — reuse `_select_attacks`), `--out` (record path),
  and reuse the Phase-12 `--host/--port/--route` merge. `proxy --serve` builds a `ProxySession`
  (config's `catalog` for the attack load, an owned `httpx.AsyncClient`) and calls `serve`.
- Tests: `tests/test_proxy_core.py` (routing, injection per surface, upstream build + key forwarding,
  outcome extraction for openai/anthropic, `handle` end-to-end with a `MockTransport` upstream →
  scored `AttemptRecord`, pass-through bytes, error path), `tests/test_proxy_server.py` (one
  localhost `serve` round-trip on port 0 with a mocked upstream — proves the socket + handler
  wiring), `tests/test_cli_proxy.py` (extend — `proxy --serve` argument wiring; still no real
  network in the test, the session/serve is monkeypatched or driven with a mock upstream + a
  background thread that is shut down deterministically).

**Out of scope (deferred / non-goals)**
- **Streaming (`stream: true`) responses.** MVP handles non-streaming JSON completions; a streaming
  passthrough is noted as future (the proxy forces/── documents non-stream for the injected call).
- **A production-hardened server** (TLS, auth, concurrency tuning, rate-limit). Stdlib threading
  server is sufficient for a local red-team tool; no ASGI/uvicorn dependency.
- **Rewriting the agent's tools or auto-executing tool_calls.** Grendel reads tool *intent* (the
  returned `tool_calls`); it never executes them (that is the sandbox's job, Phase 7). The proxy
  scores intent.
- **Non-OpenAI request *shapes* from the agent.** The agent speaks the OpenAI chat/completions shape
  to the proxy (the near-universal client contract). Upstream may be openai/openrouter (same shape)
  or anthropic (Grendel translates the *response* parse; the MVP forwards the OpenAI-shaped body to
  openai-compatible upstreams and, for an `anthropic` route, documents that the agent must speak the
  provider's shape or use an openai-compatible Anthropic gateway — the response tool_call extraction
  supports both shapes). *(Kept deliberately minimal; provider-shape translation of the request body
  beyond header/url routing is future.)*
- **Persisting per-request across restarts / a resumable proxy run.** The record is written on
  shutdown; mid-run persistence is out.

---

## 3. Injection strategy (per `attack.surface`)

`inject_attack(body, attack)` returns a deep-copied body with an added message:
- `surface: prompt` (default / jailbreak / prompt-injection): append `{"role": "user", "content":
  attack.payload}` after the agent's messages.
- `surface: tool-output`: append `{"role": "tool", "content": attack.payload, "tool_call_id":
  "grendel-injected"}` (a synthesized tool result — the indirect-injection vector).
- any other surface: fall back to the appended `user` message (documented).

The strategy is intentionally simple and pure; the *content* is the attack payload verbatim. The
attack id/category ride into the recorded `AttemptRecord` for scoring + reporting. (Surface-aware
placement into the *middle* of the conversation, or system-prompt injection, is future.)

---

## 4. Scoring reuse (T4 tool-intent + T1 text)

The proxy builds `AdapterResponse(text=…, tool_calls=<normalized or None>, provider=…, model=…,
raw=upstream_json)` and calls the **existing** `Scorer.score_async(attack, response_text=text,
response=resp)`:
- `success_when: side-effect` (`assert: send_email.called == true`) → **T4** scores on the returned
  `tool_calls` (the model's tool *intent*) — exactly the Phase-7 evaluator, no new grammar. When the
  upstream returns no tool_calls, `tool_calls` is `[]` (the model was asked but declined) → the
  assertion is **defended** (PASS) for a `.called == true` check; a plain-LLM upstream that never
  emits the tools key yields `None` → SKIPPED (consistent with Phase 7 semantics).
- `success_when: string` → **T1** on the returned text (planted canary etc.).
- `judge`/`classifier`/`mcp-assert` → unchanged (mcp-assert SKIPS: the proxy sets `mcp=None`).

`tool_calls` normalization: `[{name, args, ordinal}]` with `ordinal` the index in the returned list,
`args` the parsed JSON arguments (OpenAI `function.arguments` string → dict; Anthropic `input` dict).
This is the sandbox shape the T4 evaluator + the TUI/reports already consume — full reuse.

---

## 5. Server + CLI

`grendel proxy --serve [--host H] [--port P] [--route PATH=PROVIDER …] [--pack ID|CAT …]
[--out PATH] [--config C]`:
- Merges `--host/--port/--route` over `cfg.proxy` (Phase 12) and validates (Phase 12 rules). If
  `--serve` is absent, behaviour is exactly Phase 12 (print the resolved config; no socket).
- With `--serve`: requires at least one route (else exit 2 — nothing to route). Loads the attacks
  (`_load_attacks(cfg)` filtered by `--pack` via `_select_attacks`; empty selection → exit 2).
  Builds a `ProxySession` (owned `httpx.AsyncClient`), prints a startup banner (bound address, routes,
  attack count, the `base_url` the agent should use), and serves until interrupted. On shutdown:
  writes the `RunRecord` to `--out` or `cfg.run.output_dir`, prints the `_summary`.
- The startup banner + shutdown summary are deterministic strings (testable); the actual blocking
  `serve_forever` is only exercised in the one localhost round-trip test (started in a thread, shut
  down via `httpd.shutdown()`), never in the unit tests.

Exit codes: `--serve` with no route or no attacks → 2 (usage); a clean shutdown → 0; bad
config/route/port → 2 (Phase 12).

---

## 6. Deliberate contract updates (enumerated)

1. **`grendel proxy` gains `--serve`, `--pack`, `--out`.** Additive; without `--serve` it is exactly
   the Phase-12 preview. `--serve` requires a route + at least one attack.
2. **New module `src/grendel/proxy.py`** — pure helpers + `ProxySession` + `serve`. New code only.
3. **`AdapterResponse` is reused as the proxy's outcome carrier** (no field change) so the existing
   `Scorer.score_async` T4/T1 paths score proxied exchanges with zero new scoring logic.
4. No change to scoring/records/config/runner/target-adapter behaviour. `ProxyConfig` (Phase 12) is
   consumed as-is (host/port/routes). No new runtime dependency (stdlib `http.server` + `httpx`).

---

## 7. Testing strategy (offline + deterministic)

- **Pure helpers** (`test_proxy_core.py`): `select_route` (longest-prefix, no-match→None);
  `inject_attack` (user-append for `prompt`, tool-message for `tool-output`, original body
  unmutated); `build_upstream_request` (openai→`/chat/completions`, anthropic→`/messages`, the
  agent's `Authorization` forwarded verbatim, provider default headers merged, Grendel adds no key);
  `extract_outcome` (OpenAI tool_calls with a JSON `arguments` string → `[{name,args,ordinal}]`;
  Anthropic `tool_use` blocks → same; text extraction; empty/none cases).
- **`handle` end-to-end** (`test_proxy_core.py`): a `ProxySession` with an injected
  `httpx.MockTransport` upstream that returns (a) a `tool_calls` completion → the recorded
  `AttemptRecord` has the normalized tool_calls and scores **FAIL/T4** for a matching side-effect
  attack; (b) a benign text completion for a string attack → scored by T1; (c) the returned bytes to
  the caller **equal** the upstream body (pass-through); (d) an upstream 500 → an ERROR
  `AttemptRecord` and a clean error response to the agent; (e) the agent's `Authorization` header
  reached the upstream request (assert via the MockTransport handler). Attack cycling across N calls
  records N attempts in order. All offline.
- **Server round-trip** (`test_proxy_server.py`): build a `ProxySession` with a mocked upstream, run
  `serve` on `("127.0.0.1", 0)` in a background thread, `POST` a real chat-completions request to the
  bound port with a stdlib/httpx client, assert the response is the (mocked) upstream body and one
  `AttemptRecord` was recorded, then `shutdown()` deterministically. Localhost only; upstream mocked;
  no external network.
- **CLI** (`test_cli_proxy.py` extend): `proxy --serve` with no route → exit 2; with a route but no
  matching `--pack`/attacks → exit 2; the preview path (no `--serve`) unchanged. The serve wiring is
  asserted by monkeypatching `proxy.serve` to capture the built `ProxySession` (host/port/routes/
  attack count) without binding a socket, plus the deterministic startup banner string.
- **No behaviour drift:** prior 465 tests (1 skipped) stay green; only the additive §6 updates. No
  network, no API keys, no real tool execution.

---

## 8. Acceptance criteria

Phase 13 is done when:
1. `ruff check .` + `ruff format --check .` clean; `pytest` green **offline, no keys/network**; the
   prior 465 tests (1 skipped) pass plus the new proxy-core/server/CLI tests.
2. **Zero-touch proxy:** `grendel proxy --serve` exposes an OpenAI-compatible endpoint (the agent
   only sets `base_url`); each proxied chat-completions call has an attack injected, is forwarded to
   the routed provider carrying the agent's own key, and the returned `tool_calls`/text are read,
   scored (T4 tool-intent / T1 text via the existing Scorer), and recorded — the agent gets the
   upstream response unchanged.
3. **Multi-provider routing by path** (openai/anthropic/openrouter/custom via `ProxyConfig.routes`)
   and **key forwarding** (agent's `Authorization` passed through; Grendel adds none), verified by
   unit tests with a mocked upstream.
4. **Recording + reporting:** a proxied session produces a `RunRecord` (written on shutdown) that the
   existing report/diff/TUI consume; tool intent shows as `AttemptRecord.tool_calls`.
5. Everything offline + deterministic; no new dependency; scoring/records/config/runner unchanged;
   the proxy core is a pure/async unit with one localhost round-trip test for the socket wiring.
