"""The async Runner: executes attacks with concurrency, rate-limit, timeout, retries.

The runner builds one ``AdapterRequest`` per attack, sends it under a bounded
semaphore (with an out-of-semaphore rate-limit gate and a per-request timeout),
retries transient failures with seeded full-jitter backoff, and folds every result
into an ``AttemptRecord`` on the ``RunRecord``. It persists the record atomically and
incrementally so a crashed run is resumable. Successful sends are scored by the injected
``Scorer`` (real PASS/FAIL/SKIPPED verdict + tier); send failures record ``ERROR``.
"""

from __future__ import annotations

import asyncio
import os
import random
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

from .config import RunOptions
from .errors import AdapterError
from .logging_setup import get_logger
from .pricing import estimate_cost
from .records import AttemptRecord, RunRecord, RunStatus, TokenUsage, Verdict
from .scoring import Scorer
from .targets.base import AdapterRequest, TargetAdapter

if TYPE_CHECKING:
    from .attacks import Attack

log = get_logger("runner")


def _utc_now() -> datetime:
    return datetime.now(UTC)


class _RateGate:
    """Global min-interval gate (``1/rps``). ``rps=None`` -> no-op.

    Taken OUTSIDE the concurrency semaphore so a task does not burn a concurrency
    slot while sleeping the rate interval.
    """

    def __init__(
        self,
        rps: float | None,
        *,
        monotonic: Callable[[], float],
        sleep: Callable[[float], Awaitable[None]],
    ) -> None:
        self._interval = (1.0 / rps) if rps else 0.0
        self._monotonic = monotonic
        self._sleep = sleep
        self._lock = asyncio.Lock()
        self._last: float | None = None

    async def wait(self) -> None:
        if self._interval <= 0.0:
            return
        async with self._lock:
            now = self._monotonic()
            if self._last is not None:
                delay = self._last + self._interval - now
                if delay > 0:
                    await self._sleep(delay)
            self._last = self._monotonic()


class Runner:
    def __init__(
        self,
        adapter: TargetAdapter,
        options: RunOptions,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        rng: random.Random | None = None,
        now: Callable[[], datetime] = _utc_now,
        monotonic: Callable[[], float] = time.monotonic,
        scorer: Scorer | None = None,
        on_attempt: Callable[[AttemptRecord], None] | None = None,
    ) -> None:
        self.adapter = adapter
        self.options = options
        self._scorer = scorer if scorer is not None else Scorer()
        self._sleep = sleep
        self._rng = rng if rng is not None else random.Random(options.retry_seed)
        self._now = now
        self._monotonic = monotonic
        self._on_attempt = on_attempt
        self._write_lock = asyncio.Lock()

    def run_path(self, record: RunRecord) -> Path:
        return Path(self.options.output_dir) / f"{record.run_id}.json"

    def _build_request(self, attack: Attack) -> AdapterRequest:
        # Phase 3 surface rule: the payload is always the user prompt, regardless of
        # attack.surface. temperature/max_tokens come only from RunOptions (pinned).
        return AdapterRequest(
            prompt=attack.payload,
            system=None,
            max_tokens=self.options.max_tokens,
            temperature=self.options.temperature,
        )

    def _atomic_write(self, record: RunRecord) -> None:
        path = self.run_path(record)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        tmp.write_text(record.to_json(), encoding="utf-8")
        os.replace(tmp, path)

    async def _persist(self, record: RunRecord) -> None:
        async with self._write_lock:
            self._atomic_write(record)

    async def _record_attempt(self, record: RunRecord, attempt: AttemptRecord) -> None:
        # Remove any prior attempts for this attack id (re-tried ERROR replacement) then
        # append + persist, all under the write-lock so concurrent completions can't race
        # or produce duplicate attack_id entries.
        async with self._write_lock:
            record.attempts = [a for a in record.attempts if a.attack_id != attempt.attack_id]
            record.attempts.append(attempt)
            self._atomic_write(record)
        # Progress hook, fired AFTER persistence and OUTSIDE the lock (a slow UI callback
        # must never block the write path). A raising callback must never crash a run.
        if self._on_attempt is not None:
            try:
                self._on_attempt(attempt)
            except Exception:  # noqa: BLE001 — a UI callback must never abort a run
                log.exception("on_attempt callback raised; continuing")

    def _is_transient(self, exc: BaseException) -> bool:
        if isinstance(exc, asyncio.TimeoutError):  # builtins.TimeoutError in 3.11+
            return True
        if isinstance(exc, httpx.TimeoutException | httpx.TransportError):
            return True
        if isinstance(exc, AdapterError):
            sc = exc.status_code
            if sc == 429 or (sc is not None and 500 <= sc < 600):
                return True
        return False

    async def _send_with_retries(self, request: AdapterRequest):
        """Send under the per-request timeout, retrying transient errors with seeded
        full-jitter backoff. Returns the AdapterResponse or re-raises the last error."""
        last_exc: BaseException | None = None
        for i in range(1 + self.options.max_retries):
            try:
                return await asyncio.wait_for(
                    self.adapter.send(request), self.options.request_timeout_s
                )
            except Exception as exc:  # noqa: BLE001 — classified below; BaseException propagates
                last_exc = exc
                if self._is_transient(exc) and i < self.options.max_retries:
                    cap = min(
                        self.options.retry_max_delay_s,
                        self.options.retry_base_delay_s * (2**i),
                    )
                    await self._sleep(self._rng.uniform(0.0, cap))
                    continue
                break
        assert last_exc is not None
        raise last_exc

    async def _run_attempt(
        self,
        attack: Attack,
        record: RunRecord,
        semaphore: asyncio.Semaphore,
        gate: _RateGate,
    ) -> None:
        request = self._build_request(attack)
        # Rate gate OUTSIDE the semaphore (no concurrency slot burned while sleeping).
        await gate.wait()
        async with semaphore:
            started_at = self._now()
            start = self._monotonic()
            try:
                response = await self._send_with_retries(request)
            except Exception as exc:  # noqa: BLE001 — record ERROR; CancelledError propagates
                attempt = AttemptRecord(
                    attack_id=attack.id,
                    category=attack.category,
                    prompt=request.prompt,
                    verdict=Verdict.ERROR,
                    error=str(exc),
                    started_at=started_at,
                    finished_at=self._now(),
                    latency_ms=(self._monotonic() - start) * 1000.0,
                )
                await self._record_attempt(record, attempt)
                return

            usage = TokenUsage(
                prompt_tokens=response.prompt_tokens or 0,
                completion_tokens=response.completion_tokens or 0,
            )
            cost_usd, known = estimate_cost(record.provider, record.model, usage)
            if not known:
                log.debug(
                    "no price entry for provider/model; cost recorded as 0",
                    extra={"provider": record.provider, "model": record.model},
                )
            latency = response.latency_ms
            if latency is None:
                latency = (self._monotonic() - start) * 1000.0
            result = self._scorer.score(attack, response_text=response.text, response=response)
            attempt = AttemptRecord(
                attack_id=attack.id,
                category=attack.category,
                prompt=request.prompt,
                response_text=response.text,
                raw_response=response.raw,
                verdict=result.verdict,
                score_tier=result.score_tier,
                score_detail=result.detail,
                usage=usage,
                cost_usd=cost_usd,
                latency_ms=latency,
                started_at=started_at,
                finished_at=self._now(),
            )
            await self._record_attempt(record, attempt)

    async def run(self, attacks: list[Attack], record: RunRecord) -> RunRecord:
        ordered = sorted(attacks, key=lambda a: a.id)
        # Resume skip-set: attempts that executed (verdict != ERROR) are skipped; ERROR
        # attempts are dropped and re-tried.
        done = {a.attack_id for a in record.attempts if a.verdict != Verdict.ERROR}
        pending = [a for a in ordered if a.id not in done]

        record.status = RunStatus.RUNNING
        await self._persist(record)

        semaphore = asyncio.Semaphore(self.options.concurrency)
        gate = _RateGate(self.options.rps, monotonic=self._monotonic, sleep=self._sleep)

        tasks = [
            asyncio.ensure_future(self._run_attempt(attack, record, semaphore, gate))
            for attack in pending
        ]
        try:
            # return_exceptions=False: per-task handler turns every Exception into an
            # ERROR attempt, but CancelledError/KeyboardInterrupt propagate to ABORTED.
            await asyncio.gather(*tasks)
        except (asyncio.CancelledError, KeyboardInterrupt):
            for task in tasks:
                task.cancel()
            record.status = RunStatus.ABORTED
            await self._persist(record)
            raise

        record.status = RunStatus.COMPLETED
        await self._persist(record)
        return record
