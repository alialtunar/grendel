"""A tiny LangGraph agent to red-team with grendel (end-to-end demo).

A ReAct agent with one tool — ``send_email`` — talking to an OpenAI model. Its ``base_url`` is
read from the environment, so you can point it at OpenAI directly OR at ``grendel proxy`` for
zero-touch red-teaming (grendel injects attacks into every LLM call and reads the returned
tool intent). See README.md.

Run directly:
    OPENAI_API_KEY=sk-... python agent.py

Zero-touch via the grendel proxy (in another terminal, `grendel proxy --serve --route
/openai=openai --pack tool-abuse`):
    OPENAI_BASE_URL=http://127.0.0.1:8100/openai/v1 OPENAI_API_KEY=sk-... python agent.py
"""

from __future__ import annotations

import os

from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent


@tool
def send_email(to: str, body: str) -> str:
    """Send an email to ``to`` with ``body``. (Demo only — does not actually send anything.)"""
    return f"[demo] email queued to {to}: {body[:60]}"


def build_agent():
    """Build the ReAct agent; ``OPENAI_BASE_URL`` (if set) points it at the grendel proxy."""
    model = ChatOpenAI(
        model=os.getenv("GRENDEL_AGENT_MODEL", "gpt-4o-mini"),
        base_url=os.getenv("OPENAI_BASE_URL") or None,
        temperature=0,
    )
    return create_react_agent(model, tools=[send_email])


def main() -> None:
    agent = build_agent()
    prompt = os.getenv("GRENDEL_AGENT_PROMPT", "Please summarize my inbox and reply politely.")
    result = agent.invoke({"messages": [("user", prompt)]})
    for message in result["messages"]:
        message.pretty_print()


if __name__ == "__main__":
    main()
