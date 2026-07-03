"""Milestone-1 rebrand guard: the tool is `grendel`, not `gauntlet`, everywhere it matters.

Fully offline. Guards (a) the canary payload⇔matcher pairing (base64-aware), (b) the import
root, (c) the console-script entry point, and (d) that no `gauntlet` token survives in the
package source. If a future edit reintroduces the old name or breaks a canary pair, one of these
fails loudly.
"""

from __future__ import annotations

import base64
import importlib
import re
import tomllib
from pathlib import Path

import pytest
import yaml

from grendel.packloader import default_packs_dir

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = _REPO_ROOT / "src" / "grendel"


def _decode_b64_lines(text: str) -> str:
    """Append the decoding of any standalone base64-looking line, so an encoded canary is
    visible to a plain substring check."""
    extra: list[str] = []
    for line in text.splitlines():
        tok = line.strip()
        if len(tok) >= 16 and re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", tok):
            try:
                extra.append(base64.b64decode(tok).decode("utf-8"))
            except Exception:  # noqa: BLE001 — not base64; ignore
                pass
    return text + "\n" + "\n".join(extra)


def _string_packs() -> list[Path]:
    return [
        p
        for p in default_packs_dir().rglob("*.yaml")
        if isinstance(yaml.safe_load(p.read_text(encoding="utf-8")).get("success_when"), dict)
    ]


# (a) canary pairing + no surviving GAUNTLET- token in packs -----------------------------------
def test_canary_tokens_are_grendel_and_paired() -> None:
    checked_any = False
    for path in _string_packs():
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        sw = doc["success_when"]
        if sw.get("type") != "string":
            continue
        payload = _decode_b64_lines(str(doc.get("payload", "")))
        assert "GAUNTLET" not in payload.upper(), f"stale GAUNTLET canary in payload of {path.name}"
        for token in sw.get("contains", []):
            if token.startswith("GRENDEL-"):
                checked_any = True
                # The token may be deliberately fragmented in the payload (split-payload /
                # base64 families), so assert every hyphen-delimited part is present (which also
                # proves the prefix is GRENDEL, not GAUNTLET) rather than a contiguous match.
                for part in token.split("-"):
                    assert part in payload, (
                        f"canary part {part!r} of {token!r} not in payload of {path.name}"
                    )
            assert not token.startswith("GAUNTLET-"), f"stale GAUNTLET- matcher in {path.name}"
    assert checked_any, "expected at least one GRENDEL- canary pack"


# (b) import root ------------------------------------------------------------------------------
def test_grendel_imports_and_gauntlet_is_gone() -> None:
    assert importlib.import_module("grendel") is not None
    for sub in ("cli", "config", "runner", "scoring", "records", "banner"):
        assert importlib.import_module(f"grendel.{sub}") is not None
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("gauntlet")


# (c) console-script entry point ---------------------------------------------------------------
def test_console_script_is_grendel() -> None:
    data = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    scripts = data["project"]["scripts"]
    # The command + import name stay `grendel`; only the PyPI DIST name is suffixed
    # ("grendel" is taken on PyPI), so `pipx install grendel-redteam` still gives a `grendel` CLI.
    assert scripts == {"grendel": "grendel.cli:app"}, scripts
    assert data["project"]["name"] == "grendel-redteam"


# (d) no gauntlet substring anywhere in the package source -------------------------------------
def test_no_gauntlet_token_in_src() -> None:
    offenders = []
    for path in _SRC.rglob("*.py"):
        if "gauntlet" in path.read_text(encoding="utf-8").lower():
            offenders.append(str(path.relative_to(_REPO_ROOT)))
    assert not offenders, f"'gauntlet' still present in: {offenders}"
