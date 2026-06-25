"""Pure unit tests for backend.distributions.build_distribution_data.

No DB / no creds — the function is pure compute over already-fetched volatility_history rows.
Fixtures are deterministic so bin counts, percentiles, mean/stdev, windowing, and the
MIN_SAMPLES omission can be asserted exactly.
"""

import statistics
from datetime import date, timedelta

import pytest

from backend.distributions import (
    LOOKBACKS,
    MIN_SAMPLES,
    NUM_BINS,
    build_distribution_data,
)

LATEST = date(2026, 6, 1)


def _rows(latest=LATEST, *, rv=None, iv=None, vrp=None, n=None):
    """Build `n` consecutive daily volatility_history rows ENDING at `latest`.

    Each value list is oldest -> newest (so the last element lands on `latest`). A `None` entry
    leaves that metric null for the day; an omitted list leaves the metric null for every day.
    """
    length = n if n is not None else len(rv if rv is not None else iv if iv is not None else vrp)
    start = latest - timedelta(days=length - 1)

    def cell(seq, i):
        return seq[i] if seq is not None else None

    return [
        {
            "date": (start + timedelta(days=i)).isoformat(),
            "rv": cell(rv, i),
            "iv_atm": cell(iv, i),
            "vrp_wedge": cell(vrp, i),
        }
        for i in range(length)
    ]


def _set(result, metric, lookback):
    return next(s for s in result if s["metric"] == metric and s["lookback"] == lookback)


def _set_list(result, metric):
    return [s for s in result if s["metric"] == metric]


# --- shape, tagging, bin invariants ------------------------------------------


def test_bins_sum_shape_and_contiguous_edges():
    rows = _rows(rv=list(range(40)))  # 40 rows, all within 1Y -> every lookback included
    result = build_distribution_data(rows)

    rv_sets = [s for s in result if s["metric"] == "rv"]
    assert len(rv_sets) == len(LOOKBACKS)  # one per lookback
    # iv/vrp are null in this fixture, so no sets for them
    assert not [s for s in result if s["metric"] in ("iv", "vrp")]

    for s in rv_sets:
        assert s["scope"] == "stock"
        assert s["lookback"] in LOOKBACKS
        assert len(s["bins"]) == NUM_BINS
        # counts always sum back to the sample size
        assert sum(b["count"] for b in s["bins"]) == 40
        # equal-width, contiguous edges spanning [min, max]
        for a, b in zip(s["bins"], s["bins"][1:]):
            assert a["bin_high"] == pytest.approx(b["bin_low"])
        assert s["bins"][0]["bin_low"] == pytest.approx(0)
        assert s["bins"][-1]["bin_high"] == pytest.approx(39)


def test_known_uniform_histogram_counts():
    # 45 evenly-spaced values -> NUM_BINS (15) equal-width bins of 3 each (max lands in last bin).
    result = build_distribution_data(_rows(rv=list(range(45))))
    counts = [b["count"] for b in _set(result, "rv", "MAX")["bins"]]
    assert counts == [3] * NUM_BINS


def test_all_three_metrics_tagged():
    rows = _rows(rv=list(range(40)), iv=list(range(40)), vrp=list(range(40)))
    result = build_distribution_data(rows)
    metrics = {s["metric"] for s in result}
    assert metrics == {"rv", "iv", "vrp"}
    # 3 metrics x 4 lookbacks
    assert len(result) == 3 * len(LOOKBACKS)
    for s in result:
        assert s["scope"] == "stock"


# --- current value / percentile / mean / stdev -------------------------------


def test_current_value_stats_when_latest_is_max():
    vals = list(range(40))
    one = _set(build_distribution_data(_rows(rv=vals)), "rv", "MAX")
    assert one["current_value"] == 39  # latest (newest date) non-null value
    assert one["current_percentile"] == pytest.approx(100.0)  # max -> 100th pctl
    assert one["mean"] == pytest.approx(statistics.mean(vals))
    assert one["stdev"] == pytest.approx(statistics.stdev(vals))


def test_current_percentile_midrange():
    # Same value set, but force the NEWEST day to carry 20 so current_value = 20.
    seq = [v for v in range(40) if v != 20] + [20]
    one = _set(build_distribution_data(_rows(rv=seq)), "rv", "MAX")
    assert one["current_value"] == 20
    # weak percentile: share of observations <= 20 = {0..20} = 21 of 40
    assert one["current_percentile"] == pytest.approx(100.0 * 21 / 40)


# --- MIN_SAMPLES omission ----------------------------------------------------


def test_combo_below_min_samples_is_omitted():
    short = MIN_SAMPLES - 1
    rv = [float(i) for i in range(short)] + [None] * 11  # 29 non-null rv
    iv = list(range(short + 11))  # 40 non-null iv
    result = build_distribution_data(_rows(rv=rv, iv=iv, n=short + 11))

    assert not [s for s in result if s["metric"] == "rv"]  # rv dropped everywhere
    assert len(_set_list(result, "iv")) == len(LOOKBACKS)  # iv kept


# --- date windowing ----------------------------------------------------------


def test_lookback_windows_select_by_date():
    # ~2.2 years of consecutive daily rows ending 2026-06-01: each lookback selects an exact,
    # date-bounded subset (inclusive of both ends). 5Y/MAX cover all 800.
    n = 800
    result = build_distribution_data(_rows(rv=list(range(n)), n=n))
    sums = {
        s["lookback"]: sum(b["count"] for b in s["bins"]) for s in result if s["metric"] == "rv"
    }
    assert sums == {
        "3M": 92,  # 2026-03-02 .. 2026-06-01
        "6M": 183,  # 2025-12-01 .. 2026-06-01
        "YTD": 152,  # 2026-01-01 .. 2026-06-01 (calendar year-to-date)
        "1Y": 366,  # 2025-06-01 .. 2026-06-01
        "2Y": 731,  # 2024-06-01 .. 2026-06-01
        "5Y": 800,  # window wider than the data -> all rows
        "MAX": 800,  # every row
    }


def test_ytd_window_uses_calendar_year_not_trailing_days():
    # Rows straddle a year boundary (2025-10-01 .. 2026-03-15). YTD must cut at 2026-01-01,
    # not "365 days back": Jan(31) + Feb(28) + Mar 1..15(15) = 74 rows.
    n = (date(2026, 3, 15) - date(2025, 10, 1)).days + 1
    result = build_distribution_data(_rows(date(2026, 3, 15), rv=list(range(n)), n=n))
    ytd = _set(result, "rv", "YTD")
    assert sum(b["count"] for b in ytd["bins"]) == 74


# --- never raises ------------------------------------------------------------


def test_empty_none_and_unparseable_return_empty():
    assert build_distribution_data([]) == []
    assert build_distribution_data(None) == []
    assert build_distribution_data([{"date": None, "rv": 1.0}]) == []


def test_non_numeric_metric_cells_are_skipped_not_raised():
    # A stray non-numeric cell must not raise; it's just skipped (so is None). Pad with good values.
    rv = [float(i) for i in range(MIN_SAMPLES)] + ["oops", None]
    result = build_distribution_data(_rows(rv=rv, n=MIN_SAMPLES + 2))
    one = _set(result, "rv", "MAX")
    # only the MIN_SAMPLES numeric values survive; the string and None are dropped.
    assert sum(b["count"] for b in one["bins"]) == MIN_SAMPLES
