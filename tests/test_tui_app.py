"""M3/M4: Textual app pilot tests — static render, live updates, every keybinding.

The only test module importing ``textual``. Fully offline: a fake engine emits scripted
AttemptRecords (no runner, no network) and signals completion via an ``asyncio.Event`` so
the live/rerun assertions are deterministic (fix #6), never racy.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from fakes import make_attack
from gauntlet.records import (
    AttemptRecord,
    RunRecord,
    RunStatus,
    ScoreDetail,
    TokenUsage,
    Verdict,
)
from gauntlet.tui.app import DetailPane, ScoreboardApp

T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def _plan() -> list:
    return [
        make_attack("alpha/a1", severity="critical"),
        make_attack("alpha/a2", severity="low"),
        make_attack("beta/b1", severity="high"),
        make_attack("beta/b2", severity="medium"),
    ]


def _attempt(attack_id: str, verdict: Verdict, **kw) -> AttemptRecord:
    cat = attack_id.split("/", 1)[0]
    detail = None
    if "reason" in kw:
        detail = ScoreDetail(tier="T1", reason=kw["reason"], matched=kw.get("matched"))
    return AttemptRecord(
        attack_id=attack_id,
        category=cat,
        prompt=f"p {attack_id}",
        response_text=kw.get("response_text", "resp"),
        verdict=verdict,
        score_tier=kw.get("score_tier"),
        score_detail=detail,
        error=kw.get("error"),
        usage=TokenUsage(prompt_tokens=1, completion_tokens=2),
        cost_usd=0.001,
        started_at=T0,
        finished_at=T0 + timedelta(seconds=1),
    )


def _record(attempts=None, status=RunStatus.COMPLETED) -> RunRecord:
    return RunRecord(
        run_id="run-app",
        created_at=T0,
        status=status,
        target_name="gpt",
        provider="openai",
        model="gpt-4o-mini",
        attempts=attempts or [],
    )


def _failures_record() -> RunRecord:
    # 2 failures (a1 critical FAIL, b1 high FAIL) + 1 error (b2) + 1 pass (a2).
    return _record(
        attempts=[
            _attempt(
                "alpha/a1", Verdict.FAIL, reason="canary matched", matched="x", score_tier="T1"
            ),
            _attempt("alpha/a2", Verdict.PASS, reason="refusal", score_tier="T1"),
            _attempt("beta/b1", Verdict.FAIL, reason="classifier said so", score_tier="T2"),
            _attempt("beta/b2", Verdict.ERROR, response_text=None, error="boom"),
        ]
    )


def _detail_text(app: ScoreboardApp) -> str:
    return str(app.query_one("#detail", DetailPane).render())


class FakeEngine:
    """Async callback-only engine: emits scripted attempts honoring the resume skip-set."""

    def __init__(self, record: RunRecord, scripted: list[AttemptRecord]) -> None:
        self.record = record
        self.scripted = scripted
        self.done = asyncio.Event()
        self.emitted: list[str] = []

    async def __call__(self, on_attempt) -> RunRecord:
        # Mirror the runner's resume: skip attack_ids already present as non-ERROR.
        already = {a.attack_id for a in self.record.attempts if a.verdict != Verdict.ERROR}
        for att in self.scripted:
            if att.attack_id in already:
                continue
            # The runner mutates record.attempts in place BEFORE the callback fires.
            self.record.attempts = [a for a in self.record.attempts if a.attack_id != att.attack_id]
            self.record.attempts.append(att)
            self.emitted.append(att.attack_id)
            on_attempt(att)
            await asyncio.sleep(0)
        self.done.set()
        return self.record


# --- M3: static + live smoke ----------------------------------------------------------


async def test_static_render_smoke() -> None:
    app = ScoreboardApp(_plan(), _failures_record(), target_name="gpt", engine=None)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.state.done == 4
        assert app.state.total == 4
        header = str(app.query_one("#header").render())
        assert "ASR" in header and "status: completed" in header
        # 2 categories rendered; 3 failures (a1, b1, b2).
        assert app.query_one("#categories").row_count == 2
        assert app.query_one("#failures").row_count == 3
        assert app.state.failures[0].attack_id == "alpha/a1"


async def test_live_updates_via_fake_engine() -> None:
    record = _record(status=RunStatus.CREATED)
    scripted = [
        _attempt("alpha/a1", Verdict.FAIL, reason="canary", matched="x", score_tier="T1"),
        _attempt("alpha/a2", Verdict.PASS, score_tier="T1"),
        _attempt("beta/b1", Verdict.FAIL, reason="cls", score_tier="T2"),
    ]
    engine = FakeEngine(record, scripted)
    app = ScoreboardApp(_plan(), record, target_name="gpt", engine=engine)
    async with app.run_test() as pilot:
        await asyncio.wait_for(engine.done.wait(), timeout=5)
        await pilot.pause()
        assert app.state.done == 3
        assert app.state.status == RunStatus.COMPLETED
        # 2 FAIL / 3 scored.
        assert abs(app.state.overall_asr - (2 / 3)) < 1e-9
        assert app.query_one("#failures").row_count == 2  # a1, b1


# --- M4: bindings ---------------------------------------------------------------------


async def test_select_keys_move_and_clamp() -> None:
    app = ScoreboardApp(_plan(), _failures_record(), target_name="gpt", engine=None)
    async with app.run_test() as pilot:
        assert app.state.selected_index == 0
        await pilot.press("j")
        assert app.state.selected_index == 1
        await pilot.press("j")
        assert app.state.selected_index == 2
        await pilot.press("j")
        assert app.state.selected_index == 2  # clamp at end
        await pilot.press("k")
        assert app.state.selected_index == 1
        await pilot.press("k")
        await pilot.press("k")
        assert app.state.selected_index == 0  # clamp at start


async def test_verdict_filter_key() -> None:
    app = ScoreboardApp(_plan(), _failures_record(), target_name="gpt", engine=None)
    async with app.run_test() as pilot:
        assert app.state.filter.verdict is None
        assert len(app.state.failures) == 3
        await pilot.press("f")
        assert app.state.filter.verdict == Verdict.FAIL
        assert {f.attack_id for f in app.state.failures} == {"alpha/a1", "beta/b1"}
        await pilot.press("f")
        assert app.state.filter.verdict == Verdict.ERROR
        assert {f.attack_id for f in app.state.failures} == {"beta/b2"}
        await pilot.press("f")
        assert app.state.filter.verdict is None
        assert len(app.state.failures) == 3


async def test_category_filter_key() -> None:
    app = ScoreboardApp(_plan(), _failures_record(), target_name="gpt", engine=None)
    async with app.run_test() as pilot:
        await pilot.press("c")
        assert app.state.filter.category == "alpha"
        assert {f.attack_id for f in app.state.failures} == {"alpha/a1"}
        await pilot.press("c")
        assert app.state.filter.category == "beta"
        assert {f.attack_id for f in app.state.failures} == {"beta/b1", "beta/b2"}
        await pilot.press("c")
        assert app.state.filter.category is None


async def test_severity_filter_key() -> None:
    app = ScoreboardApp(_plan(), _failures_record(), target_name="gpt", engine=None)
    async with app.run_test() as pilot:
        # None -> LOW -> MEDIUM -> HIGH -> CRITICAL -> None.
        await pilot.press("s")  # LOW: all 3 (>= low)
        assert app.state.filter.severity.value == "low"
        assert len(app.state.failures) == 3
        await pilot.press("s")  # MEDIUM: a1(crit), b1(high), b2(medium) = 3
        assert app.state.filter.severity.value == "medium"
        assert len(app.state.failures) == 3
        await pilot.press("s")  # HIGH: a1(crit), b1(high) = 2
        assert app.state.filter.severity.value == "high"
        assert {f.attack_id for f in app.state.failures} == {"alpha/a1", "beta/b1"}
        await pilot.press("s")  # CRITICAL: a1 only
        assert {f.attack_id for f in app.state.failures} == {"alpha/a1"}
        await pilot.press("s")  # None
        assert app.state.filter.severity is None


async def test_explain_key_toggles_detail() -> None:
    app = ScoreboardApp(_plan(), _failures_record(), target_name="gpt", engine=None)
    async with app.run_test() as pilot:
        assert app.state.explain_visible is False
        assert "canary matched" not in _detail_text(app)
        await pilot.press("e")
        assert app.state.explain_visible is True
        text = _detail_text(app)
        assert "canary matched" in text  # a1's reason
        assert "gauntlet repro" in text
        await pilot.press("e")
        assert app.state.explain_visible is False
        assert "canary matched" not in _detail_text(app)


async def test_copy_repro_key(monkeypatch) -> None:
    app = ScoreboardApp(_plan(), _failures_record(), target_name="gpt", engine=None)
    captured: list[str] = []
    app._clipboard_write = lambda text: captured.append(text)
    async with app.run_test() as pilot:
        await pilot.press("y")
        assert app.last_repro is not None
        assert app.last_repro.startswith("# gauntlet repro — alpha/a1")
        assert captured == [app.last_repro]


async def test_copy_repro_noop_when_no_failure() -> None:
    app = ScoreboardApp(_plan(), _record(), target_name="gpt", engine=None)  # no failures
    captured: list[str] = []
    app._clipboard_write = lambda text: captured.append(text)
    async with app.run_test() as pilot:
        await pilot.press("y")
        assert app.last_repro is None
        assert captured == []


async def test_rerun_key_reinvokes_engine_for_selected() -> None:
    # Start with a1 already FAILED; engine scripted to re-emit it. Pressing r drops a1
    # from the record and re-invokes the engine -> a1 re-emitted (skip-set re-runs it).
    record = _failures_record()
    rerun_attempt = _attempt("alpha/a1", Verdict.PASS, reason="now defended", score_tier="T1")
    engine = FakeEngine(record, [rerun_attempt])
    app = ScoreboardApp(_plan(), record, target_name="gpt", engine=engine)
    async with app.run_test() as pilot:
        # Engine ran once at mount; a1 already present non-ERROR so nothing emitted.
        await asyncio.wait_for(engine.done.wait(), timeout=5)
        await pilot.pause()
        assert engine.emitted == []
        assert app.state.selected_index == 0
        assert app.state.selected_failure.attack_id == "alpha/a1"

        engine.done = asyncio.Event()  # fresh completion signal for the rerun
        await pilot.press("r")
        await asyncio.wait_for(engine.done.wait(), timeout=5)
        await pilot.pause()
        assert engine.emitted == ["alpha/a1"]  # exactly the highlighted failure re-run
        a1 = next(a for a in app.record.attempts if a.attack_id == "alpha/a1")
        assert a1.verdict == Verdict.PASS  # folded in via AttemptRecorded


async def test_quit_key_exits() -> None:
    app = ScoreboardApp(_plan(), _failures_record(), target_name="gpt", engine=None)
    async with app.run_test() as pilot:
        await pilot.press("q")
        await pilot.pause()
    # Exiting the context without hanging proves q quit; return_code is 0.
    assert app.return_code == 0


@pytest.mark.parametrize("key", ["j", "k", "f", "c", "s", "e", "y", "r"])
async def test_keys_do_not_crash_on_empty_failures(key: str) -> None:
    app = ScoreboardApp(_plan(), _record(), target_name="gpt", engine=None)  # no failures
    async with app.run_test() as pilot:
        await pilot.press(key)
        await pilot.pause()
        assert app.state.selected_index == -1
