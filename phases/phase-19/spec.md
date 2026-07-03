# Phase 19 — spec: agent-agnostic targets + finalize

## 1. Goal
Let anyone red-team **any agent from the terminal**, whatever the shape of its HTTP API,
with no code changes and nothing about a provider/format hardcoded. Then review the project
end-to-end and **finalize** it.

## 2. The two capabilities

### 2.1 Configurable `custom` adapter (the primary way to connect to an agent)
Today `HTTPTargetAdapter` speaks exactly three wire formats (`openai`/`anthropic`/`ollama`),
each hardcoded. An agent with a bespoke JSON API (e.g. `POST /chat {"message": …}` →
`{"reply": …}`) cannot be connected. Fix: a fourth `api_style: custom` whose request shape and
response-field are described in **config, not code**:

```yaml
providers:
  myagent:
    base_url: http://localhost:8080
    api_style: custom
    request:
      path: /chat
      body: { message: "{prompt}", sys: "{system}" }   # {prompt}/{system}/{model}/{api_key} substituted
      headers: { Authorization: "Bearer {api_key}" }   # optional
    response:
      text_path: reply                                  # dotted path, e.g. choices.0.message.content
targets:
  t: { type: http, provider: myagent, model: "-" }
```

### 2.2 Proxy demoted to indirect-injection only
The proxy sits between agent and LLM, so it tests the agent↔LLM boundary — not the agent's own
front door. It's the wrong tool for direct attacks; its real niche is indirect (RAG/tool-output)
injection. The engine stays; only its **positioning** changes (out of the add-target menu, doc
reframed). No behaviour change to `grendel proxy`.

## 3. Non-goals
- No new scoring tier, no new attack corpus, no TUI.
- Proxy engine is NOT removed.
- No GET/streaming custom requests (POST + non-streaming JSON only).

## 4. Development strategy (per milestone)
`plan.md` → **plan-reviewer** (REVISE→addressed) → implement → **reviewer** (BLOCKING→addressed)
→ **tester** → `ruff` clean + `pytest` green + `STATUS: PASS`. Phase close appends
`phase 19: DONE …` to `PROGRESS.md`.

## 5. Finalize (in scope, per user: architecture review + bug hunt + docs)
1. Architecture consistency: target-add → resolve_provider → adapter → run → score → report is
   gap-free; the four `api_style`s are consistent across `_build_request`/`_parse_response`/
   `PRESETS`/`API_PATHS`; no dead code / unreachable branch / double source of truth.
2. Hardcode scan: no residual provider-name special-cases or embedded model/URL/format literals —
   "openai is special nowhere" holds.
3. Bug hunt on edge cases (empty/bad config, missing key, wrong `text_path`, placeholder
   collision, ad-hoc target leak) — fix + cover.
4. Docs: README + docs/authoring-packs reflect the new mental model (agent test = custom adapter;
   proxy = indirect).
5. Live end-to-end: a tiny bespoke-JSON echo agent → `grendel run --target … --pack jailbreak` →
   report.

## 6. Done when
Full suite green + `ruff` clean + `grendel doctor` healthy; reviewer + tester `STATUS: PASS`.
