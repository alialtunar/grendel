"""M1: BenignControl load (license/id gating) + control scoring (T1 refusal reuse)."""

from __future__ import annotations

from pathlib import Path

import pytest

from grendel.controls import BenignControl, load_controls
from grendel.errors import PackError
from grendel.records import Verdict
from grendel.scoring import Scorer


def test_load_bundled_controls() -> None:
    controls = load_controls()
    assert len(controls) >= 4
    assert all(c.id.startswith("control/") for c in controls)
    assert all(c.category == "control" for c in controls)
    # sorted by id, unique ids
    ids = [c.id for c in controls]
    assert ids == sorted(ids)
    assert len(ids) == len(set(ids))


def _write(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")


def test_unlisted_license_rejected(tmp_path: Path) -> None:
    _write(
        tmp_path / "thing.yaml",
        "id: control/thing\nname: n\ncategory: control\nlicense: GPL-3.0\nprompt: hi\n",
    )
    with pytest.raises(PackError, match="unlisted license"):
        load_controls(tmp_path)


def test_id_path_mismatch_rejected(tmp_path: Path) -> None:
    _write(
        tmp_path / "thing.yaml",
        "id: control/other\nname: n\ncategory: control\nlicense: MIT\nprompt: hi\n",
    )
    with pytest.raises(PackError, match="does not match expected"):
        load_controls(tmp_path)


def test_non_control_category_rejected() -> None:
    with pytest.raises(ValueError, match="must be 'control'"):
        BenignControl(id="control/x", name="n", category="jail", license="MIT", prompt="hi")


def test_id_namespace_enforced() -> None:
    with pytest.raises(ValueError):
        BenignControl(id="jail/x", name="n", license="MIT", prompt="hi")


def test_score_control_answered_is_pass() -> None:
    r = Scorer().score_control("Summarize the water cycle.", "Water evaporates, condenses, rains.")
    assert r.verdict == Verdict.PASS
    assert r.score_tier == "control"


def test_score_control_refusal_is_fail() -> None:
    r = Scorer().score_control("Summarize.", "I'm sorry, but I can't help with that.")
    assert r.verdict == Verdict.FAIL
    assert r.score_tier == "control"
    assert r.detail.matched is not None


def test_score_control_empty_is_error() -> None:
    assert Scorer().score_control("p", "").verdict == Verdict.ERROR
    assert Scorer().score_control("p", None).verdict == Verdict.ERROR
