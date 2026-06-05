"""
cadence_experiment.py — Test retrain cadence on the post-backtest extension period.

Re-runs WFA-style retraining over the existing extension window (post-2025-10-29)
with a configurable step_days. Writes predictions to a separate directory so
we can A/B compare against the live single-retrain extension data without
clobbering it.

Each output row carries `model_age_bd` so we can plot R²-vs-staleness directly.

Usage:
    python -m model.pipeline.scripts.cadence_experiment --step-days 10
    python -m model.pipeline.scripts.cadence_experiment --step-days 10 --tickers AAPL MSFT
    python -m model.pipeline.scripts.cadence_experiment --step-days 10 --sequential   # debug

Outputs land at:
    model/pipeline/results/cadence_experiment/step_<N>/predictions_<TICKER>.csv

Analysis (after run completes):
    python -m model.pipeline.scripts.cadence_experiment --analyze
"""
from __future__ import annotations

import argparse
import sys
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

from model.pipeline.config import load_config
from model.pipeline.data_loader import fetch_dataset, append_recent_data
from model.pipeline.features import FeatureBuilder
from model.pipeline.models import EnsembleVolModel
from model.pipeline.extend_predictions import (
    _realized_gk_forward, _slice_raw_for_ticker,
)

warnings.filterwarnings('ignore', category=UserWarning)

# Extension cutoff = last day before extend_predictions started running.
# All tickers share a common calendar so a single cutoff is fine.
EXTENSION_START = pd.Timestamp('2025-10-29')


def extend_with_cadence(ticker: str, dc, mc, bc, raw_data: dict,
                        today: pd.Timestamp, step_days: int) -> dict:
    """Re-extend predictions for one ticker with retrains every `step_days` BD.

    Returns a status dict. Writes to results/cadence_experiment/step_<N>/.
    """
    out_dir = bc.results_dir / 'cadence_experiment' / f'step_{step_days}'
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f'predictions_{ticker}.csv'

    try:
        builder = FeatureBuilder(dc, mc)
        feature_df = builder.build(ticker, raw_data, drop_nan_targets=False)
    except Exception as e:
        return {'ticker': ticker, 'status': 'error', 'error': f'feature build: {e}'}

    if feature_df.empty:
        return {'ticker': ticker, 'status': 'error', 'error': 'empty feature_df'}

    predictors = builder.get_predictor_columns(feature_df)
    valid_predictors = [c for c in predictors if feature_df[c].notna().any()]
    train_target_cols = [f'y_{h}' for h in mc.horizons if f'y_{h}' in feature_df.columns]

    ohlcv = raw_data['ohlcv']
    ohlcv_ticker = ohlcv[ohlcv['ticker'] == ticker] if 'ticker' in ohlcv.columns else ohlcv

    feature_dates = pd.to_datetime(feature_df.index)

    # Walk the extension window in step_days chunks, retraining at each boundary.
    cutoff = EXTENSION_START
    new_rows = []
    n_retrains = 0

    while cutoff < today:
        next_end = cutoff + pd.tseries.offsets.BDay(step_days)
        if next_end > today:
            next_end = today

        # Train on everything available through `cutoff` with all targets observed
        train_df = feature_df.dropna(subset=train_target_cols)
        train_df = train_df[train_df.index <= cutoff]
        if len(train_df) < 100:
            cutoff = next_end
            continue

        X_train = train_df[valid_predictors].ffill().bfill().fillna(0)
        y_train = {h: train_df[f'y_{h}'] for h in mc.horizons if f'y_{h}' in train_df.columns}

        try:
            model = EnsembleVolModel(mc)
            model.train_wfa(X_train, y_train)
            n_retrains += 1
        except Exception as e:
            return {'ticker': ticker, 'status': 'error',
                    'error': f'train at {cutoff.date()}: {e}'}

        # Predict for dates (cutoff, next_end]
        pred_mask = (feature_dates > cutoff) & (feature_dates <= next_end)
        pred_dates = feature_dates[pred_mask]

        for D in pred_dates:
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

            vrp = row.get('vrp_wedge', np.nan)
            skew = row.get('put_call_skew_30d', np.nan)
            model_age = int(np.busday_count(cutoff.date(), D.date()))

            for h in mc.horizons:
                elapsed = (today - D).days
                y_true = _realized_gk_forward(ohlcv_ticker, D, h) if elapsed >= h else np.nan
                new_rows.append({
                    'date': D,
                    'y_true': y_true,
                    'y_pred': float(curve.get(h, np.nan)),
                    'vrp_wedge': float(vrp) if pd.notna(vrp) else np.nan,
                    'put_call_skew_30d': float(skew) if pd.notna(skew) else np.nan,
                    'ticker': ticker,
                    'horizon': int(h),
                    'model_age_bd': model_age,
                    'retrain_date': cutoff.date(),
                })

        cutoff = next_end

    if not new_rows:
        return {'ticker': ticker, 'status': 'skip',
                'reason': f'no predictions made (n_retrains={n_retrains})'}

    new_df = pd.DataFrame(new_rows)
    new_df = new_df.sort_values(['horizon', 'date']).reset_index(drop=True)
    new_df.to_csv(out_path, index=False)

    return {'ticker': ticker, 'status': 'ok', 'new_rows': len(new_rows),
            'n_retrains': n_retrains,
            'first_date': str(new_df['date'].min().date()),
            'last_date':  str(new_df['date'].max().date())}


def extend_with_dynamic_retrain(ticker: str, dc, mc, bc, raw_data: dict,
                                today: pd.Timestamp,
                                sigma_threshold: float = 2.0,
                                consecutive_shocks: int = 3,
                                min_bd_between: int = 5,
                                trigger_horizon: int = 21) -> dict:
    """Re-extend predictions with retrain triggered by realized-vs-predicted shocks.

    Trigger logic: monitor residuals of past H=21 predictions as their y_true
    materializes. If |residual| > sigma_threshold * baseline_sigma for
    `consecutive_shocks` predictions in a row AND at least `min_bd_between` BD
    have passed since last retrain, retrain.

    baseline_sigma is the std of in-sample residuals from the current model.
    Updated on every retrain.
    """
    out_dir = bc.results_dir / 'cadence_experiment' / \
              f'dynamic_s{int(sigma_threshold*10)}_n{consecutive_shocks}'
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f'predictions_{ticker}.csv'

    try:
        builder = FeatureBuilder(dc, mc)
        feature_df = builder.build(ticker, raw_data, drop_nan_targets=False)
    except Exception as e:
        return {'ticker': ticker, 'status': 'error', 'error': f'feature build: {e}'}

    if feature_df.empty:
        return {'ticker': ticker, 'status': 'error', 'error': 'empty feature_df'}

    predictors = builder.get_predictor_columns(feature_df)
    valid_predictors = [c for c in predictors if feature_df[c].notna().any()]
    train_target_cols = [f'y_{h}' for h in mc.horizons if f'y_{h}' in feature_df.columns]

    ohlcv = raw_data['ohlcv']
    ohlcv_ticker = ohlcv[ohlcv['ticker'] == ticker] if 'ticker' in ohlcv.columns else ohlcv

    def _train_at(cutoff: pd.Timestamp):
        train_df = feature_df.dropna(subset=train_target_cols)
        train_df = train_df[train_df.index <= cutoff]
        if len(train_df) < 100:
            return None, None
        X_tr = train_df[valid_predictors].ffill().bfill().fillna(0)
        y_tr = {h: train_df[f'y_{h}']
                for h in mc.horizons if f'y_{h}' in train_df.columns}
        mdl = EnsembleVolModel(mc)
        mdl.train_wfa(X_tr, y_tr)
        # In-sample baseline sigma for the trigger horizon
        try:
            ins_preds = []
            for D in X_tr.index:
                row = X_tr.loc[D]
                pred = mdl.predict_curve(row.to_frame().T).get(trigger_horizon, np.nan)
                ins_preds.append(pred)
            ins_preds = np.asarray(ins_preds, dtype=float)
            actual = y_tr[trigger_horizon].values
            mask = np.isfinite(ins_preds) & np.isfinite(actual)
            sigma = float(np.std(ins_preds[mask] - actual[mask])) if mask.sum() > 5 else 0.05
        except Exception:
            sigma = 0.05  # safe default
        return mdl, sigma

    # Initial train at EXTENSION_START
    model, baseline_sigma = _train_at(EXTENSION_START)
    if model is None:
        return {'ticker': ticker, 'status': 'error', 'error': 'initial train failed'}

    feature_dates = pd.to_datetime(feature_df.index)
    ext_dates = feature_dates[(feature_dates > EXTENSION_START) & (feature_dates <= today)]

    # Cache per-date predictions for residual lookback
    pred_at_date_h21 = {}
    new_rows = []
    retrain_log = [{'date': EXTENSION_START.date(), 'reason': 'init'}]
    last_retrain_date = EXTENSION_START
    consecutive_shock_count = 0
    last_observed_lookback = None  # avoid double-counting residuals

    for D in ext_dates:
        # Predict at D using current model
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

        vrp = row.get('vrp_wedge', np.nan)
        skew = row.get('put_call_skew_30d', np.nan)
        model_age = int(np.busday_count(last_retrain_date.date(), D.date()))
        pred_at_date_h21[D] = float(curve.get(trigger_horizon, np.nan))

        for h in mc.horizons:
            elapsed = (today - D).days
            y_true = _realized_gk_forward(ohlcv_ticker, D, h) if elapsed >= h else np.nan
            new_rows.append({
                'date': D,
                'y_true': y_true,
                'y_pred': float(curve.get(h, np.nan)),
                'vrp_wedge': float(vrp) if pd.notna(vrp) else np.nan,
                'put_call_skew_30d': float(skew) if pd.notna(skew) else np.nan,
                'ticker': ticker,
                'horizon': int(h),
                'model_age_bd': model_age,
                'retrain_date': last_retrain_date.date(),
            })

        # Check shock trigger: any prediction at D - trigger_horizon BD now has y_true
        D_back = D - pd.tseries.offsets.BDay(trigger_horizon)
        if (D_back in pred_at_date_h21
                and (last_observed_lookback is None or D_back > last_observed_lookback)):
            past_pred = pred_at_date_h21[D_back]
            actual_h21 = _realized_gk_forward(ohlcv_ticker, D_back, trigger_horizon)
            if np.isfinite(past_pred) and np.isfinite(actual_h21):
                residual = past_pred - actual_h21
                if abs(residual) > sigma_threshold * baseline_sigma:
                    consecutive_shock_count += 1
                else:
                    consecutive_shock_count = 0
                last_observed_lookback = D_back

                bd_since_retrain = int(np.busday_count(last_retrain_date.date(), D.date()))
                if (consecutive_shock_count >= consecutive_shocks
                        and bd_since_retrain >= min_bd_between):
                    new_model, new_sigma = _train_at(D)
                    if new_model is not None:
                        model = new_model
                        baseline_sigma = new_sigma
                        last_retrain_date = D
                        consecutive_shock_count = 0
                        retrain_log.append(
                            {'date': D.date(), 'reason': f'shock|residual={residual:+.4f}|sigma={baseline_sigma:.4f}'})

    if not new_rows:
        return {'ticker': ticker, 'status': 'skip', 'reason': 'no predictions'}

    new_df = pd.DataFrame(new_rows)
    new_df = new_df.sort_values(['horizon', 'date']).reset_index(drop=True)
    new_df.to_csv(out_path, index=False)

    # Save retrain log alongside
    log_path = out_dir / f'retrain_log_{ticker}.csv'
    pd.DataFrame(retrain_log).to_csv(log_path, index=False)

    return {'ticker': ticker, 'status': 'ok', 'new_rows': len(new_rows),
            'n_retrains': len(retrain_log),
            'retrain_dates': [r['date'] for r in retrain_log]}


def extend_with_multi_trigger(ticker: str, dc, mc, bc, raw_data: dict,
                              today: pd.Timestamp,
                              bias_window: int = 5,
                              bias_sigma_mult: float = 0.5,
                              rmse_window: int = 21,
                              rmse_mult: float = 1.3,
                              ceiling_bd: int = 30,
                              min_bd_between: int = 5,
                              trigger_horizon: int = 21) -> dict:
    """Multi-trigger dynamic retrain. Fires if ANY of:

      (a) BIAS: last `bias_window` residuals all same sign AND
          |mean residual| > `bias_sigma_mult` * sigma_train
      (b) RMSE: rolling `rmse_window`-BD RMSE > `rmse_mult` * RMSE_train
      (c) CEILING: `ceiling_bd` BD since last retrain

    All gated by `min_bd_between` to prevent thrashing.
    Logs which trigger fired so we can see what actually caught the regime shift.
    """
    out_dir = bc.results_dir / 'cadence_experiment' / \
              f'multi_b{bias_window}s{int(bias_sigma_mult*10)}_r{rmse_window}m{int(rmse_mult*10)}_c{ceiling_bd}'
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f'predictions_{ticker}.csv'

    try:
        builder = FeatureBuilder(dc, mc)
        feature_df = builder.build(ticker, raw_data, drop_nan_targets=False)
    except Exception as e:
        return {'ticker': ticker, 'status': 'error', 'error': f'feature build: {e}'}

    if feature_df.empty:
        return {'ticker': ticker, 'status': 'error', 'error': 'empty feature_df'}

    predictors = builder.get_predictor_columns(feature_df)
    valid_predictors = [c for c in predictors if feature_df[c].notna().any()]
    train_target_cols = [f'y_{h}' for h in mc.horizons if f'y_{h}' in feature_df.columns]

    ohlcv = raw_data['ohlcv']
    ohlcv_ticker = ohlcv[ohlcv['ticker'] == ticker] if 'ticker' in ohlcv.columns else ohlcv

    def _train_at(cutoff: pd.Timestamp):
        train_df = feature_df.dropna(subset=train_target_cols)
        train_df = train_df[train_df.index <= cutoff]
        if len(train_df) < 100:
            return None, None, None
        X_tr = train_df[valid_predictors].ffill().bfill().fillna(0)
        y_tr = {h: train_df[f'y_{h}']
                for h in mc.horizons if f'y_{h}' in train_df.columns}
        mdl = EnsembleVolModel(mc)
        mdl.train_wfa(X_tr, y_tr)
        # In-sample benchmark on last 252 BD of training only (more representative
        # of current regime than full-history overfit).
        try:
            recent_X = X_tr.tail(252)
            recent_y = y_tr[trigger_horizon].tail(252).values
            preds = []
            for D in recent_X.index:
                row = recent_X.loc[D]
                preds.append(mdl.predict_curve(row.to_frame().T).get(trigger_horizon, np.nan))
            preds = np.asarray(preds, dtype=float)
            mask = np.isfinite(preds) & np.isfinite(recent_y)
            if mask.sum() < 5:
                sigma, rmse = 0.05, 0.07
            else:
                resid = preds[mask] - recent_y[mask]
                sigma = float(np.std(resid))
                rmse = float(np.sqrt(np.mean(resid ** 2)))
        except Exception:
            sigma, rmse = 0.05, 0.07
        return mdl, sigma, rmse

    model, sigma_train, rmse_train = _train_at(EXTENSION_START)
    if model is None:
        return {'ticker': ticker, 'status': 'error', 'error': 'initial train failed'}

    feature_dates = pd.to_datetime(feature_df.index)
    ext_dates = feature_dates[(feature_dates > EXTENSION_START) & (feature_dates <= today)]

    # Cache predictions for residual lookback
    pred_at_date = {}  # D -> y_pred at trigger_horizon
    residual_buffer = []  # list of (D, residual) for observable residuals, newest last
    new_rows = []
    retrain_log = [{'date': EXTENSION_START.date(), 'reason': 'init',
                    'sigma_train': sigma_train, 'rmse_train': rmse_train}]
    last_retrain_date = EXTENSION_START

    for D in ext_dates:
        # ── Predict at D ────────────────────────────────────────────────
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

        vrp = row.get('vrp_wedge', np.nan)
        skew = row.get('put_call_skew_30d', np.nan)
        model_age = int(np.busday_count(last_retrain_date.date(), D.date()))
        pred_at_date[D] = float(curve.get(trigger_horizon, np.nan))

        for h in mc.horizons:
            elapsed = (today - D).days
            y_true = _realized_gk_forward(ohlcv_ticker, D, h) if elapsed >= h else np.nan
            new_rows.append({
                'date': D, 'y_true': y_true,
                'y_pred': float(curve.get(h, np.nan)),
                'vrp_wedge': float(vrp) if pd.notna(vrp) else np.nan,
                'put_call_skew_30d': float(skew) if pd.notna(skew) else np.nan,
                'ticker': ticker, 'horizon': int(h),
                'model_age_bd': model_age,
                'retrain_date': last_retrain_date.date(),
            })

        # ── Update residual buffer: check if any past prediction now has y_true ──
        D_back = D - pd.tseries.offsets.BDay(trigger_horizon)
        if D_back in pred_at_date:
            past_pred = pred_at_date[D_back]
            actual = _realized_gk_forward(ohlcv_ticker, D_back, trigger_horizon)
            if np.isfinite(past_pred) and np.isfinite(actual):
                resid = past_pred - actual
                # Only add if newer than last observation in buffer
                if not residual_buffer or residual_buffer[-1][0] < D_back:
                    residual_buffer.append((D_back, resid))

        # ── Check triggers (with min_bd_between protection) ──────────────
        bd_since_retrain = int(np.busday_count(last_retrain_date.date(), D.date()))
        if bd_since_retrain < min_bd_between:
            continue

        trigger_fired = None

        # Bias trigger
        if len(residual_buffer) >= bias_window:
            last_window = [r for _, r in residual_buffer[-bias_window:]]
            same_sign = all(r > 0 for r in last_window) or all(r < 0 for r in last_window)
            mean_abs = abs(np.mean(last_window))
            if same_sign and mean_abs > bias_sigma_mult * sigma_train:
                trigger_fired = f'bias|sign={"+" if last_window[0]>0 else "-"}|mean={np.mean(last_window):+.4f}|thr={bias_sigma_mult*sigma_train:.4f}'

        # RMSE trigger
        if trigger_fired is None and len(residual_buffer) >= rmse_window:
            recent = [r for _, r in residual_buffer[-rmse_window:]]
            rolling_rmse = float(np.sqrt(np.mean(np.square(recent))))
            if rolling_rmse > rmse_mult * rmse_train:
                trigger_fired = f'rmse|roll={rolling_rmse:.4f}|thr={rmse_mult*rmse_train:.4f}'

        # Ceiling trigger
        if trigger_fired is None and bd_since_retrain >= ceiling_bd:
            trigger_fired = f'ceiling|bd_since={bd_since_retrain}'

        if trigger_fired is not None:
            new_model, new_sigma, new_rmse = _train_at(D)
            if new_model is not None:
                model = new_model
                sigma_train = new_sigma
                rmse_train = new_rmse
                last_retrain_date = D
                retrain_log.append({'date': D.date(), 'reason': trigger_fired,
                                    'sigma_train': new_sigma, 'rmse_train': new_rmse})

    if not new_rows:
        return {'ticker': ticker, 'status': 'skip', 'reason': 'no predictions'}

    new_df = pd.DataFrame(new_rows).sort_values(['horizon', 'date']).reset_index(drop=True)
    new_df.to_csv(out_path, index=False)
    pd.DataFrame(retrain_log).to_csv(out_dir / f'retrain_log_{ticker}.csv', index=False)

    # Count which triggers fired
    bias_fires = sum(1 for r in retrain_log if r['reason'].startswith('bias'))
    rmse_fires = sum(1 for r in retrain_log if r['reason'].startswith('rmse'))
    ceiling_fires = sum(1 for r in retrain_log if r['reason'].startswith('ceiling'))

    return {'ticker': ticker, 'status': 'ok', 'new_rows': len(new_rows),
            'n_retrains': len(retrain_log),
            'triggers': f'bias={bias_fires}|rmse={rmse_fires}|ceiling={ceiling_fires}'}


def _worker(args):
    mode, ticker, dc, mc, bc, raw_slice, today, params = args
    try:
        if mode == 'fixed':
            return extend_with_cadence(ticker, dc, mc, bc, raw_slice, today, params['step_days'])
        elif mode == 'dynamic':
            return extend_with_dynamic_retrain(
                ticker, dc, mc, bc, raw_slice, today,
                sigma_threshold=params['sigma_threshold'],
                consecutive_shocks=params['consecutive_shocks'],
                min_bd_between=params['min_bd_between'],
                trigger_horizon=params['trigger_horizon'],
            )
        elif mode == 'multi':
            return extend_with_multi_trigger(
                ticker, dc, mc, bc, raw_slice, today,
                bias_window=params['bias_window'],
                bias_sigma_mult=params['bias_sigma_mult'],
                rmse_window=params['rmse_window'],
                rmse_mult=params['rmse_mult'],
                ceiling_bd=params['ceiling_bd'],
                min_bd_between=params['min_bd_between'],
                trigger_horizon=params['trigger_horizon'],
            )
        else:
            return {'ticker': ticker, 'status': 'error', 'error': f'unknown mode {mode}'}
    except Exception as e:
        import traceback
        return {'ticker': ticker, 'status': 'error',
                'error': f'{e}\n{traceback.format_exc()}'}


def run_experiment(mode: str, params: dict, tickers=None, sequential: bool = False):
    dc, mc, bc = load_config()
    tickers = tickers or dc.tickers
    today = pd.Timestamp.today().normalize()

    n_workers = 1 if sequential else bc.parallel_tickers
    print(f'[CADENCE] mode={mode} | params={params} | tickers={len(tickers)} | '
          f'today={today.date()} | workers={n_workers}')

    print(f'[CADENCE] Loading dataset (using cache as-is)...')
    raw_data = fetch_dataset(dc)
    print(f'[CADENCE] Dataset loaded. Slicing per ticker...')

    work_items = []
    for ticker in tickers:
        raw_slice = _slice_raw_for_ticker(raw_data, ticker, dc.all_factor_etfs)
        work_items.append((mode, ticker, dc, mc, bc, raw_slice, today, params))

    results = []
    def _fmt(r):
        triggers = f' [{r["triggers"]}]' if 'triggers' in r else ''
        return (f'  [{r["ticker"]}] {r["status"]}: '
                f'{r.get("n_retrains", "")} retrains, '
                f'{r.get("new_rows", r.get("reason", r.get("error", "")))} rows'
                + triggers)

    if sequential or n_workers <= 1:
        for item in work_items:
            r = _worker(item)
            print(_fmt(r))
            results.append(r)
    else:
        with ProcessPoolExecutor(max_workers=n_workers) as ex:
            futures = {ex.submit(_worker, item): item[1] for item in work_items}
            for fut in as_completed(futures):
                r = fut.result()
                print(_fmt(r))
                results.append(r)

    n_ok = sum(1 for r in results if r['status'] == 'ok')
    n_err = sum(1 for r in results if r['status'] == 'error')
    print(f'\n[CADENCE] Done. {n_ok} ok, {n_err} errors.')

    if n_err > 0:
        print('\nErrors:')
        for r in results:
            if r['status'] == 'error':
                print(f'  [{r["ticker"]}] {r["error"]}')


def analyze():
    """Compare R² across all experiment configs vs the live extension baseline.

    Auto-discovers any subdir under cadence_experiment/ (step_<N> for fixed
    cadence, dynamic_s<S>_n<N> for dynamic) and includes it in the comparison.
    Matches each experiment's tickers to the baseline by ticker+date+horizon
    so the comparison is strictly apples-to-apples.
    """
    _, _, bc = load_config()
    base_dir = bc.results_dir / 'cadence_experiment'

    exp_dirs = sorted([d for d in base_dir.glob('*') if d.is_dir()])
    if not exp_dirs:
        print('[ANALYZE] No experiment outputs found.')
        return

    baseline_path = bc.results_dir / 'all_predictions.csv'
    base = pd.read_csv(baseline_path, parse_dates=['date'])
    base = base[(base.date > EXTENSION_START)
                & base.y_pred.notna() & base.y_true.notna()].copy()

    def metrics(yt, yp):
        if len(yt) < 5: return (np.nan, np.nan, np.nan)
        ss_res = ((yt - yp)**2).sum()
        ss_tot = ((yt - yt.mean())**2).sum()
        r2 = 1 - ss_res/ss_tot if ss_tot > 0 else np.nan
        bias = float((yp - yt).mean())
        rmse = float(np.sqrt(((yt - yp)**2).mean()))
        return r2, bias, rmse

    rows = []
    for exp_dir in exp_dirs:
        files = sorted(exp_dir.glob('predictions_*.csv'))
        if not files:
            continue
        dfs = [pd.read_csv(f, parse_dates=['date']) for f in files]
        exp = pd.concat(dfs, ignore_index=True)
        exp = exp[exp.y_pred.notna() & exp.y_true.notna()]
        # Restrict baseline to same tickers + dates for apples-to-apples
        b_sub = base.merge(exp[['ticker','date','horizon']],
                           on=['ticker','date','horizon'])
        for h in [21, 63, 126]:
            e_h = exp[exp.horizon == h]
            b_h = b_sub[b_sub.horizon == h]
            r2_e, bias_e, rmse_e = metrics(e_h.y_true.values, e_h.y_pred.values)
            r2_b, bias_b, rmse_b = metrics(b_h.y_true.values, b_h.y_pred.values)
            n_retrains_avg = None
            if 'retrain_date' in exp.columns:
                # Average retrains per ticker
                n_retrains_avg = exp.groupby('ticker')['retrain_date'].nunique().mean()
            rows.append({
                'config': exp_dir.name,
                'horizon': h,
                'n_tickers': len(files),
                'n_obs': len(e_h),
                'R2_baseline': r2_b,
                'R2_experiment': r2_e,
                'R2_delta': r2_e - r2_b,
                'bias_experiment': bias_e,
                'rmse_experiment': rmse_e,
                'rmse_delta': rmse_e - rmse_b,
                'avg_retrains_per_ticker': n_retrains_avg,
            })
    df = pd.DataFrame(rows)
    print('\n=== Cadence comparison (apples-to-apples per config) ===')
    print(df.to_string(index=False))


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--mode', choices=['fixed', 'dynamic', 'multi'], default='fixed')
    # fixed
    p.add_argument('--step-days', type=int, default=10)
    # dynamic (single residual trigger)
    p.add_argument('--sigma-threshold', type=float, default=2.0)
    p.add_argument('--consecutive', type=int, default=3)
    # multi
    p.add_argument('--bias-window', type=int, default=5,
                   help='[multi] last K residuals same-sign for bias trigger')
    p.add_argument('--bias-sigma-mult', type=float, default=0.5,
                   help='[multi] mean |resid| threshold as multiple of sigma_train')
    p.add_argument('--rmse-window', type=int, default=21,
                   help='[multi] rolling RMSE window')
    p.add_argument('--rmse-mult', type=float, default=1.3,
                   help='[multi] RMSE trigger as multiple of RMSE_train')
    p.add_argument('--ceiling-bd', type=int, default=30,
                   help='[multi] hard ceiling: retrain if no other trigger fired')
    # shared
    p.add_argument('--min-bd-between', type=int, default=5)
    p.add_argument('--trigger-horizon', type=int, default=21)
    p.add_argument('--tickers', nargs='*', default=None)
    p.add_argument('--sequential', action='store_true')
    p.add_argument('--analyze', action='store_true')
    args = p.parse_args()

    if args.analyze:
        analyze()
        return 0

    if args.mode == 'fixed':
        params = {'step_days': args.step_days}
    elif args.mode == 'dynamic':
        params = {
            'sigma_threshold': args.sigma_threshold,
            'consecutive_shocks': args.consecutive,
            'min_bd_between': args.min_bd_between,
            'trigger_horizon': args.trigger_horizon,
        }
    else:  # multi
        params = {
            'bias_window': args.bias_window,
            'bias_sigma_mult': args.bias_sigma_mult,
            'rmse_window': args.rmse_window,
            'rmse_mult': args.rmse_mult,
            'ceiling_bd': args.ceiling_bd,
            'min_bd_between': args.min_bd_between,
            'trigger_horizon': args.trigger_horizon,
        }

    run_experiment(args.mode, params, tickers=args.tickers, sequential=args.sequential)
    return 0


if __name__ == '__main__':
    sys.exit(main())
