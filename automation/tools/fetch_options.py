"""
fetch_options.py — standalone options-chain importer (CLAUDE.md §5).

Fetches a scoped daily options snapshot from yfinance and upserts it into `options_chain`. Reuses the
exact core (`automation.options_import`) the pipeline's `fetch_options` stage uses, so the standalone
result matches the scheduled run.

Usage (call from repo root):

    # Fetch + print normalized rows, NO DB writes, no Supabase creds needed:
    python -m automation.tools.fetch_options --tickers AAPL MSFT --dry-run

    # Write to the configured Supabase (set SUPABASE_URL + SUPABASE_SECRET_KEY):
    python -m automation.tools.fetch_options --tickers AAPL MSFT

    # Re-fetch even if today's snapshot already exists:
    python -m automation.tools.fetch_options --tickers AAPL --force

Notes:
  - --dry-run still calls yfinance (free, read-only) so you can see the chain; it just skips DB writes
    and DB reads, so no Supabase credentials are required.
  - snapshot_date is the most recent trading session (data-derived, so a midnight run stamps the
    prior session, holiday-safe); override with --snapshot-date.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date, datetime, timedelta
from datetime import time as dt_time
from zoneinfo import ZoneInfo

from ..config import load_config
from ..db import WriteClient
from ..options_import import import_options_for_security, make_options_provider

DEFAULT_TICKERS = ["AAPL", "MSFT"]


def _computed_session_date(now_et: datetime) -> date:
    """Clock-based fallback for the trading session (used only if the data-derived lookup fails).

    Before today's market open (or on a weekend) the latest data is the previous trading day. NOT
    holiday-aware — that's why the data-derived `provider.latest_session_date()` is preferred.
    """
    d = now_et.date()
    if now_et.time() < dt_time(9, 30):  # before the 9:30 ET open → today's session has no data yet
        d -= timedelta(days=1)
    while d.weekday() >= 5:  # Sat/Sun → roll back to Friday
        d -= timedelta(days=1)
    return d


def _resolve_snapshot_date(args: argparse.Namespace, provider) -> date:
    """Resolve the trading session the snapshot belongs to.

    Priority: explicit --snapshot-date → the provider's latest *begun* session (data-derived, so a
    midnight run stamps yesterday's close as yesterday, and it's holiday-safe) → a clock-based
    fallback. Resolved once per run so every ticker shares one snapshot_date.
    """
    if args.snapshot_date:
        return datetime.strptime(args.snapshot_date, "%Y-%m-%d").date()
    try:
        derived = provider.latest_session_date()
    except Exception:  # noqa: BLE001 — date resolution must not crash the run; fall back to the clock
        derived = None
    return derived or _computed_session_date(datetime.now(ZoneInfo("America/New_York")))


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="python -m automation.tools.fetch_options",
        description="Standalone daily options-chain import (yfinance → options_chain).",
    )
    p.add_argument(
        "--tickers",
        nargs="+",
        default=DEFAULT_TICKERS,
        help=f"Tickers to import (default: {' '.join(DEFAULT_TICKERS)}).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch + print only; no DB writes/reads (no Supabase creds needed).",
    )
    p.add_argument(
        "--force", action="store_true", help="Re-fetch even if today's snapshot already exists."
    )
    p.add_argument(
        "--snapshot-date",
        default=None,
        help="Override the snapshot/business date (YYYY-MM-DD). Default: today US/Eastern.",
    )
    return p.parse_args(argv)


async def _run(args: argparse.Namespace) -> int:
    cfg = load_config(dry_run=args.dry_run, force=args.force)
    tickers = [t.upper() for t in args.tickers]

    provider = make_options_provider(cfg.options)
    snapshot_date = _resolve_snapshot_date(args, provider)
    db = WriteClient(cfg.supabase, dry_run=cfg.dry_run)
    await db.connect()

    mode = "DRY-RUN (no writes)" if cfg.dry_run else f"writing to {cfg.env} Supabase"
    print(f"[options] snapshot_date={snapshot_date}  tickers={tickers}  {mode}")

    n_ok = n_skip = n_err = 0
    try:
        # Resolve security_id from the DB (skipped in dry-run — uses a placeholder so the yfinance
        # fetch can still be demonstrated without Supabase).
        if cfg.dry_run:
            secmap = {t: 0 for t in tickers}
        else:
            secmap = await db.resolve_security_ids(tickers)

        for ticker in tickers:
            sid = secmap.get(ticker)
            if sid is None:
                print(f"  {ticker:6s} SKIP — not found in securities (cannot resolve security_id)")
                n_skip += 1
                continue

            res = await import_options_for_security(
                db,
                provider,
                ticker=ticker,
                security_id=sid,
                snapshot_date=snapshot_date,
                config=cfg.options,
                force=cfg.force,
                dry_run=cfg.dry_run,
            )

            if res.error:
                print(f"  {ticker:6s} ERROR — {res.error}")
                n_err += 1
            elif res.skipped:
                print(
                    f"  {ticker:6s} SKIP — today's snapshot already present (use --force to refetch)"
                )
                n_skip += 1
            else:
                spot = f"{res.spot:.2f}" if res.spot is not None else "n/a"
                exp = ", ".join(d.isoformat() for d in res.expiries)
                tail = f"contracts={res.n_contracts} written={res.rows_written}"
                print(f"  {ticker:6s} OK   — spot={spot} expiries=[{exp}] {tail}")
                n_ok += 1
    finally:
        await db.close()

    print(f"[options] done — ok={n_ok} skipped={n_skip} errors={n_err}")
    # Non-zero only if everything we attempted failed (so one bad ticker doesn't fail the run).
    return 1 if (n_err > 0 and n_ok == 0) else 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_run(_parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
