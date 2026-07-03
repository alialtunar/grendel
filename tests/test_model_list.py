"""Phase 21 M1: live model discovery — fetch_models per api_style, offline via MockTransport.

Locks in that discovery is best-effort: real shapes are parsed, and every failure mode (no key,
non-2xx, network error, bad shape, custom/no-base_url) degrades to [] without raising — so the
picker can always fall back to the preset's static suggestions.
"""

from __future__ import annotations

import httpx

from grendel.targets.model_list import fetch_models
from grendel.targets.providers import PRESETS


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_openai_style_reads_data_ids() -> None:
    captured: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["path"] = req.url.path
        captured["auth"] = req.headers.get("authorization")
        return httpx.Response(200, json={"data": [{"id": "gpt-4o"}, {"id": "o3-mini"}]})

    with _client(handler) as c:
        out = fetch_models(PRESETS["openai"], "sk-test", client=c)
    assert out == ["gpt-4o", "o3-mini"]
    assert captured["path"] == "/v1/models"
    assert captured["auth"] == "Bearer sk-test"


def test_openai_missing_key_sends_no_auth_and_401_gives_empty() -> None:
    seen: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["auth"] = req.headers.get("authorization")
        return httpx.Response(401, json={"error": "no key"})

    with _client(handler) as c:
        out = fetch_models(PRESETS["openai"], None, client=c)
    assert out == []  # 401 → [], no raise
    assert seen["auth"] is None  # no key → no Authorization header


def test_anthropic_style_sets_x_api_key_and_version() -> None:
    seen: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["x-api-key"] = req.headers.get("x-api-key")
        seen["version"] = req.headers.get("anthropic-version")
        return httpx.Response(200, json={"data": [{"id": "claude-sonnet-5"}]})

    with _client(handler) as c:
        out = fetch_models(PRESETS["anthropic"], "ak-1", client=c)
    assert out == ["claude-sonnet-5"]
    assert seen["x-api-key"] == "ak-1"
    assert seen["version"] == "2023-06-01"


def test_anthropic_missing_key_no_header_and_403_gives_empty() -> None:
    seen: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["x-api-key"] = req.headers.get("x-api-key")
        return httpx.Response(403, json={"error": "forbidden"})

    with _client(handler) as c:
        out = fetch_models(PRESETS["anthropic"], None, client=c)
    assert out == []  # 403 → [], no TypeError from a None header value
    assert seen["x-api-key"] is None


def test_ollama_style_reads_model_names_no_auth() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/api/tags"
        assert req.headers.get("authorization") is None
        return httpx.Response(200, json={"models": [{"name": "llama3.1"}, {"name": "qwen2.5"}]})

    with _client(handler) as c:
        out = fetch_models(PRESETS["ollama"], None, client=c)
    assert out == ["llama3.1", "qwen2.5"]


def test_network_error_degrades_to_empty() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    with _client(handler) as c:
        assert fetch_models(PRESETS["openai"], "k", client=c) == []


def test_bad_shape_degrades_to_empty() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": True})

    with _client(handler) as c:
        assert fetch_models(PRESETS["openai"], "k", client=c) == []


def test_openai_compatible_has_no_base_url_returns_empty() -> None:
    # base_url is None → never issues a request to a null URL
    assert fetch_models(PRESETS["openai-compatible"], "k") == []


def test_static_fallback_lists_are_nontrivial() -> None:
    for name in ("openai", "anthropic", "ollama"):
        assert len(PRESETS[name].models) >= 5
