"""
ttm_smooth.py — TTM construction + per-share legs + 20Q cyclical smoothing.

Inputs: the per-period DataFrame from xbrl_extract.extract_facts.
Outputs: same frame with the 4 raw RAFI legs plus the 2 smoothed cyclical legs.

Pipeline (per spec)
-------------------
  revenue_ttm = trailing-4Q sum of revenue_q
  ocf_ttm     = trailing-4Q sum of ocf_q
  dps_ttm     = trailing-4Q sum of dps_q  (already per-share; TTM is just sum)

  rev_ps   = revenue_ttm / shares       (cyclical → smoothed below)
  ocf_ps   = ocf_ttm     / shares       (cyclical → smoothed below)
  book_ps  = equity      / shares       (stable; left raw per spec)
  dps      = dps_ttm                    (stable; left raw per spec)

  rev_ps_smoothed = trailing-20Q mean of rev_ps   (5yr lookback)
  ocf_ps_smoothed = trailing-20Q mean of ocf_ps

Per-share convention: divide TTM dollars by TODAY's shares (point-in-time). Spec
is explicit: "Per-share is mandatory — it matches price-per-share and neutralizes
buybacks/dilution." This gives "rev/ocf per share assuming today's share count
held through the trailing 12 months" — the right gauge against a current price.

The 4 raw + 2 smoothed = the inputs to composite.py.
"""
from __future__ import annotations

import pandas as pd


TTM_WINDOW = 4         # quarters in a trailing 12 months
SMOOTH_WINDOW = 20     # quarters in a 5-year cyclical smoother
SMOOTH_MIN_PERIODS = 1    # Smoothed = raw when only 1 observation in window;
                          # converges to true 5yr trailing mean once 20Q accumulate.
                          # Strict 8 broke recent spinoffs / IPOs (ABBV had 2Q
                          # at canonical → all legs NaN). With min_periods=1
                          # every firm gets a canonical-1.0 anchor as long as
                          # ANY data exists pre-canonical; the smoothing
                          # "warms up" naturally as more quarters land.
                          # For firms with full pre-canonical history (CVX,
                          # JNJ, etc.) the value at canonical is identical to
                          # min_periods=8 because there are >= 8 obs there.

# Split detection bounds. Forward splits 2:1 through 30:1 are common; reverse
# splits 1:2 through 1:30 likewise. Tolerance: ratio must be within 5% of an
# integer (or 1/integer) to count as a split — keeps buybacks (~1-3%/qtr) and
# secondary offerings (5-15%) out of the false-positive set.
MIN_SPLIT_RATIO = 2.0
MAX_SPLIT_RATIO = 30.0
SPLIT_TOLERANCE = 0.05


def compute_per_share_legs(facts: pd.DataFrame) -> pd.DataFrame:
    """Add TTM, per-share, and smoothed columns to a per-period facts frame.

    Args:
      facts: DataFrame with one row per period_end (output of extract_facts).
             Required columns: period_end, revenue_q, ocf_q, equity, shares, dps_q.

    Returns:
      A copy with the following columns added:
        revenue_ttm, ocf_ttm, dps_ttm           (4-quarter trailing sums)
        rev_ps, ocf_ps, book_ps, dps            (4 raw RAFI legs)
        rev_ps_smoothed, ocf_ps_smoothed        (20Q cyclical smooth)
    """
    df = facts.sort_values('period_end').reset_index(drop=True).copy()

    # Coerce flow columns to numeric float — XBRL extract may leave pd.NA
    # placeholders for tags entirely absent from a filer's submission (e.g.
    # JNJ has no CommonStockDividendsPerShareDeclared tag historically), and
    # pd.NA in an object column breaks pandas rolling. np.nan is safe.
    for col in ('revenue_q', 'ocf_q', 'dps_q', 'equity', 'shares'):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    # ffill shares: many filers report shares only in 10-Ks (annually) or
    # in some 10-Qs but not others. The share count is stable quarter-to-
    # quarter (small buybacks/issuance aside) — carrying the last known
    # value forward gives valid per-share legs without inventing data.
    df['shares'] = df['shares'].ffill()

    # Split adjustment. XBRL's shares-outstanding does NOT auto-adjust for
    # splits, but adj_close does. To keep per-share legs comparable to the
    # split-adjusted price series, back-adjust historical shares AND dps_q
    # by the cumulative split factor. Detection: a shares ratio close to
    # an integer in [2, 30] (forward split) or 1/N (reverse split). Buybacks
    # and secondary offerings sit outside this window and are not flagged.
    df = _split_adjust(df)

    # dps_q gap fill: many issuers' 10-Ks don't publish a per-share dividends
    # tag with a 12-month duration — only the 10-Qs do. That leaves Q4 NaN
    # every year and the TTM sum NaN-propagates. Per spec dps is the "stable"
    # leg; forward-fill the last known quarterly rate within each firm's
    # series so Q4 inherits Q3's rate (matches the common-practice
    # "dividend rate continues unchanged" baseline).
    df['dps_q_filled'] = df['dps_q'].ffill()

    df['revenue_ttm'] = df['revenue_q'].rolling(TTM_WINDOW, min_periods=TTM_WINDOW).sum()
    df['ocf_ttm']     = df['ocf_q'].rolling(TTM_WINDOW, min_periods=TTM_WINDOW).sum()
    df['dps_ttm']     = df['dps_q_filled'].rolling(TTM_WINDOW, min_periods=TTM_WINDOW).sum()

    # Per-share — divide TTM dollars (and equity for book) by point-in-time shares.
    # Use the split-adjusted shares so the series stays continuous through splits.
    shares = pd.to_numeric(df['shares'], errors='coerce')
    df['rev_ps']  = pd.to_numeric(df['revenue_ttm'], errors='coerce') / shares
    df['ocf_ps']  = pd.to_numeric(df['ocf_ttm'],     errors='coerce') / shares
    df['book_ps'] = pd.to_numeric(df['equity'],      errors='coerce') / shares
    df['dps']     = pd.to_numeric(df['dps_ttm'],     errors='coerce')

    # Smooth ALL 4 legs with the 20Q trailing window. Spec language said only
    # cyclical legs need smoothing, but in practice book_ps + dps step
    # discontinuously at M&A events (e.g. CVX Hess Q3 2025: shares +16%,
    # equity +30%, book_ps jumps in a single quarter). Without smoothing,
    # the RAFI composite shows a sharp step at the M&A. Per the validated
    # CVX visual reference (gentle rise rather than step at Hess close),
    # all 4 legs share the 5yr smoother. Structural break flag still
    # surfaces the underlying event for chart annotation.
    for col in ('rev_ps', 'ocf_ps', 'book_ps', 'dps'):
        df[f'{col}_smoothed'] = (
            df[col].rolling(SMOOTH_WINDOW, min_periods=SMOOTH_MIN_PERIODS).mean()
        )

    return df


def _split_adjust(df: pd.DataFrame) -> pd.DataFrame:
    """Back-adjust historical shares + dps_q for stock splits.

    Forward N-for-1 split: post-split shares = N × pre-split shares. To restore
    a continuous series on the POST-split basis, multiply all pre-split shares
    by N and divide pre-split dps_q (per-share value) by N. Multiple splits
    compound their factors.

    Reverse 1-for-N: divide pre-split shares by N, multiply pre-split dps_q by N.

    Detection: ratio of consecutive shares values must land within 5% of an
    integer in [MIN_SPLIT_RATIO, MAX_SPLIT_RATIO]. Excludes buybacks and
    offerings.
    """
    if 'shares' not in df.columns or df['shares'].isna().all():
        return df
    sh = pd.to_numeric(df['shares'], errors='coerce')
    ratios = (sh / sh.shift(1)).fillna(1.0)

    # Build cumulative split factor that walks BACKWARD: each row's factor is
    # the product of all split ratios from later splits. Pre-split rows end up
    # with factor = N (for an N-for-1 forward split that happens after them);
    # post-split rows have factor = 1.0.
    factors = pd.Series(1.0, index=df.index)
    cum = 1.0
    for i in range(len(df) - 1, 0, -1):
        r = ratios.iloc[i]
        if not pd.isna(r) and r > 0:
            if MIN_SPLIT_RATIO <= r <= MAX_SPLIT_RATIO:
                nearest = round(r)
                if abs(r - nearest) < SPLIT_TOLERANCE * nearest:
                    cum *= nearest
            elif 1 / MAX_SPLIT_RATIO <= r <= 1 / MIN_SPLIT_RATIO:
                recip = 1.0 / r
                nearest = round(recip)
                if abs(recip - nearest) < SPLIT_TOLERANCE * nearest:
                    cum /= nearest
        factors.iloc[i - 1] = cum

    df['shares'] = sh * factors
    if 'dps_q' in df.columns:
        dps = pd.to_numeric(df['dps_q'], errors='coerce')
        df['dps_q'] = dps / factors
    return df


def detect_structural_breaks(facts: pd.DataFrame,
                              joint_qoq_threshold: float = 0.10) -> pd.Series:
    """Flag periods where shares AND equity stepped TOGETHER (M&A signature).

    Per spec: M&A steps shares/equity (CVX: Noble +59M sh in 2020; Hess ~+16%
    sh, ~+30% equity in 2025). The signature is BOTH legs moving in the same
    direction by a meaningful amount. We require:

      min(|shares_qoq|, |equity_qoq|) > threshold,  AND
      sign(shares_qoq) == sign(equity_qoq)

    This filters out:
      - Stock splits (shares jump 4-5x, equity unchanged → equity_qoq ~ 0)
      - Deficit fluctuations / equity restatements (shares unchanged,
        equity moves → shares_qoq ~ 0)
    """
    df = facts.sort_values('period_end').reset_index(drop=True)
    sh = pd.to_numeric(df['shares'], errors='coerce')
    eq = pd.to_numeric(df['equity'], errors='coerce')
    sh_qoq = (sh - sh.shift(1)) / sh.shift(1).abs()
    eq_qoq = (eq - eq.shift(1)) / eq.shift(1).abs()
    joint_min = pd.concat([sh_qoq.abs(), eq_qoq.abs()], axis=1).min(axis=1)
    same_sign = (sh_qoq * eq_qoq) > 0
    return (joint_min > joint_qoq_threshold) & same_sign.fillna(False)


if __name__ == '__main__':
    import sys
    from .edgar_xbrl import company_facts
    from .xbrl_extract import extract_facts

    cik = int(sys.argv[1]) if len(sys.argv) > 1 else 93410
    blob = company_facts(cik)
    raw = extract_facts(blob)
    df = compute_per_share_legs(raw)
    breaks = detect_structural_breaks(df)
    df['structural_break'] = breaks.values

    df = df[df['period_end'].dt.year >= 2009].reset_index(drop=True)
    print(f'{blob.get("entityName")} — {len(df)} periods\n')

    cols = ['period_end', 'rev_ps', 'rev_ps_smoothed', 'ocf_ps',
            'ocf_ps_smoothed', 'book_ps', 'dps', 'structural_break']
    print('Most recent 8 periods:')
    print(df.tail(8)[cols].to_string(index=False))

    if df['structural_break'].any():
        print(f'\nStructural breaks ({int(df["structural_break"].sum())}):')
        print(df[df['structural_break']][['period_end', 'shares', 'equity']].to_string(index=False))
