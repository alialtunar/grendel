"""End-to-end offline flow: config -> adapter -> AttemptRecord -> RunRecord -> report."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
from typer.testing import CliRunner

from gauntlet.cli import app
from gauntlet.config import load_config
from gauntlet.records import AttemptRecord, TokenUsage, Verdict, make_run_record
from gauntlet.targets import build_target
from gauntlet.targets.base import AdapterRequest

runner = CliRunner()
EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "gauntlet.example.yaml"


def _handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": "gpt-4o-mini",
            "choices": [{"message": {"content": "I refuse."}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 3},
        },
    )


async def test_full_offline_flow(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-dummy")
    cfg = load_config(EXAMPLE)

    client = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
    async with build_target("gpt", cfg, client=client) as adapter:
        resp = await adapter.send(AdapterRequest(prompt="do something bad"))
    await client.aclose()

    attempt = AttemptRecord(
        prompt="do something bad",
        response_text=resp.text,
        raw_response=resp.raw,
        verdict=Verdict.PASS,
        category="injection",
        usage=TokenUsage(
            prompt_tokens=resp.prompt_tokens or 0,
            completion_tokens=resp.completion_tokens or 0,
        ),
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
    )
    record = make_run_record(
        target_name="gpt",
        provider="openai",
        model="gpt-4o-mini",
        config=cfg,
        attempts=[attempt],
    )

    out = tmp_path / "run.json"
    out.write_text(record.to_json(), encoding="utf-8")

    # config_snapshot leaks no secret.
    assert "sk-dummy" not in out.read_text(encoding="utf-8")

    result = runner.invoke(app, ["report", "--run", str(out)])
    assert result.exit_code == 0
    assert record.run_id in result.output
    assert "gpt" in result.output
