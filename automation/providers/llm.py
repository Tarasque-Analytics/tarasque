"""
llm.py — provider/model-agnostic LLM abstraction for AI overviews (PLAN §8).

Design goal (kickoff decision): be able to swap models freely. Every provider consumes a relatively
similar **OverviewInput** and returns a relatively similar **OverviewOutput**, so the `ai_overviews`
stage and the `ai_overview` table are provider-independent. Each provider may run its own internal
"workflow" (prompt template, message formatting, tool use) — that variation is hidden behind
`generate()`.

A small **registry** maps a provider name (config.llm.provider) to its class. Claude is the first
provider; others (OpenAI, etc.) implement the same protocol and register themselves.

Vendor SDKs (anthropic, ...) are imported lazily inside providers so `import automation` is dep-free.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional, Protocol

if TYPE_CHECKING:
    from ..config import LLMConfig


# ── shared contract (the "relatively similar" in/out — PLAN §8.1) ─────────────────────────────────
@dataclass
class OverviewInput:
    """
    Standardized, provider-independent bundle for one security, assembled from uploaded model outputs.
    This is the data EVERY provider workflow receives — keep it provider-neutral.
    """

    ticker: str
    sector: Optional[str] = None
    forecast_rv: dict[str, float] = field(default_factory=dict)   # {"21": .., "63": .., "126": ..}
    vrp_wedge: Optional[float] = None
    vrp_percentile_1y: Optional[float] = None
    vol_regime: Optional[str] = None
    risk_tier: Optional[str] = None
    top_shap_drivers: list[dict[str, Any]] = field(default_factory=list)   # empty until SHAP exists (§7.5.2)
    extra: dict[str, Any] = field(default_factory=dict)            # provider-neutral escape hatch


@dataclass
class OverviewOutput:
    """
    Standardized result, mapping straight onto ai_overview columns. Every provider returns this shape.
    """

    headline: str
    content: dict[str, Any]      # jsonb body (sections/bullets/etc.)
    model_ver: str               # provider-specific model id → ai_overview.model_ver
    prompt_ver: str              # prompt/spec version → ai_overview.prompt_ver
    usage: dict[str, Any] = field(default_factory=dict)   # tokens/cost for budget tracking (§9.3)


class LLMProvider(Protocol):
    """The interface the ai_overviews stage depends on."""

    async def generate(self, payload: "OverviewInput") -> "OverviewOutput":
        """Run this provider's workflow and return the standardized output."""
        ...


# ── concrete providers ────────────────────────────────────────────────────────────────────────────
class ClaudeProvider:
    """Anthropic Claude implementation (first provider tested — PLAN §8)."""

    def __init__(self, config: "LLMConfig") -> None:
        self._config = config
        self._client: Optional[Any] = None

    @property
    def client(self) -> Any:
        """TODO(PLAN §8): lazily build the Anthropic client from config.anthropic_api_key."""
        raise NotImplementedError

    async def generate(self, payload: "OverviewInput") -> "OverviewOutput":
        """
        TODO(PLAN §8):
          - render this provider's prompt from `payload` (its own "workflow"; versioned by prompt_ver)
          - call the Anthropic Messages API (enable prompt caching per the claude-api guidance)
          - parse the response into OverviewOutput(headline, content, model_ver=config.model,
            prompt_ver=config.prompt_ver, usage=...)
        """
        raise NotImplementedError("TODO(PLAN §8): Claude overview workflow")


# ── registry (PLAN §8.1) ──────────────────────────────────────────────────────────────────────────
# name → provider class. Add new providers here; selection is via config.llm.provider.
_REGISTRY: dict[str, type] = {
    "claude": ClaudeProvider,
    # "openai": OpenAIProvider,   # implement the same protocol, then register
}


def get_llm_provider(config: "LLMConfig") -> "LLMProvider":
    """
    Resolve the configured provider from the registry.

    TODO(PLAN §8): look up config.provider in _REGISTRY (clear error if unknown) and return an
    instance constructed with `config`.
    """
    raise NotImplementedError("TODO(PLAN §8): registry lookup → provider instance")


def content_hash(payload: "OverviewInput") -> str:
    """
    Stable hash of the overview inputs, for the content-hash cache (PLAN §8.2). Re-running with
    unchanged inputs must produce the same hash so the LLM call is skipped.

    TODO: canonical-serialize the salient fields (exclude volatile bits) and sha256 them.
    """
    raise NotImplementedError("TODO(PLAN §8.2): deterministic content hash")
