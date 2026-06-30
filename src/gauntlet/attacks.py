"""The Attack schema, the success_when tagged union, and the license allowlist."""

from __future__ import annotations

import re
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Permissive, embeddable, commercial-safe SPDX licenses (ROADMAP §2 "Clean licensing").
ALLOWED_LICENSES: frozenset[str] = frozenset(
    {"Apache-2.0", "MIT", "BSD-2-Clause", "BSD-3-Clause", "CC0-1.0"}
)


class Surface(str, Enum):
    """Where the payload is injected."""

    PROMPT = "prompt"
    TOOL_OUTPUT = "tool-output"
    RAG = "rag"
    MCP_DESC = "mcp-desc"


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class StringCheck(BaseModel):
    """Deterministic text match against the target's response."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["string"]
    contains: list[str] | None = None
    pattern: str | None = None
    case_sensitive: bool = False
    match: Literal["any", "all"] = "any"

    @model_validator(mode="after")
    def _check_at_least_one(self) -> StringCheck:
        # Falsy check so contains=[] with no pattern is rejected too (review fix #2).
        if not self.contains and self.pattern is None:
            raise ValueError("string check requires at least one of 'contains' or 'pattern'")
        if self.pattern is not None:
            try:
                re.compile(self.pattern)
            except re.error as exc:
                raise ValueError(f"invalid regex pattern: {exc}") from exc
        return self


class SideEffectCheck(BaseModel):
    """Outcome assertion against an agent/sandbox target (evaluated in Phase 7)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    type: Literal["side-effect"]
    assert_: str = Field(alias="assert", min_length=1)


class ClassifierCheck(BaseModel):
    """Refusal/harm classifier outcome (evaluated in Phase 4 T2)."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["classifier"]
    classifier: str
    label: str
    threshold: float = Field(default=0.5, ge=0.0, le=1.0)


class JudgeCheck(BaseModel):
    """LLM-as-judge outcome (evaluated in Phase 6 T3)."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["judge"]
    rubric: str = Field(min_length=1)
    pass_if: str = "attack_succeeded"


SuccessWhen = Annotated[
    StringCheck | SideEffectCheck | ClassifierCheck | JudgeCheck,
    Field(discriminator="type"),
]


class Attack(BaseModel):
    """A single attack, loaded from one YAML file (ROADMAP §4)."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9-]+/[a-z0-9-]+$")
    name: str
    category: str = Field(pattern=r"^[a-z0-9-]+$")
    owasp: str = Field(pattern=r"^LLM(0[1-9]|10)$")
    atlas: str = Field(pattern=r"^AML\.T\d{4}(\.\d{3})?$")
    surface: Surface
    severity: Severity
    license: str
    version: int = Field(ge=1)
    payload: str
    success_when: SuccessWhen
    references: list[Annotated[str, Field(min_length=1)]] = []

    @field_validator("payload", "name")
    @classmethod
    def _non_empty_after_strip(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must be non-empty after stripping whitespace")
        return v
