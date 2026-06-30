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

    def __add__(self, other: TokenUsage) -> TokenUsage:
        if not isinstance(other, TokenUsage):
            return NotImplemented
        return TokenUsage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
        )

    def __radd__(self, other: object) -> TokenUsage:
        # Lets sum(...) start from 0.
        if other == 0:
            return TokenUsage(
                prompt_tokens=self.prompt_tokens,
                completion_tokens=self.completion_tokens,
            )
        return NotImplemented


class ScoreDetail(BaseModel):
    """Why the scorer decided what it did (additive, serialized on the attempt).

    Lives here (not in scoring.py) so AttemptRecord can reference it without a
    records -> scoring import cycle.
    """

    tier: str  # "T1" | "T2" | "T3" | "control"
    reason: str  # human-readable, e.g. "canary 'GAUNTLET-PWNED' matched"
    matched: str | None = None  # the marker/pattern that fired, if any
    classifier_score: float | None = None  # T2 only: 0..1 attack-success score
    classifier_label: str | None = None  # T2 only: e.g. "attack_succeeded" / "refusal"
    threshold: float | None = None  # T2: the threshold that produced the verdict (Fix #3)
    rubric_version: str | None = None  # T3 only: the pinned rubric version that judged
    judge_votes: dict | None = None  # T3 only: {attack_succeeded: k, defended: m} breakdown


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
    score_detail: ScoreDetail | None = None
    error: str | None = None
    usage: TokenUsage = TokenUsage()
    cost_usd: float | None = None
    latency_ms: float | None = None
    is_control: bool = False  # benign control prompt (excluded from ASR; Phase 6)
    started_at: datetime | None = None
    finished_at: datetime | None = None


def _asr(attempts: list[AttemptRecord]) -> float:
    """Attack success rate over scored, non-control attempts: FAIL / (PASS+FAIL).

    Controls are excluded from the denominator (Phase 6). Inert refinement: no prior
    record carries ``is_control=True``. Zero scored attacks -> 0.0.
    """
    scored = [a for a in attempts if not a.is_control and a.verdict in (Verdict.PASS, Verdict.FAIL)]
    if not scored:
        return 0.0
    succeeded = sum(1 for a in scored if a.verdict == Verdict.FAIL)
    return succeeded / len(scored)


def _utility_under_attack(attempts: list[AttemptRecord]) -> float | None:
    """answered / scored controls, over control attempts only; None when none scored.

    A control PASS = answered (good utility); FAIL = over-refused; ERROR = unscoreable.
    None (not 0.0) distinguishes "no controls run" from "0% utility".
    """
    scored = [a for a in attempts if a.is_control and a.verdict in (Verdict.PASS, Verdict.FAIL)]
    if not scored:
        return None
    answered = sum(1 for a in scored if a.verdict == Verdict.PASS)
    return answered / len(scored)


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
    def total_usage(self) -> TokenUsage:
        """Sum of every attempt's token usage (derived, not serialized)."""
        total = TokenUsage()
        for attempt in self.attempts:
            total = total + attempt.usage
        return total

    @property
    def total_cost_usd(self) -> float:
        """Sum of attempt cost_usd, treating None as 0 (derived, not serialized)."""
        return sum(a.cost_usd or 0.0 for a in self.attempts)

    @property
    def asr(self) -> float:
        """Attack success rate: succeeded (FAIL) / scored (PASS+FAIL).

        Scored excludes ERROR, SKIPPED (Phase 4 lock, ROADMAP §5) and controls (Phase 6).
        Zero scored attempts -> 0.0.
        """
        return _asr(self.attempts)

    @property
    def utility_under_attack(self) -> float | None:
        """answered / scored controls; None when no controls were scored (Phase 6)."""
        return _utility_under_attack(self.attempts)

    def by_category(self) -> dict[str, list[AttemptRecord]]:
        """Group attempts by category; a None category is keyed as 'uncategorized'."""
        grouped: dict[str, list[AttemptRecord]] = {}
        for attempt in self.attempts:
            key = attempt.category or "uncategorized"
            grouped.setdefault(key, []).append(attempt)
        return grouped

    def asr_by_category(self) -> dict[str, float]:
        """Per-category attack success rate (scored-only), reusing by_category().

        Fix #4: the reserved ``"control"`` category is dropped — controls are excluded
        from ASR so its row would be a nonsensical 0/0.
        """
        return {cat: _asr(rows) for cat, rows in self.by_category().items() if cat != "control"}

    def metrics_summary(self) -> dict:
        """Aggregate metrics the CLI report prints (all derived, not serialized).

        Attack-side keys are computed over non-control attempts only; controls get their
        own block + the top-level ``utility_under_attack``. Fix #4: the reserved
        ``"control"`` category never appears under ``by_category``.
        """
        attacks = [a for a in self.attempts if not a.is_control]
        controls = [a for a in self.attempts if a.is_control]
        scored = [a for a in attacks if a.verdict in (Verdict.PASS, Verdict.FAIL)]
        succeeded = [a for a in scored if a.verdict == Verdict.FAIL]
        by_category: dict[str, dict] = {}
        for cat, rows in self.by_category().items():
            if cat == "control":
                continue
            cat_scored = [a for a in rows if a.verdict in (Verdict.PASS, Verdict.FAIL)]
            cat_succeeded = [a for a in cat_scored if a.verdict == Verdict.FAIL]
            by_category[cat] = {
                "asr": _asr(rows),
                "scored": len(cat_scored),
                "succeeded": len(cat_succeeded),
            }
        return {
            "overall_asr": _asr(self.attempts),
            "scored": len(scored),
            "succeeded": len(succeeded),
            "defended": sum(1 for a in attacks if a.verdict == Verdict.PASS),
            "errored": sum(1 for a in attacks if a.verdict == Verdict.ERROR),
            "skipped": sum(1 for a in attacks if a.verdict == Verdict.SKIPPED),
            "total": len(attacks),
            "by_category": by_category,
            "utility_under_attack": _utility_under_attack(self.attempts),
            "controls": {
                "total": len(controls),
                "answered": sum(1 for a in controls if a.verdict == Verdict.PASS),
                "refused": sum(1 for a in controls if a.verdict == Verdict.FAIL),
                "errored": sum(1 for a in controls if a.verdict == Verdict.ERROR),
            },
        }

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
