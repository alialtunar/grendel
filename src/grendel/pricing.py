"""Illustrative price table + cost estimation for token usage.

The numbers here are placeholders, not authoritative pricing. Adding a model is a
one-line edit to ``PRICES``; an unknown ``(provider, model)`` costs ``0.0`` so a run
never fails for lack of a price.
"""

from __future__ import annotations

from .records import TokenUsage

# (provider) -> {model -> (input_per_1k, output_per_1k)} in USD. Illustrative placeholders.
PRICES: dict[str, dict[str, tuple[float, float]]] = {
    "openai": {
        "gpt-4o-mini": (0.00015, 0.00060),
        "gpt-4o": (0.00250, 0.01000),
    },
    "anthropic": {
        "claude-3-5-haiku": (0.00080, 0.00400),
        "claude-3-5-sonnet": (0.00300, 0.01500),
    },
    # ollama / openai-compatible: local/unknown -> not listed -> cost 0.0
}


def estimate_cost(provider: str, model: str, usage: TokenUsage) -> tuple[float, bool]:
    """Return ``(cost_usd, known)``. Unknown ``(provider, model)`` -> ``(0.0, False)``."""
    entry = PRICES.get(provider, {}).get(model)
    if entry is None:
        return 0.0, False
    input_per_1k, output_per_1k = entry
    cost = (usage.prompt_tokens / 1000.0) * input_per_1k + (
        usage.completion_tokens / 1000.0
    ) * output_per_1k
    return cost, True
