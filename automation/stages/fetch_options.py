"""
fetch_options.py — Stage 1b: options chain → options_chain (PLAN §2, §3.1, §4.3).

A **point-in-time daily snapshot**. For each active security, if today's snapshot
(`options_chain.snapshot_date == run_date`) already exists, **skip** it; otherwise fetch one fresh
snapshot. Upsert on the unique tuple (security_id, snapshot_date, expiry, option_type, strike) so a
same-day re-run overwrites in place — no duplicates.

⚠ **This is the heaviest market-data call (PLAN §4.3).** Scope aggressively: only the active
universe, and only the expiries/strike-band the model + frontend need (config: option_max_dte,
option_strike_band_pct). The exact expiry set tied to the model's IV term points is a TODO with the
model dev (PLAN §7.5.4).

Source: Alpaca options (OPRA). Runs concurrently with fetch_prices (1a).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .base import Stage

if TYPE_CHECKING:
    from ..context import RunContext
    from ..logging_utils import StageReport


class FetchOptionsStage(Stage):
    name = "fetch_options"
    depends_on = ("ensure_universe",)
    critical = False   # IV is valuable but a missing chain shouldn't necessarily abort the run

    async def is_stale(self, ctx: "RunContext") -> bool:
        """
        Stale if any active security lacks today's snapshot.

        TODO(PLAN §3.1): plan = await plan_options_fetch(ctx, security_ids); return plan.n_to_fetch > 0
        (or True if ctx.force).
        """
        raise NotImplementedError

    async def run(self, ctx: "RunContext") -> "StageReport":
        """
        TODO(PLAN §3.1, §4.3, §5):
          - plan = await plan_options_fetch(ctx, security_ids)   # securities still needing today's snapshot
          - provider = AlpacaProvider(ctx.config.alpaca)
          - per security (bounded concurrency), fetch the scoped chain (DTE ≤ option_max_dte,
            strikes within ±option_strike_band_pct of spot) → rows shaped as options_chain:
              {security_id, snapshot_date=run_date, expiry, strike, option_type('C'/'P'),
               bid, ask, mid, last, volume, open_interest, iv, delta}
          - in dry_run: log how many securities would be fetched (and the saved calls) — no calls
          - await ctx.db.upsert_options_chain(rows)              # on_conflict on the 5-col unique tuple
          - isolate per-ticker failures; tally → StageReport
        NOTE: rate-limit/backoff lives in the provider (PLAN §5).
        """
        raise NotImplementedError("TODO(PLAN §4.3): scoped daily options snapshot + upsert")
