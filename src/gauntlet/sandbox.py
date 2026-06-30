"""Instrumented sandbox: ``ToolCall`` + ``ToolRegistry`` + ``ToolContext``.

The sandbox *observes* tool use; the registered tools are **fakes that only record**
(an optional ``fn`` is a fake implementation returning a canned value — never a real
side effect: no email, no filesystem, no network). A fresh ``ToolRegistry`` is built per
``send`` so observations never leak across attacks.
"""

from __future__ import annotations

import json
from collections.abc import Callable

from pydantic import BaseModel, ConfigDict

# Real attributes of ToolContext — a tool may not be registered under one of these
# names (else it would shadow the context's own API). Fix #4.
_RESERVED_NAMES: frozenset[str] = frozenset(
    {"register", "call", "calls", "count", "called", "snapshot"}
)


class ToolCall(BaseModel):
    """One observed tool invocation within a single send (JSON-serializable args)."""

    model_config = ConfigDict(extra="forbid")

    name: str
    args: dict = {}
    ordinal: int  # 0-based call order within this send


class ToolRegistry:
    """Holds registered fake tools and records every invocation for one send."""

    def __init__(self) -> None:
        self._fns: dict[str, Callable | None] = {}
        self._calls: list[ToolCall] = []

    def register(self, name: str, fn: Callable | None = None) -> None:
        if name in _RESERVED_NAMES:
            raise ValueError(
                f"cannot register tool under reserved name {name!r}; reserved names: "
                f"{', '.join(sorted(_RESERVED_NAMES))}"
            )
        self._fns[name] = fn

    def is_registered(self, name: str) -> bool:
        return name in self._fns

    def call(self, name: str, **kwargs: object) -> object:
        # Fix #9: enforce JSON-serializable kwargs at record time, consistent with
        # ToolCall.args and the called_with evaluator's json.dumps.
        try:
            json.dumps(kwargs)
        except TypeError as exc:
            raise ValueError(
                f"tool {name!r} called with non-JSON-serializable args: {exc}"
            ) from exc
        ordinal = len(self._calls)
        self._calls.append(ToolCall(name=name, args=dict(kwargs), ordinal=ordinal))
        fn = self._fns.get(name)
        if fn is not None:
            return fn(**kwargs)
        return None

    @property
    def calls(self) -> list[ToolCall]:
        return list(self._calls)

    def count(self, name: str) -> int:
        return sum(1 for c in self._calls if c.name == name)

    def called(self, name: str) -> bool:
        return self.count(name) > 0

    def snapshot(self) -> list[dict]:
        """``[{name, args, ordinal}, ...]`` for the response / record."""
        return [c.model_dump() for c in self._calls]


class ToolContext:
    """The object handed to an agent callable.

    Registered tools are exposed as bound callables via ``__getattr__`` (so the agent
    writes ``tools.send_email(to=..., body=...)``); the explicit ``tools.call(name,
    **kwargs)`` path is also available. Both route through ``ToolRegistry.call``.
    """

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    def register(self, name: str, fn: Callable | None = None) -> None:
        self._registry.register(name, fn)

    def call(self, name: str, **kwargs: object) -> object:
        return self._registry.call(name, **kwargs)

    @property
    def calls(self) -> list[ToolCall]:
        return self._registry.calls

    def count(self, name: str) -> int:
        return self._registry.count(name)

    def called(self, name: str) -> bool:
        return self._registry.called(name)

    def snapshot(self) -> list[dict]:
        return self._registry.snapshot()

    def __getattr__(self, name: str) -> Callable[..., object]:
        # Only reached when normal attribute lookup fails (so the reserved names above,
        # being real attributes, never land here).
        registry = self.__dict__["_registry"]
        if registry.is_registered(name):

            def _bound(**kwargs: object) -> object:
                return registry.call(name, **kwargs)

            return _bound
        raise AttributeError(f"no tool registered under {name!r}")
