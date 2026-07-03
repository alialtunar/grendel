"""HTML + Markdown report renderers over a RunRecord.

Pure functions, stdlib templating (f-strings + ``html.escape``) — no Jinja2 (spec §5.1).
Driven entirely by ``record.metrics_summary()`` + record fields (the single source of
truth the text report consumes). Deterministic: sorted breakdowns, the failure list
sorted by ``(attack_id, attempt_id)``, the record's own ``created_at`` (never now()).
"""

from __future__ import annotations

import html
import re

from .records import AttemptRecord, RunRecord, Verdict

_BACKTICK_RUN = re.compile(r"`+")


def _failures(record: RunRecord) -> list[AttemptRecord]:
    """Succeeded (FAIL), non-control attempts, sorted deterministically."""
    rows = [a for a in record.attempts if not a.is_control and a.verdict == Verdict.FAIL]
    return sorted(rows, key=lambda a: (a.attack_id or "", a.attempt_id))


def _latency_summary(record: RunRecord) -> tuple[float | None, float | None]:
    """(mean, median) over non-None attempt.latency_ms; (None, None) when none."""
    values = sorted(a.latency_ms for a in record.attempts if a.latency_ms is not None)
    if not values:
        return (None, None)
    mean = sum(values) / len(values)
    mid = len(values) // 2
    if len(values) % 2:
        median = values[mid]
    else:
        median = (values[mid - 1] + values[mid]) / 2
    return (mean, median)


def _fence(content: str) -> str:
    """A backtick fence one longer than the longest backtick run in content (min 3).

    Fix #3: payloads are adversarial and may contain ``` — a 3-backtick fence would
    close early. Picking a longer run guarantees the block can't be broken out of.
    """
    longest = max((len(m.group(0)) for m in _BACKTICK_RUN.finditer(content)), default=0)
    return "`" * max(3, longest + 1)


def _code_block(content: str) -> str:
    fence = _fence(content)
    return f"{fence}\n{content}\n{fence}"


# --------------------------------------------------------------------------- text


def render_text(record: RunRecord) -> str:
    """A plain-text report — the single source the `report` command and the menu viewer print."""
    m = record.metrics_summary()
    lines: list[str] = []
    lines.append(f"Run {record.run_id}")
    lines.append(f"  target: {record.target_name} ({record.provider}/{record.model})")
    lines.append(f"  status: {record.status.value}")
    lines.append(f"  attempts: {record.total_attempts}")
    lines.append(f"  ASR (overall): {m['overall_asr']:.2%}")
    util = m["utility_under_attack"]
    util_str = f"{util:.2%}" if util is not None else "n/a"
    lines.append(f"  utility-under-attack: {util_str}")
    ctrl = m["controls"]
    if ctrl["total"] > 0:
        lines.append(
            f"  controls: answered {ctrl['answered']} / {ctrl['total']} "
            f"(refused {ctrl['refused']}, errored {ctrl['errored']})"
        )
    lines.append(
        f"  scored: {m['scored']} succeeded: {m['succeeded']} "
        f"defended: {m['defended']} errored: {m['errored']} "
        f"skipped: {m['skipped']}"
    )
    lines.append("  by category:")
    for cat, stats in sorted(m["by_category"].items()):
        lines.append(
            f"    {cat}: ASR {stats['asr']:.2%} (succeeded {stats['succeeded']}/{stats['scored']})"
        )
    lines.append("  by OWASP:")
    for code, stats in sorted(m["by_owasp"].items()):
        lines.append(
            f"    {code}: ASR {stats['asr']:.2%} (succeeded {stats['succeeded']}/{stats['scored']})"
        )
    lines.append("  by ATLAS:")
    for code, stats in sorted(m["by_atlas"].items()):
        lines.append(
            f"    {code}: ASR {stats['asr']:.2%} (succeeded {stats['succeeded']}/{stats['scored']})"
        )
    return "\n".join(lines)


# --------------------------------------------------------------------------- markdown


def render_markdown(record: RunRecord) -> str:
    """A GitHub-flavoured Markdown report. Pure f-strings; deterministic."""
    m = record.metrics_summary()
    lines: list[str] = []

    lines.append(f"# Grendel report — `{record.run_id}`")
    lines.append("")
    lines.append(f"- **Target:** {record.target_name} ({record.provider}/{record.model})")
    lines.append(f"- **Status:** {record.status.value}")
    lines.append(f"- **Created:** {record.created_at.isoformat()}")
    lines.append(f"- **Packs:** {', '.join(record.pack_ids) if record.pack_ids else '(none)'}")
    lines.append("")

    lines.append("## Headline")
    lines.append("")
    lines.append("| metric | value |")
    lines.append("| --- | --- |")
    lines.append(f"| Overall ASR | {m['overall_asr']:.2%} |")
    lines.append(f"| Scored | {m['scored']} |")
    lines.append(f"| Succeeded | {m['succeeded']} |")
    lines.append(f"| Defended | {m['defended']} |")
    lines.append(f"| Errored | {m['errored']} |")
    lines.append(f"| Skipped | {m['skipped']} |")
    lines.append(f"| Total | {m['total']} |")
    lines.append("")

    ctrl = m["controls"]
    if ctrl["total"] > 0:
        util = m["utility_under_attack"]
        util_str = f"{util:.2%}" if util is not None else "n/a"
        lines.append("## Utility under attack")
        lines.append("")
        lines.append(f"- **Utility:** {util_str}")
        lines.append(
            f"- **Controls:** answered {ctrl['answered']} / {ctrl['total']} "
            f"(refused {ctrl['refused']}, errored {ctrl['errored']})"
        )
        lines.append("")

    usage = record.total_usage
    mean_lat, median_lat = _latency_summary(record)
    mean_str = f"{mean_lat:.1f} ms" if mean_lat is not None else "n/a"
    median_str = f"{median_lat:.1f} ms" if median_lat is not None else "n/a"
    lines.append("## Cost & latency")
    lines.append("")
    lines.append(f"- **Est. cost:** ${record.total_cost_usd:.4f}")
    lines.append(f"- **Tokens:** {usage.total_tokens}")
    lines.append(f"- **Latency:** mean {mean_str}, median {median_str}")
    lines.append("")

    for axis, label in (("by_category", "category"), ("by_owasp", "OWASP"), ("by_atlas", "ATLAS")):
        lines.append(f"## By {label}")
        lines.append("")
        lines.append("| code | ASR | succeeded/scored |")
        lines.append("| --- | --- | --- |")
        for code, stats in sorted(m[axis].items()):
            lines.append(
                f"| {code} | {stats['asr']:.2%} | {stats['succeeded']}/{stats['scored']} |"
            )
        lines.append("")

    failures = _failures(record)
    lines.append(f"## Failures ({len(failures)})")
    lines.append("")
    if not failures:
        lines.append("None — the target defended every scored attack.")
        lines.append("")
    for f in failures:
        lines.append(f"### {f.attack_id or '(no id)'}")
        lines.append("")
        lines.append(
            f"- **Category:** {f.category or '(none)'} · **OWASP:** {f.owasp or '(none)'} "
            f"· **ATLAS:** {f.atlas or '(none)'}"
        )
        if f.score_detail is not None:  # Fix #1: nullable
            lines.append(f"- **Reason:** {f.score_detail.reason}")
        lines.append("")
        lines.append("**Payload:**")
        lines.append("")
        lines.append(_code_block(f.prompt))
        lines.append("")
        lines.append("**Response:**")
        lines.append("")
        lines.append(_code_block(f.response_text or "(no response)"))  # Fix #1: nullable
        lines.append("")
        if f.tool_calls:
            lines.append("**Tool calls:**")
            lines.append("")
            lines.append(_code_block("\n".join(repr(tc) for tc in f.tool_calls)))
            lines.append("")

    return "\n".join(lines)


# ------------------------------------------------------------------------------- html

_STYLE = """
  body { font-family: system-ui, sans-serif; margin: 2rem auto; max-width: 56rem;
         color: #1a1a1a; line-height: 1.5; }
  h1, h2, h3 { line-height: 1.2; }
  table { border-collapse: collapse; margin: 0.5rem 0; }
  th, td { border: 1px solid #ccc; padding: 0.3rem 0.6rem; text-align: left; }
  th { background: #f2f2f2; }
  pre { background: #f6f8fa; border: 1px solid #ddd; padding: 0.6rem; overflow-x: auto;
        white-space: pre-wrap; word-break: break-word; }
  .fail { color: #b00020; font-weight: 600; }
  .pass { color: #1a7f37; font-weight: 600; }
  .failure { border-left: 4px solid #b00020; padding-left: 1rem; margin: 1rem 0; }
  .meta { color: #555; }
"""


def _e(value: object) -> str:
    """html.escape every record-derived string (payloads are adversarial)."""
    return html.escape(str(value))


def _html_axis_table(m: dict, axis: str, label: str) -> list[str]:
    rows = ["<h2>By " + _e(label) + "</h2>", "<table>"]
    rows.append("<tr><th>code</th><th>ASR</th><th>succeeded/scored</th></tr>")
    for code, stats in sorted(m[axis].items()):
        rows.append(
            f"<tr><td>{_e(code)}</td><td>{stats['asr']:.2%}</td>"
            f"<td>{stats['succeeded']}/{stats['scored']}</td></tr>"
        )
    rows.append("</table>")
    return rows


def render_html(record: RunRecord) -> str:
    """A single self-contained <!DOCTYPE html> document. No JS/CDN/external assets.

    Every interpolated record value is html.escape-d. Deterministic.
    """
    m = record.metrics_summary()
    p: list[str] = []
    p.append("<!DOCTYPE html>")
    p.append('<html lang="en">')
    p.append("<head>")
    p.append('<meta charset="utf-8">')
    p.append(f"<title>Grendel report {_e(record.run_id)}</title>")
    p.append(f"<style>{_STYLE}</style>")
    p.append("</head>")
    p.append("<body>")

    p.append(f"<h1>Grendel report — {_e(record.run_id)}</h1>")
    p.append('<p class="meta">')
    p.append(f"Target: {_e(record.target_name)} ({_e(record.provider)}/{_e(record.model)})<br>")
    p.append(f"Status: {_e(record.status.value)}<br>")
    p.append(f"Created: {_e(record.created_at.isoformat())}<br>")
    packs = ", ".join(record.pack_ids) if record.pack_ids else "(none)"
    p.append(f"Packs: {_e(packs)}")
    p.append("</p>")

    p.append("<h2>Headline</h2>")
    p.append("<table>")
    p.append(f"<tr><th>Overall ASR</th><td>{m['overall_asr']:.2%}</td></tr>")
    p.append(f"<tr><th>Scored</th><td>{m['scored']}</td></tr>")
    p.append(f"<tr><th>Succeeded</th><td>{m['succeeded']}</td></tr>")
    p.append(f"<tr><th>Defended</th><td>{m['defended']}</td></tr>")
    p.append(f"<tr><th>Errored</th><td>{m['errored']}</td></tr>")
    p.append(f"<tr><th>Skipped</th><td>{m['skipped']}</td></tr>")
    p.append(f"<tr><th>Total</th><td>{m['total']}</td></tr>")
    p.append("</table>")

    ctrl = m["controls"]
    if ctrl["total"] > 0:
        util = m["utility_under_attack"]
        util_str = f"{util:.2%}" if util is not None else "n/a"
        p.append("<h2>Utility under attack</h2>")
        p.append(f"<p>Utility: {util_str}<br>")
        p.append(
            f"Controls: answered {ctrl['answered']} / {ctrl['total']} "
            f"(refused {ctrl['refused']}, errored {ctrl['errored']})</p>"
        )

    usage = record.total_usage
    mean_lat, median_lat = _latency_summary(record)
    mean_str = f"{mean_lat:.1f} ms" if mean_lat is not None else "n/a"
    median_str = f"{median_lat:.1f} ms" if median_lat is not None else "n/a"
    p.append("<h2>Cost &amp; latency</h2>")
    p.append(f"<p>Est. cost: ${record.total_cost_usd:.4f}<br>")
    p.append(f"Tokens: {usage.total_tokens}<br>")
    p.append(f"Latency: mean {mean_str}, median {median_str}</p>")

    p.extend(_html_axis_table(m, "by_category", "category"))
    p.extend(_html_axis_table(m, "by_owasp", "OWASP"))
    p.extend(_html_axis_table(m, "by_atlas", "ATLAS"))

    failures = _failures(record)
    p.append(f"<h2>Failures ({len(failures)})</h2>")
    if not failures:
        p.append("<p>None — the target defended every scored attack.</p>")
    for f in failures:
        p.append('<section class="failure">')
        p.append(f'<h3 class="fail">{_e(f.attack_id or "(no id)")}</h3>')
        p.append(
            f'<p class="meta">Category: {_e(f.category or "(none)")} · '
            f"OWASP: {_e(f.owasp or '(none)')} · ATLAS: {_e(f.atlas or '(none)')}</p>"
        )
        if f.score_detail is not None:  # Fix #1
            p.append(f"<p><strong>Reason:</strong> {_e(f.score_detail.reason)}</p>")
        p.append("<p><strong>Payload:</strong></p>")
        p.append(f"<pre>{_e(f.prompt)}</pre>")
        p.append("<p><strong>Response:</strong></p>")
        p.append(f"<pre>{_e(f.response_text or '(no response)')}</pre>")  # Fix #1
        if f.tool_calls:
            p.append("<p><strong>Tool calls:</strong></p>")
            calls = "\n".join(repr(tc) for tc in f.tool_calls)
            p.append(f"<pre>{_e(calls)}</pre>")
        p.append("</section>")

    p.append("</body>")
    p.append("</html>")
    return "\n".join(p)


__all__ = ["render_html", "render_markdown", "render_text"]
