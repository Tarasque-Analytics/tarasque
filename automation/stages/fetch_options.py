"""
fetch_options.py — Stage 1b: options chain → options_chain (OPTIONS_IMPORT_PLAN.md; PLAN §2, §3.1).

A **point-in-time daily snapshot**. For each active security, if today's snapshot
(`options_chain.snapshot_date == run_date`) already exists, **skip** it; otherwise fetch one fresh
snapshot. Upsert on the unique tuple (security_id, snapshot_date, expiry, option_type, strike) so a
same-day re-run overwrites in place — no duplicates.

Source: **yfinance** (current-day chain; OPTIONS_IMPORT_PLAN.md supersedes PLAN.md's Alpaca-for-options
assumption — Alpaca has no OI/volume). Scoped to a few expiries (30/60/90/180 DTE + front monthlies)
and a strike band, so the call stays cheap. `delta` is computed in-house (Black-Scholes).

Reuses the exact core (`automation.options_import`) the standalone CLI uses — same behavior, one
implementation. Runs concurrently with fetch_prices (1a) in the DAG.
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

from .base import Stage

if TYPE_CHECKING:
    from ..context import RunContext
    from ..logging_utils import StageReport


class FetchOptionsStage(Stage):
    name = "fetch_options"
    depends_on = ("ensure_universe",)
    critical = False   # IV/chain is valuable but a missing chain shouldn't abort the whole run

    async def is_stale(self, ctx: "RunContext") -> bool:
        """Stale if any active security lacks today's snapshot (or always, under --force)."""
        if ctx.force:
            return True
        universe = await ctx.db.active_universe()
        ids = [row["security_id"] for row in universe]
        if not ids:
            return False
        exists = await ctx.db.options_snapshot_exists(ids, ctx.run_date)
        return any(not present for present in exists.values())

    async def run(self, ctx: "RunContext") -> "StageReport":
        """
        Import the day's options snapshot for the active universe, isolating per-ticker failures so
        one bad ticker can't sink the stage (PLAN §9.2).
        """
        from ..logging_utils import StageReport, StageStatus
        from ..options_import import import_options_for_security, make_options_provider

        started = time.monotonic()
        universe = await ctx.db.active_universe()
        provider = make_options_provider(ctx.config.options)

        rows_written = n_skipped = n_failed = 0
        for row in universe:
            res = await import_options_for_security(
                ctx.db, provider,
                ticker=str(row["ticker"]).upper(),
                security_id=row["security_id"],
                snapshot_date=ctx.run_date,
                config=ctx.config.options,
                force=ctx.force,
                dry_run=ctx.dry_run,
            )
            if res.error:
                n_failed += 1
            elif res.skipped:
                n_skipped += 1
            else:
                rows_written += res.rows_written

        n = len(universe)
        if n == 0:
            status = StageStatus.SKIPPED
        elif n_failed == 0:
            status = StageStatus.SUCCESS
        elif n_failed >= max(1, int(n * ctx.config.stage_failure_threshold)):
            status = StageStatus.FAILED
        else:
            status = StageStatus.PARTIAL

        return StageReport(
            stage=self.name,
            status=status,
            rows_written=rows_written,
            n_securities=n,
            n_skipped=n_skipped,
            n_failed=n_failed,
            duration_seconds=time.monotonic() - started,
            meta={"provider": ctx.config.options.provider},
        )
