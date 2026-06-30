"""The durable RunRecord data model and supporting types."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, Field

from .config import GauntletConfig


class Verdict(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    ERROR = "error"
    SKIPPED = "skipped"


class RunStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    ABORTED = "aborted"


class TokenUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class AttemptRecord(BaseModel):
    attempt_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    attack_id: str | None = None
    category: str | None = None
    prompt: str
    response_text: str | None = None
    raw_response: dict | None = None
    tool_calls: list[dict] = []
    verdict: Verdict = Verdict.SKIPPED
    score_tier: str | None = None
    error: str | None = None
    usage: TokenUsage = TokenUsage()
    latency_ms: float | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class RunRecord(BaseModel):
    schema_version: int = 1
    run_id: str
    created_at: datetime
    status: RunStatus = RunStatus.CREATED
    target_name: str
    provider: str
    model: str
    pack_ids: list[str] = []
    config_snapshot: dict = {}
    attempts: list[AttemptRecord] = []

    @property
    def total_attempts(self) -> int:
        return len(self.attempts)

    @property
    def asr(self) -> float:
        """Attack success rate: fraction of attempts whose verdict is FAIL.

        Phase 1 computes over all attempts; the non-control filter lands in Phase 6.
        """
        if not self.attempts:
            return 0.0
        failures = len([a for a in self.attempts if a.verdict == Verdict.FAIL])
        return failures / len(self.attempts)

    def by_category(self) -> dict[str, list[AttemptRecord]]:
        """Group attempts by category; a None category is keyed as 'uncategorized'."""
        grouped: dict[str, list[AttemptRecord]] = {}
        for attempt in self.attempts:
            key = attempt.category or "uncategorized"
            grouped.setdefault(key, []).append(attempt)
        return grouped

    def to_json(self) -> str:
        return self.model_dump_json()

    @classmethod
    def from_json(cls, s: str) -> RunRecord:
        return cls.model_validate_json(s)


def make_run_record(
    *,
    target_name: str,
    provider: str,
    model: str,
    config: GauntletConfig,
    pack_ids: list[str] | None = None,
    attempts: list[AttemptRecord] | None = None,
) -> RunRecord:
    """Construct a RunRecord, filling run_id, created_at and a sanitized snapshot.

    config_snapshot is built from ``config.model_dump(mode="json")`` — it contains only
    env-var *names* (api_key_env), never resolved secret values.
    """
    return RunRecord(
        run_id=uuid.uuid4().hex,
        created_at=datetime.now(UTC),
        target_name=target_name,
        provider=provider,
        model=model,
        pack_ids=pack_ids or [],
        config_snapshot=config.model_dump(mode="json"),
        attempts=attempts or [],
    )
