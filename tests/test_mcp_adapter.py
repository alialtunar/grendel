"""M6: MCP adapter interface via a fake client + the lazy guarded import."""

from __future__ import annotations

import importlib.util
import sys

import pytest

from gauntlet.errors import AdapterError
from gauntlet.targets.base import AdapterRequest
from gauntlet.targets.mcp_adapter import MCPTargetAdapter


class FakeMCPClient:
    """Minimal in-memory MCP-shaped client (no `mcp` package, no network)."""

    def __init__(self) -> None:
        self._calls: list[dict] = []

    def call_tool(self, prompt: str) -> dict:
        self._calls.append({"name": "send_email", "args": {"prompt": prompt}, "ordinal": 0})
        return {"text": f"handled: {prompt}"}

    def snapshot(self) -> list[dict]:
        return list(self._calls)


async def test_send_with_injected_client() -> None:
    adapter = MCPTargetAdapter(client=FakeMCPClient())
    resp = await adapter.send(AdapterRequest(prompt="hello"))
    assert resp.text == "handled: hello"
    assert resp.provider == "mcp"
    assert resp.tool_calls == [{"name": "send_email", "args": {"prompt": "hello"}, "ordinal": 0}]


def test_import_gauntlet_does_not_import_mcp() -> None:
    import gauntlet  # noqa: F401
    import gauntlet.targets  # noqa: F401
    import gauntlet.targets.mcp_adapter  # noqa: F401

    assert "mcp" not in sys.modules


@pytest.mark.skipif(importlib.util.find_spec("mcp") is not None, reason="mcp installed")
async def test_real_path_raises_when_mcp_absent() -> None:
    adapter = MCPTargetAdapter(client=None)
    with pytest.raises(AdapterError, match="pip install gauntlet"):
        await adapter.send(AdapterRequest(prompt="x"))
