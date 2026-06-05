"""
universe.py — resolve the run's equity universe (PLAN §10).

Source of truth is the **`securities.active`** flag: each run operates over the securities rows where
`active = true`. Adding/removing a name is a DB edit (toggle `active`, set `excluded_reason`), keeping
the pipeline, the model's universe, and the app's served set consistent without code changes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .context import RunContext


@dataclass(frozen=True)
class Security:
    """A single member of the active universe."""

    security_id: int
    ticker: str
    gics_sector: str | None = None
    sector_etf: str | None = None
    min_history_date: str | None = None   # ISO date; backfill floor for new listings (PLAN §3.1)


async def resolve_active_universe(ctx: "RunContext") -> list[Security]:
    """
    Return the active universe for this run, ordered deterministically (by ticker) so logs/retries
    are stable.

    TODO(PLAN §10):
      - rows = await ctx.db.active_universe()   # securities where active = true
      - map rows → Security; sort by ticker
      - if empty, log a clear warning (a misconfigured universe would otherwise silently no-op)
    """
    raise NotImplementedError


# NOTE: reconciling this DB-driven universe with the model's own `model/pipeline/config.py` ticker
# list is an open coordination item (PLAN §10, §13) — the model dev owns that list today.
