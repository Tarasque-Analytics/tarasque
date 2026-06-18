"""
regimes.py — Per (ticker, date) daily rolling β_mkt and β_mz.

These two values are the (x, y) coordinates that place each name on the
Macro page's 2×2 Regime Modeler. β_mkt is its CAPM market beta, β_mz is
the calibration slope of the model's forecast against realized vol — a
direct gauge of where the model is systematically miscalibrated.

Definitions
-----------
β_mkt(T)  = cov(log_ret_ticker, log_ret_SPY) / var(log_ret_SPY)
            over the trailing 252 BD ending at T.

β_mz_h(T) = cov(log y_true_h, log y_pred_h) / var(log y_pred_h)
            over the trailing 252 prediction pairs whose y_true is realized
            by T — i.e. prediction_date + h_BD <= T.
α_mz_h(T) = mean(log y_true_h) - β_mz_h(T) * mean(log y_pred_h) on the same
            window. The MZ intercept.

Both are pandas-rolling vectorized — no per-date Python loop. Cost on the
93-ticker × 3-horizon × ~3000-date corpus is dominated by I/O, not compute.

Realization-date subtlety
-------------------------
At date T the only valid MZ pairs are those whose y_true is observable.
A horizon-h prediction made on D becomes observable at D + h_BD. So β_mz_h(T)
is indexed naturally by "asof = D + h_BD" — the realization date — and
mapped back onto calendar dates via pd.merge_asof(direction='backward').
"""
from __future__ import annotations

import numpy as np
import pandas as pd

WINDOW_BD = 252
MIN_PERIODS_BMKT = 200    # tolerate ~20% missing days from data joins
MIN_PERIODS_BMZ  = 60     # matches validated research-script floor
LOG_FLOOR = 1e-6           # vol can be ~0 in calm regimes; floor before log


def beta_mkt_series(
    closes_ticker: pd.Series,
    closes_mkt: pd.Series,
    window: int = WINDOW_BD,
    min_periods: int = MIN_PERIODS_BMKT,
) -> pd.Series:
    """Rolling 252-BD market beta of a ticker on a market index (log returns).

    Both series should be split-adjusted (adj_close), indexed by date.
    Returns a Series indexed by the same date axis as `closes_ticker`.
    """
    paired = (
        pd.concat(
            [
                np.log(closes_ticker).diff().rename('rt'),
                np.log(closes_mkt).diff().rename('rm'),
            ],
            axis=1,
        )
        .dropna(how='all')
    )
    cov = paired['rt'].rolling(window, min_periods=min_periods).cov(paired['rm'])
    var = paired['rm'].rolling(window, min_periods=min_periods).var()
    beta = cov / var
    beta.name = 'beta_mkt_252d'
    return beta


def beta_mz_series_one_horizon(
    preds: pd.DataFrame,
    horizon: int,
    window: int = WINDOW_BD,
    min_periods: int = MIN_PERIODS_BMZ,
) -> pd.DataFrame:
    """Rolling MZ slope + intercept (log y_true ~ log y_pred) for one horizon.

    Args:
      preds: DataFrame with columns ['date', 'y_pred', 'y_true'] — one
             horizon's predictions for one ticker, ascending by date.

    Returns:
      DataFrame indexed by 'asof' (= prediction_date + horizon BD = realization
      date) with columns ['beta_mz', 'mz_alpha']. Empty DataFrame if no usable
      pairs (e.g. no realized y_true yet).
    """
    p = preds.dropna(subset=['y_true', 'y_pred']).copy()
    if p.empty:
        return pd.DataFrame(columns=['beta_mz', 'mz_alpha'])
    p['date'] = pd.to_datetime(p['date'])
    p = p.sort_values('date').reset_index(drop=True)
    p['asof'] = p['date'] + pd.tseries.offsets.BDay(horizon)
    p['log_yt'] = np.log(p['y_true'].clip(lower=LOG_FLOOR))
    p['log_yp'] = np.log(p['y_pred'].clip(lower=LOG_FLOOR))
    p = p.set_index('asof').sort_index()

    cov = p['log_yt'].rolling(window, min_periods=min_periods).cov(p['log_yp'])
    var = p['log_yp'].rolling(window, min_periods=min_periods).var()
    beta = cov / var

    mean_yt = p['log_yt'].rolling(window, min_periods=min_periods).mean()
    mean_yp = p['log_yp'].rolling(window, min_periods=min_periods).mean()
    alpha = mean_yt - beta * mean_yp

    return pd.DataFrame({'beta_mz': beta, 'mz_alpha': alpha})


def add_regime_columns(
    out: pd.DataFrame,
    df_pred_wide: pd.DataFrame,
    ohlcv_ticker: pd.DataFrame,
    ohlcv_mkt: pd.DataFrame,
    horizons=(21, 63, 126),
) -> pd.DataFrame:
    """Append regime columns to a per-ticker wide DataFrame.

    Adds 7 columns:
      beta_mkt_252d,
      beta_mz_h{21,63,126},
      mz_alpha_h{21,63,126}

    Args:
      out: per-ticker wide DataFrame already containing 'date' (sorted asc).
      df_pred_wide: wide predictions for this ticker; must have y_pred_h and
                    y_true_h columns for each horizon.
      ohlcv_ticker: this ticker's OHLCV — needs 'date' and 'adj_close'.
      ohlcv_mkt:    market index OHLCV (typically SPY) — same columns.

    Returns a copy of `out` with the 7 new columns appended. Row count
    unchanged.
    """
    out = out.copy()

    closes_ticker = (
        ohlcv_ticker[['date', 'adj_close']]
        .dropna()
        .drop_duplicates('date')
        .set_index('date')['adj_close']
        .sort_index()
    )
    closes_mkt = (
        ohlcv_mkt[['date', 'adj_close']]
        .dropna()
        .drop_duplicates('date')
        .set_index('date')['adj_close']
        .sort_index()
    )

    bmkt = beta_mkt_series(closes_ticker, closes_mkt).dropna()
    bmkt_df = bmkt.reset_index()
    bmkt_df.columns = ['date', 'beta_mkt_252d']
    bmkt_df['date'] = pd.to_datetime(bmkt_df['date'])
    out = pd.merge_asof(
        out.sort_values('date').reset_index(drop=True),
        bmkt_df.sort_values('date').reset_index(drop=True),
        on='date', direction='backward',
    )

    for h in horizons:
        yp_col, yt_col = f'y_pred_{h}', f'y_true_{h}'
        if yp_col not in df_pred_wide.columns or yt_col not in df_pred_wide.columns:
            out[f'beta_mz_h{h}'] = np.nan
            out[f'mz_alpha_h{h}'] = np.nan
            continue
        sub = df_pred_wide[['date', yp_col, yt_col]].rename(
            columns={yp_col: 'y_pred', yt_col: 'y_true'}
        )
        bmz = beta_mz_series_one_horizon(sub, h).dropna()
        if bmz.empty:
            out[f'beta_mz_h{h}'] = np.nan
            out[f'mz_alpha_h{h}'] = np.nan
            continue
        bmz_flat = bmz.reset_index().rename(
            columns={
                'asof': 'date',
                'beta_mz': f'beta_mz_h{h}',
                'mz_alpha': f'mz_alpha_h{h}',
            }
        )
        bmz_flat['date'] = pd.to_datetime(bmz_flat['date'])
        out = pd.merge_asof(
            out.sort_values('date').reset_index(drop=True),
            bmz_flat.sort_values('date').reset_index(drop=True),
            on='date', direction='backward',
        )

    return out
