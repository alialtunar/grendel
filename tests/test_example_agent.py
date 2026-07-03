"""Phase 16: the LangGraph example agent exists and is valid Python (no langgraph import)."""

from __future__ import annotations

import ast
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1] / "examples" / "langgraph-agent"


def test_example_agent_files_exist() -> None:
    assert (AGENT_DIR / "agent.py").exists()
    assert (AGENT_DIR / "requirements.txt").exists()
    assert (AGENT_DIR / "README.md").exists()


def test_example_agent_is_valid_python_and_referenced_bits() -> None:
    src = (AGENT_DIR / "agent.py").read_text(encoding="utf-8")
    ast.parse(src)  # syntax-valid offline, without importing langgraph
    assert "send_email" in src
    assert "OPENAI_BASE_URL" in src  # base_url is env-configurable (points at grendel proxy)
    assert "create_react_agent" in src


def test_requirements_list_langgraph() -> None:
    reqs = (AGENT_DIR / "requirements.txt").read_text(encoding="utf-8")
    assert "langgraph" in reqs and "langchain-openai" in reqs
