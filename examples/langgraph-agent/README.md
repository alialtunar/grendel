# LangGraph demo agent (end-to-end target for grendel)

A minimal [LangGraph](https://github.com/langchain-ai/langgraph) ReAct agent with a `send_email`
tool, used to demonstrate grendel red-teaming a **real** tool-using agent end-to-end.

It's a normal agent — it only changes **one** setting to be tested: its `base_url`.

## Install

```bash
pip install -r requirements.txt
```

## Run it directly (talks straight to OpenAI)

```bash
export OPENAI_API_KEY=sk-...        # your key (never commit it)
python agent.py
```

## Zero-touch red-team via `grendel proxy`

Point the agent's `base_url` at grendel — grendel injects an attack into every LLM call, forwards
it to OpenAI carrying **your** key, and records the returned tool intent. The agent needs **no code
change**.

Terminal 1 — start the proxy in front of OpenAI, injecting the tool-abuse pack:

```bash
grendel proxy --serve --route /openai=openai --pack tool-abuse --out runs/agent-e2e.json
```

Terminal 2 — run the agent against the proxy:

```bash
export OPENAI_API_KEY=sk-...
export OPENAI_BASE_URL=http://127.0.0.1:8100/openai/v1
python agent.py
```

Stop the proxy (Ctrl-C). It writes a run record; open it with:

```bash
grendel report --run runs/agent-e2e.json --format md
```

You'll see, per proxied call, whether an injected attack made the model emit a `send_email`
tool call it shouldn't have — the outcome-based verdict grendel is built for.

## Environment knobs

| Var | Meaning | Default |
|-----|---------|---------|
| `OPENAI_API_KEY` | your OpenAI key (forwarded by the proxy) | — (required) |
| `OPENAI_BASE_URL` | point at the grendel proxy for zero-touch testing | OpenAI direct |
| `GRENDEL_AGENT_MODEL` | model id | `gpt-4o-mini` |
| `GRENDEL_AGENT_PROMPT` | the user turn to run | "Please summarize my inbox …" |

> This is example code — it is **not** part of the `grendel` package or its test suite, and its
> dependencies live here (not in the project's `pyproject.toml`).
