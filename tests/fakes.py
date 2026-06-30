"""Offline test doubles for the runner: FakeAdapter + recording sleep + manual clock."""

from __future__ import annotations

import asyncio

from gauntlet.attacks import Attack
from gauntlet.targets.base import AdapterRequest, AdapterResponse, TargetAdapter


def make_attack(id: str, payload: str = "do the bad thing") -> Attack:
    """Build a minimal valid Attack. ``id`` must be ``<category>/<slug>``."""
    category = id.split("/", 1)[0]
    return Attack(
        id=id,
        name=f"attack {id}",
        category=category,
        owasp="LLM01",
        atlas="AML.T0051",
        surface="prompt",
        severity="high",
        license="MIT",
        version=1,
        payload=payload,
        success_when={"type": "string", "contains": ["x"]},
    )


class FakeAdapter(TargetAdapter):
    """In-memory TargetAdapter: canned responses, recorded requests, scripted failures.

    - ``failures``: a list of exceptions raised on the first calls (across all attacks,
      in order) before sends start succeeding — used to exercise retries / taxonomy.
    - ``barrier``: an ``asyncio.Barrier`` whose ``parties`` equals the expected max
      in-flight; each send waits on it so the test can assert ``max_active``.
    """

    def __init__(
        self,
        *,
        text: str = "ok",
        prompt_tokens: int | None = 1,
        completion_tokens: int | None = 2,
        model: str = "fake-model",
        provider: str = "fake",
        failures: list[BaseException] | None = None,
        barrier: asyncio.Barrier | None = None,
    ) -> None:
        self.name = "fake"
        self.text = text
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.model = model
        self.provider = provider
        self._failures = list(failures or [])
        self._call_count = 0
        self.barrier = barrier
        self.requests: list[AdapterRequest] = []
        self.active = 0
        self.max_active = 0
        self.closed = False

    async def send(self, request: AdapterRequest) -> AdapterResponse:
        self.requests.append(request)

        if self.barrier is not None:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            try:
                await self.barrier.wait()
            finally:
                self.active -= 1

        idx = self._call_count
        self._call_count += 1
        if idx < len(self._failures):
            raise self._failures[idx]

        return AdapterResponse(
            text=self.text,
            raw={"echo": request.prompt},
            model=self.model,
            provider=self.provider,
            finish_reason="stop",
            prompt_tokens=self.prompt_tokens,
            completion_tokens=self.completion_tokens,
            latency_ms=1.0,
        )

    async def aclose(self) -> None:
        self.closed = True


class ManualClock:
    """A monotonic clock advanced explicitly (or by RecordingSleep)."""

    def __init__(self, start: float = 0.0) -> None:
        self.t = start

    def monotonic(self) -> float:
        return self.t

    def advance(self, delta: float) -> None:
        self.t += delta


class RecordingSleep:
    """An async sleep that records requested delays instead of really sleeping.

    If a ``clock`` is given, each sleep advances it so rate-limit spacing and backoff
    can be asserted against the fake clock.
    """

    def __init__(self, clock: ManualClock | None = None) -> None:
        self.calls: list[float] = []
        self.clock = clock

    async def __call__(self, delay: float) -> None:
        self.calls.append(delay)
        if self.clock is not None:
            self.clock.advance(delay)
        # Yield so other tasks make progress without real time passing.
        await asyncio.sleep(0)
