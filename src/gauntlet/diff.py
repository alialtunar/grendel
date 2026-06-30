"""Score-diff over two RunRecords: the RunDiff model + diff_runs() + renderers.

Pure read-side projection (no engine behaviour): per-axis ASR deltas are read from each
record's ``metrics_summary()`` (already div-by-zero-guarded), and newly-failing/fixed
transitions are computed by joining attempts on ``attack_id``. Deterministic: sorted
outputs, no clock/network.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from .records import RunRecord, Verdict


class AsrDelta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    asr_a: float
    asr_b: float
    delta: float  # asr_b - asr_a (positive = regression: more attacks succeeded in B)


class RunDiff(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_a: str
    run_b: str
    overall_asr_a: float
    overall_asr_b: float
    overall_asr_delta: float
    by_category: list[AsrDelta]
    by_owasp: list[AsrDelta]
    by_atlas: list[AsrDelta]
    newly_failing: list[str]
    newly_fixed: list[str]
    cost_delta_usd: float
    latency_delta_ms: float | None


def _axis_deltas(metrics_a: dict, metrics_b: dict, axis: str) -> list[AsrDelta]:
    """Union of codes present in either side; a missing side contributes ASR 0.0."""
    a = metrics_a[axis]
    b = metrics_b[axis]
    out: list[AsrDelta] = []
    for code in sorted(set(a) | set(b)):
        asr_a = a[code]["asr"] if code in a else 0.0
        asr_b = b[code]["asr"] if code in b else 0.0
        out.append(AsrDelta(code=code, asr_a=asr_a, asr_b=asr_b, delta=asr_b - asr_a))
    return out


def _scored_verdicts(record: RunRecord) -> dict[str, Verdict]:
    """Map attack_id -> verdict over scored (PASS/FAIL), non-control attempts.

    Fix #2: attempts with ``attack_id is None`` are excluded (else two None-id attempts
    from different runs would collide as "the same attack").
    """
    out: dict[str, Verdict] = {}
    for a in record.attempts:
        if a.is_control or a.attack_id is None:
            continue
        if a.verdict in (Verdict.PASS, Verdict.FAIL):
            out[a.attack_id] = a.verdict
    return out


def _mean_latency(record: RunRecord) -> float | None:
    """Mean over non-None attempt.latency_ms; None when there are no measured latencies."""
    values = [a.latency_ms for a in record.attempts if a.latency_ms is not None]
    if not values:
        return None
    return sum(values) / len(values)


def diff_runs(a: RunRecord, b: RunRecord) -> RunDiff:
    """Compare baseline ``a`` against new run ``b`` -> a deterministic RunDiff."""
    ma = a.metrics_summary()
    mb = b.metrics_summary()

    va = _scored_verdicts(a)
    vb = _scored_verdicts(b)
    both = set(va) & set(vb)
    newly_failing = sorted(
        aid for aid in both if va[aid] == Verdict.PASS and vb[aid] == Verdict.FAIL
    )
    newly_fixed = sorted(aid for aid in both if va[aid] == Verdict.FAIL and vb[aid] == Verdict.PASS)

    lat_a = _mean_latency(a)
    lat_b = _mean_latency(b)
    latency_delta = None if lat_a is None or lat_b is None else lat_b - lat_a

    return RunDiff(
        run_a=a.run_id,
        run_b=b.run_id,
        overall_asr_a=ma["overall_asr"],
        overall_asr_b=mb["overall_asr"],
        overall_asr_delta=mb["overall_asr"] - ma["overall_asr"],
        by_category=_axis_deltas(ma, mb, "by_category"),
        by_owasp=_axis_deltas(ma, mb, "by_owasp"),
        by_atlas=_axis_deltas(ma, mb, "by_atlas"),
        newly_failing=newly_failing,
        newly_fixed=newly_fixed,
        cost_delta_usd=b.total_cost_usd - a.total_cost_usd,
        latency_delta_ms=latency_delta,
    )


def _sign(delta: float) -> str:
    """ASCII sign (Fix #3-text): +/-/= — NOT unicode (cp1252 Windows consoles)."""
    if delta > 0:
        return "+"
    if delta < 0:
        return "-"
    return "="


def _latency_text(d: RunDiff) -> str:
    if d.latency_delta_ms is None:
        return "latency: n/a"  # Fix #9 sentinel
    return f"latency: {_sign(d.latency_delta_ms)}{abs(d.latency_delta_ms):.1f} ms"


def render_text(d: RunDiff) -> str:
    """Human summary: overall delta, per-axis deltas, transitions, cost/latency."""
    lines: list[str] = []
    lines.append(f"diff {d.run_a} -> {d.run_b}")
    lines.append(
        f"overall ASR: {d.overall_asr_a:.2%} -> {d.overall_asr_b:.2%} "
        f"({_sign(d.overall_asr_delta)}{abs(d.overall_asr_delta):.2%})"
    )
    for axis, label in (("by_category", "category"), ("by_owasp", "OWASP"), ("by_atlas", "ATLAS")):
        rows = getattr(d, axis)
        lines.append(f"by {label}:")
        if not rows:
            lines.append("  (none)")
        for r in rows:
            lines.append(
                f"  {r.code}: {r.asr_a:.2%} -> {r.asr_b:.2%} ({_sign(r.delta)}{abs(r.delta):.2%})"
            )
    lines.append(f"newly failing: {', '.join(d.newly_failing) if d.newly_failing else '(none)'}")
    lines.append(f"newly fixed: {', '.join(d.newly_fixed) if d.newly_fixed else '(none)'}")
    lines.append(f"cost: {_sign(d.cost_delta_usd)}${abs(d.cost_delta_usd):.4f}")
    lines.append(_latency_text(d))
    return "\n".join(lines)


def render_markdown(d: RunDiff) -> str:
    """Tables + lists for a PR/CI comment (the regression-tracking use)."""
    lines: list[str] = []
    lines.append(f"# Score diff: `{d.run_a}` -> `{d.run_b}`")
    lines.append("")
    lines.append(
        f"**Overall ASR:** {d.overall_asr_a:.2%} -> {d.overall_asr_b:.2%} "
        f"({_sign(d.overall_asr_delta)}{abs(d.overall_asr_delta):.2%})"
    )
    lines.append("")
    for axis, label in (("by_category", "Category"), ("by_owasp", "OWASP"), ("by_atlas", "ATLAS")):
        rows = getattr(d, axis)
        lines.append(f"## By {label}")
        lines.append("")
        lines.append("| code | ASR (a) | ASR (b) | delta |")
        lines.append("| --- | --- | --- | --- |")
        for r in rows:
            lines.append(
                f"| {r.code} | {r.asr_a:.2%} | {r.asr_b:.2%} | {_sign(r.delta)}{abs(r.delta):.2%} |"
            )
        lines.append("")
    lines.append("## Transitions")
    lines.append("")
    lines.append(
        f"- **Newly failing:** {', '.join(d.newly_failing) if d.newly_failing else '(none)'}"
    )
    lines.append(f"- **Newly fixed:** {', '.join(d.newly_fixed) if d.newly_fixed else '(none)'}")
    lines.append("")
    lines.append(f"**Cost delta:** {_sign(d.cost_delta_usd)}${abs(d.cost_delta_usd):.4f}")
    lines.append("")
    lines.append(f"**{_latency_text(d)}**")
    return "\n".join(lines)


__all__ = [
    "AsrDelta",
    "RunDiff",
    "diff_runs",
    "render_markdown",
    "render_text",
]
