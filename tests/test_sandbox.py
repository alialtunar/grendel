"""M1: ToolRegistry/ToolContext record tool calls with no real side effect."""

from __future__ import annotations

from pathlib import Path

import pytest

from grendel.sandbox import ToolCall, ToolContext, ToolRegistry


def test_call_records_in_order_with_ordinals() -> None:
    reg = ToolRegistry()
    reg.register("send_email")
    reg.register("delete_file")
    reg.call("send_email", to="a@x.example")
    reg.call("delete_file", path="/tmp/x")
    reg.call("send_email", to="b@x.example")

    calls = reg.calls
    assert [c.ordinal for c in calls] == [0, 1, 2]
    assert [c.name for c in calls] == ["send_email", "delete_file", "send_email"]
    assert all(isinstance(c, ToolCall) for c in calls)


def test_count_and_called() -> None:
    reg = ToolRegistry()
    reg.register("send_email")
    reg.call("send_email", to="a@x.example")
    reg.call("send_email", to="b@x.example")
    assert reg.count("send_email") == 2
    assert reg.called("send_email") is True
    # Never-called / unknown tool.
    assert reg.count("delete_file") == 0
    assert reg.called("delete_file") is False


def test_snapshot_shape() -> None:
    reg = ToolRegistry()
    reg.register("send_email")
    reg.call("send_email", to="a@x.example", body="hi")
    snap = reg.snapshot()
    assert snap == [
        {"name": "send_email", "args": {"to": "a@x.example", "body": "hi"}, "ordinal": 0}
    ]


def test_registered_fake_runs_but_no_real_side_effect(tmp_path: Path) -> None:
    target = tmp_path / "should_not_exist.txt"
    calls: list[str] = []

    def fake_delete(*, path: str) -> str:
        calls.append(path)  # record only — never touches the filesystem
        return "deleted"

    reg = ToolRegistry()
    reg.register("delete_file", fake_delete)
    result = reg.call("delete_file", path=str(target))

    assert result == "deleted"
    assert calls == [str(target)]
    assert not target.exists()  # the fake performed no real side effect


def test_register_rejects_reserved_names() -> None:
    reg = ToolRegistry()
    for reserved in ("register", "call", "calls", "count", "called", "snapshot"):
        with pytest.raises(ValueError, match="reserved"):
            reg.register(reserved)


def test_non_json_serializable_args_rejected() -> None:
    reg = ToolRegistry()
    reg.register("send_email")
    with pytest.raises(ValueError, match="JSON-serializable"):
        reg.call("send_email", to=object())


def test_context_getattr_routes_through_registry() -> None:
    reg = ToolRegistry()
    ctx = ToolContext(reg)
    ctx.register("send_email", lambda *, to: "queued")
    out = ctx.send_email(to="evil@x.example")
    assert out == "queued"
    assert ctx.snapshot() == [
        {"name": "send_email", "args": {"to": "evil@x.example"}, "ordinal": 0}
    ]


def test_context_unregistered_tool_raises_attributeerror() -> None:
    ctx = ToolContext(ToolRegistry())
    missing = "not_a_tool"
    with pytest.raises(AttributeError):
        getattr(ctx, missing)


def test_fresh_registry_isolation() -> None:
    a = ToolRegistry()
    b = ToolRegistry()
    a.register("send_email")
    a.call("send_email", to="x@x.example")
    # b is a separate registry — observes nothing from a.
    assert a.count("send_email") == 1
    assert b.count("send_email") == 0
    assert b.snapshot() == []
