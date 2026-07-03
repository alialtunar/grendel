"""The async HTTP/LLM target adapter (openai, anthropic, ollama shapes)."""

from __future__ import annotations

import time

import httpx

from ..errors import AdapterError, ProviderError
from .base import AdapterRequest, AdapterResponse, TargetAdapter
from .providers import API_PATHS, ProviderPreset

# Placeholder keys substituted into a `custom` provider's request template. Only these four are
# replaced; any other `{...}` in the template (e.g. inside an agent's own payload) is left verbatim.
_CUSTOM_PLACEHOLDERS = ("prompt", "system", "model", "api_key")


def _subst(value, mapping: dict[str, str]):
    """Recursively replace the known {placeholders} in string leaves of a JSON-like template."""
    if isinstance(value, str):
        out = value
        for key in _CUSTOM_PLACEHOLDERS:
            if key in mapping:
                out = out.replace("{" + key + "}", mapping[key])
        return out
    if isinstance(value, dict):
        return {k: _subst(v, mapping) for k, v in value.items()}
    if isinstance(value, list):
        return [_subst(v, mapping) for v in value]
    return value


def _dotted_get(data, path: str):
    """Walk a dotted path (dict keys + numeric list indices) into a parsed JSON response."""
    cur = data
    for part in path.split("."):
        if isinstance(cur, dict):
            if part not in cur:
                raise AdapterError(f"response has no field {path!r} (missing key {part!r})")
            cur = cur[part]
        elif isinstance(cur, list):
            if not part.isdigit() or int(part) >= len(cur):
                raise AdapterError(f"response has no field {path!r} (bad list index {part!r})")
            cur = cur[int(part)]
        else:
            raise AdapterError(
                f"response has no field {path!r} (cannot index into {type(cur).__name__})"
            )
    return cur


class HTTPTargetAdapter(TargetAdapter):
    """Speaks to OpenAI / Anthropic / Ollama-shaped HTTP endpoints via httpx."""

    def __init__(
        self,
        *,
        name: str,
        preset: ProviderPreset,
        model: str,
        base_url: str,
        api_key: str | None,
        client: httpx.AsyncClient | None = None,
        extra_headers: dict[str, str] | None = None,
        owns_client: bool = False,
    ) -> None:
        self.name = name
        self.preset = preset
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._client = client
        self._owns_client = owns_client
        self.extra_headers = dict(preset.default_headers)
        if extra_headers:
            self.extra_headers.update(extra_headers)

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()

    async def send(self, request: AdapterRequest) -> AdapterResponse:
        if self._client is None:
            raise AdapterError(f"target {self.name!r} has no HTTP client (built with dry_run=True)")
        style = self.preset.api_style
        if self.preset.requires_key and not self.api_key:
            raise ProviderError(
                f"target {self.name!r} ({style}) requires an API key but none was "
                f"resolved (set {self.preset.api_key_env or 'the api_key_env'})"
            )

        url, body, headers = self._build_request(style, request)

        start = time.perf_counter()
        resp = await self._client.post(url, json=body, headers=headers)
        latency_ms = (time.perf_counter() - start) * 1000.0

        if not (200 <= resp.status_code < 300):
            raise AdapterError(
                f"target {self.name!r} returned HTTP {resp.status_code}: {resp.text[:500]}",
                status_code=resp.status_code,
            )

        data = resp.json()
        return self._parse_response(style, data, latency_ms)

    def _build_request(
        self, style: str, request: AdapterRequest
    ) -> tuple[str, dict, dict[str, str]]:
        headers = dict(self.extra_headers)

        if style == "openai":
            messages = []
            if request.system:
                messages.append({"role": "system", "content": request.system})
            messages.append({"role": "user", "content": request.prompt})
            body = {
                "model": self.model,
                "messages": messages,
                "max_tokens": request.max_tokens,
                "temperature": request.temperature,
            }
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            return f"{self.base_url}{API_PATHS['openai']}", body, headers

        if style == "anthropic":
            body = {
                "model": self.model,
                "max_tokens": request.max_tokens,
                "temperature": request.temperature,
                "messages": [{"role": "user", "content": request.prompt}],
            }
            if request.system:
                body["system"] = request.system
            if self.api_key:
                headers["x-api-key"] = self.api_key
            headers.setdefault("anthropic-version", "2023-06-01")
            return f"{self.base_url}{API_PATHS['anthropic']}", body, headers

        if style == "ollama":
            messages = []
            if request.system:
                messages.append({"role": "system", "content": request.system})
            messages.append({"role": "user", "content": request.prompt})
            body = {
                "model": self.model,
                "messages": messages,
                "stream": False,
                "options": {
                    "temperature": request.temperature,
                    "num_predict": request.max_tokens,
                },
            }
            return f"{self.base_url}{API_PATHS['ollama']}", body, headers

        if style == "custom":
            req = self.preset.request or {}
            mapping = {
                "prompt": request.prompt,
                "system": request.system or "",
                "model": self.model,
                "api_key": self.api_key or "",
            }
            url = f"{self.base_url}{req.get('path', '')}"
            body = _subst(req.get("body") or {}, mapping)
            headers.update(_subst(req.get("headers") or {}, mapping))
            return url, body, headers

        raise AdapterError(f"unsupported api_style {style!r}")

    def _parse_response(self, style: str, data: dict, latency_ms: float) -> AdapterResponse:
        if style == "openai":
            choice = (data.get("choices") or [{}])[0]
            message = choice.get("message") or {}
            usage = data.get("usage") or {}
            return AdapterResponse(
                text=message.get("content") or "",
                raw=data,
                model=data.get("model", self.model),
                provider=self.preset.name,
                finish_reason=choice.get("finish_reason"),
                prompt_tokens=usage.get("prompt_tokens"),
                completion_tokens=usage.get("completion_tokens"),
                latency_ms=latency_ms,
            )

        if style == "anthropic":
            blocks = data.get("content") or []
            text = ""
            for block in blocks:
                if isinstance(block, dict) and block.get("type", "text") == "text":
                    text = block.get("text") or ""
                    break
            usage = data.get("usage") or {}
            return AdapterResponse(
                text=text,
                raw=data,
                model=data.get("model", self.model),
                provider=self.preset.name,
                finish_reason=data.get("stop_reason"),
                prompt_tokens=usage.get("input_tokens"),
                completion_tokens=usage.get("output_tokens"),
                latency_ms=latency_ms,
            )

        if style == "ollama":
            message = data.get("message") or {}
            return AdapterResponse(
                text=message.get("content") or "",
                raw=data,
                model=data.get("model", self.model),
                provider=self.preset.name,
                finish_reason=data.get("done_reason"),
                prompt_tokens=data.get("prompt_eval_count"),
                completion_tokens=data.get("eval_count"),
                latency_ms=latency_ms,
            )

        if style == "custom":
            path = (self.preset.response or {}).get("text_path")
            if not path:
                raise AdapterError(
                    f"custom provider {self.preset.name!r} has no response.text_path"
                )
            value = _dotted_get(data, path)
            return AdapterResponse(
                text=value if isinstance(value, str) else str(value),
                raw=data,
                model=self.model,
                provider=self.preset.name,
                latency_ms=latency_ms,
            )

        raise AdapterError(f"unsupported api_style {style!r}")
