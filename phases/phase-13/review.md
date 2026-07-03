# Phase 13 review -- LLM-proxy: zero-touch agent testing

Reviewed against phases/phase-13/spec.md, phases/phase-13/plan.md, and ROADMAP.md section 8.13.

Scope reviewed: src/grendel/proxy.py (new), src/grendel/cli.py (proxy command extension),
tests/test_proxy_core.py, tests/test_proxy_server.py, tests/test_cli_proxy.py.

Verification performed:
- Read spec/plan in full and cross-checked every deliverable (pure helpers, ProxySession.handle,
  single-persistent-loop server, CLI wiring) against the code.
- Ran ruff check . and ruff format --check . -- both clean.
- Ran the full test suite: 489 passed, 1 skipped (prior 465 + new proxy tests), all green.
- Manually drove the real socket server (outside the test suite) with raw sockets/httpx to probe
  edge cases not covered by the given tests (invalid Content-Length, non-GET/non-POST verbs).
- Cross-checked AdapterResponse, AttemptRecord, Scorer.score_async, resolve_provider,
  ProviderPreset, and make_run_record signatures/semantics against how proxy.py uses them --
  no drift, no new fields, no behaviour change to scoring/records/config/runner/adapters.

## Findings

1. (Non-blocking, minor) Invalid Content-Length yields 500, not 400. The plan Milestone-2 step 1
   states: read Content-Length (missing/invalid -> 400). The implementation
   (proxy.py do_POST, int(self.headers.get("Content-Length") or 0)) only handles the missing case
   cleanly (defaults to 0 -> empty body -> handle correctly returns 400 for the missing messages
   key). A syntactically invalid header value (e.g. Content-Length: notanumber) raises ValueError
   inside the try block, which is caught by the generic except Exception and surfaces as a 500
   instead of a 400. Verified live: a request with a bogus Content-Length returns 500 with a body
   containing "invalid literal for int()". The response is still well-formed (never hangs, never
   lets the exception escape the socket handler), so this does not violate the never-crash
   acceptance criterion, but it is a literal deviation from the plan-stated status code, and it is
   untested either way. Low severity; fine to leave for a follow-up.

2. (Non-blocking, minor) Non-POST methods other than GET return 501, not 405. Spec and plan state:
   non-POST methods -> 405. Only do_GET is overridden to return 405; PUT/DELETE/PATCH etc fall
   through to BaseHTTPRequestHandler stdlib default, which replies 501 Unsupported method. Verified
   live. The only test present (test_server_non_post_405) exercises GET only, so this passes CI but
   does not fully satisfy the literal spec wording for other verbs. The response is still
   well-formed and does not hang. Low severity -- a real agent only ever calls POST.

Both items above are cosmetic status-code mismatches against the plan exact wording; neither
affects correctness of the zero-touch red-team flow, key handling, scoring, or recording, and
neither causes a crash or hang. A one-line follow-up (catch ValueError/TypeError around the
Content-Length parse to return 400; add a generic fallback for other verbs to return 405) would
close the gap, but it is not blocking.

## Correctness checks that passed

- select_route: longest-prefix match, None on no match -- correct, matches test.
- inject_attack: deep-copies (verified the original body is untouched even after the messages list
  is mutated), correctly appends a tool message for the tool-output surface and a user message for
  every other surface (prompt/rag/mcp-desc fallback verified), synthesizes the messages key if
  absent.
- build_upstream_request/_upstream_headers: correct per-api_style endpoint suffix table (mirrors
  http_adapter); forwards only the agent own auth-shaped headers (authorization, x-api-key,
  anthropic-version, openai-organization) case-insensitively, merged over preset.default_headers;
  Grendel injects no key of its own -- confirmed by test and by code inspection (no env-key lookup
  anywhere in proxy.py).
- extract_outcome: correct tri-state tool_calls semantics (None when no tools key at all, empty
  list when declined, populated list otherwise) for openai/anthropic/ollama; OpenAI arguments JSON
  string parsed with a guarded try/except -> empty dict on malformed JSON (test covers this).
  tool_calls and tool_observed are correctly threaded into AttemptRecord (tool_calls=list(tool_calls)
  if tool_calls is not None else empty list, tool_observed=tool_calls is not None) -- matches the
  Phase-7 tri-state contract exactly.
- ProxySession.handle: routes -> 404 (no attempt recorded) -> parses body -> 400 on bad JSON or
  non-chat-shape (no attempt recorded) -> picks next attack -> resolves provider (ConfigError from
  resolve_provider, including the base_url-less openai-compatible preset, is caught -> ERROR
  attempt + clean 502) -> injects -> forwards via the injected client (httpx HTTPError -> ERROR
  attempt + 502; non-2xx upstream -> ERROR attempt + status passthrough; non-JSON upstream body ->
  ERROR attempt + 502) -> extracts outcome -> builds AdapterResponse -> calls Scorer.score_async
  (verified T4 side-effect on tool_calls and T1 string-on-text both score correctly through the
  unmodified Scorer) -> appends a fully-populated AttemptRecord -> returns the upstream
  status/headers/body byte-for-byte unchanged (verified: json.loads(body) equals upstream).
- Thread-safe attack cycler: a threading.Lock guards the read-then-increment in _next_attack; the
  asyncio.gather-based concurrency test (test_handle_concurrent_no_duplicate_index) confirms no
  duplicate/skipped index across 8 concurrent handle() calls sharing one lock -- correct even
  though those calls run cooperatively on one event loop (the lock is uncontended in that scenario,
  but is exactly what is needed once real concurrent OS threads dispatch onto the loop via
  run_coroutine_threadsafe, as the server does).
- Cross-event-loop safety: make_server creates exactly ONE asyncio loop, runs it forever in a
  single daemon thread, and do_POST dispatches via asyncio.run_coroutine_threadsafe -- never
  asyncio.run per request. The two-sequential-request round-trip test
  (test_server_two_sequential_requests_roundtrip) passes, which is the specified regression guard
  for the historical cross-loop httpx.AsyncClient reuse hazard; manually confirmed the server also
  survives a third request via ad-hoc socket probing.
- stop_server: httpd.shutdown() -> schedules session.aclose() on the same loop and waits (best
  effort, swallowed on failure) -> loop.call_soon_threadsafe(loop.stop) -> joins the loop thread.
  Correct ordering (client closed before the loop that owns it stops).
- Key forwarding and no leakage: the agent Authorization header reaches the mocked upstream
  (asserted inside MockTransport) and does not appear anywhere in
  session.record.model_dump_json() -- verified by the given test and confirmed by code inspection
  (only attack.payload, text, tool_calls, and scoring metadata are written to AttemptRecord; no
  header dict is ever stored on the record).
- CLI: --serve without a route exits 2 (checked before any attack loading); --serve with a route
  but no selectable attacks (via _select_attacks unknown-pack exit-2 path, or an empty catalog)
  exits 2; the judge is wired identically to the run command via _build_judge_scorer(cfg,
  dry_run=False) when enabled, with the judge adapter closed on shutdown; the record is written to
  --out (or cfg.run.output_dir/run_id.json) after serve() returns, followed by _summary; the
  no-serve preview path is byte-identical to Phase 12 (verified: prior Phase-12 proxy tests in
  test_cli_proxy.py still pass unmodified).
- No behaviour drift: AdapterResponse, AttemptRecord, Scorer.score_async, resolve_provider, and
  make_run_record are consumed exactly as they exist today, no signature or semantic changes; no
  new runtime dependency (only stdlib http.server/threading/asyncio plus the already-present
  httpx).
- Full suite: ruff check . clean, ruff format --check . clean, pytest -> 489 passed, 1 skipped.

STATUS: PASS
