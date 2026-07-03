"""The bare-`grendel` landing banner (inline, no TUI)."""

from __future__ import annotations

from typer.testing import CliRunner

from grendel.banner import COMMANDS, render_banner
from grendel.cli import app

runner = CliRunner()


def test_render_banner_lists_commands_and_notice() -> None:
    text = render_banner(color=False)
    assert "grendel" in text
    for name, _ in COMMANDS:
        assert name in text
    assert "defensive use only" in text


def test_bare_grendel_prints_banner_exit_0() -> None:
    result = runner.invoke(app, [])
    assert result.exit_code == 0
    assert "grendel" in result.output
    assert "run" in result.output and "proxy" in result.output
    assert "defensive use only" in result.output


def test_help_still_works() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "run" in result.output


def test_banner_includes_config_and_doctor() -> None:
    names = {name for name, _ in COMMANDS}
    assert {"config", "doctor"} <= names


def test_commands_stay_in_sync_with_registered() -> None:
    # The banner list must equal the actually-registered Typer commands (so none can drift).
    registered = {c.name or c.callback.__name__ for c in app.registered_commands}
    listed = {name for name, _ in COMMANDS}
    assert listed == registered, f"banner {listed} != registered {registered}"


# --- Phase 16: logo helpers -------------------------------------------------------------------
from grendel.banner import config_header, render_logo  # noqa: E402


def test_render_logo_and_appears_in_banner() -> None:
    logo = render_logo(color=False)
    assert "█" in logo  # the block wordmark
    assert logo in render_banner(color=False)


def test_config_header_has_brand_and_path() -> None:
    hdr = config_header("grendel.yaml", color=False)
    assert "GRENDEL" in hdr and "grendel.yaml" in hdr


# --- Phase 17: ASCII fallback for non-UTF-8 consoles (e.g. Windows cp1254) ---------------------
from grendel.banner import stream_supports_unicode  # noqa: E402


class _FakeStream:
    def __init__(self, encoding: str) -> None:
        self.encoding = encoding


def test_stream_supports_unicode_detects_legacy_codepage() -> None:
    assert stream_supports_unicode(_FakeStream("utf-8")) is True
    assert stream_supports_unicode(_FakeStream("cp1254")) is False  # the user's Windows locale
    assert stream_supports_unicode(_FakeStream("ascii")) is False


def test_ascii_banner_is_encodable_on_legacy_console() -> None:
    # The bug: bare `grendel` crashed with UnicodeEncodeError on a cp1254 console. The ASCII
    # fallback must encode cleanly there (and in pure ASCII), and still be a real banner.
    text = render_banner(color=False, unicode=False)
    text.encode("cp1254")  # must not raise
    text.encode("ascii")  # fully ASCII fallback
    assert "grendel" in text
    for name, _ in COMMANDS:
        assert name in text
    assert "defensive use only" in text


def test_ascii_config_header_is_encodable() -> None:
    hdr = config_header("grendel.yaml", color=False, unicode=False)
    hdr.encode("cp1254")
    assert "GRENDEL" in hdr and "grendel.yaml" in hdr
