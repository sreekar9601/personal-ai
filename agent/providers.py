"""Resolve a task tier to a concrete model + provider-appropriate settings.

This is the only module that knows about `models.yaml`. Everything else asks
for a tier ("cheap" | "default" | "strong") and gets back a model string and a
ModelSettings object with caching enabled where the provider supports it.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

import yaml
from pydantic_ai import ModelSettings

from . import config

Tier = Literal["cheap", "default", "strong"]

_MODELS_YAML = config.AGENT_DIR / "models.yaml"


@lru_cache(maxsize=1)
def _cfg() -> dict:
    with open(_MODELS_YAML) as f:
        return yaml.safe_load(f)


def provider_name() -> str:
    return _cfg().get("provider", "anthropic")


def model_for(tier: Tier) -> str:
    """Return the Pydantic AI model string for a tier, e.g. 'anthropic:claude-...'."""
    tiers = _cfg()["tiers"]
    if tier not in tiers:
        raise KeyError(f"Unknown tier {tier!r}; known: {list(tiers)}")
    return tiers[tier]


def settings_for(tier: Tier, *, max_tokens: int = 4096) -> ModelSettings:
    """Build ModelSettings for a tier.

    Caching is the single biggest cost lever, so we turn it on for the stable
    prefix (instructions + tool definitions). It is configured per-provider;
    here we wire the Anthropic flags and degrade gracefully for others.
    """
    base: dict = {"max_tokens": max_tokens}
    if provider_name() == "anthropic":
        # Cache the static prefix: AGENT.md/memory live in `instructions`, and
        # tool schemas are stable. Keep the prefix static-first so it stays hot.
        base["anthropic_cache_instructions"] = True
        base["anthropic_cache_tool_definitions"] = True
    return ModelSettings(**base)
