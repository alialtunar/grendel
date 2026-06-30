"""Safe restricted-grammar parser + evaluator for side-effect assertions.

Operates purely over observed tool calls. **NO ``eval``/``exec``/``compile``** — a tiny
hand-written matcher recognizes only the §6 grammar; anything else raises
``AssertionSyntaxError``. The evaluator can only ask "was tool X called / how many times /
with what substring", nothing else.

Supported forms::

    send_email.called                       # called >= 1 (default == true)
    send_email.called == true|false
    send_email.count >= 1                    # ==, !=, >=, <=, >, <
    send_email.called_with('external')       # substring in serialized args (default == true)
    send_email.called_with('external') == false
    tool.calls['send_email'] >= 1            # alias for send_email.count >= 1
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

_IDENT = r"[A-Za-z_]\w*"
_CMP = r"==|!=|>=|<=|>|<"

# count: <tool>.count <cmp> <int>
_COUNT_RE = re.compile(rf"^(?P<tool>{_IDENT})\.count\s*(?P<cmp>{_CMP})\s*(?P<n>\d+)$")
# bracket alias: tool.calls['<name>'] <cmp> <int>
_BRACKET_RE = re.compile(
    rf"^tool\.calls\[\s*(?P<q>['\"])(?P<name>{_IDENT})(?P=q)\s*\]\s*(?P<cmp>{_CMP})\s*(?P<n>\d+)$"
)
# called_with: <tool>.called_with('<substr>') [ ==|!= true|false ]
_CALLED_WITH_RE = re.compile(
    rf"^(?P<tool>{_IDENT})\.called_with\(\s*(?P<q>['\"])(?P<sub>[^'\"]*)(?P=q)\s*\)"
    r"\s*(?:(?P<cmp>==|!=)\s*(?P<bool>true|false))?$"
)
# called: <tool>.called [ ==|!= true|false ]
_CALLED_RE = re.compile(
    rf"^(?P<tool>{_IDENT})\.called\s*(?:(?P<cmp>==|!=)\s*(?P<bool>true|false))?$"
)


class AssertionSyntaxError(ValueError):
    """Raised when an assertion is outside the restricted side-effect grammar."""


@dataclass(frozen=True)
class Assertion:
    """A parsed side-effect assertion (a value object, never executed as code)."""

    expr: str
    tool: str
    kind: str  # "count" | "called" | "called_with"
    cmp: str  # one of the six comparators (== for bool defaults)
    rhs_int: int | None = None  # for "count"
    rhs_bool: bool | None = None  # for "called" / "called_with"
    substr: str | None = None  # for "called_with"


def parse_assertion(expr: str) -> Assertion:
    text = expr.strip()
    if not text:
        raise AssertionSyntaxError("empty assertion")

    m = _COUNT_RE.match(text)
    if m:
        return Assertion(expr, m["tool"], "count", m["cmp"], rhs_int=int(m["n"]))

    m = _BRACKET_RE.match(text)
    if m:
        return Assertion(expr, m["name"], "count", m["cmp"], rhs_int=int(m["n"]))

    m = _CALLED_WITH_RE.match(text)
    if m:
        cmp = m["cmp"] or "=="
        rhs_bool = (m["bool"] or "true") == "true"
        return Assertion(expr, m["tool"], "called_with", cmp, rhs_bool=rhs_bool, substr=m["sub"])

    m = _CALLED_RE.match(text)
    if m:
        cmp = m["cmp"] or "=="
        rhs_bool = (m["bool"] or "true") == "true"
        return Assertion(expr, m["tool"], "called", cmp, rhs_bool=rhs_bool)

    raise AssertionSyntaxError(f"unsupported side-effect assertion: {expr!r}")


def _as_name_args(call: object) -> tuple[str, dict]:
    if isinstance(call, dict):
        return str(call.get("name", "")), dict(call.get("args", {}) or {})
    return str(getattr(call, "name", "")), dict(getattr(call, "args", {}) or {})


def _cmp_int(a: int, op: str, b: int) -> bool:
    return {
        "==": a == b,
        "!=": a != b,
        ">=": a >= b,
        "<=": a <= b,
        ">": a > b,
        "<": a < b,
    }[op]


def _cmp_bool(actual: bool, op: str, expected: bool) -> bool:
    # Only == / != are meaningful for booleans; the grammar's bool forms restrict to these.
    return actual == expected if op == "==" else actual != expected


def evaluate(expr: str, calls: list) -> bool:
    """Parse ``expr`` and evaluate it over the observed ``calls`` (ToolCalls or dicts)."""
    assertion = parse_assertion(expr)
    pairs = [_as_name_args(c) for c in (calls or [])]

    if assertion.kind == "count":
        count = sum(1 for name, _ in pairs if name == assertion.tool)
        assert assertion.rhs_int is not None
        return _cmp_int(count, assertion.cmp, assertion.rhs_int)

    if assertion.kind == "called":
        called = any(name == assertion.tool for name, _ in pairs)
        assert assertion.rhs_bool is not None
        return _cmp_bool(called, assertion.cmp, assertion.rhs_bool)

    # called_with: case-insensitive substring over json.dumps(args, sort_keys=True).
    needle = (assertion.substr or "").casefold()
    matched = any(
        name == assertion.tool and needle in json.dumps(args, sort_keys=True).casefold()
        for name, args in pairs
    )
    assert assertion.rhs_bool is not None
    return _cmp_bool(matched, assertion.cmp, assertion.rhs_bool)
