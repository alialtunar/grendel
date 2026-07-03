"""Tests for HTTPTargetAdapter across all three api_styles, via httpx.MockTransport."""

from __future__ import annotations

import httpx
import pytest

from grendel.config import GrendelConfig, TargetConfig
from grendel.errors import AdapterError, ProviderError
from grendel.targets import build_target
from grendel.targets.base import AdapterRequest


def _handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path.endswith("/chat/completions"):
        return httpx.Response(
            200,
            json={
                "model": "gpt-4o-mini",
                "choices": [{"message": {"content": "openai-text"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 4},
            },
        )
    if path.endswith("/messages"):
        return httpx.Response(
            200,
            json={
                "model": "claude-x",
                "content": [{"type": "text", "text": "anthropic-text"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 5, "output_tokens": 6},
            },
        )
    if path.endswith("/api/chat"):
        return httpx.Response(
            200,
            json={
                "model": "llama3",
                "message": {"content": "ollama-text"},
                "done_reason": "stop",
                "prompt_eval_count": 7,
                "eval_count": 8,
            },
        )
    return httpx.Response(404, json={"error": "not found"})


def _mock_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(_handler))


async def test_openai_style(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-dummy")
    cfg = GrendelConfig(targets={"t": TargetConfig(provider="openai", model="gpt-4o-mini")})
    async with _mock_client() as client:
        adapter = build_target("t", cfg, client=client)
        resp = await adapter.send(AdapterRequest(prompt="hi"))
    assert resp.text == "openai-text"
    assert resp.finish_reason == "stop"
    assert resp.prompt_tokens == 3
    assert resp.completion_tokens == 4
    assert resp.provider == "openai"


async def test_anthropic_style(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-dummy")
    cfg = GrendelConfig(targets={"t": TargetConfig(provider="anthropic", model="claude-x")})
    async with _mock_client() as client:
        adapter = build_target("t", cfg, client=client)
        resp = await adapter.send(AdapterRequest(prompt="hi", system="be safe"))
    assert resp.text == "anthropic-text"
    assert resp.finish_reason == "end_turn"
    assert resp.prompt_tokens == 5
    assert resp.completion_tokens == 6


async def test_ollama_style() -> None:
    cfg = GrendelConfig(targets={"t": TargetConfig(provider="ollama", model="llama3")})
    async with _mock_client() as client:
        adapter = build_target("t", cfg, client=client)
        resp = await adapter.send(AdapterRequest(prompt="hi"))
    assert resp.text == "ollama-text"
    assert resp.finish_reason == "stop"
    assert resp.prompt_tokens == 7
    assert resp.completion_tokens == 8


async def test_non_2xx_raises_adapter_error(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-dummy")
    cfg = GrendelConfig(
        targets={
            "t": TargetConfig(
                provider="openai",
                model="gpt-4o-mini",
            )
        }
    )

    def error_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    transport = httpx.MockTransport(error_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = build_target("t", cfg, client=client)
        with pytest.raises(AdapterError, match="500"):
            await adapter.send(AdapterRequest(prompt="hi"))


async def test_missing_key_raises_provider_error(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    cfg = GrendelConfig(targets={"t": TargetConfig(provider="openai", model="gpt-4o-mini")})
    async with _mock_client() as client:
        adapter = build_target("t", cfg, client=client)
        with pytest.raises(ProviderError, match="API key"):
            await adapter.send(AdapterRequest(prompt="hi"))


async def test_owns_created_client_closes(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-dummy")
    cfg = GrendelConfig(targets={"t": TargetConfig(provider="openai", model="gpt-4o-mini")})
    adapter = build_target("t", cfg)  # no client -> adapter owns one
    assert adapter._owns_client is True
    await adapter.aclose()
