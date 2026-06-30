"""The MCP attack-surface model: ``McpToolDescriptor`` + ``McpObservation``.

A **leaf module** (pydantic + json only) — no imports from ``targets``/``scoring`` so
``targets/base.py`` can import it with no cycle. JSON-serializable, offline, deterministic.
"""

from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict


class McpToolDescriptor(BaseModel):
    """One advertised MCP tool: name, description, and a stable schema fingerprint."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""
    schema_fingerprint: str | None = None  # stable repr of inputSchema (json.dumps(sort_keys))


class McpObservation(BaseModel):
    """The MCP observation attached to a response (the not-applicable data seam)."""

    model_config = ConfigDict(extra="forbid")

    tools: list[McpToolDescriptor] = []  # the CURRENT tool catalog
    approved_descriptions: dict[str, str] = {}  # name -> description, snapshotted at "approval"
    current_descriptions: dict[str, str] = {}  # name -> description, snapshotted "now"


def descriptions_of(tools: list[McpToolDescriptor]) -> dict[str, str]:
    """``{name: description}`` for the given descriptors."""
    return {d.name: d.description for d in tools}


def fingerprint_schema(schema: object) -> str | None:
    """Stable repr of an inputSchema (``json.dumps(sort_keys=True)``), or None when absent."""
    if schema is None:
        return None
    return json.dumps(schema, sort_keys=True, default=str)
