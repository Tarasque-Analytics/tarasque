"""Unit tests for expiry selection (pure; no network). Run: python -m pytest automation/tests"""
from __future__ import annotations

from datetime import date, timedelta

from automation.expiry_selection import is_standard_monthly, select_expiries


def test_is_standard_monthly_third_friday():
    # 2026-06-19 is the 3rd Friday of June 2026.
    assert is_standard_monthly(date(2026, 6, 19)) is True
    # A Friday that is the 1st/2nd Friday is not a standard monthly.
    assert is_standard_monthly(date(2026, 6, 12)) is False
    # A non-Friday is never a standard monthly.
    assert is_standard_monthly(date(2026, 6, 18)) is False


def test_select_picks_nearest_to_each_term_point():
    today = date(2026, 6, 9)
    # Weekly-ish ladder spanning the term points.
    available = [today + timedelta(days=d) for d in (7, 28, 35, 63, 92, 120, 178, 200, 365)]
    chosen = select_expiries(available, today, term_dte_targets=(30, 60, 90, 180), front_monthlies=0)
    chosen_dte = sorted((d - today).days for d in chosen)
    # Nearest to 30→28, 60→63, 90→92, 180→178.
    assert chosen_dte == [28, 63, 92, 178]


def test_select_unions_front_monthlies_and_dedupes_and_sorts():
    today = date(2026, 6, 9)
    third_fri_jun = date(2026, 6, 19)   # ~10 DTE, a standard monthly
    third_fri_jul = date(2026, 7, 17)   # ~38 DTE, a standard monthly
    available = [third_fri_jun, third_fri_jul, today + timedelta(days=90), today + timedelta(days=180)]
    chosen = select_expiries(available, today, term_dte_targets=(90, 180), front_monthlies=2)
    # term points (90,180) ∪ front 2 monthlies (Jun,Jul), sorted, no dupes.
    assert chosen == sorted(set(available))
    assert chosen == sorted(chosen)


def test_select_handles_empty_and_past_only():
    today = date(2026, 6, 9)
    assert select_expiries([], today) == []
    # Only past expiries → nothing selected.
    assert select_expiries([today - timedelta(days=5)], today) == []
