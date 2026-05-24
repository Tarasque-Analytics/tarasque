"""
test_daily_append.py — End-to-end integration test for the Supabase ETL.

Exercises the full daily-append lifecycle against a real Supabase project:
  1. Verify schema is ready (migration 001 applied)
  2. Push AAPL full history to Supabase (--push-to-supabase, no --append-only)
  3. Verify row count matches the local CSV
  4. Simulate next-day inference by appending one synthetic row to the CSV
  5. Run --push-to-supabase --append-only
  6. Verify only ONE new row was inserted
  7. Verify idempotency: run --append-only again, confirm zero new rows
  8. Print pass/fail summary

Run modes:
  --dry-run            : log operations without writing (default)
  --live               : actually write to Supabase (requires creds in .env)
  --ticker TICKER      : use a different ticker for testing (default: AAPL)
  --cleanup            : remove the test rows after pass/fail

Designed to be run on a test Supabase project, OR with a dedicated test
ticker on prod that gets cleaned up afterward.
"""
from __future__ import annotations
import argparse
import sys
import time
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from .db import SupabaseClient
from .export_for_webapp import (
    EXPORT_DIR, TICKERS_DIR,
    export_one_ticker, push_ticker_to_supabase,
)


def banner(text: str):
    print('\n' + '=' * 72)
    print(f'  {text}')
    print('=' * 72)


def count_vol_rows(db: SupabaseClient, security_id: int) -> int:
    """Count rows in volatility_history for a security."""
    if db.dry_run:
        return -1
    result = (
        db.client.table('volatility_history')
        .select('date', count='exact')
        .eq('security_id', security_id)
        .execute()
    )
    return result.count or 0


def cleanup_test_ticker(db: SupabaseClient, security_id: int):
    """Remove all rows for security_id from time-series tables.
    For test isolation; do NOT run against production data without scope."""
    if db.dry_run:
        print('  [cleanup] dry-run: would delete rows')
        return
    db.client.table('volatility_history').delete().eq('security_id', security_id).execute()
    db.client.table('prices_history').delete().eq('security_id', security_id).execute()
    print(f'  [cleanup] Removed all rows for security_id={security_id}')


def synth_next_day_row(df: pd.DataFrame) -> pd.DataFrame:
    """Append one synthetic row dated +1 trading day after the last row,
    with plausible values derived from the last row + small jitter."""
    last = df.iloc[-1].copy()
    next_date = pd.to_datetime(last['date']) + pd.Timedelta(days=1)
    # Skip weekends
    while next_date.dayofweek >= 5:
        next_date += pd.Timedelta(days=1)

    rng = np.random.default_rng(seed=42)
    jitter = 1 + rng.normal(0, 0.005, len(df.columns))
    new_row = last.copy()
    new_row['date'] = next_date.strftime('%Y-%m-%d')
    for col in ['open', 'high', 'low', 'close', 'adj_close']:
        if col in new_row.index and pd.notna(new_row[col]):
            new_row[col] = round(float(new_row[col]) * float(jitter[df.columns.get_loc(col)]), 4)
    for col in ['rv', 'iv_atm_30d', 'vrp_wedge', 'vrp_wedge_ewma_21d',
                'pfv_21', 'pfv_63', 'pfv_126',
                'pfv_q15_21', 'pfv_q15_63', 'pfv_q15_126',
                'pfv_cal_21', 'pfv_cal_63', 'pfv_cal_126']:
        if col in new_row.index and pd.notna(new_row[col]):
            new_row[col] = round(float(new_row[col]) * float(jitter[df.columns.get_loc(col)]), 6)

    return pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--dry-run', action='store_true', default=True,
                   help='log operations without writing (default)')
    p.add_argument('--live', action='store_true',
                   help='actually write to Supabase')
    p.add_argument('--ticker', default='AAPL',
                   help='test ticker (default: AAPL)')
    p.add_argument('--cleanup', action='store_true',
                   help='remove test rows after the run')
    p.add_argument('--run-id', type=int, default=999,
                   help='model_run_id to use for test rows (default: 999)')
    args = p.parse_args()

    # --live overrides --dry-run
    dry_run = not args.live

    banner(f'Tarasque  Daily Append Integration Test  (ticker={args.ticker}, '
           f'mode={"dry-run" if dry_run else "LIVE"})')

    db = SupabaseClient(dry_run=dry_run)

    # ── Step 1: Verify schema ─────────────────────────────────────────────
    banner('STEP 1 — Verify schema')
    if not dry_run:
        try:
            missing = db.verify_schema()
            if missing:
                print(f'\nSchema gaps: {missing}')
                print('Apply migration 001_supabase_schema_fixes.sql before continuing.')
                sys.exit(2)
        except Exception as e:
            print(f'FATAL: schema verification failed: {e}')
            sys.exit(2)
    else:
        print('  (skipped in dry-run mode)')

    # ── Step 2: Resolve security_id ────────────────────────────────────────
    banner(f'STEP 2 — Lookup security_id for {args.ticker}')
    security_id = None
    if not dry_run:
        security_id = db.get_security_id(args.ticker)
        if security_id is None:
            print(f'FATAL: {args.ticker} not found in securities table. '
                  f'Insert a row for it first.')
            sys.exit(2)
        print(f'  security_id={security_id}')
    else:
        print(f'  (dry-run) would look up security_id for {args.ticker}')
        security_id = -1

    # ── Step 3: Full upload ───────────────────────────────────────────────
    banner('STEP 3 — Full corpus upload (no --append-only)')
    csv_path = TICKERS_DIR / f'predictions_{args.ticker}.csv'
    if not csv_path.exists():
        print(f'  Per-ticker CSV not found. Generating via export_for_webapp...')
        export_one_ticker(args.ticker, run_id=args.run_id)
    full_df = pd.read_csv(csv_path)
    print(f'  Local CSV: {len(full_df):,} rows')

    push_ticker_to_supabase(db, args.ticker, full_df, run_id=args.run_id, append_only=False)

    if not dry_run:
        time.sleep(2)  # let writes propagate
        db_count = count_vol_rows(db, security_id)
        if db_count == len(full_df):
            print(f'  PASS: DB count ({db_count:,}) matches CSV count ({len(full_df):,})')
        else:
            print(f'  FAIL: DB count ({db_count}) != CSV count ({len(full_df)})')

    # ── Step 4: Simulate next-day inference ────────────────────────────────
    banner('STEP 4 — Simulate next-day inference')
    augmented = synth_next_day_row(full_df)
    new_date = augmented['date'].iloc[-1]
    print(f'  Synthesized new row dated {new_date}')
    print(f'  CSV now has {len(augmented):,} rows (was {len(full_df):,})')

    # ── Step 5: Append-only run ────────────────────────────────────────────
    banner('STEP 5 — Run with --append-only (should add 1 new row only)')
    push_ticker_to_supabase(db, args.ticker, augmented, run_id=args.run_id, append_only=True)

    if not dry_run:
        time.sleep(2)
        db_count = count_vol_rows(db, security_id)
        if db_count == len(full_df) + 1:
            print(f'  PASS: DB count ({db_count:,}) is full + 1 ({len(full_df)+1:,})')
        else:
            print(f'  FAIL: DB count ({db_count}) != expected ({len(full_df)+1})')

    # ── Step 6: Idempotency check ──────────────────────────────────────────
    banner('STEP 6 — Re-run append-only (should add 0 new rows)')
    push_ticker_to_supabase(db, args.ticker, augmented, run_id=args.run_id, append_only=True)

    if not dry_run:
        time.sleep(2)
        db_count = count_vol_rows(db, security_id)
        if db_count == len(full_df) + 1:
            print(f'  PASS: DB count unchanged ({db_count:,}), upserts idempotent')
        else:
            print(f'  FAIL: DB count changed to {db_count} on rerun (idempotency broken)')

    # ── Cleanup ────────────────────────────────────────────────────────────
    if args.cleanup and not dry_run:
        banner('CLEANUP — removing test rows')
        cleanup_test_ticker(db, security_id)

    banner('Integration test complete')


if __name__ == '__main__':
    main()
