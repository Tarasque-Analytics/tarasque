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

TAG_SHARES = 'EntityCommonStockSharesOutstanding'   # taxonomy: dei

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

    # Restatement dedup: per (start, end), keep latest-filed
    latest: Dict[tuple, dict] = {}
    for r in rows:
        key = (r['start'], r['end'])
        if key not in latest or r['filed'] > latest[key]['filed']:
            latest[key] = r

    # Group by `start` (a YTD chain shares its start date)
    by_start: Dict[str, List[dict]] = defaultdict(list)
    for r in latest.values():
        by_start[r['start']].append(r)

    out_rows = []
    for start, group in by_start.items():
        # Sort by end ascending; consecutive subtractions give QTD
        group.sort(key=lambda x: x['end'])
        prev = 0.0
        for r in group:
            qtd_val = float(r['val']) - prev
            out_rows.append({
                'period_end': pd.Timestamp(r['end']),
                'fy': r.get('fy'),
                'fp': r.get('fp'),
                'form': r.get('form'),
                'filed': pd.Timestamp(r['filed']),
                'accn': r.get('accn'),
                col_name: qtd_val,
            })
            prev = float(r['val'])

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
    return df.sort_values(['period_end', 'filed']).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Shares: keyed by accession (not period_end) because dei date is near-filing
# ---------------------------------------------------------------------------

def _extract_shares_per_accn(blob: Dict) -> pd.DataFrame:
    """One shares value per accession (the filing that published it).

    The dei tag's `end` is typically a few days before the filing date, NOT
    period_end. So we tag by accn — later, per-accn join attaches the shares
    value to whatever period that accn was reporting.
    """
    rows = _accepted(_rows_for_tag(blob, 'dei', TAG_SHARES, 'shares'))
    if not rows:
        return pd.DataFrame(columns=['accn', 'shares', 'shares_as_of'])
    df = pd.DataFrame([{
        'accn': r.get('accn'),
        'shares_as_of': pd.Timestamp(r['end']),
        'shares': float(r['val']),
        'filed': pd.Timestamp(r['filed']),
    } for r in rows])
    # Per accn, keep the latest dei row (some accns publish multiple snapshots).
    df = (
        df.sort_values(['accn', 'filed', 'shares_as_of'])
          .drop_duplicates(subset=['accn'], keep='last')
          .reset_index(drop=True)
    )
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

    eq_long = pd.DataFrame()
    for tag in TAG_EQUITY_PRIORITY:
        candidate = _extract_instant(blob, 'us-gaap', tag, 'equity', 'USD')
        if len(candidate) >= MIN_EQUITY_ROWS:
            eq_long = candidate
            break
        if not candidate.empty and eq_long.empty:
            eq_long = candidate  # at least something to fall back on
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
        latest_per_period = eq_long.groupby('period_end', as_index=False).last()
        primary_per_period = (
            eq_long.groupby('period_end', as_index=False)
                   .first()[['period_end', 'accn']]
                   .rename(columns={'accn': 'primary_accn'})
        )
        base = latest_per_period.merge(primary_per_period, on='period_end', how='left')
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
