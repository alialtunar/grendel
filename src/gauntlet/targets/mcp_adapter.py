"""MCP target adapter — interface + lazy guarded ``mcp`` import (optional dep).

No module-level ``import mcp``: the real ``mcp`` import fires only inside the
connect/send path, raising ``AdapterError`` when the optional package is absent. An
injectable ``client`` seam makes the request -> response -> observed-tool-calls contract
fully testable offline with a fake in-memory client. The detailed MCP attack surface is
Phase 8; Phase 7 ships the adapter + interface + offline test only.
"""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING

from ..errors import AdapterError
from .base import AdapterRequest, AdapterResponse, TargetAdapter

if TYPE_CHECKING:
    from ..config import McpConfig

_MISSING_MCP = "MCP target requires the optional 'mcp' package; pip install gauntlet[mcp]"


class MCPTargetAdapter(TargetAdapter):
    """A ``TargetAdapter`` over an MCP server (real transport behind a lazy import)."""

    def __init__(
        self,
        *,
        name: str = "mcp",
        config: McpConfig | None = None,
        client: object | None = None,
    ) -> None:
        self.name = name
        self._config = config
        self._client = client

    def _ensure_client(self) -> object:
        if self._client is not None:
            return self._client
        # Lazy guarded import: only here does `mcp` get imported.
        try:
            import mcp  # noqa: F401  # real SDK; optional extra
        except ImportError as exc:
            raise AdapterError(_MISSING_MCP) from exc
        # The real client construction (from McpConfig) is a Phase 8 detail.
        raise AdapterError(
            "MCP real client construction is not implemented yet; "
            "inject a client to exercise the adapter offline"
        )

    async def send(self, request: AdapterRequest) -> AdapterResponse:
        client = self._ensure_client()
        out = client.call_tool(request.prompt)
        if inspect.isawaitable(out):
            out = await out
        if isinstance(out, dict):
            text = str(out.get("text", ""))
            raw = dict(out)
        else:
            text = str(out)
            raw = {"text": text}
        snapshot = getattr(client, "snapshot", None)
        tool_calls = list(snapshot()) if callable(snapshot) else []
        return AdapterResponse(
            text=text,
            raw=raw,
            model=self.name,
            provider="mcp",
            tool_calls=tool_calls,
        )
