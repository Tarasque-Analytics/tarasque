"""
utils.py — Shared helpers used across the pipeline.

Ported from volarbmodel_backtest.py: clean_num (:35-42), QuantLib (:517-546),
EventCalendar (:91-97).
"""
import numpy as np
import pandas as pd
from datetime import datetime, date
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
FOMC_DATES = sorted([
    datetime.strptime(d, "%Y-%m-%d").date()
    for d in [
        "2025-12-17",
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
