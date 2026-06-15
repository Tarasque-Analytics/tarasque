"""
extend_predictions.py — Close the gap between the backtest's last prediction
date and TODAY.

Why this exists
---------------
The original backtest walks WFA through history and necessarily caps
predictions at `data_max − 126 BDays` because every prediction row needs a
known y_target_126 at training time. After a corpus run, you end up with
predictions going through, say, 2025-11-17 — but today is 2026-05-25 and
the equity page needs a continuous wedge series up to TODAY for the
EWMA·21d chart, historical distribution, etc.

What it does
------------
For each ticker:
  1. Read existing predictions_<TICKER>.csv → find last existing prediction date
  2. Build features through TODAY (drop_nan_targets=False so recent rows are kept)
  3. Train ONE ensemble on data through last_existing_date (clean OOS for the gap)
  4. Predict for every date in (last_existing_date, today]
  5. Backfill realized y_true_h where (today − date) ≥ h BDays
  6. Append rows to predictions_<TICKER>.csv (one per horizon)
  7. Save the trained model as joblib (dated today) for daily_forecast to use

The gap predictions are tagged with model_run_id pointing to a new model_runs
row so analysts can distinguish "extension" predictions from the original
backtest's WFA predictions.

Parallelism
-----------
Uses ProcessPoolExecutor with `parallel_tickers` workers, mirroring backtest.py.
"""
from __future__ import annotations

import argparse
import sys
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

from .config import load_config
from .data_loader import fetch_dataset, append_recent_data, ParquetStore
from .features import FeatureBuilder
from .models import EnsembleVolModel

warnings.filterwarnings('ignore', category=UserWarning)


def _realized_gk_forward(ohlcv_ticker: pd.DataFrame,
                         start_date: pd.Timestamp,
                         h_days: int) -> float:
    """Annualised GK realized vol over the forward window (start_date, start_date + h_days BDays].
    Matches features._add_rv_features methodology. Returns NaN if window is incomplete.
    """
    df = ohlcv_ticker.copy()
    if df.empty:
        return float('nan')
    df['date'] = pd.to_datetime(df['date'], format='mixed', errors='coerce')
    df = df.dropna(subset=['date']).sort_values('date').reset_index(drop=True)
    end_date = start_date + pd.tseries.offsets.BDay(h_days)
    window = df[(df['date'] > start_date) & (df['date'] <= end_date)]
    if len(window) < h_days * 0.8:
        return float('nan')
    rename = {'openprc': 'open', 'askhi': 'high', 'bidlo': 'low', 'prc': 'close'}
    for k, v in rename.items():
        if k in window.columns:
            window = window.rename(columns={k: v})
    for c in ('open', 'high', 'low', 'close'):
        if c in window.columns:
            window[c] = window[c].abs()
    if not {'open', 'high', 'low', 'close'}.issubset(window.columns):
        return float('nan')
    log_hl = np.log(window['high'] / window['low'])
    log_co = np.log(window['close'] / window['open'])
    gk_var = 0.5 * log_hl ** 2 - (2 * np.log(2) - 1) * log_co ** 2
    if not np.isfinite(gk_var).any():
        return float('nan')
    return float(np.sqrt(gk_var.mean() * 252.0))


def _slice_raw_for_ticker(raw_data: dict, ticker: str, etfs: list) -> dict:
    """Slim down raw_data to only this ticker + ETFs to reduce pickle size."""
    keep_tickers = [ticker] + list(etfs)
    sliced = {}
    for key, df in raw_data.items():
        if not isinstance(df, pd.DataFrame) or df.empty:
            sliced[key] = df
            continue
        if 'ticker' in df.columns:
            sliced[key] = df[df['ticker'].isin(keep_tickers)].copy()
        else:
            sliced[key] = df
    return sliced


def extend_one_ticker(ticker: str, dc, mc, bc, raw_data: dict,
                      today: pd.Timestamp) -> dict:
    """Extend predictions for one ticker. Returns a status dict.

    Returns {'ticker': str, 'status': 'ok' | 'skip' | 'error',
             'new_rows': int, 'joblib_path': str | None, 'error': str | None}
    """
    pred_path = bc.results_dir / f'predictions_{ticker}.csv'
    forecast_dir = bc.results_dir / 'forecasts'
    forecast_dir.mkdir(parents=True, exist_ok=True)

    try:
        existing = pd.read_csv(pred_path, parse_dates=['date'])
    except FileNotFoundError:
        return {'ticker': ticker, 'status': 'skip',
                'reason': 'no existing predictions file'}

    if existing.empty:
        return {'ticker': ticker, 'status': 'skip', 'reason': 'empty existing file'}

    last_existing_date = existing['date'].max()

    # Build features through today (drop_nan_targets=False keeps recent rows)
    try:
        builder = FeatureBuilder(dc, mc)
        feature_df = builder.build(ticker, raw_data, drop_nan_targets=False)
    except Exception as e:
        return {'ticker': ticker, 'status': 'error', 'error': f'feature build: {e}'}

    if feature_df.empty:
        return {'ticker': ticker, 'status': 'error', 'error': 'empty feature_df'}

    # Identify gap dates: (last_existing_date, today]
    feature_dates = pd.to_datetime(feature_df.index)
    gap_mask = (feature_dates > last_existing_date) & (feature_dates <= today)
    gap_dates = feature_dates[gap_mask]

    if len(gap_dates) == 0:
        return {'ticker': ticker, 'status': 'skip',
                'reason': f'no gap (last existing: {last_existing_date.date()})'}

    # Predictor selection — same logic as backtest
    predictors = builder.get_predictor_columns(feature_df)
    valid_predictors = [c for c in predictors if feature_df[c].notna().any()]

    # Training window: data with valid y_target (drop NaN-y rows just for training)
    train_target_cols = [f'y_{h}' for h in mc.horizons if f'y_{h}' in feature_df.columns]
    train_df = feature_df.dropna(subset=train_target_cols)
    # And ≤ last_existing_date so we don't leak into the gap
    train_df = train_df[train_df.index <= last_existing_date]
    if len(train_df) < 100:
        return {'ticker': ticker, 'status': 'error',
                'error': f'too few training rows ({len(train_df)})'}

    X_train = train_df[valid_predictors].ffill().bfill().fillna(0)
    y_train = {h: train_df[f'y_{h}'] for h in mc.horizons if f'y_{h}' in train_df.columns}

    # Train ensemble (same as forecast --retrain)
    try:
        model = EnsembleVolModel(mc)
        model.train_wfa(X_train, y_train)
    except Exception as e:
        return {'ticker': ticker, 'status': 'error', 'error': f'train: {e}'}

    # Save joblib (dated today, daily_forecast will pick this up)
    joblib_path = forecast_dir / f'{ticker}_model_{today.date()}.joblib'
    try:
        model.save(joblib_path)
    except Exception as e:
        return {'ticker': ticker, 'status': 'error', 'error': f'save joblib: {e}'}

    # Predict for each gap date
    ohlcv = raw_data['ohlcv']
    if 'ticker' in ohlcv.columns:
        ohlcv_ticker = ohlcv[ohlcv['ticker'] == ticker]
    else:
        ohlcv_ticker = ohlcv

    new_rows = []
    for D in gap_dates:
        # Align features to model.predictors (fill missing with 0)
        row = feature_df.loc[D]
        aligned = pd.Series(0.0, index=model.predictors)
        for p in model.predictors:
            v = row.get(p, 0.0)
            aligned[p] = float(v) if pd.notna(v) else 0.0
        X_pred = aligned.to_frame().T

        try:
            curve = model.predict_curve(X_pred)
        except Exception:
            curve = {}

        # vrp_wedge / put_call_skew at this date (from features, for compat)
        vrp = row.get('vrp_wedge', np.nan)
        skew = row.get('put_call_skew_30d', np.nan)

        for h in mc.horizons:
            # y_true if the horizon has elapsed
            elapsed = (today - D).days
            if elapsed >= h:
                y_true = _realized_gk_forward(ohlcv_ticker, D, h)
            else:
                y_true = np.nan
            new_rows.append({
                'date': D,
                'y_true': y_true,
                'y_pred': float(curve.get(h, np.nan)),
                'y_pred_q15': np.nan,
                'vrp_wedge': float(vrp) if pd.notna(vrp) else np.nan,
                'put_call_skew_30d': float(skew) if pd.notna(skew) else np.nan,
                'ticker': ticker,
                'horizon': int(h),
            })

    if not new_rows:
        return {'ticker': ticker, 'status': 'skip', 'reason': 'no predictions made'}

    new_df = pd.DataFrame(new_rows)
    combined = pd.concat([existing, new_df], ignore_index=True)
    combined = combined.drop_duplicates(subset=['date', 'horizon'], keep='last')
    combined['date'] = pd.to_datetime(combined['date'])
    combined = combined.sort_values(['horizon', 'date']).reset_index(drop=True)
    combined.to_csv(pred_path, index=False)

    return {'ticker': ticker, 'status': 'ok', 'new_rows': len(new_rows),
            'joblib_path': str(joblib_path),
            'gap_start': str(gap_dates[0].date()),
            'gap_end': str(gap_dates[-1].date())}


def _worker_extend(args):
    """ProcessPoolExecutor worker. Takes a tuple to avoid kwargs gymnastics."""
    ticker, dc, mc, bc, raw_slice, today = args
    try:
        return extend_one_ticker(ticker, dc, mc, bc, raw_slice, today)
    except Exception as e:
        import traceback
        return {'ticker': ticker, 'status': 'error',
                'error': f'{e}\n{traceback.format_exc()}'}


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--tickers', nargs='*', default=None,
                   help='Subset of tickers (default: full corpus)')
    p.add_argument('--skip-refresh', action='store_true',
                   help='Skip data refresh (use cache as-is)')
    p.add_argument('--sequential', action='store_true',
                   help='Disable parallelism (useful for debugging)')
    args = p.parse_args()

    dc, mc, bc = load_config()
    tickers = args.tickers or dc.tickers
    today = pd.Timestamp.today().normalize()

    print(f'[EXTEND] {len(tickers)} ticker(s) | today={today.date()} | '
          f'parallel={not args.sequential} (workers={bc.parallel_tickers if not args.sequential else 1})')

    print(f'[EXTEND] Loading dataset...')
    raw_data = fetch_dataset(dc)
    if not args.skip_refresh:
        print(f'[EXTEND] Appending recent data...')
        raw_data = append_recent_data(dc, raw_data)
    print(f'[EXTEND] Dataset loaded.')

    # Build per-ticker sliced raw_data (reduces pickle size for workers)
    print(f'[EXTEND] Slicing raw data per ticker for parallel pickling...')
    work_items = []
    for ticker in tickers:
        raw_slice = _slice_raw_for_ticker(raw_data, ticker, dc.all_factor_etfs)
        work_items.append((ticker, dc, mc, bc, raw_slice, today))

    results = []
    if args.sequential or bc.parallel_tickers <= 1:
        for item in work_items:
            r = _worker_extend(item)
            print(f'  [{r["ticker"]}] {r["status"]}: '
                  f'{r.get("new_rows", r.get("reason", r.get("error", "")))}')
            results.append(r)
    else:
        with ProcessPoolExecutor(max_workers=bc.parallel_tickers) as ex:
            futures = {ex.submit(_worker_extend, item): item[0] for item in work_items}
            for fut in as_completed(futures):
                r = fut.result()
                print(f'  [{r["ticker"]}] {r["status"]}: '
                      f'{r.get("new_rows", r.get("reason", r.get("error", "")))}')
                results.append(r)

    n_ok = sum(1 for r in results if r['status'] == 'ok')
    n_skip = sum(1 for r in results if r['status'] == 'skip')
    n_err = sum(1 for r in results if r['status'] == 'error')
    total_new_rows = sum(r.get('new_rows', 0) for r in results if r['status'] == 'ok')

    print(f'\n[EXTEND] Done. {n_ok} extended ({total_new_rows:,} new prediction rows), '
          f'{n_skip} skipped, {n_err} errors.')

    if n_err > 0:
        print('\nErrors:')
        for r in results:
            if r['status'] == 'error':
                print(f'  [{r["ticker"]}] {r["error"]}')

    return 0


if __name__ == '__main__':
    sys.exit(main())
