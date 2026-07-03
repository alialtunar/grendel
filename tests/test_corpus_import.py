"""Phase 14 M1: open-corpus import engine — garak fixture → validated Attack YAML, offline."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from grendel.corpus import RawEntry, import_corpus, import_entries, to_attack
from grendel.errors import PackError
from grendel.packloader import load_packs

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "garak"
ID_RE = re.compile(r"^[a-z0-9-]+/[a-z0-9-]+$")


def _entry(text: str, category: str = "jailbreak", license: str = "Apache-2.0") -> RawEntry:
    return RawEntry(text=text, category=category, source_name="fix", license=license)


# --- convert + write --------------------------------------------------------------------------
def test_import_converts_and_writes_loadable_packs(tmp_path: Path) -> None:
    out = tmp_path / "cat"
    result = import_corpus("garak", FIXTURE, out)
    # fixture: 2 dan + (2 inthewild, 1 a whitespace dup) + 2 json = 6 seen, 5 imported, 1 dup
    assert result.seen == 6
    assert result.imported == 5
    assert result.duplicate == 1
    assert result.license_skipped == 0

    loaded = load_packs(out)
    assert len(loaded) == 5
    for atk in loaded:
        assert ID_RE.match(atk.id)
        assert atk.category in {"jailbreak", "dan"}
        assert atk.success_when.type == "classifier"
        assert atk.license == "Apache-2.0"


def test_written_yaml_has_scalar_enums(tmp_path: Path) -> None:
    out = tmp_path / "cat"
    import_corpus("garak", FIXTURE, out)
    sample = next(out.glob("*/*.yaml"))
    text = sample.read_text(encoding="utf-8")
    assert "surface: prompt" in text  # plain scalar, not a Python enum repr
    assert "severity: medium" in text
    assert "Surface." not in text and "Severity." not in text


def test_ids_are_path_safe(tmp_path: Path) -> None:
    out = tmp_path / "cat"
    result = import_corpus("garak", FIXTURE, out)
    for rel in result.written:
        assert ".." not in rel
        assert rel.count("/") == 1  # <category>/<stem>.yaml


# --- dedup / incremental ----------------------------------------------------------------------
def test_rerun_is_idempotent(tmp_path: Path) -> None:
    out = tmp_path / "cat"
    import_corpus("garak", FIXTURE, out)
    again = import_corpus("garak", FIXTURE, out)
    assert again.imported == 0
    assert again.duplicate == again.seen == 6


def test_whitespace_variant_dedupes(tmp_path: Path) -> None:
    out = tmp_path / "cat"
    entries = [
        _entry("Do the forbidden thing now."),
        _entry("Do   the forbidden   thing now."),  # whitespace variant -> same hash
    ]
    result = import_entries(entries, out)
    assert result.imported == 1 and result.duplicate == 1


# --- license gate + ordering ------------------------------------------------------------------
def test_license_gate_skips_unlisted(tmp_path: Path) -> None:
    out = tmp_path / "cat"
    result = import_entries([_entry("bad license prompt", license="GPL-3.0-only")], out)
    assert result.imported == 0 and result.license_skipped == 1
    assert not list(out.glob("*/*.yaml"))


def test_allow_unlisted_licenses_override(tmp_path: Path) -> None:
    out = tmp_path / "cat"
    result = import_entries(
        [_entry("bad license prompt", license="GPL-3.0-only")], out, allow_unlisted_licenses=True
    )
    assert result.imported == 1 and result.license_skipped == 0


def test_dedup_runs_before_license_gate(tmp_path: Path) -> None:
    # An entry that is BOTH an exact duplicate AND has a bad license -> counted as duplicate.
    out = tmp_path / "cat"
    entries = [
        _entry("shared prompt"),  # Apache -> imported
        _entry("shared prompt", license="GPL-3.0-only"),  # dup+bad-license -> duplicate
    ]
    result = import_entries(entries, out)
    assert result.imported == 1
    assert result.duplicate == 1 and result.license_skipped == 0


# --- limit / dry-run --------------------------------------------------------------------------
def test_limit_stops_after_n_and_reports_counts(tmp_path: Path) -> None:
    out = tmp_path / "cat"
    result = import_corpus("garak", FIXTURE, out, limit=1)
    assert result.imported == 1
    # break after the 1st write -> only entries processed up to the stop are counted
    assert result.seen == 1
    assert result.duplicate == 0 and result.license_skipped == 0
    assert len(list(out.glob("*/*.yaml"))) == 1


def test_dry_run_writes_nothing_but_reports(tmp_path: Path) -> None:
    out = tmp_path / "cat"
    result = import_corpus("garak", FIXTURE, out, dry_run=True)
    assert result.imported == 5
    assert not out.exists() or not list(out.glob("*/*.yaml"))


# --- conversion errors + partial-failure convergence ------------------------------------------
def test_invalid_entry_raises_packerror_after_earlier_writes(tmp_path: Path) -> None:
    out = tmp_path / "cat"
    good, bad = _entry("a good prompt"), _entry("   ")  # whitespace-only payload -> invalid Attack
    with pytest.raises(PackError):
        import_entries([good, bad], out)
    # the earlier good entry was already written atomically
    assert len(list(out.glob("*/*.yaml"))) == 1
    # re-running without the bad entry adds only the remainder, no duplicate of the good one
    remainder = import_entries([good, _entry("another good prompt")], out)
    assert remainder.imported == 1 and remainder.duplicate == 1


def test_unknown_source_raises() -> None:
    with pytest.raises(PackError, match="unknown source"):
        import_corpus("nope", FIXTURE, Path("x"))


def test_same_payload_same_id() -> None:
    a = to_attack(_entry("identical text"), seq=0)
    b = to_attack(_entry("identical text"), seq=9)
    assert a.id == b.id


# --- garak .txt formats + category mapping (Phase 16 follow-on) -------------------------------
from grendel.corpus import GarakSource, _category_for  # noqa: E402


def test_read_txt_line_separated(tmp_path) -> None:
    # a one-prompt-per-line file (harmbench/tap/rtp style) -> one entry per line
    f = tmp_path / "harmbench_prompts.txt"
    f.write_text("prompt one\nprompt two\nprompt three\n", encoding="utf-8")
    entries = list(GarakSource().read(f))
    assert [e.text for e in entries] == ["prompt one", "prompt two", "prompt three"]
    assert all(e.category == "harmbench" for e in entries)


def test_read_txt_paragraph_separated(tmp_path) -> None:
    # a blank-line-separated file -> one entry per paragraph (multi-line prompts preserved)
    f = tmp_path / "jb.txt"
    f.write_text("line a\nline b\n\nsecond prompt\n", encoding="utf-8")
    entries = list(GarakSource().read(f))
    assert [e.text for e in entries] == ["line a\nline b", "second prompt"]


def test_category_mapping() -> None:
    assert _category_for("Dan_11_0") == "dan"
    assert _category_for("harmbench_prompts") == "harmbench"
    assert _category_for("rtp_insult") == "toxicity"
    assert _category_for("tap_jailbreaks") == "jailbreak"
