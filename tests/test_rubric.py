"""M2: the versioned rubric artifact + deterministic render + get_rubric lookup."""

from __future__ import annotations

import pytest

from gauntlet.errors import ConfigError
from gauntlet.judge import RUBRIC_V1, get_rubric


def test_rubric_v1_pinned() -> None:
    assert RUBRIC_V1.version == "v1"
    assert get_rubric("v1") is RUBRIC_V1


def test_render_is_deterministic_and_complete() -> None:
    out1 = RUBRIC_V1.render(criteria="leaks the canary", payload="PAY", response_text="RESP")
    out2 = RUBRIC_V1.render(criteria="leaks the canary", payload="PAY", response_text="RESP")
    assert out1 == out2
    assert "leaks the canary" in out1
    assert "PAY" in out1
    assert "RESP" in out1
    assert "VERDICT: attack_succeeded|defended" in out1


def test_unknown_version_raises_config_error() -> None:
    with pytest.raises(ConfigError, match="unknown rubric_version"):
        get_rubric("nope")
