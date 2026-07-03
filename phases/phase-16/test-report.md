# Phase 16 — Offline Test Report

All commands run offline, no network calls, no API key used.

## 1. `python -m ruff check .`
Result: **All checks passed!**

## 2. `python -m ruff format --check .`
Result: **96 files already formatted**

## 3. `python -m pytest -q -p no:cacheprovider`
Result: **488 passed, 1 skipped in 18.87s**

Matches expected baseline (476 passed +1 skipped prior -> 488 passed +1 skipped now, i.e. +12 new tests from `tests/test_cli_config.py`, `tests/test_banner.py`, `tests/test_example_agent.py`, `tests/test_proxy_core.py`).

## 4. No `textual` import / example agent not imported by suite
```
python -c "import sys; from grendel.cli import app; assert 'textual' not in sys.modules; print('ok')"
```
Output: `ok`

`tests/test_example_agent.py` validates `examples/langgraph-agent/agent.py` via `ast.parse()` only (syntax check), and does not import `langgraph` or the agent module — confirms the example agent is example-only and not imported by the suite.

## 5. Sanity: bare `grendel` banner (offline, no key)
```
python -c "from typer.testing import CliRunner; from grendel.cli import app; r=CliRunner().invoke(app,[]); print(r.exit_code, 'GRENDEL' in r.output or 'grendel' in r.output)"
```
Output: `0 True` — exit code 0, banner text present.

## Failures
None.

## 6. Live end-to-end validation (real OpenAI API — manual; key via env only, never on disk)

The user provided an OpenAI key used **only** as a shell env var (never written to any file — a
repo grep for `sk-proj` returns nothing; run records store env-var *names*, not values).

**(a) Direct real-API run**
```
OPENAI_API_KEY=… grendel run --provider openai --model gpt-4o-mini --pack prompt-injection --out …
```
→ `attempts=6 succeeded=5 defended=1 asr=83.33% tokens=351 est_cost=$0.0001`; `grendel report`
rendered the full breakdown (by category / OWASP LLM01 100% + LLM07 0% / ATLAS). The model actually
complied with 5 of 6 prompt-injection payloads — real verdicts.

**(b) Zero-touch proxy in front of the LangGraph agent**
```
grendel proxy --serve --route /openai=openai --pack tool-abuse --out …      # terminal 1
OPENAI_BASE_URL=…/openai/v1 OPENAI_API_KEY=… python examples/langgraph-agent/agent.py   # terminal 2
```
→ Grendel injected tool-abuse attacks into the agent's LLM calls, forwarded them to OpenAI carrying
the agent's own key, and read the returned tool intent. The real `gpt-4o-mini`-backed agent was
manipulated into emitting `send_email` calls to attacker addresses (`partner@external-domain.example`,
`thief@evil.example`). Run record: `attempts=3, scored=2, succeeded=2, asr=100%` (tool-abuse / LLM06 /
AML.T0051), skipped=1. The agent received the upstream replies unchanged (zero-touch).

**Bug found + fixed during the live run:** the proxy injected a bare `role:"tool"` message for the
`tool-output` surface, which OpenAI rejects (400: a tool message must follow an assistant
`tool_calls`). Fixed to inject a valid assistant-tool_call + tool-result **pair**; also added
**incremental record persistence** (`ProxySession._persist` writes atomically after every attempt) so
an ungraceful stop/kill never loses the run — verified the record survived a force-kill. Both covered
by new offline tests.

Both end-to-end paths run cleanly and produce sane reports. **The system works end-to-end.**

> Reminder to the user: **revoke/rotate the provided OpenAI key** — it was pasted in plaintext.

STATUS: PASS
