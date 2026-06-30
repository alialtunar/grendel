"""The pure, framework-free presentation model for the TUI scoreboard.

This module computes *everything the UI needs* from a ``RunRecord`` (live results) plus
the selected ``list[Attack]`` (the plan). It holds plain ``@dataclass(frozen=True)`` types
and pure functions only — **no Textual import, no I/O, no network**. The Textual widgets in
``app.py`` are thin renderers over the state these functions produce.

Reuse rule: ASR and per-category grouping come from ``records`` helpers (``_asr``,
``by_category``, ``metrics_summary``); we never recompute ASR by hand.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from datetime import datetime

from ..attacks import Attack, Severity
from ..records import RunRecord, RunStatus, Verdict, _asr

# Severity has no native ordering (it is a str-Enum), so we define an explicit rank for
# "this severity or worse" filtering and worst-first sorting (review fix #2).
_SEVERITY_RANK: dict[Severity, int] = {
    Severity.LOW: 0,
    Severity.MEDIUM: 1,
    Severity.HIGH: 2,
    Severity.CRITICAL: 3,
}


def _rank(severity: Severity | None) -> int:
    """Sort/compare rank for a severity; ``None`` ranks below everything."""
    return _SEVERITY_RANK[severity] if severity is not None else -1


@dataclass(frozen=True)
class AttemptFilter:
    category: str | None = None  # show only this category (None = all)
    verdict: Verdict | None = None  # show only this verdict in the failures list (None = all)
    severity: Severity | None = None  # show only this severity or worse (None = all)


@dataclass(frozen=True)
class CategoryRow:
    category: str
    total: int  # attacks planned in this category (from the plan)
    done: int  # attempts recorded in this category
    passed: int
    failed: int
    errored: int
    skipped: int
    asr: float  # _asr over scored (PASS+FAIL) rows
    flag_severity: Severity | None  # max Severity among FAILED attacks; None if no failures


@dataclass(frozen=True)
class FailureItem:
    attempt_id: str
    attack_id: str | None
    name: str | None
    category: str | None
    severity: Severity | None
    owasp: str | None
    atlas: str | None
    verdict: Verdict  # FAIL or ERROR
    score_tier: str | None
    payload: str | None
    prompt: str
    response_text: str | None
    reason: str | None
    matched: str | None
    classifier_score: float | None
    error: str | None


@dataclass(frozen=True)
class ScoreboardState:
    run_id: str
    target_name: str
    provider: str
    model: str
    status: RunStatus
    total: int
    done: int
    passed: int
    failed: int
    errored: int
    skipped: int
    overall_asr: float
    elapsed_s: float
    total_cost_usd: float
    total_tokens: int
    categories: tuple[CategoryRow, ...]
    failures: tuple[FailureItem, ...]  # AFTER filter applied
    selected_index: int  # index into `failures`; clamped to [0, len-1], or -1 if empty
    filter: AttemptFilter
    explain_visible: bool
    # Complete, sorted FAIL/ERROR set BEFORE filtering — kept so with_filter() can re-filter
    # purely from a state alone (not part of the rendered surface).
    all_failures: tuple[FailureItem, ...] = field(default=(), repr=False)

    @property
    def progress(self) -> float:
        return (self.done / self.total) if self.total else 0.0

    @property
    def selected_failure(self) -> FailureItem | None:
        if 0 <= self.selected_index < len(self.failures):
            return self.failures[self.selected_index]
        return None


def _clamp_index(index: int, n: int) -> int:
    """Clamp a selection index into ``[0, n-1]``, or ``-1`` when the list is empty."""
    if n <= 0:
        return -1
    return max(0, min(index, n - 1))


def _elapsed_s(record: RunRecord, now: datetime | None) -> float:
    """Deterministic elapsed seconds from the attempt timestamps (spec §3.6)."""
    starts = [a.started_at for a in record.attempts if a.started_at is not None]
    if not starts:
        return 0.0
    start = min(starts)
    if record.status == RunStatus.RUNNING and now is not None:
        end = now
    else:
        ends = [a.finished_at for a in record.attempts if a.finished_at is not None]
        end = max(ends) if ends else start
    return max(0.0, (end - start).total_seconds())


def _failure_sort_key(item: FailureItem) -> tuple[int, str, str]:
    """Worst-first: severity desc, then category, then attack_id."""
    return (-_rank(item.severity), item.category or "", item.attack_id or "")


def apply_filter(items: list[FailureItem], f: AttemptFilter) -> list[FailureItem]:
    """Filter failures by category, verdict, and "this severity or worse" (pure)."""
    out = []
    for item in items:
        if f.category is not None and item.category != f.category:
            continue
        if f.verdict is not None and item.verdict != f.verdict:
            continue
        if f.severity is not None and _rank(item.severity) < _rank(f.severity):
            continue
        out.append(item)
    return out


def build_scoreboard(
    attacks: list[Attack],
    record: RunRecord,
    *,
    now: datetime | None = None,
    filter: AttemptFilter = AttemptFilter(),  # noqa: B008 — frozen, hashable default is safe
    selected_index: int = 0,
    explain_visible: bool = False,
) -> ScoreboardState:
    """Compute the full scoreboard view-model from the plan + live results (pure)."""
    by_id = {a.id: a for a in attacks}
    metrics = record.metrics_summary()

    # CategoryRow.total comes from the PLAN, not executed attempts (review fix #5).
    plan_by_cat: dict[str, int] = {}
    for atk in attacks:
        plan_by_cat[atk.category] = plan_by_cat.get(atk.category, 0) + 1

    executed_by_cat = record.by_category()
    categories: list[CategoryRow] = []
    for cat in sorted(set(plan_by_cat) | set(executed_by_cat)):
        rows = executed_by_cat.get(cat, [])
        failed_severities = [
            by_id[a.attack_id].severity
            for a in rows
            if a.verdict == Verdict.FAIL and a.attack_id in by_id
        ]
        flag = max(failed_severities, key=_rank) if failed_severities else None
        categories.append(
            CategoryRow(
                category=cat,
                total=plan_by_cat.get(cat, 0),
                done=len(rows),
                passed=sum(1 for a in rows if a.verdict == Verdict.PASS),
                failed=sum(1 for a in rows if a.verdict == Verdict.FAIL),
                errored=sum(1 for a in rows if a.verdict == Verdict.ERROR),
                skipped=sum(1 for a in rows if a.verdict == Verdict.SKIPPED),
                asr=_asr(rows),
                flag_severity=flag,
            )
        )

    all_failures: list[FailureItem] = []
    for a in record.attempts:
        if a.verdict not in (Verdict.FAIL, Verdict.ERROR):
            continue
        atk = by_id.get(a.attack_id) if a.attack_id is not None else None
        detail = a.score_detail
        all_failures.append(
            FailureItem(
                attempt_id=a.attempt_id,
                attack_id=a.attack_id,
                name=atk.name if atk else None,
                category=a.category or (atk.category if atk else None),
                severity=atk.severity if atk else None,
                owasp=atk.owasp if atk else None,
                atlas=atk.atlas if atk else None,
                verdict=a.verdict,
                score_tier=a.score_tier,
                payload=atk.payload if atk else None,
                prompt=a.prompt,
                response_text=a.response_text,
                reason=detail.reason if detail else None,
                matched=detail.matched if detail else None,
                classifier_score=detail.classifier_score if detail else None,
                error=a.error,
            )
        )
    all_failures.sort(key=_failure_sort_key)

    filtered = apply_filter(all_failures, filter)
    sel = _clamp_index(selected_index, len(filtered))

    return ScoreboardState(
        run_id=record.run_id,
        target_name=record.target_name,
        provider=record.provider,
        model=record.model,
        status=record.status,
        total=len(attacks),
        done=metrics["total"],
        passed=metrics["defended"],
        failed=metrics["succeeded"],
        errored=metrics["errored"],
        skipped=metrics["skipped"],
        overall_asr=metrics["overall_asr"],
        elapsed_s=_elapsed_s(record, now),
        total_cost_usd=record.total_cost_usd,
        total_tokens=record.total_usage.total_tokens,
        categories=tuple(categories),
        failures=tuple(filtered),
        selected_index=sel,
        filter=filter,
        explain_visible=explain_visible,
        all_failures=tuple(all_failures),
    )


def with_filter(state: ScoreboardState, f: AttemptFilter) -> ScoreboardState:
    """Re-filter the complete failure set under a new filter; reset/clamp selection (pure)."""
    filtered = apply_filter(list(state.all_failures), f)
    return dataclasses.replace(
        state,
        filter=f,
        failures=tuple(filtered),
        selected_index=_clamp_index(0, len(filtered)),
    )


def select_next(state: ScoreboardState, step: int) -> ScoreboardState:
    """Move the selection by ``step`` within the filtered failures, clamped (pure)."""
    n = len(state.failures)
    if n == 0:
        return dataclasses.replace(state, selected_index=-1)
    base = state.selected_index if state.selected_index >= 0 else 0
    return dataclasses.replace(state, selected_index=_clamp_index(base + step, n))


def toggle_explain(state: ScoreboardState) -> ScoreboardState:
    """Flip the explain-visible flag (pure)."""
    return dataclasses.replace(state, explain_visible=not state.explain_visible)


def repro_for(item: FailureItem, *, target_name: str) -> str:
    """Deterministic, copy-paste repro string for one failure (spec §3.7)."""

    def _dash(value: object | None) -> str:
        if value is None:
            return "-"
        if isinstance(value, Severity):
            return value.value
        return str(value)

    attack_id = item.attack_id if item.attack_id is not None else "(unknown)"
    response = item.response_text if item.response_text else "(no response)"
    tier = item.score_tier if item.score_tier is not None else "-"
    detail = item.reason or item.error or "(no detail)"
    return (
        f"# gauntlet repro — {attack_id}\n"
        f"# category={_dash(item.category)} severity={_dash(item.severity)} "
        f"owasp={_dash(item.owasp)} atlas={_dash(item.atlas)}\n"
        f"gauntlet run --target {target_name} --pack {attack_id}\n"
        f"# payload sent:\n"
        f"{_dash(item.payload)}\n"
        f"# target response:\n"
        f"{response}\n"
        f"# verdict: {item.verdict.value.upper()} [{tier}] — {detail}"
    )
