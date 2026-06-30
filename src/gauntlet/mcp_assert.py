"""Safe restricted-grammar parser + evaluator for MCP protocol assertions.

Operates purely over an ``McpObservation`` (or its dict). **NO ``eval``/``exec``/
``compile``** — a tiny hand-written regex matcher recognizes only the §5 grammar; anything
else raises ``McpAssertSyntaxError``. The evaluator can only ask the four whitelisted
protocol questions (description changed / contains / any-contains / shadowed).

Supported forms::

    mcp.description_changed('send_email')                # rug-pull (default == true)
    mcp.description_changed('send_email') == false
    mcp.description_contains('search', 'ignore')         # poisoning (case-insensitive)
    mcp.any_description_contains('exfiltrate')           # poisoning, tool-name agnostic
    mcp.tool_shadowed('send_email')                      # cross-tool shadowing
    ... == false / ... != true                           # negations on every predicate
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Override-marker tells for cross-tool shadowing (data — extending it is a one-line edit).
SHADOW_MARKERS: tuple[str, ...] = (
    "instead of",
    "rather than",
    "do not use",
    "don't use",
    "deprecated",
    "replace ",
    "override",
    "shadow",
    "supersedes",
)

_STR = r"(?P<q{i}>['\"])(?P<s{i}>.*?)(?P=q{i})"
_BOOLTAIL = r"(?:\s*(?P<cmp>==|!=)\s*(?P<bool>true|false))?"

_CHANGED_RE = re.compile(rf"^mcp\.description_changed\(\s*{_STR.format(i=0)}\s*\){_BOOLTAIL}$")
_CONTAINS_RE = re.compile(
    rf"^mcp\.description_contains\(\s*{_STR.format(i=0)}\s*,\s*{_STR.format(i=1)}\s*\){_BOOLTAIL}$"
)
_ANY_CONTAINS_RE = re.compile(
    rf"^mcp\.any_description_contains\(\s*{_STR.format(i=0)}\s*\){_BOOLTAIL}$"
)
_SHADOWED_RE = re.compile(rf"^mcp\.tool_shadowed\(\s*{_STR.format(i=0)}\s*\){_BOOLTAIL}$")


class McpAssertSyntaxError(ValueError):
    """Raised when an assertion is outside the restricted MCP-assert grammar."""


@dataclass(frozen=True)
class McpAssertion:
    """A parsed MCP assertion (a value object, never executed as code)."""

    expr: str
    kind: str  # "changed" | "contains" | "any_contains" | "shadowed"
    arg0: str  # tool name (changed/contains/shadowed) or substring (any_contains)
    arg1: str | None = None  # substring, for "contains"
    expected: bool = True  # the RHS bool the predicate is compared against (default true)


def parse_mcp_assertion(expr: str) -> McpAssertion:
    text = expr.strip()
    if not text:
        raise McpAssertSyntaxError("empty mcp assertion")

    m = _CHANGED_RE.match(text)
    if m:
        return McpAssertion(expr, "changed", m["s0"], expected=_expected(m))

    m = _CONTAINS_RE.match(text)
    if m:
        return McpAssertion(expr, "contains", m["s0"], arg1=m["s1"], expected=_expected(m))

    m = _ANY_CONTAINS_RE.match(text)
    if m:
        return McpAssertion(expr, "any_contains", m["s0"], expected=_expected(m))

    m = _SHADOWED_RE.match(text)
    if m:
        return McpAssertion(expr, "shadowed", m["s0"], expected=_expected(m))

    raise McpAssertSyntaxError(f"unsupported mcp assertion: {expr!r}")


def _expected(m: re.Match) -> bool:
    """Resolve the optional ``== true|false`` / ``!= true|false`` tail to a bool RHS.

    ``!=`` flips the literal: ``!= true`` means the predicate should be false.
    """
    cmp = m["cmp"] or "=="
    literal = (m["bool"] or "true") == "true"
    return literal if cmp == "==" else not literal


def _as_observation(obs: object) -> tuple[list[dict], dict[str, str], dict[str, str]]:
    """Normalize an ``McpObservation`` or dict to (tools, approved, current)."""
    if isinstance(obs, dict):
        tools = list(obs.get("tools", []) or [])
        approved = dict(obs.get("approved_descriptions", {}) or {})
        current = dict(obs.get("current_descriptions", {}) or {})
    else:
        tools = [t if isinstance(t, dict) else t.model_dump() for t in getattr(obs, "tools", [])]
        approved = dict(getattr(obs, "approved_descriptions", {}) or {})
        current = dict(getattr(obs, "current_descriptions", {}) or {})
    return tools, approved, current


def _tool_name(t: dict) -> str:
    return str(t.get("name", ""))


def _tool_desc(t: dict) -> str:
    return str(t.get("description", "") or "")


def _evaluate_predicate(a: McpAssertion, obs: object) -> bool:
    tools, approved, current = _as_observation(obs)

    if a.kind == "changed":
        # Fix #4: approved-then-changed OR approved-then-vanished -> true; never-approved
        # -> false (the `is not None` guard on the approved side).
        prior = approved.get(a.arg0)
        return prior is not None and prior != current.get(a.arg0)

    if a.kind == "contains":
        assert a.arg1 is not None
        return a.arg1.casefold() in current.get(a.arg0, "").casefold()

    if a.kind == "any_contains":
        needle = a.arg0.casefold()
        return any(needle in (v or "").casefold() for v in current.values())

    # shadowed: Fix #9 — absent target -> false BEFORE scanning other tools.
    targets = [t for t in tools if _tool_name(t) == a.arg0]
    if not targets:
        return False
    others = [t for t in tools if t not in targets]
    # Duplicate-name collision: the catalog advertises two tools both named arg0.
    if len(targets) > 1:
        return True
    for y in others:
        ydesc = _tool_desc(y).casefold()
        if a.arg0.casefold() in ydesc and any(mark in ydesc for mark in SHADOW_MARKERS):
            return True
    return False


def evaluate_mcp(expr: str, obs: object) -> bool:
    """Parse ``expr`` and evaluate it over ``obs`` (an ``McpObservation`` or dict)."""
    assertion = parse_mcp_assertion(expr)
    raw = _evaluate_predicate(assertion, obs)
    return raw == assertion.expected
