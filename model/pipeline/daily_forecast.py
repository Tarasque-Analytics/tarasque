"""
daily_forecast.py — Per-ticker daily forecast cycle.

For each ticker:
  1. Load most recent persisted joblib model (the weekly retrain target).
  2. Build features for the latest available date.
  3. Predict pfv_21 / pfv_63 / pfv_126 via the ensemble.
  4. Append today's rows (one per horizon) to predictions_<TICKER>.csv with
     y_true = NaN; backfill happens in step 6.
  5. Compute ensemble SHAP per horizon, append to forecasts/<TICKER>_shap.csv
     (parallel file; the predictions CSV stays SHAP-free per the
     "concurrent only" architecture).
  6. Backfill: scan predictions_<TICKER>.csv for rows where
     (today − row_date) >= horizon AND y_true is NaN → fill from realized
     GK vol computed off the now-available forward window.

Usage:
  python -m model.pipeline.daily_forecast                  # all 93 tickers
  python -m model.pipeline.daily_forecast --tickers AAPL  # canary
  python -m model.pipeline.daily_forecast --skip-shap --skip-backfill  # predictions only

Retrain is OUT of scope here — that's --mode forecast --retrain (weekly cron).
"""
from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from .config import load_config
from .data_loader import fetch_dataset, append_recent_data
from .features import FeatureBuilder
from .models import EnsembleVolModel
from .shap_explainer import compute_ensemble_shap_top_k, serialize_shap_blob

warnings.filterwarnings('ignore', category=UserWarning)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _realized_gk_forward(ohlcv_ticker: pd.DataFrame,
                         start_date: pd.Timestamp,
                         h_days: int) -> float:
    """Compute annualised GK realized vol over the forward window
    [start_date + 1 BDay, start_date + h_days BDays].

    Matches features._add_rv_features methodology exactly: GK var per day from
    raw H/L/O/C (split-safe intraday), mean over h days, annualised via sqrt(252).
    Returns NaN if the window doesn't have h valid daily bars.
    """
    df = ohlcv_ticker.copy()
    if df.empty:
        return float('nan')
    df['date'] = pd.to_datetime(df['date'], format='mixed', errors='coerce')
    df = df.dropna(subset=['date']).sort_values('date').reset_index(drop=True)
    end_date = start_date + pd.tseries.offsets.BDay(h_days)
    window = df[(df['date'] > start_date) & (df['date'] <= end_date)]
    if len(window) < h_days * 0.8:  # tolerate up to 20% missing bars
        return float('nan')
    # Column normalisation (CRSP uses openprc/askhi/bidlo/prc)
    cols = {'openprc': 'open', 'askhi': 'high', 'bidlo': 'low', 'prc': 'close'}
    for k, v in cols.items():
        if k in window.columns:
            window = window.rename(columns={k: v})
    # Negative price = bid/ask midpoint flag (CRSP) → abs()
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


def _read_or_empty(path: Path, parse_dates=None) -> pd.DataFrame:
    """Read CSV if exists, else return empty DataFrame."""
    if path.exists():
        return pd.read_csv(path, parse_dates=parse_dates or [])
    return pd.DataFrame()


def _append_dedupe_sort(existing: pd.DataFrame, new: pd.DataFrame,
                        key_cols: list[str]) -> pd.DataFrame:
    """Concat existing + new, drop dupes on key_cols keeping new, sort by date."""
    combined = pd.concat([existing, new], ignore_index=True)
    combined = combined.drop_duplicates(subset=key_cols, keep='last')
    if 'date' in combined.columns:
        combined['date'] = pd.to_datetime(combined['date'], errors='coerce')
        combined = combined.sort_values('date').reset_index(drop=True)
    return combined


# ─────────────────────────────────────────────────────────────────────────────
# Daily flow per ticker
# ─────────────────────────────────────────────────────────────────────────────

def forecast_one_ticker(ticker: str, dc, mc, bc, raw_data: dict,
                        do_shap: bool = True) -> bool:
    """Run today's forecast for a single ticker. Returns True if a new row
    was written, False if skipped (no persisted model, no feature data, etc.).
    """
    forecast_dir = bc.results_dir / 'forecasts'
    forecast_dir.mkdir(parents=True, exist_ok=True)
    pred_path = bc.results_dir / f'predictions_{ticker}.csv'
    shap_path = forecast_dir / f'{ticker}_shap.csv'

    # 1. Locate most recent persisted joblib
    existing = sorted(forecast_dir.glob(f'{ticker}_model_*.joblib'))
    if not existing:
        print(f'  [{ticker}] no persisted model — skip (run --mode forecast --retrain first)')
        return False
    joblib_path = existing[-1]

    # 2. Build features for the ticker — drop_nan_targets=False so we pick the
    # latest OHLCV-available date (not today − 126 BDays).
    try:
        builder = FeatureBuilder(dc, mc)
        feature_df = builder.build(ticker, raw_data, drop_nan_targets=False)
    except Exception as e:
        print(f'  [{ticker}] feature build failed: {e}')
        return False

    if feature_df.empty:
        print(f'  [{ticker}] empty feature DataFrame')
        return False

    # 3. Load model + align latest row to predictor schema
    model = EnsembleVolModel.load(joblib_path)
    latest_idx = feature_df.index[-1]
    latest_date = pd.Timestamp(latest_idx) if not isinstance(latest_idx, pd.Timestamp) \
        else latest_idx
    # FeatureBuilder may return date as index OR as a column — handle both
    if 'date' in feature_df.columns:
        latest_date = pd.Timestamp(feature_df['date'].iloc[-1])
    latest_row = feature_df.iloc[-1]

    # Build the aligned 1-row feature frame the model expects
    aligned = pd.Series(index=model.predictors, dtype=float)
    for p in model.predictors:
        v = latest_row.get(p, 0.0)
        aligned[p] = float(v) if pd.notna(v) else 0.0
    X_today = aligned.to_frame().T  # one-row DataFrame

    # 4. Predict
    try:
        curve = model.predict_curve(X_today)
    except Exception as e:
        print(f'  [{ticker}] predict failed: {e}')
        return False

    print(f'  [{ticker}] date={latest_date.date()}  '
          f'H21={curve.get(21, float("nan")):.4f}  '
          f'H63={curve.get(63, float("nan")):.4f}  '
          f'H126={curve.get(126, float("nan")):.4f}')

    # 5. Append prediction rows (one per horizon) to predictions_<TICKER>.csv
    pred_existing = _read_or_empty(pred_path, parse_dates=['date'])
    new_pred_rows = []
    for h in mc.horizons:
        new_pred_rows.append({
            'date': latest_date,
            'y_true': float('nan'),
            'y_pred': float(curve.get(h, float('nan'))),
            'y_pred_q15': float('nan'),  # quantile model not loaded here; v2
            'vrp_wedge': float(latest_row.get('vrp_wedge', float('nan'))) if pd.notna(latest_row.get('vrp_wedge', float('nan'))) else float('nan'),
            'put_call_skew_30d': float(latest_row.get('put_call_skew_30d', float('nan'))) if pd.notna(latest_row.get('put_call_skew_30d', float('nan'))) else float('nan'),
            'ticker': ticker,
            'horizon': int(h),
        })
    new_pred = pd.DataFrame(new_pred_rows)
    combined_pred = _append_dedupe_sort(pred_existing, new_pred,
                                        key_cols=['date', 'horizon'])
    # Restore the canonical column order
    canonical_cols = ['date', 'y_true', 'y_pred', 'y_pred_q15', 'vrp_wedge',
                      'put_call_skew_30d', 'ticker', 'horizon']
    keep = [c for c in canonical_cols if c in combined_pred.columns]
    combined_pred = combined_pred[keep + [c for c in combined_pred.columns if c not in keep]]
    combined_pred.to_csv(pred_path, index=False)

    # 6. SHAP per horizon → forecasts/<TICKER>_shap.csv
    if do_shap:
        shap_existing = _read_or_empty(shap_path, parse_dates=['date'])
        new_shap_rows = []
        for h in mc.horizons:
            try:
                blob = compute_ensemble_shap_top_k(
                    ensemble=model.models[h],
                    weights=model.weights[h],
                    X_raw_row=latest_row,
                    final_scaler=model.final_scaler,
                    predictors=model.predictors,
                    k=10,
                )
            except Exception as e:
                print(f'  [{ticker}] SHAP H={h} failed: {e}')
                continue
            new_shap_rows.append({
                'date': latest_date,
                'horizon': int(h),
                'model_version': joblib_path.stem,  # e.g. AAPL_model_2026-05-01
                'shap_blob_json': serialize_shap_blob(blob),
            })
        if new_shap_rows:
            new_shap = pd.DataFrame(new_shap_rows)
            combined_shap = _append_dedupe_sort(shap_existing, new_shap,
                                                key_cols=['date', 'horizon'])
            combined_shap.to_csv(shap_path, index=False)

    return True


def backfill_y_true(ticker: str, ohlcv: pd.DataFrame, bc) -> int:
    """Fill realized y_true on stale predictions where the horizon has elapsed.

    Returns the number of cells filled.
    """
    pred_path = bc.results_dir / f'predictions_{ticker}.csv'
    if not pred_path.exists():
        return 0

    df = pd.read_csv(pred_path, parse_dates=['date'])
    if df.empty:
        return 0

    # Filter ohlcv to ticker once (faster than per-row)
    ohlcv = ohlcv.copy()
    if 'ticker' in ohlcv.columns:
        ohlcv = ohlcv[ohlcv['ticker'] == ticker]
    if ohlcv.empty:
        return 0
    ohlcv['date'] = pd.to_datetime(ohlcv['date'], format='mixed', errors='coerce')
    today = pd.Timestamp.today().normalize()

    n_filled = 0
    for idx, row in df.iterrows():
        if pd.notna(row['y_true']):
            continue
        h = int(row['horizon'])
        row_date = pd.Timestamp(row['date'])
        # Has the horizon window elapsed?
        elapsed_bdays = len(pd.bdate_range(row_date, today)) - 1
        if elapsed_bdays < h:
            continue
        gk_vol = _realized_gk_forward(ohlcv, row_date, h)
        if pd.notna(gk_vol):
            df.at[idx, 'y_true'] = gk_vol
            n_filled += 1

    if n_filled > 0:
        df.to_csv(pred_path, index=False)
    return n_filled


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--tickers', nargs='*', default=None,
                   help='Tickers to process (default: full corpus from config)')
    p.add_argument('--skip-shap', action='store_true',
                   help='Skip SHAP computation (faster, predictions only)')
    p.add_argument('--skip-backfill', action='store_true',
                   help='Skip y_true backfill on stale rows')
    p.add_argument('--skip-refresh', action='store_true',
                   help='Skip data_loader.append_recent_data (use cache as-is)')
    args = p.parse_args()

    dc, mc, bc = load_config()
    tickers = args.tickers or dc.tickers
    print(f'[DAILY] {len(tickers)} ticker(s) | shap={not args.skip_shap} | '
          f'backfill={not args.skip_backfill}')

    # Load data once for the whole run
    print(f'[DAILY] Loading dataset...')
    raw_data = fetch_dataset(dc)
    if not args.skip_refresh:
        print(f'[DAILY] Appending recent data...')
        raw_data = append_recent_data(dc, raw_data)

    n_ok = 0
    n_skipped = 0
    for i, ticker in enumerate(tickers, start=1):
        print(f'\n[{i}/{len(tickers)}] {ticker}')
        ok = forecast_one_ticker(ticker, dc, mc, bc, raw_data,
                                 do_shap=not args.skip_shap)
        if ok:
            n_ok += 1
        else:
            n_skipped += 1

    # Backfill pass (after all forecasts written)
    if not args.skip_backfill:
        print(f'\n[DAILY] Backfilling realized y_true on stale rows...')
        n_filled_total = 0
        for ticker in tickers:
            n = backfill_y_true(ticker, raw_data.get('ohlcv', pd.DataFrame()), bc)
            if n > 0:
                print(f'  [{ticker}] filled {n} cells')
                n_filled_total += n
        print(f'[DAILY] Total y_true cells filled: {n_filled_total}')

    print(f'\n[DAILY] Done. {n_ok} OK, {n_skipped} skipped.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
