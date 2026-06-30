"""The Textual scoreboard app — the ONLY module that imports ``textual``.

The widgets are thin renderers over the pure ``ScoreboardState`` (``state.py``): every
update reads ``self.state`` and writes cell/label text; no metric is computed here. Live
results arrive through an injected async ``engine`` that invokes an ``on_attempt`` callback
per recorded attempt; the callback posts an ``AttemptRecorded`` message (NOT
``call_from_thread`` — the engine runs as an async worker on the app's own event loop, so
``call_from_thread`` would deadlock), and the handler simply rebuilds the state.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import DataTable, Footer, ProgressBar, Static

from ..attacks import Attack, Severity
from ..logging_setup import get_logger
from ..records import AttemptRecord, RunRecord, RunStatus, Verdict
from .state import (
    AttemptFilter,
    ScoreboardState,
    build_scoreboard,
    repro_for,
    select_next,
    toggle_explain,
    with_filter,
)

log = get_logger("tui")

_VERDICT_CYCLE: tuple[Verdict | None, ...] = (None, Verdict.FAIL, Verdict.ERROR)
_SEVERITY_CYCLE: tuple[Severity | None, ...] = (
    None,
    Severity.LOW,
    Severity.MEDIUM,
    Severity.HIGH,
    Severity.CRITICAL,
)


def _fmt_elapsed(seconds: float) -> str:
    total = int(seconds)
    return f"{total // 60:02d}:{total % 60:02d}"


def _sev_label(severity: Severity | None) -> str:
    return severity.value if severity is not None else "-"


class AttemptRecorded(Message):
    """Posted (thread-safe) when the engine records one attempt; triggers a re-render."""

    def __init__(self, attempt: AttemptRecord) -> None:
        self.attempt = attempt
        super().__init__()


class HeaderBar(Static):
    """One-line metrics header (ASR / elapsed / cost / tokens / progress / status)."""


class DetailPane(Static):
    """Right pane: the selected failure's payload, response, and (when explained) the score."""


class CategoryGrid(DataTable):
    """Per-category PASS/FAIL grid (pure renderer)."""

    def on_mount(self) -> None:
        self.can_focus = False
        self.cursor_type = "none"
        self.add_columns("Category", "Pass", "Fail", "Err", "Skip", "ASR", "Sev", "Done/Total")


class FailuresList(DataTable):
    """Selectable failure list; the highlighted row mirrors ``state.selected_index``."""

    def on_mount(self) -> None:
        self.can_focus = False
        self.cursor_type = "row"
        self.add_columns("Sev", "Category", "Attack", "Verdict")


class ScoreboardApp(App):
    CSS_PATH = "app.tcss"
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("ctrl+c", "quit", "Quit"),
        ("j", "select_next", "Next"),
        ("down", "select_next", "Next"),
        ("k", "select_prev", "Prev"),
        ("up", "select_prev", "Prev"),
        ("f", "cycle_filter", "Verdict"),
        ("c", "cycle_category_filter", "Category"),
        ("s", "cycle_severity_filter", "Severity"),
        ("e", "toggle_explain", "Explain"),
        ("y", "copy_repro", "Copy repro"),
        ("r", "rerun_failures", "Re-run"),
    ]

    def __init__(
        self,
        attacks: list[Attack],
        record: RunRecord,
        *,
        target_name: str,
        engine: Callable[[Callable[[AttemptRecord], None]], Awaitable[RunRecord]] | None = None,
    ) -> None:
        super().__init__()
        self.attacks = attacks
        self.record = record
        self.target_name = target_name
        self._engine = engine
        # Mutable view inputs; the pure functions recompute self.state from these.
        self._filter = AttemptFilter()
        self._selected_index = 0
        self._explain_visible = False
        self.last_repro: str | None = None
        self.state: ScoreboardState = self._build()

    # --- state plumbing ---------------------------------------------------------------
    def _build(self) -> ScoreboardState:
        return build_scoreboard(
            self.attacks,
            self.record,
            now=datetime.now(UTC),
            filter=self._filter,
            selected_index=self._selected_index,
            explain_visible=self._explain_visible,
        )

    def _adopt(self, state: ScoreboardState) -> None:
        """Adopt a state produced by a pure transition and refresh the widgets."""
        self.state = state
        self._filter = state.filter
        self._selected_index = state.selected_index
        self._explain_visible = state.explain_visible
        self.update_widgets()

    def _rebuild(self) -> None:
        """Recompute from the (possibly mutated) record, preserving the view inputs."""
        self.state = self._build()

    # --- composition ------------------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield HeaderBar(id="header")
        yield ProgressBar(id="progress", show_eta=False)
        with Horizontal(id="body"):
            with Vertical(id="left"):
                yield CategoryGrid(id="categories")
                yield FailuresList(id="failures")
            yield DetailPane(id="detail")
        yield Footer()

    def on_mount(self) -> None:
        self.update_widgets()
        if self._engine is not None:
            self.record.status = RunStatus.RUNNING
            self.run_worker(self._run_engine(), exclusive=False)

    # --- live engine ------------------------------------------------------------------
    async def _run_engine(self) -> None:
        assert self._engine is not None
        await self._engine(self._post_attempt)
        self.record.status = RunStatus.COMPLETED
        self._rebuild()
        self.update_widgets()

    def _post_attempt(self, attempt: AttemptRecord) -> None:
        # Correct primitive (fix #3): post a message on the app's own loop. The record is
        # already mutated in place by the runner before this fires.
        self.post_message(AttemptRecorded(attempt))

    def on_attempt_recorded(self, message: AttemptRecorded) -> None:
        # Re-render ONLY (fix #4): never re-insert — record.attempts already holds it.
        self._rebuild()
        self.update_widgets()

    # --- rendering (pure over self.state) ---------------------------------------------
    def update_widgets(self) -> None:
        state = self.state
        header = self.query_one("#header", HeaderBar)
        header.update(
            f"ASR {state.overall_asr:.1%}  ·  elapsed {_fmt_elapsed(state.elapsed_s)}  ·  "
            f"cost ${state.total_cost_usd:.4f}  ·  tokens {state.total_tokens}  ·  "
            f"{state.done}/{state.total}  ·  status: {state.status.value}"
        )

        progress = self.query_one("#progress", ProgressBar)
        progress.update(total=state.total or None, progress=state.done)

        categories = self.query_one("#categories", CategoryGrid)
        categories.clear()
        for row in state.categories:
            categories.add_row(
                row.category,
                str(row.passed),
                str(row.failed),
                str(row.errored),
                str(row.skipped),
                f"{row.asr:.0%}",
                _sev_label(row.flag_severity),
                f"{row.done}/{row.total}",
            )

        failures = self.query_one("#failures", FailuresList)
        failures.clear()
        for item in state.failures:
            failures.add_row(
                _sev_label(item.severity),
                item.category or "-",
                item.attack_id or "(unknown)",
                item.verdict.value.upper(),
            )
        if state.selected_index >= 0 and state.failures:
            failures.move_cursor(row=state.selected_index)

        self.query_one("#detail", DetailPane).update(self._detail_text())

    def _detail_text(self) -> str:
        state = self.state
        item = state.selected_failure
        if item is None:
            return "(no failure selected)"
        lines = [
            f"{item.name or '(unknown)'}  [{item.attack_id or '(unknown)'}]",
            f"severity={_sev_label(item.severity)} owasp={item.owasp or '-'} "
            f"atlas={item.atlas or '-'}",
            "",
            "payload sent:",
            item.payload or "-",
            "",
            "target response:",
            item.response_text if item.response_text else "(no response)",
        ]
        if state.explain_visible:
            cls = item.classifier_score if item.classifier_score is not None else "-"
            lines += [
                "",
                "--- explain ---",
                f"verdict: {item.verdict.value.upper()} [{item.score_tier or '-'}]",
                f"reason: {item.reason or item.error or '(no detail)'}",
                f"matched: {item.matched or '-'}",
                f"classifier_score: {cls}",
                "",
                repro_for(item, target_name=self.target_name),
            ]
        return "\n".join(lines)

    # --- actions (each effect assertable via self.state / widgets) --------------------
    def action_select_next(self) -> None:
        self._adopt(select_next(self.state, 1))

    def action_select_prev(self) -> None:
        self._adopt(select_next(self.state, -1))

    def _apply_filter(self, new_filter: AttemptFilter) -> None:
        self._adopt(with_filter(self.state, new_filter))

    def action_cycle_filter(self) -> None:
        cur = self._filter.verdict
        nxt = _VERDICT_CYCLE[(_VERDICT_CYCLE.index(cur) + 1) % len(_VERDICT_CYCLE)]
        self._apply_filter(dataclasses.replace(self._filter, verdict=nxt))

    def action_cycle_category_filter(self) -> None:
        cats: list[str | None] = [None] + sorted({a.category for a in self.attacks})
        cur = self._filter.category
        idx = cats.index(cur) if cur in cats else 0
        self._apply_filter(dataclasses.replace(self._filter, category=cats[(idx + 1) % len(cats)]))

    def action_cycle_severity_filter(self) -> None:
        cur = self._filter.severity
        nxt = _SEVERITY_CYCLE[(_SEVERITY_CYCLE.index(cur) + 1) % len(_SEVERITY_CYCLE)]
        self._apply_filter(dataclasses.replace(self._filter, severity=nxt))

    def action_toggle_explain(self) -> None:
        self._adopt(toggle_explain(self.state))

    def _clipboard_write(self, text: str) -> None:
        """Best-effort clipboard write; monkeypatched in tests. Errors are swallowed."""
        try:
            self.copy_to_clipboard(text)
        except Exception:  # noqa: BLE001 — clipboard is best-effort, never fatal
            log.debug("clipboard write failed; ignoring")

    def action_copy_repro(self) -> None:
        item = self.state.selected_failure
        if item is None:
            return
        text = repro_for(item, target_name=self.target_name)
        self.last_repro = text
        self._clipboard_write(text)

    def action_rerun_failures(self) -> None:
        # Re-run exactly the highlighted failure (fix #1/#8). The engine is callback-only
        # with no subset param, so drop the attempt from the record (mirroring the runner's
        # resume drop-set) then re-invoke the SAME engine with the full plan — resume logic
        # re-runs just the dropped attack.
        item = self.state.selected_failure
        if item is None:
            return
        if self._engine is None:
            log.info("rerun requested but no engine configured; no-op")
            return
        self.record.attempts = [a for a in self.record.attempts if a.attack_id != item.attack_id]
        self._rebuild()
        self.update_widgets()
        self.record.status = RunStatus.RUNNING
        self.run_worker(self._run_engine(), exclusive=False)
