"""Data-integrity tests for the two bundled packs, via the real loader."""

from __future__ import annotations

import re

from grendel.attacks import ALLOWED_LICENSES
from grendel.packloader import default_packs_dir, list_packs, load_packs

OWASP_RE = re.compile(r"^LLM(0[1-9]|10)$")
ATLAS_RE = re.compile(r"^AML\.T\d{4}(\.\d{3})?$")


def test_packs_dir_is_populated() -> None:
    # First distinguish a packaging problem from a validation failure (review fix #5).
    packs_dir = default_packs_dir()
    assert packs_dir.is_dir(), f"packs dir missing — packaging problem: {packs_dir}"
    for category in ("prompt-injection", "jailbreak"):
        sub = packs_dir / category
        assert sub.is_dir(), f"missing category dir: {sub}"
        assert list(sub.glob("*.yaml")), f"no yaml files in {sub}"


def test_loads_exactly_twenty_one() -> None:
    # 12 string packs (prompt-injection + jailbreak) + 5 side-effect tool-abuse + 4 mcp.
    attacks = load_packs(default_packs_dir())
    assert len(attacks) == 21


def test_ids_unique_and_match_path() -> None:
    attacks = load_packs(default_packs_dir())
    ids = [a.id for a in attacks]
    assert len(ids) == len(set(ids))
    for a in attacks:
        stem = a.id.split("/", 1)[1]
        assert a.id == f"{a.category}/{stem}"


def test_category_counts() -> None:
    attacks = load_packs(default_packs_dir())
    counts: dict[str, int] = {}
    for a in attacks:
        counts[a.category] = counts.get(a.category, 0) + 1
    assert counts == {"prompt-injection": 6, "jailbreak": 6, "tool-abuse": 5, "mcp": 4}


def test_all_fields_well_formed() -> None:
    attacks = load_packs(default_packs_dir())
    for a in attacks:
        assert a.license in ALLOWED_LICENSES
        # Fix #11: tool-abuse -> side-effect; mcp -> mcp-assert OR side-effect (3+1);
        # everything else -> string.
        if a.category == "tool-abuse":
            assert a.success_when.type == "side-effect"
        elif a.category == "mcp":
            assert a.success_when.type in {"mcp-assert", "side-effect"}
        else:
            assert a.success_when.type == "string"
        assert OWASP_RE.match(a.owasp)
        assert ATLAS_RE.match(a.atlas)


def test_list_packs_twenty_one_rows_license_ok() -> None:
    infos = list_packs(default_packs_dir())
    assert len(infos) == 21
    assert all(info.license_ok for info in infos)
