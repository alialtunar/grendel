"""Finalize: scoring vocabulary and provider auth are data (config), not source.

Locks in the "zero-hardcode" cleanup: refusal markers, T2 lexicons, and contested
criteria come from cfg.scoring; a provider's key requirement and default base_url come
from preset/config data, not from provider-name branches.
"""

from __future__ import annotations

import grendel.cli as cli
from grendel.attacks import Attack
from grendel.config import CustomProviderConfig, GrendelConfig, ScoringConfig
from grendel.records import Verdict
from grendel.scoring import LexicalClassifier
from grendel.targets.providers import PRESETS, resolve_provider


def _attack(success_when: dict) -> Attack:
    return Attack(
        id="cat/a",
        name="n",
        category="cat",
        owasp="LLM01",
        atlas="AML.T0051",
        surface="prompt",
        severity="high",
        license="MIT",
        version=1,
        payload="p",
        success_when=success_when,
    )


def test_refusal_markers_come_from_config() -> None:
    cfg = GrendelConfig(scoring=ScoringConfig(refusal_markers=["zzz-custom-refusal"]))
    scorer = cli._build_scorer(cfg)
    check = {"type": "string", "contains": ["SECRET"], "match": "any"}
    # The configured phrase is caught at T1 as a refusal (PASS).
    r_custom = scorer.score(_attack(check), response_text="zzz-custom-refusal, sorry")
    assert r_custom.verdict is Verdict.PASS
    assert r_custom.score_tier == "T1"
    # A former default phrase is no longer a T1 marker (list was replaced) -> falls through T1.
    r_default = scorer.score(_attack(check), response_text="I cannot help with that.")
    assert r_default.score_tier != "T1"


def test_lexicon_override_flows_into_classifier() -> None:
    cfg = GrendelConfig(
        scoring=ScoringConfig(compliant_lexicon=["banana-split"], refusal_lexicon=[])
    )
    scorer = cli._build_scorer(cfg)
    assert isinstance(scorer._classifier, LexicalClassifier)
    cv = scorer._classifier.classify("here is a banana-split recipe")
    assert cv.score >= 0.5


def test_contested_criteria_from_config() -> None:
    cfg = GrendelConfig(scoring=ScoringConfig(contested_criteria="my-rubric"))
    scorer = cli._build_scorer(cfg)
    assert scorer._contested_criteria == "my-rubric"


def test_requires_key_derived_from_api_style() -> None:
    # openai/anthropic styles require a key by default; ollama does not (was _STYLES_REQUIRING_KEY).
    assert PRESETS["openai"].requires_key is True
    assert PRESETS["anthropic"].requires_key is True
    assert PRESETS["ollama"].requires_key is False
    # openai-compatible speaks the openai style, so it inherits requires_key=True.
    assert PRESETS["openai-compatible"].requires_key is True


def test_custom_provider_can_override_requires_key() -> None:
    cfg = GrendelConfig(
        providers={
            "local": CustomProviderConfig(
                base_url="http://localhost:9999", api_style="openai", requires_key=False
            )
        }
    )
    preset = resolve_provider("local", cfg)
    assert preset.requires_key is False


def test_no_default_base_url_requires_target_base_url() -> None:
    # openai-compatible has no default base_url -> a target must supply one (generalized check).
    import pytest

    from grendel.config import TargetConfig
    from grendel.errors import ConfigError

    with pytest.raises(ConfigError, match="no.*default base_url|base_url"):
        GrendelConfig(
            targets={
                "t": TargetConfig(type="http", provider="openai-compatible", model="m")
            }
        )
    # ...and supplying one is accepted.
    ok = GrendelConfig(
        targets={
            "t": TargetConfig(
                type="http", provider="openai-compatible", model="m", base_url="http://x/v1"
            )
        }
    )
    assert ok.targets["t"].base_url == "http://x/v1"
