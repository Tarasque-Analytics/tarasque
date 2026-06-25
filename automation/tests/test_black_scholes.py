"""Unit tests for the Black-Scholes delta helper (pure). Run: python -m pytest automation/tests"""

from __future__ import annotations

from automation.black_scholes import bs_delta


def test_atm_call_and_put_deltas_are_sensible():
    # ATM, ~0.5 / ~-0.5 delta region.
    c = bs_delta(100.0, 100.0, 30, 0.25, "C", r=0.0, q=0.0)
    p = bs_delta(100.0, 100.0, 30, 0.25, "P", r=0.0, q=0.0)
    assert c is not None and p is not None
    assert 0.4 < c < 0.6
    assert -0.6 < p < -0.4
    # Put-call parity for delta (q=0): call_delta - put_delta == 1.
    assert abs((c - p) - 1.0) < 1e-9


def test_deep_itm_call_delta_near_one():
    c = bs_delta(200.0, 100.0, 30, 0.25, "call", r=0.045)
    assert c is not None and c > 0.95


def test_deep_otm_call_delta_near_zero():
    c = bs_delta(50.0, 100.0, 30, 0.25, "C", r=0.045)
    assert c is not None and c < 0.05


def test_degenerate_inputs_return_none():
    assert bs_delta(None, 100.0, 30, 0.25, "C") is None
    assert bs_delta(100.0, 100.0, 0, 0.25, "C") is None  # DTE <= 0
    assert bs_delta(100.0, 100.0, 30, 0.0, "C") is None  # iv <= 0
    assert bs_delta(100.0, 100.0, 30, 0.25, "X") is None  # bad option type
