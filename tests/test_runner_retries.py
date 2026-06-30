"""M3: seeded full-jitter backoff + error taxonomy."""

from __future__ import annotations

import random
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from fakes import FakeAdapter, RecordingSleep, make_attack
from gauntlet.config import RunOptions
from gauntlet.errors import AdapterError, ProviderError
from gauntlet.records import RunRecord, RunStatus, Verdict
from gauntlet.runner import Runner

SEED = 1234


def _record() -> RunRecord:
    return RunRecord(
        run_id="run-retry",
        created_at=datetime.now(UTC),
        target_name="t",
        provider="fake",
        model="fake-model",
    )


def _opts(tmp_path: Path, **kw) -> RunOptions:
    return RunOptions(
        output_dir=tmp_path,
        max_retries=3,
        retry_base_delay_s=0.5,
        retry_max_delay_s=30.0,
        **kw,
    )


async def test_transient_retries_then_succeeds(tmp_path: Path) -> None:
    adapter = FakeAdapter(failures=[TimeoutError(), TimeoutError()])
    sleep = RecordingSleep()
    runner = Runner(adapter, _opts(tmp_path), sleep=sleep, rng=random.Random(SEED))
    record = await runner.run([make_attack("cat/a")], _record())

    assert record.status == RunStatus.COMPLETED
    # eventually succeeded -> scored (benign "ok" -> PASS), no longer the P3 SKIPPED.
    assert record.attempts[0].verdict == Verdict.PASS

    ref = random.Random(SEED)
    expected = [ref.uniform(0.0, 0.5), ref.uniform(0.0, 1.0)]  # caps: base*2^0, base*2^1
    assert sleep.calls == expected


async def test_transient_exhausted_records_error(tmp_path: Path) -> None:
    adapter = FakeAdapter(failures=[TimeoutError() for _ in range(4)])
    sleep = RecordingSleep()
    runner = Runner(adapter, _opts(tmp_path), sleep=sleep, rng=random.Random(SEED))
    record = await runner.run([make_attack("cat/a")], _record())

    assert record.status == RunStatus.COMPLETED  # one bad attack never crashes the run
    assert record.attempts[0].verdict == Verdict.ERROR
    assert len(sleep.calls) == 3  # 4 tries -> 3 backoff sleeps


async def test_429_and_5xx_are_transient(tmp_path: Path) -> None:
    for status in (429, 503):
        adapter = FakeAdapter(failures=[AdapterError("rate", status_code=status)])
        sleep = RecordingSleep()
        runner = Runner(adapter, _opts(tmp_path), sleep=sleep, rng=random.Random(SEED))
        record = await runner.run([make_attack("cat/a")], _record())
        assert record.attempts[0].verdict == Verdict.PASS  # benign "ok" scored PASS
        assert len(sleep.calls) == 1  # retried once then succeeded


async def test_httpx_transport_error_is_transient(tmp_path: Path) -> None:
    adapter = FakeAdapter(failures=[httpx.ConnectError("boom")])
    sleep = RecordingSleep()
    runner = Runner(adapter, _opts(tmp_path), sleep=sleep, rng=random.Random(SEED))
    record = await runner.run([make_attack("cat/a")], _record())
    assert record.attempts[0].verdict == Verdict.PASS  # benign "ok" scored PASS
    assert len(sleep.calls) == 1


@pytest.mark.parametrize(
    "exc",
    [
        AdapterError("no status"),
        AdapterError("not found", status_code=404),
        ProviderError("missing key"),
        ValueError("bad"),
    ],
)
async def test_non_transient_records_error_with_zero_sleeps(tmp_path: Path, exc: Exception) -> None:
    adapter = FakeAdapter(failures=[exc])
    sleep = RecordingSleep()
    runner = Runner(adapter, _opts(tmp_path), sleep=sleep, rng=random.Random(SEED))
    record = await runner.run([make_attack("cat/a")], _record())

    assert record.status == RunStatus.COMPLETED
    att = record.attempts[0]
    assert att.verdict == Verdict.ERROR
    assert att.error == str(exc)
    assert sleep.calls == []  # non-transient -> no retry


async def test_adapter_error_str_is_message() -> None:
    assert str(AdapterError("x")) == "x"
    assert str(AdapterError("y", status_code=500)) == "y"


async def test_failing_attack_does_not_crash_mixed_run(tmp_path: Path) -> None:
    # One attack fails non-transiently, another succeeds; run still COMPLETED.
    class _Mixed(FakeAdapter):
        async def send(self, request):
            if request.prompt == "boom":
                raise ValueError("boom")
            return await super().send(request)

    adapter = _Mixed()
    sleep = RecordingSleep()
    runner = Runner(adapter, _opts(tmp_path, concurrency=1), sleep=sleep, rng=random.Random(SEED))
    attacks = [make_attack("cat/a", payload="ok"), make_attack("cat/b", payload="boom")]
    record = await runner.run(attacks, _record())

    assert record.status == RunStatus.COMPLETED
    verdicts = {a.attack_id: a.verdict for a in record.attempts}
    assert verdicts["cat/a"] == Verdict.PASS  # benign "ok" scored PASS
    assert verdicts["cat/b"] == Verdict.ERROR
