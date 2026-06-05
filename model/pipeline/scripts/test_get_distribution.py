"""Smoke-test the get_distribution() RPC against live Supabase.

Run AFTER applying model/sql/migrations/005_get_distribution_rpc.sql.

Usage:
    python -m model.pipeline.scripts.test_get_distribution
    python -m model.pipeline.scripts.test_get_distribution --ticker MSFT --metric vrp_wedge
"""
from __future__ import annotations

import argparse
import sys

import pandas as pd
from dotenv import load_dotenv

from model.pipeline.db import SupabaseClient


def main() -> int:
    load_dotenv('model/.env')

    p = argparse.ArgumentParser()
    p.add_argument('--ticker', default='AAPL')
    p.add_argument('--metric', default='rv',
                   help='volatility_history column to bin (rv, iv_atm_30d, vrp_wedge, pfv_cal_21, ...)')
    p.add_argument('--lookback', type=int, default=1260)
    args = p.parse_args()

    db = SupabaseClient()
    security_id = db.get_security_id(args.ticker)
    if security_id is None:
        print(f'[!] {args.ticker} not in securities table')
        return 1

    print(f'[i] {args.ticker} → security_id={security_id}, '
          f'metric={args.metric}, lookback={args.lookback}d')

    result = db.client.rpc(
        'get_distribution',
        {
            'p_security_id': security_id,
            'p_metric': args.metric,
            'p_lookback_days': args.lookback,
        },
    ).execute()

    rows = result.data or []
    if not rows:
        print('[!] RPC returned zero rows — check that the metric column has '
              f'data for {args.ticker} and the lookback window')
        return 1

    df = pd.DataFrame(rows)
    print(f'\n[i] {len(df)} rows returned, shape: {df.shape}')
    print(f'    columns: {list(df.columns)}')

    # Spec: ~30 bins × 3 scopes = ~90 rows
    counts = df.groupby('scope').size()
    print(f'\n[i] bins per scope:')
    print(counts.to_string())

    # Per-scope sanity
    for scope, sub in df.groupby('scope'):
        cur_val = sub['current_value'].iloc[0]
        pct = sub['current_percentile'].iloc[0]
        total = sub['count'].sum()
        lo, hi = sub['bin_low'].min(), sub['bin_high'].max()
        pct_str = f'{pct:.1f}%' if pd.notna(pct) else 'NULL'
        cur_str = f'{cur_val:.4f}' if pd.notna(cur_val) else 'NULL'
        print(f'\n  [{scope}] n_obs={total:,}  range=[{lo:.4f}, {hi:.4f}]  '
              f'current={cur_str} @ p{pct_str}')

    # Coherence check: current_value identical within each scope
    for scope, sub in df.groupby('scope'):
        if sub['current_value'].nunique(dropna=False) > 1:
            print(f'[!] BUG: current_value varies within {scope} scope')
            return 1
        if sub['current_percentile'].nunique(dropna=False) > 1:
            print(f'[!] BUG: current_percentile varies within {scope} scope')
            return 1

    # Sample rows
    print('\n[i] first 3 rows of stock scope:')
    print(df[df['scope'] == 'stock'].head(3).to_string(index=False))

    # Negative test: bad metric should raise
    print('\n[i] negative test: invalid metric should error...')
    try:
        db.client.rpc(
            'get_distribution',
            {'p_security_id': security_id, 'p_metric': 'definitely_not_a_column'},
        ).execute()
        print('[!] BUG: invalid metric did NOT raise')
        return 1
    except Exception as e:
        msg = str(e)
        if 'whitelist' in msg or 'not in' in msg:
            print(f'    OK — rejected with: {msg.splitlines()[0][:120]}')
        else:
            print(f'    rejected (unexpected message): {msg.splitlines()[0][:120]}')

    print('\n[OK] get_distribution() RPC is live and behaving sanely')
    return 0


if __name__ == '__main__':
    sys.exit(main())
