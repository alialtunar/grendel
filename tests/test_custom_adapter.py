"""Phase 19 M1: the configurable `custom` api_style — connect to any bespoke JSON agent API.

Locks in that an agent's request shape and response field come from CONFIG, not code:
config validation, provider resolution (dicts carried onto the preset), template substitution,
dotted response reads, and an offline end-to-end round-trip via httpx.MockTransport.
"""

from __future__ import annotations

import httpx
import pytest

from grendel.config import (
    CustomProviderConfig,
    CustomRequestSpec,
    CustomResponseSpec,
    GrendelConfig,
    TargetConfig,
)
from grendel.errors import AdapterError, ConfigError
from grendel.targets import build_target
from grendel.targets.base import AdapterRequest
from grendel.targets.http_adapter import _dotted_get, _subst
from grendel.targets.providers import resolve_provider


def _custom_cfg() -> GrendelConfig:
    return GrendelConfig(
        providers={
            "myagent": CustomProviderConfig(
                base_url="http://localhost:8080",
                api_style="custom",
                request=CustomRequestSpec(
                    path="/chat",
                    body={"message": "{prompt}", "sys": "{system}"},
                    headers={"X-Key": "Bearer {api_key}"},
                ),
                response=CustomResponseSpec(text_path="reply"),
            )
        },
        targets={"t": TargetConfig(provider="myagent", model="-")},
    )


# --- config validation ------------------------------------------------------------------------
def test_custom_requires_request_and_response() -> None:
    with pytest.raises(ConfigError, match="request.*response|both"):
        CustomProviderConfig(base_url="http://x", api_style="custom")


def test_custom_with_both_is_ok() -> None:
    p = CustomProviderConfig(
        base_url="http://x",
        api_style="custom",
        request=CustomRequestSpec(body={"m": "{prompt}"}),
        response=CustomResponseSpec(text_path="reply"),
    )
    assert p.api_style == "custom"


def test_request_response_rejected_for_non_custom_style() -> None:
    with pytest.raises(ConfigError, match="only valid for api_style 'custom'"):
        CustomProviderConfig(
            base_url="http://x",
            api_style="openai",
            response=CustomResponseSpec(text_path="reply"),
        )


# --- provider resolution: dicts carried, key optional -----------------------------------------
def test_resolve_carries_request_response_as_dicts() -> None:
    preset = resolve_provider("myagent", _custom_cfg())
    assert preset.api_style == "custom"
    assert preset.request == {"path": "/chat", "body": {"message": "{prompt}", "sys": "{system}"},
                              "headers": {"X-Key": "Bearer {api_key}"}}
    assert preset.response == {"text_path": "reply"}
    assert preset.requires_key is False  # custom is not an auth-requiring style by default


# --- pure helpers -----------------------------------------------------------------------------
def test_subst_replaces_known_leaves_only() -> None:
    tmpl = {"a": "{prompt}", "b": ["{system}", "{foo}"], "n": 5}
    out = _subst(tmpl, {"prompt": "P", "system": "S"})
    assert out == {"a": "P", "b": ["S", "{foo}"], "n": 5}  # {foo} untouched, non-str untouched


def test_dotted_get_walks_dicts_and_indices() -> None:
    data = {"choices": [{"message": {"content": "hi"}}]}
    assert _dotted_get(data, "choices.0.message.content") == "hi"


def test_dotted_get_missing_path_raises() -> None:
    with pytest.raises(AdapterError, match="no field"):
        _dotted_get({"reply": "x"}, "nope")


# --- end-to-end via MockTransport (offline) ---------------------------------------------------
async def test_custom_round_trip() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        captured["header"] = request.headers.get("x-key")
        return httpx.Response(200, json={"reply": "custom-answer"})

    cfg = _custom_cfg()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = build_target("t", cfg, client=client)
        resp = await adapter.send(AdapterRequest(prompt="attack!", system="be safe"))

    assert captured["path"] == "/chat"
    assert captured["body"] == {"message": "attack!", "sys": "be safe"}
    assert captured["header"] == "Bearer "  # no api_key set -> empty substitution
    assert resp.text == "custom-answer"
    assert resp.provider == "myagent"


def test_describe_target_custom_shows_path_and_text_path() -> None:
    # The add-target confirmation must show the real POST path + response field for a custom agent,
    # not the openai /chat/completions fallback.
    import grendel.cli as cli

    cfg = _custom_cfg()
    summary = cli.describe_target(cfg.targets["t"], cfg)
    assert "POST http://localhost:8080/chat" in summary
    assert "reply" in summary


async def test_custom_bad_text_path_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"different": "shape"})

    cfg = _custom_cfg()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = build_target("t", cfg, client=client)
        with pytest.raises(AdapterError, match="no field 'reply'"):
            await adapter.send(AdapterRequest(prompt="hi"))
