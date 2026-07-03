"""End-to-end offline flow: config -> adapter -> AttemptRecord -> RunRecord -> report."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
from typer.testing import CliRunner

from grendel.cli import app
from grendel.config import load_config
from grendel.records import AttemptRecord, RunRecord, TokenUsage, Verdict, make_run_record
from grendel.targets import build_target
from grendel.targets.base import AdapterRequest

runner = CliRunner()
EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "grendel.example.yaml"


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


def test_run_report_diff_offline(tmp_path: Path) -> None:
    """End-to-end (offline): two records -> report html/md -> diff, all connecting."""
    rec_a = RunRecord(
        run_id="ea",
        created_at=datetime.now(UTC),
        target_name="gpt",
        provider="openai",
        model="gpt-4o-mini",
        attempts=[
            AttemptRecord(
                attack_id="inj/x",
                category="inj",
                owasp="LLM01",
                atlas="AML.T0051",
                prompt="p",
                verdict=Verdict.PASS,
                latency_ms=5.0,
            )
        ],
    )
    rec_b = RunRecord(
        run_id="eb",
        created_at=datetime.now(UTC),
        target_name="gpt",
        provider="openai",
        model="gpt-4o-mini",
        attempts=[
            AttemptRecord(
                attack_id="inj/x",
                category="inj",
                owasp="LLM01",
                atlas="AML.T0051",
                prompt="p",
                verdict=Verdict.FAIL,
                latency_ms=9.0,
            )
        ],
    )
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    a.write_text(rec_a.to_json(), encoding="utf-8")
    b.write_text(rec_b.to_json(), encoding="utf-8")

    html_out = tmp_path / "b.html"
    md_out = tmp_path / "b.md"
    assert (
        runner.invoke(
            app, ["report", "--run", str(b), "--format", "html", "--out", str(html_out)]
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app, ["report", "--run", str(b), "--format", "md", "--out", str(md_out)]
        ).exit_code
        == 0
    )
    assert html_out.read_text(encoding="utf-8").startswith("<!DOCTYPE html>")
    assert "# Grendel report" in md_out.read_text(encoding="utf-8")

    diff_res = runner.invoke(app, ["diff", str(a), str(b), "--format", "text"])
    assert diff_res.exit_code == 0
    assert "newly failing: inj/x" in diff_res.output
