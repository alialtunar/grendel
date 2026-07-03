"""Phase 17: no console write crashes on a non-UTF-8 terminal (Windows cp1254 / iso-8859-*).

CliRunner ALWAYS captures as UTF-8, so it cannot catch this bug class — these tests exercise the
real stdout encoding: a fast unit test of the codec fallback, plus a subprocess test that runs the
crash-prone commands under a limited PYTHONIOENCODING and asserts exit 0 / no traceback.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from grendel.banner import _HANDLER_NAME, install_console_fallback


def test_console_fallback_downgrades_glyphs_instead_of_raising() -> None:
    install_console_fallback()
    s = "cost — 5 · done ✓ bad ✗ ⚠ 🐺 → next"
    # iso-8859-9 (Turkish) lacks em-dash / ✓ / ✗ / emoji — must not raise, must strip them.
    out = s.encode("iso-8859-9", _HANDLER_NAME).decode("iso-8859-9")
    for glyph in ("—", "✓", "✗", "⚠", "🐺", "→"):
        assert glyph not in out
    assert "cost" in out and "next" in out


def _run(args: list[str], encoding: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONIOENCODING": encoding, "GRENDEL_NO_AUTOCONFIG": "1"}
    code = (
        "from grendel.cli import app\n"
        "try:\n"
        f"    app({args!r}, standalone_mode=False)\n"
        "except SystemExit:\n"
        "    pass\n"
    )
    return subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        input=stdin,
        capture_output=True,
        text=True,
        encoding=encoding,
        errors="replace",
    )


# The newcomer's first commands, on codepages that each lack a glyph grendel used to hardcode:
# iso-8859-5 lacks '·' (config labels), iso-8859-9 lacks '—' (list/doctor em-dashes).
@pytest.mark.parametrize("encoding", ["iso-8859-5", "iso-8859-9"])
@pytest.mark.parametrize(
    "args,stdin",
    [
        ([], None),  # bare grendel (banner)
        (["doctor"], None),
        (["list"], None),  # no targets configured -> the em-dash "(none) — ..." line
        (["config"], "q\n"),  # non-TTY letter menu -> the '·' labels
    ],
)
def test_commands_never_crash_on_legacy_console(encoding, args, stdin) -> None:
    r = _run(args, encoding, stdin)
    assert r.returncode == 0, f"args={args} enc={encoding}\nSTDERR:\n{r.stderr}"
    assert "UnicodeEncodeError" not in (r.stderr or "")
    assert "Traceback" not in (r.stderr or "")
