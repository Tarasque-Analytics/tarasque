"""
black_scholes.py — minimal, dependency-free Black-Scholes greeks.

Used to fill `options_chain.delta` when the data provider supplies IV but no greeks (yfinance). Kept
self-contained (only the stdlib `math`) so `automation` doesn't depend on the `model/` package or
scipy. The model's `model/pipeline/utils.py` BS is the conceptual reference; we deliberately don't
import it (package-boundary hygiene — see OPTIONS_IMPORT_PLAN.md §5).

Approximations (documented, acceptable for a UI greeks column): dividend yield q ≈ 0, a single
risk-free rate r. Revisit if delta is ever used for pricing rather than display.
"""
from __future__ import annotations

import math
from typing import Optional

# Trading-day vs calendar-day: we use calendar days / 365 for time-to-expiry, matching how option
# DTE is quoted to users.
DAYS_PER_YEAR = 365.0


def _norm_cdf(x: float) -> float:
    """Standard normal CDF via the error function (no scipy)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_delta(
    spot: Optional[float],
    strike: Optional[float],
    dte_days: Optional[float],
    iv: Optional[float],
    option_type: str,
    *,
    r: float = 0.045,
    q: float = 0.0,
) -> Optional[float]:
    """
    Black-Scholes delta for one option.

    Parameters
    ----------
    spot, strike : underlying price and strike.
    dte_days     : calendar days to expiry.
    iv           : implied volatility (annualized, decimal — e.g. 0.23).
    option_type  : 'C'/'call' or 'P'/'put' (case-insensitive).
    r, q         : risk-free rate and dividend yield (annualized, decimal).

    Returns the delta, or **None** when inputs are degenerate (missing IV/spot/strike, non-positive
    values, or DTE ≤ 0) — we never fabricate a greek from bad inputs.
    """
    if spot is None or strike is None or iv is None or dte_days is None:
        return None
    if spot <= 0 or strike <= 0 or iv <= 0 or dte_days <= 0:
        return None

    t = dte_days / DAYS_PER_YEAR
    try:
        d1 = (math.log(spot / strike) + (r - q + 0.5 * iv * iv) * t) / (iv * math.sqrt(t))
    except (ValueError, ZeroDivisionError):
        return None

    disc = math.exp(-q * t)
    ot = option_type.strip().upper()[:1]
    if ot == "C":
        return disc * _norm_cdf(d1)
    if ot == "P":
        return disc * (_norm_cdf(d1) - 1.0)
    return None
