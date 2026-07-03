"""M3: the safe side-effect grammar parser + evaluator (no eval)."""

from __future__ import annotations

import inspect

import pytest

from grendel import sideeffect
from grendel.sandbox import ToolCall
from grendel.sideeffect import AssertionSyntaxError, evaluate, parse_assertion

# Two send_email calls (one to an external address) + one delete_file.
CALLS = [
    {"name": "send_email", "args": {"to": "a@internal.example", "body": "hi"}, "ordinal": 0},
    {"name": "send_email", "args": {"to": "thief@external.example"}, "ordinal": 1},
    {"name": "delete_file", "args": {"path": "/x"}, "ordinal": 2},
]


@pytest.mark.parametrize(
    ("expr", "expected"),
    [
        ("send_email.called", True),
        ("send_email.called == true", True),
        ("send_email.called == false", False),
        ("never_called.called", False),
        ("never_called.called == false", True),
        ("send_email.count == 2", True),
        ("send_email.count >= 1", True),
        ("send_email.count > 2", False),
        ("send_email.count <= 2", True),
        ("send_email.count != 0", True),
        ("send_email.count < 5", True),
        ("never_called.count == 0", True),
        ("send_email.called_with('external')", True),
        ("send_email.called_with('EXTERNAL')", True),  # case-insensitive
        ("send_email.called_with('missing')", False),
        ("send_email.called_with('external') == false", False),
        ("send_email.called_with('missing') == false", True),
        ("tool.calls['send_email'] >= 1", True),
        ("tool.calls['send_email'] == 2", True),
        ("tool.calls['delete_file'] == 1", True),
        ("delete_file.called", True),
    ],
)
def test_grammar_matrix(expr: str, expected: bool) -> None:
    assert evaluate(expr, CALLS) is expected


def test_evaluate_accepts_toolcall_objects() -> None:
    calls = [ToolCall(name="send_email", args={"to": "x@external.example"}, ordinal=0)]
    assert evaluate("send_email.called_with('external')", calls) is True
    assert evaluate("send_email.count == 1", calls) is True


def test_unknown_tool_is_false_not_error() -> None:
    assert evaluate("ghost.called", []) is False
    assert evaluate("ghost.count == 0", []) is True


@pytest.mark.parametrize(
    "expr",
    [
        "os.system('rm -rf /')",
        "a and b",
        "1 + 1",
        "send_email",  # bare ident, no attr
        "send_email.count >= 'x'",  # non-int rhs
        "send_email.delete()",  # unknown function
        "send_email.called_with()",  # wrong arity
        "send_email.called_with('a', 'b')",
        "send_email.count",  # missing comparator
        "send_email.called == maybe",  # non-bool
        "__import__('os')",
        "",
    ],
)
def test_safety_set_raises(expr: str) -> None:
    with pytest.raises(AssertionSyntaxError):
        parse_assertion(expr)


def test_no_eval_in_source() -> None:
    src = inspect.getsource(sideeffect)
    assert "eval(" not in src
    assert "exec(" not in src
