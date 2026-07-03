"""Live model discovery: ask a provider's own API which models it serves.

Best-effort and non-fatal — used only to enrich the interactive model picker. Every failure
(no key, network, timeout, non-2xx, unexpected shape) degrades to an empty list; the picker then
falls back to the preset's static suggestions. Never raises.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from .providers import ProviderPreset


def fetch_models(
    preset: ProviderPreset, api_key: str | None, *, client=None, timeout=4.0
) -> list[str]:
    """Return the provider's live model ids, or [] on any problem (never raises)."""
    base = (preset.base_url or "").rstrip("/")
    if not base or preset.api_style == "custom":
        return []
    try:
        if preset.api_style == "ollama":
            url, headers, key = f"{base}/api/tags", {}, "models"
        elif preset.api_style == "anthropic":
            url, headers, key = f"{base}/models", dict(preset.default_headers), "data"
            if api_key:
                headers["x-api-key"] = api_key
        else:  # openai + openai-compatible
            url, headers, key = f"{base}/models", {}, "data"
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
        owns = client is None
        c = client or httpx.Client(timeout=timeout)
        try:
            # pass timeout on get() too, so an injected client without a default also degrades
            resp = c.get(url, headers=headers, timeout=timeout)
        finally:
            if owns:
                c.close()
        resp.raise_for_status()
        rows = resp.json().get(key, [])
        field = "name" if preset.api_style == "ollama" else "id"
        out: list[str] = []
        for row in rows:
            val = row.get(field) if isinstance(row, dict) else None
            if isinstance(val, str) and val and val not in out:
                out.append(val)
        return out
    except Exception:  # noqa: BLE001 — discovery is best-effort; any failure → static fallback
        return []
