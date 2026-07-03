"""M2: semaphore bound, rate-limit spacing, per-request timeout."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from fakes import FakeAdapter, ManualClock, RecordingSleep, make_attack
from grendel.config import RunOptions
from grendel.records import RunRecord, RunStatus, Verdict
from grendel.runner import Runner
from grendel.targets.base import AdapterRequest, AdapterResponse, TargetAdapter


def _record() -> RunRecord:
    return RunRecord(
        run_id="run-conc",
        created_at=datetime.now(UTC),
        target_name="t",
        provider="fake",
        model="fake-model",
    )


async def test_max_in_flight_equals_concurrency(tmp_path: Path) -> None:
    barrier = asyncio.Barrier(2)
    adapter = FakeAdapter(barrier=barrier)
    opts = RunOptions(output_dir=tmp_path, concurrency=2)
    runner = Runner(adapter, opts)
    attacks = [make_attack(f"cat/a{i}") for i in range(6)]
    record = await runner.run(attacks, _record())
    assert record.status == RunStatus.COMPLETED
    assert len(record.attempts) == 6
    assert adapter.max_active == 2  # never more than the semaphore allows


async def test_rate_limit_spacing(tmp_path: Path) -> None:
    clock = ManualClock()
    sleep = RecordingSleep(clock)
    adapter = FakeAdapter()
    opts = RunOptions(output_dir=tmp_path, concurrency=5, rps=10.0)
    runner = Runner(adapter, opts, sleep=sleep, monotonic=clock.monotonic)
    attacks = [make_attack(f"cat/a{i}") for i in range(3)]
    await runner.run(attacks, _record())
    # 3 dispatches at interval 0.1: first immediate, two spaced by exactly 1/rps.
    assert sleep.calls == [0.1, 0.1]


async def test_rps_none_no_spacing(tmp_path: Path) -> None:
    clock = ManualClock()
    sleep = RecordingSleep(clock)
    adapter = FakeAdapter()
    opts = RunOptions(output_dir=tmp_path, concurrency=5, rps=None)
    runner = Runner(adapter, opts, sleep=sleep, monotonic=clock.monotonic)
    attacks = [make_attack(f"cat/a{i}") for i in range(3)]
    await runner.run(attacks, _record())
    assert sleep.calls == []  # no rate spacing


class _HangAdapter(TargetAdapter):
    """Never returns, so asyncio.wait_for must time it out."""

    def __init__(self) -> None:
        self.name = "hang"

    async def send(self, request: AdapterRequest) -> AdapterResponse:
        await asyncio.Event().wait()  # forever
        raise AssertionError("unreachable")


async def test_timeout_records_error_and_run_completes(tmp_path: Path) -> None:
    adapter = _HangAdapter()
    opts = RunOptions(output_dir=tmp_path, max_retries=0, request_timeout_s=0.01)
    runner = Runner(adapter, opts)
    record = await runner.run([make_attack("cat/a")], _record())
    assert record.status == RunStatus.COMPLETED  # run not crashed
    assert len(record.attempts) == 1
    assert record.attempts[0].verdict == Verdict.ERROR
