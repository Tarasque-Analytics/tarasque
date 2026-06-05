"""
fetch_prices.py — Stage 1a: stock bars → prices_history (PLAN §2, §3.1, §4).

**Append-only & incremental.** For each active security, fetch only the bars *after* the latest
stored date (`prices_history` MAX(date) per security), never re-pulling old history. New listings
backfill from `securities.min_history_date`. Upsert on PK (security_id, date) so re-runs can't dupe.

Source: Alpaca stock bars (PLAN §1 / §5). Runs concurrently with fetch_options (1b).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .base import Stage

if TYPE_CHECKING:
    from ..context import RunContext
    from ..logging_utils import StageReport


class FetchPricesStage(Stage):
    name = "fetch_prices"
    depends_on = ("ensure_universe",)
    critical = True   # the model + everything downstream needs current prices

    async def is_stale(self, ctx: "RunContext") -> bool:
        """
        Stale if any active security's latest stored bar predates the run's business date.

        TODO(PLAN §3.1): plan = await plan_price_fetch(ctx, security_ids); return plan.n_to_fetch > 0
        (or True if ctx.force).
        """
        raise NotImplementedError

    async def run(self, ctx: "RunContext") -> "StageReport":
        """
        TODO(PLAN §3.1, §4, §5):
          - plan = await plan_price_fetch(ctx, security_ids)          # per-security 'fetch since' cursor
          - provider = AlpacaProvider(ctx.config.alpaca)
          - fan out per security (bounded concurrency), fetch bars since cursor → app row shape
              {security_id, date, open, high, low, close, adj_close, volume}
          - in dry_run: log the per-security gap sizes and return SKIPPED/SUCCESS without calls
          - await ctx.db.upsert_prices(rows)                          # on_conflict security_id,date
          - isolate per-ticker failures; tally written/skipped/failed → StageReport
        """
        raise NotImplementedError("TODO(PLAN §3.1): incremental price fetch + upsert")
