"""
expiry_selection.py — choose which option expiries to fetch (CLAUDE.md §5).

Pure functions over an available-expiry list + today. The default preset is **A + front monthlies**:
the expiry nearest each constant-maturity term point (30/60/90/180 DTE) UNION the next 1–2 standard
monthlies (3rd Friday). This keeps the heaviest cost driver (expiries × strikes) deliberately small
while serving both a useful term structure and liquid near-term expiries for the chain display.

No network, no I/O — trivially testable.
"""

from __future__ import annotations

from datetime import date

DEFAULT_TERM_DTE_TARGETS: tuple[int, ...] = (30, 60, 90, 180)
DEFAULT_FRONT_MONTHLIES: int = 2


def dte(today: date, expiry: date) -> int:
    """Calendar days to expiry."""
    return (expiry - today).days


def is_standard_monthly(d: date) -> bool:
    """
    True if `d` is a standard monthly expiration — the 3rd Friday of its month.

    The 3rd Friday always falls on day-of-month 15–21, so: weekday == Friday and 15 ≤ day ≤ 21.
    """
    return d.weekday() == 4 and 15 <= d.day <= 21


def select_expiries(
    available: list[date],
    today: date,
    *,
    term_dte_targets: tuple[int, ...] = DEFAULT_TERM_DTE_TARGETS,
    front_monthlies: int = DEFAULT_FRONT_MONTHLIES,
) -> list[date]:
    """
    Return the sorted set of expiries to fetch (preset A + front monthlies).

    - **Term points:** for each target DTE, the available future expiry minimizing |DTE − target|.
    - **Front monthlies:** the next `front_monthlies` standard monthly expiries.
    - Union, dedupe, sort ascending.

    Degenerate inputs never raise: with no future expiries returns []; with fewer expiries than
    targets, just returns what exists.
    """
    future = sorted(d for d in available if d > today)
    if not future:
        return []

    chosen: set[date] = set()

    # Term points — nearest available expiry to each constant-maturity target.
    for target in term_dte_targets:
        nearest = min(future, key=lambda d: abs(dte(today, d) - target))
        chosen.add(nearest)

    # Front monthlies — the next N standard (3rd-Friday) expiries.
    monthlies = [d for d in future if is_standard_monthly(d)]
    for d in monthlies[: max(0, front_monthlies)]:
        chosen.add(d)

    return sorted(chosen)
