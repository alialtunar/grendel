"""In-process target adapters: ``PythonCallableAdapter`` + ``AgentSandboxAdapter``."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping

from ..sandbox import ToolContext, ToolRegistry
from .base import AdapterRequest, AdapterResponse, TargetAdapter


def _coerce_text(result: object) -> tuple[str, dict]:
    """Accept a returned str or a small mapping carrying ``text``; return (text, raw)."""
    if isinstance(result, str):
        return result, {"text": result}
    if isinstance(result, Mapping):
        text = str(result.get("text", ""))
        return text, dict(result)
    text = str(result)
    return text, {"text": text}


class PythonCallableAdapter(TargetAdapter):
    """``type: python`` — wraps an in-process ``fn(request) -> str | mapping``.

    Behaves like an LLM target (returns text); **no tool observation**, so
    ``tool_calls`` is ``None`` (a side-effect check against it is not-applicable).
    """

    def __init__(
        self, fn: Callable, *, name: str = "python", entrypoint: str | None = None
    ) -> None:
        self.name = name
        self._fn = fn
        self._model = entrypoint or getattr(fn, "__name__", "python")

    async def send(self, request: AdapterRequest) -> AdapterResponse:
        if inspect.iscoroutinefunction(self._fn):
            result = await self._fn(request)
        else:
            result = self._fn(request)
        text, raw = _coerce_text(result)
        return AdapterResponse(
            text=text,
            raw=raw,
            model=self._model,
            provider="python",
            tool_calls=None,
        )


class AgentSandboxAdapter(TargetAdapter):
    """``type: agent`` — wraps ``fn(request, tools) -> str`` with an instrumented sandbox.

    Builds a fresh ``ToolRegistry``/``ToolContext`` per send and surfaces the observed
    calls on ``AdapterResponse.tool_calls`` (a list, possibly empty).
    """

    def __init__(self, fn: Callable, *, name: str = "agent", entrypoint: str | None = None) -> None:
        self.name = name
        self._fn = fn
        self._model = entrypoint or getattr(fn, "__name__", "agent")

    async def send(self, request: AdapterRequest) -> AdapterResponse:
        registry = ToolRegistry()
        tools = ToolContext(registry)
        # Fix #5: await a coroutine agent so text is never a coroutine object.
        if inspect.iscoroutinefunction(self._fn):
            text = await self._fn(request, tools)
        else:
            text = self._fn(request, tools)
        text = str(text)
        return AdapterResponse(
            text=text,
            raw={"text": text},
            model=self._model,
            provider="agent",
            tool_calls=registry.snapshot(),
        )
