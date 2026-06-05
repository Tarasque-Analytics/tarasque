"""
merge_cadence_to_canonical.py — Splice cadence_experiment outputs into canonical
                                per-ticker prediction files.

Takes outputs from `cadence_experiment --mode fixed --step-days N` (which live
at `results/cadence_experiment/step_<N>/predictions_<TICKER>.csv`) and merges
their extension-period rows into the canonical
`results/predictions_<TICKER>.csv` files. Backtest-period rows (dates before
EXTENSION_START) are preserved untouched.

This makes `cadence_experiment` a drop-in replacement for `extend_predictions`
in the weekly pipeline. The downstream steps (`rebuild_aggregates`,
`mz_overlay`, `export_for_webapp`) all read from the canonical predictions
files, so once the merge is done they pick up the new cadence transparently.

Usage:
    python -m model.pipeline.scripts.merge_cadence_to_canonical --step-days 20
    python -m model.pipeline.scripts.merge_cadence_to_canonical --step-days 20 --dry-run
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from model.pipeline.config import load_config

EXTENSION_START = pd.Timestamp('2025-10-29')


def merge_one(canonical_path: Path, cadence_path: Path, dry_run: bool = False) -> dict:
    if not cadence_path.exists():
        return {'status': 'skip', 'reason': 'no cadence output'}
    if not canonical_path.exists():
        return {'status': 'skip', 'reason': 'no canonical predictions file'}

    canon = pd.read_csv(canonical_path, parse_dates=['date'])
    cad   = pd.read_csv(cadence_path,   parse_dates=['date'])

    # Strip cadence-experiment-only metadata cols if present
    drop_cols = [c for c in ['model_age_bd', 'retrain_date'] if c in cad.columns]
    if drop_cols:
        cad = cad.drop(columns=drop_cols)

    # Make column sets line up — canon has y_pred_q15, cad may not
    if 'y_pred_q15' in canon.columns and 'y_pred_q15' not in cad.columns:
        cad['y_pred_q15'] = float('nan')
    # Drop any cad columns canon doesn't have (defensive)
    cad = cad[[c for c in cad.columns if c in canon.columns]]
    # Ensure canon column order
    cad = cad.reindex(columns=canon.columns)

    # Keep canon rows from before extension; replace extension rows with cad.
    pre_ext = canon[canon['date'] <= EXTENSION_START]
    new_ext = cad[cad['date'] > EXTENSION_START]
    merged = pd.concat([pre_ext, new_ext], ignore_index=True)
    merged = merged.drop_duplicates(subset=['date', 'horizon'], keep='last')
    merged = merged.sort_values(['horizon', 'date']).reset_index(drop=True)

    if dry_run:
        return {'status': 'dry_run', 'pre_ext_rows': len(pre_ext),
                'new_ext_rows': len(new_ext), 'total': len(merged),
                'canon_total_before': len(canon)}

    merged.to_csv(canonical_path, index=False)
    return {'status': 'ok', 'pre_ext_rows': len(pre_ext),
            'new_ext_rows': len(new_ext), 'total': len(merged),
            'canon_total_before': len(canon)}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--step-days', type=int, required=True,
                   help='Cadence step_days that produced the source data')
    p.add_argument('--tickers', nargs='*', default=None,
                   help='Subset (default: all tickers found in cadence dir)')
    p.add_argument('--dry-run', action='store_true')
    args = p.parse_args()

    _, _, bc = load_config()
    cad_dir   = bc.results_dir / 'cadence_experiment' / f'step_{args.step_days}'
    canon_dir = bc.results_dir

    if not cad_dir.exists():
        print(f'[MERGE] Cadence dir not found: {cad_dir}')
        return 1

    if args.tickers:
        tickers = args.tickers
    else:
        tickers = sorted(f.stem.replace('predictions_', '')
                         for f in cad_dir.glob('predictions_*.csv'))

    print(f'[MERGE] step_days={args.step_days} | {len(tickers)} ticker(s) '
          f'| dry_run={args.dry_run}')

    n_ok = n_skip = 0
    total_new_ext = 0
    for t in tickers:
        cad_path   = cad_dir   / f'predictions_{t}.csv'
        canon_path = canon_dir / f'predictions_{t}.csv'
        r = merge_one(canon_path, cad_path, dry_run=args.dry_run)
        if r['status'] in ('ok', 'dry_run'):
            n_ok += 1
            total_new_ext += r['new_ext_rows']
            print(f'  [{t}] {r["status"]}: pre={r["pre_ext_rows"]} '
                  f'+ ext={r["new_ext_rows"]} = {r["total"]} '
                  f'(was {r["canon_total_before"]})')
        else:
            n_skip += 1
            print(f'  [{t}] skip: {r["reason"]}')

    print(f'\n[MERGE] Done. {n_ok} merged, {n_skip} skipped. '
          f'Total new extension rows: {total_new_ext:,}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
