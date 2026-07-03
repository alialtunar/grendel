"""Phase 12 M2: `grendel proxy` — terminal-configurable proxy preview (no serving)."""

from __future__ import annotations

from typer.testing import CliRunner

from grendel.cli import app

runner = CliRunner()


def test_proxy_defaults_no_config() -> None:
    result = runner.invoke(app, ["proxy"])
    assert result.exit_code == 0, result.output
    assert "host: 127.0.0.1" in result.output
    assert "port: 8100" in result.output
    assert "routes: (none)" in result.output
    assert "--serve" in result.output  # preview hints at how to actually run it


def test_proxy_preview_explains_indirect_injection_niche() -> None:
    # Phase 19: the proxy is demoted to indirect injection; its preview must say so and point
    # users to an agent target for direct testing (the _echo_proxy_hint helper is wired in here).
    result = runner.invoke(app, ["proxy"])
    assert result.exit_code == 0, result.output
    assert "INDIRECT injection" in result.output
    assert "agent target" in result.output


def test_proxy_merges_and_sorts_routes() -> None:
    result = runner.invoke(
        app,
        [
            "proxy",
            "--host",
            "0.0.0.0",
            "--port",
            "9000",
            "--route",
            "/openai=openai",
            "--route",
            "/anth=anthropic",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "host: 0.0.0.0" in result.output
    assert "port: 9000" in result.output
    # sorted by path: /anth before /openai
    lines = [ln.strip() for ln in result.output.splitlines()]
    i_anth = lines.index("/anth -> anthropic")
    i_openai = lines.index("/openai -> openai")
    assert i_anth < i_openai


def test_proxy_route_last_wins() -> None:
    result = runner.invoke(app, ["proxy", "--route", "/openai=openai", "--route", "/openai=ollama"])
    assert result.exit_code == 0, result.output
    assert "/openai -> ollama" in result.output
    assert "/openai -> openai" not in result.output


def test_proxy_bad_port() -> None:
    assert runner.invoke(app, ["proxy", "--port", "99999"]).exit_code == 2


def test_proxy_route_no_equals() -> None:
    result = runner.invoke(app, ["proxy", "--route", "openai"])
    assert result.exit_code == 2
    assert "PATH=PROVIDER" in result.output


def test_proxy_route_non_slash_path() -> None:
    result = runner.invoke(app, ["proxy", "--route", "openai=openai"])
    assert result.exit_code == 2
    assert "must start with '/'" in result.output


def test_proxy_route_unknown_provider() -> None:
    result = runner.invoke(app, ["proxy", "--route", "/x=nope"])
    assert result.exit_code == 2
    assert "unknown provider" in result.output


# --- Phase 13: proxy --serve wiring (no socket bound; proxy.serve monkeypatched) --------------
import grendel.cli as _cli  # noqa: E402
import grendel.proxy as _proxymod  # noqa: E402
from fakes import make_attack  # noqa: E402
from grendel.records import RunStatus  # noqa: E402


def _patch_attacks(monkeypatch, attacks):
    monkeypatch.setattr(_cli, "_load_attacks", lambda *a, **k: list(attacks))


def test_proxy_serve_no_route_exits_2() -> None:
    assert runner.invoke(app, ["proxy", "--serve"]).exit_code == 2


def test_proxy_serve_no_attacks_exits_2(monkeypatch) -> None:
    _patch_attacks(monkeypatch, [make_attack("cat/a")])
    # --pack matching nothing selectable -> _select_attacks exits 2 first
    result = runner.invoke(app, ["proxy", "--serve", "--route", "/openai=openai", "--pack", "nope"])
    assert result.exit_code == 2


def test_proxy_serve_builds_session_and_serves(monkeypatch, tmp_path) -> None:
    _patch_attacks(monkeypatch, [make_attack("cat/a"), make_attack("cat/b")])
    captured = {}

    def fake_serve(session, host, port):
        captured["host"] = host
        captured["port"] = port
        captured["routes"] = dict(session.config.proxy.routes)
        captured["n_attacks"] = len(session.attacks)
        session.record.status = RunStatus.COMPLETED
        return session.record

    monkeypatch.setattr(_proxymod, "serve", fake_serve)
    out = tmp_path / "proxyrun.json"
    result = runner.invoke(
        app,
        [
            "proxy",
            "--serve",
            "--host",
            "127.0.0.1",
            "--port",
            "9100",
            "--route",
            "/openai=openai",
            "--out",
            str(out),
        ],
    )
    assert result.exit_code == 0, result.output
    assert captured == {
        "host": "127.0.0.1",
        "port": 9100,
        "routes": {"/openai": "openai"},
        "n_attacks": 2,
    }
    # startup banner + a written record + summary
    assert "grendel proxy serving on http://127.0.0.1:9100" in result.output
    assert out.exists()
    assert "run " in result.output  # _summary line
