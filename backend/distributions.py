"""
Pure, dependency-free distribution computation for the GET /api/equity/{symbol} payload.

Builds per-security frequency histograms of RV / IV / VRP over selectable lookbacks straight
from the `volatility_history` rows that the aggregator has *already fetched* — no Supabase
client, no Postgres RPC, no extra DB query. The original cross-sectional `get_distribution` RPC
hit a statement timeout (code 57014) and was disabled; this replaces it for **stock scope**
(sector/market deferred).

Design contract:
  - This module is PURE COMPUTE. It imports no Supabase client, so it cannot cross the
    read/write client boundary (see backend/CLAUDE.md). Only the stdlib `statistics` module is
    used — no numpy/scipy.
  - `build_distribution_data` MUST NEVER RAISE. It returns `[]` on no/empty/garbage data so it
    can't fail the composite `/api/equity` payload that runs under one `asyncio.gather`.

Each returned set is one (scope, metric, lookback) histogram with current value / percentile /
mean / stdev overlays, shaped for `DistributionSet` in app/utils/database.ts.
"""
from __future__ import annotations

import statistics
from datetime import date as _date, timedelta

# Frontend metric key -> source column in volatility_history.
# (IV uses the at-the-money `iv_atm` column; RV the realized `rv`; VRP the `vrp_wedge` premium.)
METRICS: dict[str, str] = {
    "rv": "rv",
    "iv": "iv_atm",
    "vrp": "vrp_wedge",
}

# Lookback label -> window length in days (None = MAX / every available row). Short windows
# (1M/3M/6M/YTD) are intentionally omitted — too few points for a 10-bin histogram.
LOOKBACKS: dict[str, int | None] = {
    "1Y": 365,
    "2Y": 730,
    "5Y": 1825,
    "MAX": None,
}

# Minimum non-null samples in a window for a histogram to be meaningful. Below this the
# (metric, lookback) combo is omitted entirely, so the frontend shows an empty state for it.
MIN_SAMPLES = 30

# Number of equal-width frequency bins ("deciles" in #128 = 10 buckets, not equal-count quantiles).
NUM_BINS = 10


def _parse_date(value) -> _date | None:
    """Best-effort parse of a `volatility_history.date` cell to a `date` (returns None if it
    can't be parsed). Supabase serializes the column to an ISO string; tolerate a `date` too."""
    if isinstance(value, _date):
        return value
    if isinstance(value, str) and value:
        try:
            return _date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _build_set(values: list[float], current_value: float, *, metric: str, lookback: str) -> dict:
    """Build one distribution set from the window's ordered, non-null metric values.

    `values` is every non-null observation in the window; `current_value` is the latest non-null
    one (already extracted by the caller). Always emits exactly NUM_BINS equal-width bins so the
    counts sum to len(values).
    """
    lo = min(values)
    hi = max(values)
    span = hi - lo
    # Equal-width bins. If the window is perfectly flat (span == 0, e.g. a constant series) there
    # is no width to bin by — collapse everything into the first bin and keep 10 (zero-width) bins
    # so the shape is stable for the frontend.
    width = span / NUM_BINS if span > 0 else 0.0

    counts = [0] * NUM_BINS
    for v in values:
        if width > 0:
            idx = int((v - lo) / width)
            if idx >= NUM_BINS:  # the maximum value lands in the last bin, not a phantom 11th
                idx = NUM_BINS - 1
            elif idx < 0:
                idx = 0
        else:
            idx = 0
        counts[idx] += 1

    bins = [
        {
            "bin_low": lo + i * width,
            "bin_high": lo + (i + 1) * width,
            "count": counts[i],
        }
        for i in range(NUM_BINS)
    ]

    # Weak percentile rank of the current value within the window: share of observations at or
    # below it (so the max sits at 100, a unique min near 0).
    at_or_below = sum(1 for v in values if v <= current_value)
    current_percentile = 100.0 * at_or_below / len(values)

    return {
        "scope": "stock",
        "metric": metric,
        "lookback": lookback,
        "current_value": current_value,
        "current_percentile": current_percentile,
        "mean": statistics.mean(values),
        # Sample stdev (n-1); the window always has >= MIN_SAMPLES points so this is well-defined.
        "stdev": statistics.stdev(values),
        "bins": bins,
    }


def build_distribution_data(vol_rows: list[dict]) -> list[dict]:
    """Compute all stock-scope (metric x lookback) distribution sets from volatility_history rows.

    Args:
        vol_rows: rows as returned by get_volatility_history (dicts with `date` plus the metric
            columns). Order is not assumed.

    Returns:
        A flat list of distribution sets. Combos with fewer than MIN_SAMPLES non-null observations
        are omitted (the frontend renders an empty state for them). Returns `[]` on any failure —
        this function never raises, so it can't break the composite /api/equity payload.
    """
    try:
        if not vol_rows:
            return []

        # Attach a parsed date to each usable row; rows with an unparseable/missing date are dropped.
        dated: list[tuple[_date, dict]] = []
        for row in vol_rows:
            d = _parse_date(row.get("date"))
            if d is not None:
                dated.append((d, row))
        if not dated:
            return []

        dated.sort(key=lambda dr: dr[0])  # oldest -> newest
        latest = dated[-1][0]

        sets: list[dict] = []
        for metric, column in METRICS.items():
            for lookback, days in LOOKBACKS.items():
                if days is None:
                    window = dated
                else:
                    cutoff = latest - timedelta(days=days)
                    window = [dr for dr in dated if dr[0] >= cutoff]

                # Non-null metric values in date order; current = latest non-null in the window.
                values: list[float] = []
                current_value: float | None = None
                for _, row in window:
                    raw = row.get(column)
                    if raw is None:
                        continue
                    try:
                        v = float(raw)
                    except (TypeError, ValueError):
                        continue
                    values.append(v)
                    current_value = v  # ascending order -> last seen is the most recent

                if len(values) < MIN_SAMPLES or current_value is None:
                    continue

                sets.append(_build_set(values, current_value, metric=metric, lookback=lookback))

        return sets
    except Exception:  # pragma: no cover - defensive: never fail the composite payload
        return []
