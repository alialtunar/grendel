"""Safe resolution of user-provided callables for python/agent targets."""

from __future__ import annotations

import importlib
from collections.abc import Callable

from ..errors import ConfigError

__all__ = ["load_callable"]


def load_callable(spec: str) -> Callable:
    """Resolve ``"module:attr"`` to a callable via a safe importlib lookup.

    Raises ``ConfigError`` on a malformed spec, a missing module/attribute, or a
    non-callable target. No code beyond importing the named module runs.
    """
    if not isinstance(spec, str) or spec.count(":") != 1:
        raise ConfigError(f"invalid entrypoint {spec!r}; expected 'module:attr'")
    module_name, _, attr = spec.partition(":")
    module_name, attr = module_name.strip(), attr.strip()
    if not module_name or not attr:
        raise ConfigError(f"invalid entrypoint {spec!r}; expected 'module:attr'")

    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise ConfigError(
            f"cannot import module {module_name!r} for entrypoint {spec!r}: {exc}"
        ) from exc

    try:
        obj = getattr(module, attr)
    except AttributeError as exc:
        raise ConfigError(
            f"module {module_name!r} has no attribute {attr!r} for entrypoint {spec!r}"
        ) from exc

    if not callable(obj):
        raise ConfigError(f"entrypoint {spec!r} resolved to a non-callable {type(obj).__name__}")
    return obj
