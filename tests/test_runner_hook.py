"""M2: the additive on_attempt progress hook — fires after persistence, never aborts."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fakes import FakeAdapter, make_attack
from grendel.config import RunOptions
from grendel.records import AttemptRecord, RunRecord, RunStatus, Verdict
from grendel.runner import Runner


def _record() -> RunRecord:
    return RunRecord(
        run_id="run-hook",
        created_at=datetime.now(UTC),
        target_name="t",
        provider="fake",
        model="fake-model",
    )


def _options(tmp_path: Path, **kw) -> RunOptions:
    return RunOptions(output_dir=tmp_path, **kw)


async def test_hook_fires_per_attempt_after_persistence(tmp_path: Path) -> None:
    seen: list[AttemptRecord] = []
    on_disk_counts: list[int] = []

    def collector(attempt: AttemptRecord) -> None:
        seen.append(attempt)
        # The record is already persisted when the callback fires: the on-disk file
        # already contains this attempt.
        reloaded = RunRecord.from_json((tmp_path / "run-hook.json").read_text(encoding="utf-8"))
        on_disk_counts.append(len(reloaded.attempts))
        assert any(a.attack_id == attempt.attack_id for a in reloaded.attempts)

    adapter = FakeAdapter()
    runner = Runner(adapter, _options(tmp_path, concurrency=1), on_attempt=collector)
    attacks = [make_attack("cat/a"), make_attack("cat/b"), make_attack("cat/c")]
    record = await runner.run(attacks, _record())

    assert record.status == RunStatus.COMPLETED
    assert len(seen) == 3
    assert sorted(a.attack_id for a in seen) == ["cat/a", "cat/b", "cat/c"]
    assert on_disk_counts == [1, 2, 3]  # monotonically grows, persisted before callback


async def test_raising_hook_does_not_abort_run(tmp_path: Path) -> None:
    def boom(attempt: AttemptRecord) -> None:
        raise RuntimeError("callback blew up")

    adapter = FakeAdapter()
    runner = Runner(adapter, _options(tmp_path), on_attempt=boom)
    record = await runner.run([make_attack("cat/a"), make_attack("cat/b")], _record())

    assert record.status == RunStatus.COMPLETED
    assert len(record.attempts) == 2


async def test_default_none_is_inert(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    runner = Runner(adapter, _options(tmp_path))
    assert runner._on_attempt is None
    record = await runner.run([make_attack("cat/a")], _record())
    assert record.status == RunStatus.COMPLETED
    assert all(a.verdict != Verdict.ERROR for a in record.attempts)
