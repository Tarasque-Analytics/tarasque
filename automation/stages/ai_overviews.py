"""
ai_overviews.py — Stage 4: AI overviews → ai_overview (PLAN §2, §8).

Generates a natural-language overview per security from the uploaded model outputs, via a
**provider/model-agnostic** LLM abstraction (kickoff decision). Claude is the first provider tested;
others plug in through the registry (providers/llm.py). Each provider owns its own "workflow" (prompt
template / message formatting) but consumes a relatively similar `OverviewInput` and returns a
relatively similar `OverviewOutput` mapping onto the ai_overview columns.

**Cost control (PLAN §8.2 — LLM tokens are the priciest per-call resource):**
  - only securities with a NEW model output today (freshness.securities_needing_overview)
  - content-hash cache: skip the call if an equivalent (security_id, model_ver, prompt_ver, hash)
    overview already exists
  - model_ver/prompt_ver on every row → switching models writes new rows, never collides
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .base import Stage

if TYPE_CHECKING:
    from ..context import RunContext
    from ..logging_utils import StageReport


class AiOverviewsStage(Stage):
    name = "ai_overviews"
    depends_on = ("upload_outputs",)
    critical = False   # a missing overview must not roll back prices/options/model writes (PLAN §9.2)

    async def is_stale(self, ctx: "RunContext") -> bool:
        """
        TODO(PLAN §3.1, §8): targets = await securities_needing_overview(ctx); return bool(targets)
        (or True if ctx.force).
        """
        raise NotImplementedError

    async def run(self, ctx: "RunContext") -> "StageReport":
        """
        TODO(PLAN §8):
          - targets = await securities_needing_overview(ctx)         # new model output today
          - provider = get_llm_provider(ctx.config.llm)              # registry lookup; Claude first
          - for each target:
                ov_input = build_overview_input(security)            # standardized, provider-independent
                h = content_hash(ov_input)
                if await ctx.db.overview_exists(sid, model_ver, prompt_ver, h): skip   # cache hit (§8.2)
                in dry_run: count would-be calls + est. tokens/cost; DO NOT call the LLM
                out = await provider.generate(ov_input)              # OverviewOutput
                await ctx.db.insert_ai_overview({security_id, model_ver, prompt_ver, headline,
                                                 content, content_hash=h})            # dedup-aware (§8.2)
          - (later) enforce ctx.config.llm.max_overview_tokens budget ceiling (PLAN §9.3)
          - isolate per-security failures; tally generated/cached/failed → StageReport
        """
        raise NotImplementedError("TODO(PLAN §8): provider-agnostic overview generation + dedupe")
