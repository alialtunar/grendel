"""The TargetAdapter abstract interface and request/response models."""

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel

from ..mcp_surface import McpObservation


class AdapterRequest(BaseModel):
    prompt: str
    system: str | None = None
    max_tokens: int = 512
    temperature: float = 0.0


class AdapterResponse(BaseModel):
    text: str
    raw: dict
    model: str
    provider: str
    finish_reason: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    latency_ms: float | None = None
    # Phase 7 (additive, tri-state): None = adapter does not observe tools; [] = agent
    # observed zero calls; list = observed calls (each a ToolCall snapshot).
    tool_calls: list[dict] | None = None
    # Phase 8 (additive): None = adapter exposes no MCP observation (non-mcp targets ->
    # mcp-assert checks are not-applicable -> SKIPPED).
    mcp: McpObservation | None = None


class TargetAdapter(ABC):
    """Abstract base for anything grendel can fire attacks at.

    Later phases add subclasses (Python callable, MCP, sandbox) without changing
    this contract.
    """

    name: str

    @abstractmethod
    async def send(self, request: AdapterRequest) -> AdapterResponse: ...

    async def aclose(self) -> None:
        """Release any resources held by the adapter. Default: no-op."""
        return None

    async def __aenter__(self) -> TargetAdapter:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()
