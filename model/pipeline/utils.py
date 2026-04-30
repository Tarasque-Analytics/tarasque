"""
utils.py — Shared helpers used across the pipeline.

Ported from volarbmodel_backtest.py: clean_num (:35-42), QuantLib (:517-546),
EventCalendar (:91-97).
"""
from typing import Dict, Optional

import numpy as np
import pandas as pd
from datetime import datetime, date, timedelta
from scipy.stats import norm
from scipy.optimize import brentq


# ---------------------------------------------------------------------------
# Sanitisation
# ---------------------------------------------------------------------------

def clean_num(val, decimals=2):
    """Sanitize float for JSON serialization. NaN/Inf → None."""
    if val is None or pd.isna(val) or np.isinf(val):
        return None
    return round(float(val), decimals)


# ---------------------------------------------------------------------------
# Output precision schema
# ---------------------------------------------------------------------------
# Source-data precision audit (CRSP / OptionMetrics / FRED) places a hard ceiling
# on what the model can meaningfully resolve. Writing 16-decimal Python repr to
# CSVs advertises precision the inputs do not support, and exposes FP-subtraction
# artifacts (e.g. put_call_skew_30d trailing 9s). Apply this schema at every
# CSV / JSON write path.
#
# Bounded statistics on [0,1] (R², coverage) → 4 decimals.
# Vol-scale floats (forecasts, RV, IV-derived) → 6 decimals.
# Counts → integer.
DECIMAL_PRECISION: Dict[str, int] = {
    # Predictions / targets
    "y_true": 6, "y_pred": 6, "y_pred_q15": 6, "y_pred_q85": 6,
    "vrp_wedge": 6, "put_call_skew_30d": 6,
    # Forecast outputs
    "forecast_h21": 6, "forecast_h63": 6, "forecast_h126": 6,
    # Frontend payload time-series and aggregates
    "predicted_rv_21d": 6, "predicted_rv_63d": 6, "predicted_rv_126d": 6,
    "realized_rv_21d": 6, "implied_vol_30d": 6,
    "garch_21d": 6, "market_iv_atm": 6,
    "vrp_percentile_1y": 4, "z_score_stabilized": 4,
    "avg_vrp_wedge": 6, "avg_forecast_rv_21d": 6, "percentile_1y": 4,
    "forecast_rv_21d": 6, "risk_score": 4,
    "vol_regime_zscore": 4, "market_vol_21d": 6,
    "overall_r2": 4, "overall_mz_beta": 4,
    "all_y_true": 6, "all_y_pred": 6,
    # Error metrics on vol scale
    "rmse": 6, "qlike": 6, "pinball_q15": 6, "pinball_q85": 6,
    # Regression coefficients
    "mz_alpha": 4, "mz_beta": 4, "mz_r2": 4,
    # Bounded stats on [0, 1]
    "event_capture_rate": 4, "coverage_q15": 4, "coverage_q85": 4,
    # Lasso / XGB tracking
    "coef": 6, "alpha": 6, "l1_ratio": 4, "mean_abs_coef": 6,
    "mean_alpha": 6, "mean_l1_ratio": 4, "inclusion_freq": 4,
    "importance": 6, "mean_importance": 6,
    # Feature decay metrics (4 dec — stability, not precision-critical)
    "rolling_inclusion_freq": 4, "sign_flip_rate": 4,
    "importance_slope": 6, "importance_slope_pvalue": 4,
    "rolling_ic": 4, "decay_score": 4,
    # Diagnostic stats (analysis/audit.py)
    "vif": 4, "ic": 4, "spearman": 4, "pearson": 4,
    "beta": 4, "alpha_intercept": 6,
    "r2": 4, "avg_spearman": 4,
    "dm_sq": 4, "p_value": 4,
    "model_rmse": 6, "naive_rmse": 6,
    "rmse_top": 6, "rmse_middle": 6, "rmse_bottom": 6,
    "qlike_top": 6, "qlike_middle": 6, "qlike_bottom": 6,
    "top_10": 6, "middle_80": 6, "bottom_10": 6,
    "mean_bias": 6, "bias": 6, "rel_bias": 4,
    "mean_abs_wedge": 6, "ratio": 4,
    "vrp_nan_rate": 4, "nan_rate": 4,
    "inv_any_rate": 4, "inv_21_63_rate": 4, "inv_63_126_rate": 4,
    "seam_jump_ratio": 4, "boundary_mean": 6, "interior_mean": 6,
    "delta": 6, "coverage_raw": 4, "coverage_adj": 4,
    "y_cal": 6, "alpha_ew": 6, "beta_ew": 4, "lam": 6,
    # Counts
    "n_predictions": 0, "n_fits": 0, "horizon": 0, "step": 0,
    "fold": 0, "n": 0, "n_steps": 0, "n_tickers": 0, "n_total": 0,
    "sign_flips": 0,
}


def round_for_output(
    df: pd.DataFrame,
    schema: Optional[Dict[str, int]] = None,
) -> pd.DataFrame:
    """
    Return a copy of *df* with float columns rounded per *schema*.

    Columns absent from *schema* are left untouched (no surprise rounding).
    Integer-target columns (decimals == 0) are cast to nullable Int64.
    """
    schema = schema if schema is not None else DECIMAL_PRECISION
    out = df.copy()
    for col, decimals in schema.items():
        if col not in out.columns:
            continue
        if decimals == 0:
            out[col] = pd.to_numeric(out[col], errors="coerce").round(0).astype("Int64")
        else:
            out[col] = pd.to_numeric(out[col], errors="coerce").round(decimals)
    return out


def round_scalar(val, decimals: int):
    """Round a single value, returning None for NaN/Inf/None."""
    if val is None:
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return val
    if np.isnan(f) or np.isinf(f):
        return None
    return round(f, decimals)


def round_json_dict(payload, schema: Optional[Dict[str, int]] = None):
    """
    Recursively round numeric leaves in a JSON-style payload.

    Keys present in *schema* drive the decimal count. Numeric values under
    keys not in the schema fall through unchanged; lists of floats are
    rounded only when the parent key is in the schema.
    """
    schema = schema if schema is not None else DECIMAL_PRECISION

    def _walk(obj, key=None):
        if isinstance(obj, dict):
            return {k: _walk(v, k) for k, v in obj.items()}
        if isinstance(obj, list):
            if key in schema:
                d = schema[key]
                return [round_scalar(v, d) if isinstance(v, (int, float, np.floating)) else _walk(v, key) for v in obj]
            return [_walk(v, key) for v in obj]
        if isinstance(obj, (float, np.floating)):
            if key in schema:
                return round_scalar(obj, schema[key])
            return obj
        return obj

    return _walk(payload)


# ---------------------------------------------------------------------------
# Black-Scholes
# ---------------------------------------------------------------------------

def bs_price(S, K, T, r, sigma, type_="call"):
    """European option price via Black-Scholes."""
    if T <= 1e-5:
        return max(0, S - K) if type_ == "call" else max(0, K - S)
    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    if type_ == "call":
        return S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
    return K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)


def implied_vol(S, K, T, r, price, type_="call"):
    """Invert Black-Scholes for implied volatility via Brent's method."""
    intrinsic = max(0, S - K if type_ == "call" else K - S)
    if price <= intrinsic:
        return 0.0
    try:
        return brentq(
            lambda sigma: bs_price(S, K, T, r, sigma, type_) - price,
            1e-4, 5.0, xtol=1e-6,
        )
    except (ValueError, RuntimeError):
        return np.nan


# ---------------------------------------------------------------------------
# Monte Carlo cone  (from volarbmodel_backtest.py:528-546)
# ---------------------------------------------------------------------------

def monte_carlo_cone(S0, sigma, T, rmse_vol, r=0.0359, n_sims=500):
    """
    Generate a price cone via GBM with stochastic vol shocks.

    Returns
    -------
    chart_data : dict   {"p95", "p05", "mean", "steps"}
    tail_risk  : float  5th-percentile terminal price
    """
    steps = max(5, int(T * 252))
    dt = T / steps
    paths = np.zeros((n_sims, steps + 1))
    paths[:, 0] = S0

    for t in range(1, steps + 1):
        shock_vol = np.maximum(0.01, sigma + np.random.normal(0, rmse_vol, n_sims))
        z = np.random.standard_normal(n_sims)
        paths[:, t] = paths[:, t - 1] * np.exp(
            (r - 0.5 * shock_vol ** 2) * dt + shock_vol * np.sqrt(dt) * z
        )

    p95 = np.percentile(paths, 95, axis=0)
    p05 = np.percentile(paths, 5, axis=0)
    mean_path = np.mean(paths, axis=0)

    chart_data = {
        "p95": p95.tolist(),
        "p05": p05.tolist(),
        "mean": mean_path.tolist(),
        "steps": list(range(steps + 1)),
    }
    return chart_data, float(p05[-1])


# ---------------------------------------------------------------------------
# FOMC Calendar  (from volarbmodel_backtest.py:91-97)
# ---------------------------------------------------------------------------

# Extend annually as new dates are announced.
# Historical dates are the announcement/decision day of each FOMC meeting.
# 2026+ dates are scheduled projections — verify as they are confirmed.
FOMC_DATES = sorted([
    datetime.strptime(d, "%Y-%m-%d").date()
    for d in [
        # 2014
        "2014-01-29", "2014-03-19", "2014-04-30", "2014-06-18",
        "2014-07-30", "2014-09-17", "2014-10-29", "2014-12-17",
        # 2015
        "2015-01-28", "2015-03-18", "2015-04-29", "2015-06-17",
        "2015-07-29", "2015-09-17", "2015-10-28", "2015-12-16",
        # 2016
        "2016-01-27", "2016-03-16", "2016-04-27", "2016-06-15",
        "2016-07-27", "2016-09-21", "2016-11-02", "2016-12-14",
        # 2017
        "2017-02-01", "2017-03-15", "2017-05-03", "2017-06-14",
        "2017-07-26", "2017-09-20", "2017-11-01", "2017-12-13",
        # 2018
        "2018-01-31", "2018-03-21", "2018-05-02", "2018-06-13",
        "2018-08-01", "2018-09-26", "2018-11-08", "2018-12-19",
        # 2019
        "2019-01-30", "2019-03-20", "2019-05-01", "2019-06-19",
        "2019-07-31", "2019-09-18", "2019-10-30", "2019-12-11",
        # 2020 — includes two emergency cuts (Mar 3 and Mar 15)
        "2020-01-29", "2020-03-03", "2020-03-15", "2020-04-29",
        "2020-06-10", "2020-07-29", "2020-09-16", "2020-11-05",
        "2020-12-16",
        # 2021
        "2021-01-27", "2021-03-17", "2021-04-28", "2021-06-16",
        "2021-07-28", "2021-09-22", "2021-11-03", "2021-12-15",
        # 2022
        "2022-01-26", "2022-03-16", "2022-05-04", "2022-06-15",
        "2022-07-27", "2022-09-21", "2022-11-02", "2022-12-14",
        # 2023
        "2023-02-01", "2023-03-22", "2023-05-03", "2023-06-14",
        "2023-07-26", "2023-09-20", "2023-11-01", "2023-12-13",
        # 2024
        "2024-01-31", "2024-03-20", "2024-05-01", "2024-06-12",
        "2024-07-31", "2024-09-18", "2024-11-07", "2024-12-18",
        # 2025
        "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18",
        "2025-07-30", "2025-09-17", "2025-10-29", "2025-12-10",
        # 2026 (scheduled — update as confirmed)
        "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
        "2026-07-29", "2026-09-16", "2026-11-04", "2026-12-16",
    ]
])


def days_to_next_fomc(target_date):
    """Business-day-agnostic distance to next FOMC meeting."""
    if isinstance(target_date, datetime):
        target_date = target_date.date()
    future = [d for d in FOMC_DATES if d >= target_date]
    if not future:
        return 100
    return (future[0] - target_date).days


# ---------------------------------------------------------------------------
# CPI Release Calendar  (Bureau of Labor Statistics)
# ---------------------------------------------------------------------------
# CPI is released ~mid-month (10th-15th). Generated programmatically;
# accurate to +/-2 days which is negligible for 1/(days+1) gravity features.

def _mid_month_weekday(year, month, target_day=13):
    """Nearest weekday to target_day of the month."""
    d = date(year, month, target_day)
    if d.weekday() == 5:    # Saturday -> Monday
        d += timedelta(days=2)
    elif d.weekday() == 6:  # Sunday -> Monday
        d += timedelta(days=1)
    return d


CPI_DATES = sorted([
    _mid_month_weekday(y, m)
    for y in range(2014, 2027)
    for m in range(1, 13)
])


def days_to_next_cpi(target_date):
    """Distance in calendar days to next CPI release."""
    if isinstance(target_date, datetime):
        target_date = target_date.date()
    future = [d for d in CPI_DATES if d >= target_date]
    if not future:
        return 100
    return (future[0] - target_date).days


# ---------------------------------------------------------------------------
# NFP (Nonfarm Payrolls) Calendar  (BLS Employment Situation)
# ---------------------------------------------------------------------------
# Released first Friday of each month.

def _first_friday(year, month):
    """First Friday of a given month."""
    d = date(year, month, 1)
    days_ahead = (4 - d.weekday()) % 7  # Friday = weekday 4
    return d + timedelta(days=days_ahead)


NFP_DATES = sorted([
    _first_friday(y, m)
    for y in range(2014, 2027)
    for m in range(1, 13)
])


def days_to_next_nfp(target_date):
    """Distance in calendar days to next NFP release."""
    if isinstance(target_date, datetime):
        target_date = target_date.date()
    future = [d for d in NFP_DATES if d >= target_date]
    if not future:
        return 100
    return (future[0] - target_date).days
