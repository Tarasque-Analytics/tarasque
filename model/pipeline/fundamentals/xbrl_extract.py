"""
xbrl_extract.py — Pull the 5 raw fundamental tags out of a Company Facts blob.

Per spec:
  revenue_q  — ASC606 stitch: RevenueFromContractWithCustomerExcludingAssessedTax
               post-2018, Revenues / SalesRevenueNet pre-2018. Always returned
               as 3-month QTD (derived from YTD-difference when only YTD is
               published).
  ocf_q      — NetCashProvidedByUsedInOperatingActivities (or short form).
               Always 3-month QTD (same YTD-derivation pattern as revenue).
  equity     — StockholdersEquity (parent equity, excluding noncontrolling
               interest). Instant tag at period_end.
  shares     — dei:EntityCommonStockSharesOutstanding. Stamped at "near-filing"
               date, not period_end → keyed by ACCESSION (the filing that
               published it), not period_end.
  dps_q      — CommonStockDividendsPerShareDeclared. 3-month QTD (YTD-derived
               same as flow tags when needed).

YTD → QTD derivation
--------------------
Some filers publish only YTD (year-to-date) values for flow tags. Per the spec
("Q4 = FY − (Q1+Q2+Q3)"), we derive QTD by subtracting the prior YTD entry:

    Q1 QTD = Q1 YTD                    (start of FY → Q1-end, ~89 days)
    Q2 QTD = Q2 YTD − Q1 YTD           (Q2 YTD = start of FY → Q2-end, ~180d)
    Q3 QTD = Q3 YTD − Q2 YTD           (~272d)
    Q4 QTD = FY    − Q3 YTD            (~364d)

Implementation: group by `start` (which is fiscal-year start for YTD entries),
sort by `end` ascending, compute consecutive differences. Works uniformly for
QTD-direct, YTD, and mixed.

Restatements
------------
Per (period_end, tag), keep the latest-filed value. Older rows superseded.
For shares: keyed by accn so each filing's shares snapshot is preserved.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional, Sequence

import pandas as pd


TAG_OCF_PRIORITY = (
    'NetCashProvidedByUsedInOperatingActivities',
    'NetCashProvidedByOperatingActivities',
)

TAG_EQUITY_PRIORITY = (
    # Parent equity — preferred per spec.
    'StockholdersEquity',
    # Fallback: includes noncontrolling interest. Used when the parent-only
    # tag is sparse or absent (e.g., JNJ only files the combined tag). The
    # divergence math is consistent as long as the same tag is used over time
    # for one firm; cross-firm comparison is mildly impacted by minority-
    # interest differences (typically <5% of total equity).
    'StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest',
)
MIN_EQUITY_ROWS = 20  # Below this, fall back to the next priority tag.

TAG_SHARES_PRIORITY = (
    # Point-in-time shares (per spec) — preferred.
    ('dei', 'EntityCommonStockSharesOutstanding', 'shares'),
    # Fallback: weighted-average shares from the income statement (used for
    # EPS). Available for nearly every filer with 200+ rows. Approximates
    # point-in-time well for stable share counts; ~1-3% drift during quarters
    # with buybacks / new issuance. Used when dei tag has < 20 rows (i.e.,
    # the filer doesn't report point-in-time consistently — Ford, SPG, etc.).
    ('us-gaap', 'WeightedAverageNumberOfSharesOutstandingBasic', 'shares'),
)
MIN_SHARES_PRIMARY_ROWS = 20

# Outlier filter for shares: a single filing's value can be off by 1e6x
# (CRM 2011-04-30 reported "133.9" instead of "133900000" — a missing-units
# filer error). Reject any shares observation that's < 30% of the running
# median of the trailing 4 valid observations (after the firm's first 4Q).
SHARES_OUTLIER_LOW_RATIO = 0.3
SHARES_OUTLIER_HIGH_RATIO = 3.5    # > 3.5x trailing median is also suspicious
                                    # (splits handled by ttm_smooth.split_adjust)
SHARES_OUTLIER_MIN_HISTORY = 4

TAG_DPS_PRIORITY = (
    'CommonStockDividendsPerShareDeclared',
    'CommonStockDividendsPerShareCashPaid',
)

TAG_REVENUE_POST_ASC606 = 'RevenueFromContractWithCustomerExcludingAssessedTax'
TAG_REVENUE_PRE_ASC606 = (
    'Revenues',
    'SalesRevenueNet',
)
ASC606_CUTOVER = pd.Timestamp('2018-01-01')

ACCEPTED_FORMS = {'10-Q', '10-K', '10-Q/A', '10-K/A'}


# ---------------------------------------------------------------------------
# Raw row access
# ---------------------------------------------------------------------------

def _rows_for_tag(blob: Dict, taxonomy: str, tag: str,
                   unit: Optional[str] = None) -> List[dict]:
    tax = blob.get('facts', {}).get(taxonomy, {})
    if tag not in tax:
        return []
    units = tax[tag].get('units', {})
    if unit:
        return units.get(unit, [])
    if len(units) == 1:
        return next(iter(units.values()))
    return units.get('USD', units.get('USD/shares', units.get('shares', [])))


def _accepted(rows: List[dict]) -> List[dict]:
    return [r for r in rows if r.get('form') in ACCEPTED_FORMS
            and 'end' in r and 'filed' in r]


# ---------------------------------------------------------------------------
# Flow-tag normalization: any-duration → per-period QTD
# ---------------------------------------------------------------------------

def _normalize_flow_to_qtd(rows: List[dict], col_name: str) -> pd.DataFrame:
    """Convert mixed QTD/YTD flow-tag rows to one QTD value per period_end.

    Grouping by `start` separates fiscal years; sorting by `end` lets us
    derive QTD by consecutive differences. Returns one row per unique
    (start, end) — i.e., the latest-filed value at that period_end.
    """
    rows = [r for r in _accepted(rows) if 'start' in r]
    if not rows:
        return pd.DataFrame(columns=['period_end', 'fy', 'fp', 'form', 'filed',
                                      'accn', col_name])

    # Per (start, end), keep the FIRST-filed row (the original filing that
    # reported this period). Later restatements via comparative entries in
    # subsequent 10-Ks/10-Qs are ignored — the as-of join then sees the
    # original filing's value at the original filing's date, which is the
    # point-in-time correct value. Proper restatement-anchored time series
    # is a v2 concern requiring all restatements to stay in the frame.
    latest: Dict[tuple, dict] = {}
    for r in rows:
        key = (r['start'], r['end'])
        if key not in latest or r['filed'] < latest[key]['filed']:
            latest[key] = r

    # Group by `start` (a YTD chain shares its start date)
    by_start: Dict[str, List[dict]] = defaultdict(list)
    for r in latest.values():
        by_start[r['start']].append(r)

    out_rows = []
    for start, group in by_start.items():
        # Sort by end ascending; consecutive subtractions give QTD.
        group.sort(key=lambda x: x['end'])

        # Require a quarterly anchor in the group: the smallest-`end` entry
        # must have ~89-day duration (= Q1 QTD). Without this, the chain
        # has no Q1 baseline and later YTD entries can't be safely diffed.
        # Common case: 10-K comparatives for old fiscal years come in as
        # standalone annual rows (364d) — those polluted the per-period
        # frame as if they were quarterly. Skip such groups entirely.
        first = group[0]
        first_dur = (pd.Timestamp(first['end']) - pd.Timestamp(first['start'])).days
        if not (85 <= first_dur <= 100):
            continue

        prev_val = 0.0
        prev_end = None
        for r in group:
            curr_end = pd.Timestamp(r['end'])
            if prev_end is None:
                eff_dur = (curr_end - pd.Timestamp(r['start'])).days
            else:
                eff_dur = (curr_end - prev_end).days
            qtd_val = float(r['val']) - prev_val
            if 85 <= eff_dur <= 100:
                # Quarterly effective interval — emit.
                out_rows.append({
                    'period_end': curr_end,
                    'fy': r.get('fy'),
                    'fp': r.get('fp'),
                    'form': r.get('form'),
                    'filed': pd.Timestamp(r['filed']),
                    'accn': r.get('accn'),
                    col_name: qtd_val,
                })
            prev_val = float(r['val'])
            prev_end = curr_end

    if not out_rows:
        return pd.DataFrame(columns=['period_end', 'fy', 'fp', 'form', 'filed',
                                      'accn', col_name])
    df = pd.DataFrame(out_rows).sort_values('period_end').reset_index(drop=True)
    # Dedup just in case (period_end could appear in multiple `start` groups
    # if a filer is wonky); keep latest filed.
    df = (
        df.sort_values(['period_end', 'filed'])
          .drop_duplicates(subset=['period_end'], keep='last')
          .reset_index(drop=True)
    )
    return df


# ---------------------------------------------------------------------------
# Revenue: ASC606 stitch
# ---------------------------------------------------------------------------

def _extract_revenue(blob: Dict) -> pd.DataFrame:
    """Stitch ASC606 (preferred post-2018) with pre-ASC606 tags."""
    asc606 = _normalize_flow_to_qtd(
        _rows_for_tag(blob, 'us-gaap', TAG_REVENUE_POST_ASC606, 'USD'),
        'revenue_q',
    )
    pre_parts = []
    for tag in TAG_REVENUE_PRE_ASC606:
        part = _normalize_flow_to_qtd(
            _rows_for_tag(blob, 'us-gaap', tag, 'USD'),
            'revenue_q',
        )
        if not part.empty:
            pre_parts.append(part)
    pre = pd.concat(pre_parts, ignore_index=True) if pre_parts else pd.DataFrame()

    if asc606.empty and pre.empty:
        return asc606
    if asc606.empty:
        return pre
    if pre.empty:
        return asc606

    # Pre-ASC606: only periods strictly before the cutover
    pre = pre[pre['period_end'] < ASC606_CUTOVER]
    out = pd.concat([pre, asc606], ignore_index=True)
    out = (
        out.sort_values(['period_end', 'filed'])
           .drop_duplicates(subset=['period_end'], keep='last')
           .reset_index(drop=True)
    )
    return out


# ---------------------------------------------------------------------------
# Instant tag: equity at period_end
# ---------------------------------------------------------------------------

def _extract_instant(blob: Dict, taxonomy: str, tag: str,
                      col_name: str, unit: str) -> pd.DataFrame:
    """Instant tag — full long frame, one row per (period_end, accn).

    We return ALL accns per period_end (not just latest-filed) so callers can
    pick the value-version (latest = restated) AND the primary-accn (earliest =
    original-report) independently. Equity wants the restated value; shares
    want the primary-report snapshot (later filings carry stale shares).
    """
    rows = [r for r in _accepted(_rows_for_tag(blob, taxonomy, tag, unit))
            if 'start' not in r]
    if not rows:
        return pd.DataFrame(columns=['period_end', 'fy', 'fp', 'form', 'filed',
                                      'accn', col_name])
    df = pd.DataFrame([{
        'period_end': pd.Timestamp(r['end']),
        'fy': r.get('fy'),
        'fp': r.get('fp'),
        'form': r.get('form'),
        'filed': pd.Timestamp(r['filed']),
        'accn': r.get('accn'),
        col_name: float(r['val']),
    } for r in rows])
    # Per period_end, keep ALL filings as separate rows; downstream code
    # (extract_facts) picks first-filed per period for point-in-time correctness.
    return df.sort_values(['period_end', 'filed']).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Shares: keyed by accession (not period_end) because dei date is near-filing
# ---------------------------------------------------------------------------

def _extract_shares_per_accn(blob: Dict) -> pd.DataFrame:
    """One shares value per accession (the filing that published it).

    Priority: dei point-in-time tag first; falls back to weighted-average
    shares when the dei tag is too sparse (Ford has only 8 dei rows). Then
    applies an outlier filter to reject filing errors (e.g. CRM 2011-04-30
    published 133.9 instead of 133900000).
    """
    chosen: List[dict] = []
    for taxonomy, tag, unit in TAG_SHARES_PRIORITY:
        rows = _accepted(_rows_for_tag(blob, taxonomy, tag, unit))
        if len(rows) >= MIN_SHARES_PRIMARY_ROWS:
            chosen = rows
            break
        if rows and not chosen:
            chosen = rows  # at least something to fall back on
    if not chosen:
        return pd.DataFrame(columns=['accn', 'shares', 'shares_as_of'])

    df = pd.DataFrame([{
        'accn': r.get('accn'),
        'shares_as_of': pd.Timestamp(r['end']),
        'shares': float(r['val']),
        'filed': pd.Timestamp(r['filed']),
    } for r in rows])
    # Per accn, keep the LAST (latest within-accn) — some accns publish
    # multiple snapshots (mid-quarter + end-quarter). Latest = most current.
    df = (
        df.sort_values(['accn', 'filed', 'shares_as_of'])
          .drop_duplicates(subset=['accn'], keep='last')
          .reset_index(drop=True)
    )

    # Outlier filter: reject filings with shares value wildly off from
    # the trailing median (after the first MIN_HISTORY filings). Filing
    # errors typically off by 1e6x (missing units) — easy to catch.
    df = df.sort_values('filed').reset_index(drop=True)
    keep_mask = pd.Series(True, index=df.index)
    for i in range(SHARES_OUTLIER_MIN_HISTORY, len(df)):
        recent = df.loc[max(0, i - SHARES_OUTLIER_MIN_HISTORY):i - 1, 'shares']
        recent_valid = recent[keep_mask.loc[recent.index]]
        if len(recent_valid) < SHARES_OUTLIER_MIN_HISTORY:
            continue
        med = float(recent_valid.median())
        val = float(df.loc[i, 'shares'])
        if val < med * SHARES_OUTLIER_LOW_RATIO or val > med * SHARES_OUTLIER_HIGH_RATIO:
            keep_mask.iloc[i] = False
    df = df[keep_mask].reset_index(drop=True)
    return df


# ---------------------------------------------------------------------------
# Top-level: assemble per-period frame
# ---------------------------------------------------------------------------

def extract_facts(blob: Dict) -> pd.DataFrame:
    """Build the per-firm long-format frame, latest-filed per period.

    Returns:
      DataFrame, one row per period_end. Columns:
        period_end, fy, fp, form, filed, accn
        revenue_q   (3-month QTD, ASC606-stitched)
        ocf_q       (3-month QTD)
        equity      (instant @ period_end)
        shares      (from the accn that reports this period_end)
        dps_q       (3-month QTD)
        is_restatement (bool — placeholder False; restatement tracking would
                        need to retain superseded rows, which this view drops)
    """
    rev = _extract_revenue(blob)
    ocf_rows = []
    for tag in TAG_OCF_PRIORITY:
        ocf_rows = _rows_for_tag(blob, 'us-gaap', tag, 'USD')
        if ocf_rows:
            break
    ocf = _normalize_flow_to_qtd(ocf_rows, 'ocf_q')

    dps_rows = []
    for tag in TAG_DPS_PRIORITY:
        dps_rows = _rows_for_tag(blob, 'us-gaap', tag, 'USD/shares')
        if dps_rows:
            break
    dps = _normalize_flow_to_qtd(dps_rows, 'dps_q')

    # Equity stitch (per-period priority, NOT count-based). Use parent equity
    # where the filer publishes it; fall back to the combined "including
    # noncontrolling interest" tag for periods where the parent tag is missing.
    # UNH (and many post-2015 filers) switched mid-life from parent-only to
    # combined; a count-based fallback (v1) picked the stale parent tag
    # because it had >20 historical rows — leaving the post-switch periods
    # invisible. Per-period stitch fixes this without losing point-in-time
    # discipline.
    parent = _extract_instant(blob, 'us-gaap',
                                'StockholdersEquity', 'equity', 'USD')
    combined = _extract_instant(blob, 'us-gaap',
        'StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest',
        'equity', 'USD')
    if parent.empty and combined.empty:
        eq_long = parent  # empty frame with correct columns
    elif parent.empty:
        eq_long = combined
    elif combined.empty:
        eq_long = parent
    else:
        # Stitch: parent rows win where they exist; combined fills gaps.
        parent_periods = set(parent['period_end'].unique())
        combined_fill = combined[~combined['period_end'].isin(parent_periods)]
        eq_long = pd.concat([parent, combined_fill], ignore_index=True)
        eq_long = eq_long.sort_values(['period_end', 'filed']).reset_index(drop=True)
    sh = _extract_shares_per_accn(blob)

    # Build per-period spine from equity. Two roles per period_end:
    #   - LATEST-filed equity row = the restated value (per spec)
    #   - EARLIEST-filed equity row = the primary filing whose accn's shares
    #     snapshot is contemporaneous with the period (later restatements
    #     carry the FILING's shares snapshot, not the period's)
    if eq_long.empty:
        base = pd.DataFrame(columns=['period_end', 'fy', 'fp', 'form', 'filed',
                                      'accn', 'equity', 'shares'])
    else:
        # Use the FIRST (original) filing per period for both VALUES and the
        # primary-accn lookup. Restatement-stepping is v2. The values then
        # match the period as it was first reported, so the as-of join lands
        # on a row whose `filed` is the original filing's date (which falls
        # inside the historical window we're projecting onto).
        first_per_period = eq_long.groupby('period_end', as_index=False).first()
        base = first_per_period.copy()
        base = base.rename(columns={'accn': 'primary_accn'})
        base['accn'] = base['primary_accn']
        if not sh.empty:
            base = base.merge(
                sh[['accn', 'shares']].rename(columns={'accn': 'primary_accn'}),
                on='primary_accn', how='left',
            )
        else:
            base['shares'] = pd.NA
        base = base.drop(columns=['primary_accn'])

    def _attach_flow(base: pd.DataFrame, side: pd.DataFrame, col: str) -> pd.DataFrame:
        if side.empty:
            base[col] = pd.NA
            return base
        slim = side[['period_end', col]].drop_duplicates(subset=['period_end'], keep='last')
        return base.merge(slim, on='period_end', how='left')

    base = _attach_flow(base, rev, 'revenue_q')
    base = _attach_flow(base, ocf, 'ocf_q')
    base = _attach_flow(base, dps, 'dps_q')

    base['is_restatement'] = False  # placeholder; per-period dedup already chose latest
    base = base.sort_values('period_end').reset_index(drop=True)
    return base


if __name__ == '__main__':
    import sys
    from .edgar_xbrl import company_facts

    cik = int(sys.argv[1]) if len(sys.argv) > 1 else 93410
    blob = company_facts(cik)
    print(f'\nExtracting {blob.get("entityName")} (CIK {cik})...\n')
    df = extract_facts(blob)
    print(f'Per-period frame: {len(df):,} periods  '
          f'{df["period_end"].min().date()} -> {df["period_end"].max().date()}\n')
    cols = ['period_end', 'fy', 'fp', 'form', 'filed', 'revenue_q',
            'ocf_q', 'equity', 'shares', 'dps_q']
    keep = [c for c in cols if c in df.columns]
    print('Most recent 6 periods:')
    print(df.tail(6)[keep].to_string(index=False))
