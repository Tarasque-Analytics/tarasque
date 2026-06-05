"""
freshness.py — DB-derived incrementality decisions (PLAN §3).

The single principle: **freshness is derived from existing DB signals**, never from a separate state
store. Each helper answers "given what's already in the DB, what is the delta this run must do?" so
stages fetch/compute only what's stale and skip what isn't — minimizing expensive calls (PLAN §4.3).

`force=True` (from config) makes every check report "stale" to re-run everything.

These are thin planners over `WriteClient`'s freshness reads — they hold the *policy*, the client
holds the *SQL*. Nothing here makes market-data/LLM/model calls.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .context import RunContext


@dataclass
class PriceFetchPlan:
    """Per-security append cursor for fetch_prices (PLAN §3.1, append-only)."""

    # security_id → the date to fetch bars AFTER (None ⇒ backfill from securities.min_history_date).
    fetch_since: dict[int, Optional[date]]

    @property
    def n_to_fetch(self) -> int:
        return len(self.fetch_since)


@dataclass
class OptionsFetchPlan:
    """Which securities still need today's options snapshot (PLAN §3.1, skip-if-done)."""

    security_ids: list[int]        # those WITHOUT a snapshot for run_date
    snapshot_date: date

    @property
    def n_to_fetch(self) -> int:
        return len(self.security_ids)


async def plan_price_fetch(ctx: "RunContext", security_ids: list[int]) -> PriceFetchPlan:
    """
    Build the per-security price append cursor from prices_history MAX(date).

    TODO(PLAN §3.1):
      - cursors = await ctx.db.latest_price_date(security_ids)
      - for new listings (None), fall back to securities.min_history_date
      - if ctx.force: set every cursor to None (full backfill) or a configured floor
    """
    raise NotImplementedError


async def plan_options_fetch(ctx: "RunContext", security_ids: list[int]) -> OptionsFetchPlan:
    """
    Determine which securities still need today's options snapshot.

    TODO(PLAN §3.1, §4.3):
      - done = await ctx.db.options_snapshot_exists(security_ids, ctx.run_date)
      - return those NOT done (or all, if ctx.force)
    """
    raise NotImplementedError


async def should_run_model(ctx: "RunContext", model_version: str) -> bool:
    """
    Whether the model needs to run today (skip if model_runs already has today's row).

    TODO(PLAN §3.1):
      - if ctx.force: return True
      - return not await ctx.db.model_run_exists(ctx.run_date, model_version)
    """
    raise NotImplementedError


async def securities_needing_overview(ctx: "RunContext") -> set[int]:
    """
    The set of securities with a NEW model output today that should get an AI overview.

    TODO(PLAN §3.1, §8):
      - start from securities that got a fresh volatility_history row for run_date
        (await ctx.db.volatility_rows_for_date(ctx.run_date))
      - content-hash dedupe happens at call time in the ai_overviews stage (overview_exists)
    """
    raise NotImplementedError
