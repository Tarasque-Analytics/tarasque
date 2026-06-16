"""
export_for_webapp.py — Generate the handoff bundle from a completed backtest run.

Reads the existing prediction CSVs + raw data caches, produces the per-ticker
fat files + supporting CSVs documented in model/SUPABASE_SCHEMA.md.

Workflow:
  - Run manually after a completed backtest (CSV only):
      python -m model.pipeline.export_for_webapp --ticker AAPL --run-id 1
  - Full corpus bundle:
      python -m model.pipeline.export_for_webapp --all
  - Push to Supabase alongside CSV:
      python -m model.pipeline.export_for_webapp --all --push-to-supabase
  - Daily append (only new rows since last DB write):
      python -m model.pipeline.export_for_webapp --all --push-to-supabase --append-only
  - Pre-flight validation without DB writes:
      python -m model.pipeline.export_for_webapp --ticker AAPL --push-to-supabase --dry-run
  - Once validated, can be auto-invoked at the end of run.py.

Outputs (in model/pipeline/results/webapp_export/):
  tickers/predictions_<TICKER>.csv   — per-ticker fat file (28 columns)
  securities_metadata.csv            — one row per ticker
  events_history.csv                 — earnings, dividends, FOMC dates
  macro_calendar.csv                 — forward macro events
  model_run_manifest.json            — registry entry for this run

Honesty note: this script fills in what's available from the existing prediction
CSVs + caches. Where data isn't yet in the cache (IV term structure at 60d/91d/
182d, SHAP, Compustat earnings/dividends), it writes NULL so the web dev knows
what's pending vs. what's ready. Production runs from the 5950X with the full
pipeline will populate everything.
"""
from __future__ import annotations
import argparse
import json
import sys
import textwrap
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')

RESULTS_DIR     = Path('model/pipeline/results')
EXPORT_DIR      = RESULTS_DIR / 'webapp_export'
TICKERS_DIR     = EXPORT_DIR / 'tickers'

# Sector mapping — same as used elsewhere
SECTORS = {
    'AAPL':'Tech','MSFT':'Tech','NVDA':'Tech','AVGO':'Tech','TXN':'Tech',
    'INTC':'Tech','QCOM':'Tech','IBM':'Tech','ADBE':'Tech','CRM':'Tech',
    'AMAT':'Tech','AMD':'Tech','ORCL':'Tech','CSCO':'Tech','MU':'Tech',
    'AMZN':'Cons Disc','HD':'Cons Disc','NKE':'Cons Disc','TSLA':'Cons Disc',
    'LOW':'Cons Disc','TGT':'Cons Disc','BKNG':'Cons Disc','F':'Cons Disc','GM':'Cons Disc',
    'DIS':'Comm','NFLX':'Comm','CMCSA':'Comm','T':'Comm','GOOGL':'Comm',
    'JPM':'Financials','GS':'Financials','MS':'Financials','BAC':'Financials',
    'WFC':'Financials','C':'Financials','SCHW':'Financials','AXP':'Financials',
    'BLK':'Financials','USB':'Financials',
    'XOM':'Energy','CVX':'Energy','COP':'Energy','EOG':'Energy','SLB':'Energy',
    'MPC':'Energy','PSX':'Energy',
    'JNJ':'Health Care','UNH':'Health Care','LLY':'Health Care','MRK':'Health Care',
    'ABT':'Health Care','GILD':'Health Care','BMY':'Health Care','PFE':'Health Care',
    'ABBV':'Health Care','TMO':'Health Care','AMGN':'Health Care','CVS':'Health Care',
    'PG':'Staples','KO':'Staples','PEP':'Staples','WMT':'Staples','COST':'Staples',
    'PM':'Staples','MCD':'Staples','SBUX':'Staples','MO':'Staples','CL':'Staples',
    'NEE':'Utilities','DUK':'Utilities','D':'Utilities','SO':'Utilities','AEP':'Utilities',
    'CAT':'Industrials','HON':'Industrials','GE':'Industrials','LMT':'Industrials',
    'DE':'Industrials','MMM':'Industrials','FDX':'Industrials','BA':'Industrials',
    'NOC':'Industrials','UPS':'Industrials','RTX':'Industrials',
    'NEM':'Materials','FCX':'Materials','APD':'Materials','DOW':'Materials',
    'AMT':'REIT','EQIX':'REIT','CCI':'REIT','SPG':'REIT','PLD':'REIT',
}

SECTOR_ETF_MAP = {
    'Tech':'XLK','Financials':'XLF','Energy':'XLE','Industrials':'XLI',
    'Health Care':'XLV','Staples':'XLP','Comm':'XLC','Cons Disc':'XLY',
    'Materials':'XLB','Utilities':'XLU','REIT':'XLRE',
}

EXCLUDED = {
    'LIN':  'R^2=0.94 leakage from Linde-Praxair merger',
    'OXY':  'RMSE explosion in WFA folds',
    'VZ':   'Frontier Communications acquisition artifact',
    'META': 'Insufficient post-IPO history',
}

# Column order — matches SUPABASE_SCHEMA.md per-ticker file spec
PER_TICKER_COLUMNS = [
    'date',
    'open','high','low','close','adj_close','volume',
    'rv','ewma_vol',
    'iv_atm_30d','iv_atm_60d','iv_atm_91d','iv_atm_182d',
    'vrp_wedge','vrp_wedge_ewma_21d',
    'pfv_21','pfv_63','pfv_126',
    'pfv_q15_21','pfv_q15_63','pfv_q15_126',
    'pfv_cal_21','pfv_cal_63','pfv_cal_126',
    # Forward premium scalars — computed via PCHIP-on-total-variance.
    # Frontend splines the pfv_cal_* + iv_atm_* anchors client-side for the
    # Forward Vol Forecast chart; these scalars are for the side-panel
    # readout and cross-ticker SQL queries. Sign: positive = market premium.
    'fwd_premium_21d','fwd_premium_63d','fwd_premium_126d',
    'fwd_premium_21_to_63d','fwd_premium_63_to_126d',
    'fwd_premium_ewma_21d','fwd_premium_ewma_63d','fwd_premium_ewma_126d',
    'shap_h21_top10','shap_h63_top10','shap_h126_top10',
    'next_earnings_date','days_to_earnings',
    'next_dividend_date','days_to_dividend',
    'model_run_id',
]


def load_predictions() -> pd.DataFrame:
    """Load the consolidated calibrated prediction CSV."""
    path = RESULTS_DIR / 'all_predictions_cal.csv'
    if not path.exists():
        raise FileNotFoundError(f'Required input not found: {path}')
    df = pd.read_csv(path, parse_dates=['date'])
    return df


def pivot_predictions(df: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """Pivot long-format predictions to wide per (ticker, date)."""
    sub = df[df['ticker'] == ticker].copy()
    if sub.empty:
        raise ValueError(f'No predictions found for ticker {ticker}')

    wide = sub.pivot_table(
        index='date',
        columns='horizon',
        values=['y_true','y_pred','y_pred_q15','y_cal','vrp_wedge'],
    )
    wide.columns = [f'{a}_{b}' for a,b in wide.columns]
    # Keep every date with a 21-day forecast — including future-dated forecasts
    # whose y_true hasn't materialized yet. (Previous dropna on y_true_21 cut
    # the bundle off ~21 BD before today and dropped the current forecast.)
    wide = wide.reset_index().sort_values('date').dropna(subset=['y_pred_21'])
    return wide


def fetch_ohlcv(ticker: str, start: str, end: str) -> pd.DataFrame:
    """Pull OHLCV for the prediction date range from the CRSP parquet cache.

    Uses the v6 split-fix methodology: adj_close is reconstructed from CRSP's
    `ret` column (which is already split- and dividend-adjusted), then scaled
    so adj_close[-1] equals the most recent raw close. This matches the
    training-data pipeline exactly — no methodology drift between training and
    serving.
    """
    from .config import load_config
    from .data_loader import ParquetStore

    dc, _, _ = load_config()
    store = ParquetStore(dc.base_dir)
    df = store.load('ohlcv', tickers=[ticker]).copy()
    if df.empty:
        raise ValueError(f'No OHLCV in parquet cache for {ticker}')

    df['date'] = pd.to_datetime(df['date'], format='mixed', errors='coerce')
    df = df.dropna(subset=['date']).sort_values('date').reset_index(drop=True)

    # CRSP column normalisation + negative-price convention (CRSP uses negative
    # as a bid/ask average flag — take absolute value)
    rename = {'openprc': 'open', 'askhi': 'high', 'bidlo': 'low',
              'prc': 'close', 'vol': 'volume'}
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
    for c in ('open', 'high', 'low', 'close'):
        if c in df.columns:
            df[c] = df[c].abs()

    # Drop CRSP-msenames duplicate (date, ticker) rows that can occur on
    # name-range overlap. Keep the last record.
    df = df.drop_duplicates(subset=['date'], keep='last').reset_index(drop=True)

    # Reconstruct adj_close from CRSP ret (split- + dividend-adjusted).
    # Defensive: where ret is NA (Alpaca-appended rows past the CRSP cutoff),
    # backfill from close.pct_change() so the cum doesn't flatten and the
    # anchor scaling stays correct. features._pivot_ohlcv has the same gap
    # but lives in the training path — track that separately.
    if 'ret' in df.columns and df['ret'].notna().any():
        rets = df['ret'].copy()
        fallback = df['close'].pct_change()
        rets = rets.where(rets.notna(), fallback).fillna(0.0)
        cum = (1.0 + rets).cumprod()
        scale = float(df['close'].iloc[-1]) / float(cum.iloc[-1])
        df['adj_close'] = cum * scale
    else:
        df['adj_close'] = df['close']

    # Date-range filter
    df = df[(df['date'] >= pd.Timestamp(start)) & (df['date'] < pd.Timestamp(end))]

    # Volume → nullable Int64 (Postgres bigint won't accept "14820614.0" as
    # text). CRSP `vol` is float because some rows have NaN; we coerce to
    # nullable integer so the CSV writes whole numbers and the DB INSERT works.
    if 'volume' in df.columns:
        # round first (handles tiny float drift), then nullable Int64
        df['volume'] = df['volume'].round().astype('Int64')

    return df[['date', 'open', 'high', 'low', 'close', 'adj_close', 'volume']].reset_index(drop=True)


def fetch_forward_events(ticker: str, dates: pd.Series) -> pd.DataFrame:
    """Compute next_earnings_date / days_to_earnings / next_dividend_date /
    days_to_dividend per row date for a ticker.

    - next_earnings_date: from Compustat `earnings.rdq`. For row dates past the
      last known announcement, projects ~91 calendar days forward from the last
      known fiscal quarter end (Compustat's `datadate`). Marks projected dates
      with no audit field for now — flag as `is_projected` if downstream cares.
    - next_dividend_date / days_to_dividend: not available from the Compustat
      annual summary on disk (schema has `(tic, datadate, dvpsx_f)` — annual
      dividend per share, no ex-dates). Returns NaT pending an Alpaca corporate
      actions integration or alternate vendor pull.
    """
    from .config import load_config
    from .data_loader import ParquetStore
    from pandas.tseries.offsets import BDay

    dc, _, _ = load_config()
    store = ParquetStore(dc.base_dir)

    out = pd.DataFrame({'date': pd.to_datetime(dates)})

    # Earnings — use rdq (the announcement date)
    try:
        e = store.load('earnings')
        e = e[e['tic'] == ticker].copy()
        e['rdq'] = pd.to_datetime(e['rdq'], errors='coerce')
        e['datadate'] = pd.to_datetime(e['datadate'], errors='coerce')
        e = e.dropna(subset=['rdq']).sort_values('rdq').reset_index(drop=True)
    except Exception:
        e = pd.DataFrame(columns=['rdq', 'datadate'])

    if not e.empty:
        # Build a forward-projected calendar: for any date past the last rdq,
        # project the next 8 quarters using:
        #   future_rdq = last_datadate + 91*k + median_announce_lag
        # where median_announce_lag is this ticker's typical days between
        # fiscal-quarter end and the actual announcement (Compustat: rdq - datadate).
        # AAPL is ~30d; varies by company.
        rdqs = e['rdq'].dropna().sort_values()
        last_rdq = rdqs.iloc[-1]
        valid = e.dropna(subset=['rdq', 'datadate'])
        if not valid.empty:
            lag_days = (valid['rdq'] - valid['datadate']).dt.days.median()
            lag = pd.Timedelta(days=int(lag_days) if pd.notna(lag_days) else 30)
        else:
            lag = pd.Timedelta(days=30)
        last_qe = e['datadate'].iloc[-1] if e['datadate'].notna().any() else last_rdq
        proj = [last_qe + pd.Timedelta(days=91 * k) + lag for k in range(1, 9)]
        future_rdq = pd.Series(proj, dtype='datetime64[ns]')
        all_rdq = pd.concat([rdqs, future_rdq]).sort_values().drop_duplicates().reset_index(drop=True)

        # For each row date, find first rdq >= date
        out_dates = pd.to_datetime(out['date']).values
        idx = all_rdq.searchsorted(out_dates, side='left')
        next_e = all_rdq.reindex(idx).values
        out['next_earnings_date'] = pd.to_datetime(next_e)
        # BDay delta
        diffs = []
        for d, ne in zip(out['date'], out['next_earnings_date']):
            if pd.isna(ne):
                diffs.append(pd.NA)
            else:
                diffs.append(int(len(pd.bdate_range(d, ne)) - 1))
        out['days_to_earnings'] = diffs
    else:
        out['next_earnings_date'] = pd.NaT
        out['days_to_earnings'] = pd.NA

    # Dividends — not available from current Compustat schema
    out['next_dividend_date'] = pd.NaT
    out['days_to_dividend'] = pd.NA

    return out.drop(columns=['date'])


def fetch_iv_term_structure(ticker: str) -> pd.DataFrame:
    """Pull ATM IV (delta=50) at the four canonical tenors from vsurfd parquet.

    Returns DataFrame indexed by date with columns:
      iv_atm_30d, iv_atm_60d, iv_atm_91d, iv_atm_182d

    Where vsurfd has duplicate (date, days, delta) rows (multiple secids for
    the same ticker, or partition overlap), takes the median so the value
    stays robust to source-side noise.
    """
    from .config import load_config
    from .data_loader import ParquetStore

    dc, _, _ = load_config()
    store = ParquetStore(dc.base_dir)
    df = store.load('vsurfd', tickers=[ticker]).copy()
    if df.empty:
        return pd.DataFrame(columns=['iv_atm_30d', 'iv_atm_60d', 'iv_atm_91d', 'iv_atm_182d'])

    df['date'] = pd.to_datetime(df['date'], format='mixed', errors='coerce')
    df = df.dropna(subset=['date'])
    # ATM = delta 50
    atm = df[(df['delta'] == 50) & (df['days'].isin([30, 60, 91, 182]))]
    if atm.empty:
        return pd.DataFrame(columns=['iv_atm_30d', 'iv_atm_60d', 'iv_atm_91d', 'iv_atm_182d'])

    wide = (
        atm.groupby(['date', 'days'])['impl_volatility']
        .median()
        .unstack('days')
        .rename(columns={30: 'iv_atm_30d', 60: 'iv_atm_60d',
                         91: 'iv_atm_91d', 182: 'iv_atm_182d'})
    )
    # Forward-fill within a 90-business-day window. Tolerates the current
    # WRDS-vs-Alpaca-splice dead zone (Sep 2025 → May 2026 for prod ticks)
    # without leaving prediction-date rows blank on the equity page. Once
    # OptionMetrics publishes more vsurfd partitions OR Alpaca chain backfill
    # lands, this can drop back to limit=5.
    return wide.ffill(limit=90)


def build_shap_blob_placeholder(horizon: int) -> str:
    """Deprecated: SHAP on backtest rows is intentionally NULL. SHAP is only
    computed on concurrent (daily forecast) runs — see
    model/pipeline/daily_forecast.py and shap_explainer.py. This function is
    kept for compatibility but should not be called from new code."""
    return None


def load_shap_blob_file(ticker: str) -> pd.DataFrame:
    """Read forecasts/<TICKER>_shap.csv if present. Returns DataFrame with
    (date, horizon, shap_blob_json). Empty DataFrame if no file."""
    path = RESULTS_DIR / 'forecasts' / f'{ticker}_shap.csv'
    if not path.exists():
        return pd.DataFrame(columns=['date', 'horizon', 'shap_blob_json'])
    df = pd.read_csv(path, parse_dates=['date'])
    return df


def build_per_ticker_file(
    ticker: str,
    predictions: pd.DataFrame,
    ohlcv: pd.DataFrame,
    run_id: int,
) -> pd.DataFrame:
    """Compose the 28-column per-ticker file for one ticker."""

    # Merge OHLCV onto prediction dates (left join — keep all prediction days)
    df = predictions.merge(ohlcv, on='date', how='left')

    out = pd.DataFrame()
    out['date'] = df['date']

    # Price block
    for col in ['open','high','low','close','adj_close','volume']:
        out[col] = df[col] if col in df.columns else None

    # Realized vol
    out['rv']       = df['y_true_21']
    # ewma_vol: not in prediction CSVs. Compute from log adj_close returns.
    log_ret = np.log(df['adj_close'] / df['adj_close'].shift(1))
    out['ewma_vol'] = np.sqrt(log_ret.pow(2).ewm(span=21, adjust=False).mean() * 252)

    # IV term structure: all 4 tenors from vsurfd parquet (delta=50, ATM).
    # Use merge_asof so prediction dates after the last vsurfd row carry
    # the most recent value forward (tolerance=120d covers the WRDS-vs-Alpaca
    # dead zone). Tolerance bounds how stale the IV can be before going NaN.
    iv_ts = fetch_iv_term_structure(ticker).reset_index()
    iv_ts['date'] = pd.to_datetime(iv_ts['date'])
    out = out.sort_values('date').reset_index(drop=True)
    iv_ts = iv_ts.sort_values('date').reset_index(drop=True)
    out = pd.merge_asof(
        out, iv_ts, on='date', direction='backward',
        tolerance=pd.Timedelta(days=120),
    )

    # VRP — start from the source (model-training wedge: iv_atm_30d − lagged_rv).
    # On dates where the source is NaN (WRDS-vs-Alpaca dead zone), recompute
    # from the now-ffilled IV + a rolling 21d realized-vol proxy off adj_close
    # log returns. Same formula, different recomputation path.
    out['vrp_wedge'] = df['vrp_wedge_21']
    if 'iv_atm_30d' in out.columns:
        lagged_rv_21d = (
            np.log(out['adj_close'] / out['adj_close'].shift(1))
              .rolling(21).std() * np.sqrt(252)
        )
        wedge_fill = out['iv_atm_30d'] - lagged_rv_21d
        out['vrp_wedge'] = out['vrp_wedge'].where(out['vrp_wedge'].notna(), wedge_fill)
    out['vrp_wedge_ewma_21d'] = out['vrp_wedge'].ewm(span=21, adjust=False).mean()

    # Forecasts (all 9)
    out['pfv_21']      = df['y_pred_21']
    out['pfv_63']      = df['y_pred_63']
    out['pfv_126']     = df['y_pred_126']
    out['pfv_q15_21']  = df['y_pred_q15_21']
    out['pfv_q15_63']  = df['y_pred_q15_63']
    out['pfv_q15_126'] = df['y_pred_q15_126']
    out['pfv_cal_21']  = df['y_cal_21']
    out['pfv_cal_63']  = df['y_cal_63']
    out['pfv_cal_126'] = df['y_cal_126']

    # Forward premium scalars — PCHIP-on-total-variance over the 7 anchors
    # just landed (3 model + 4 market). Frontend splines anchors directly
    # for the chart; these are for side-panel readout + SQL ranking.
    from .premium_curve import compute_premium_columns
    out = compute_premium_columns(out)

    # Forward VRP EWMA — investor-facing premium gauge for the equity-page
    # "VRP EWMA·21d" subgraph. Span 21 BD across all horizons (validated
    # optimum from the EWMA span sweep — plateau across spans 10-42).
    # Does NOT replace vrp_wedge_ewma_21d above, which stays as the model
    # context-engine feature (correctly referenced by SHAP attribution).
    for _h in (21, 63, 126):
        out[f'fwd_premium_ewma_{_h}d'] = (
            out[f'fwd_premium_{_h}d'].ewm(span=21, adjust=False).mean()
        )

    # SHAP — NULL on backtest rows. Real SHAP for daily forecast dates is
    # merged in below from forecasts/<TICKER>_shap.csv (written by
    # daily_forecast.py). Per architecture: SHAP only for concurrent runs.
    out['shap_h21_top10']  = None
    out['shap_h63_top10']  = None
    out['shap_h126_top10'] = None

    shap_df = load_shap_blob_file(ticker)
    if not shap_df.empty:
        # Pivot (date, horizon) → wide columns shap_h21/63/126_top10
        wide_shap = shap_df.pivot_table(
            index='date', columns='horizon', values='shap_blob_json', aggfunc='last'
        )
        wide_shap.columns = [f'shap_h{int(c)}_top10' for c in wide_shap.columns]
        wide_shap = wide_shap.reset_index()
        # Merge onto out by date, taking shap values where present
        out = out.merge(
            wide_shap, on='date', how='left', suffixes=('', '_from_file'),
        )
        for h in (21, 63, 126):
            file_col = f'shap_h{h}_top10_from_file'
            target_col = f'shap_h{h}_top10'
            if file_col in out.columns:
                out[target_col] = out[file_col].combine_first(out[target_col])
                out.drop(columns=[file_col], inplace=True)

    # Forward events: next_earnings_date from Compustat (rdq), with ~91d
    # forward projection past the last known announcement. Dividend dates
    # stay NULL — Compustat annual schema lacks ex-dates; needs Alpaca
    # corporate actions integration.
    fwd = fetch_forward_events(ticker, out['date'])
    out['next_earnings_date'] = fwd['next_earnings_date'].values
    out['days_to_earnings']   = fwd['days_to_earnings'].values
    out['next_dividend_date'] = fwd['next_dividend_date'].values
    out['days_to_dividend']   = fwd['days_to_dividend'].values

    # Run reference
    out['model_run_id'] = run_id

    # Enforce column order from schema spec
    out = out[PER_TICKER_COLUMNS]
    return out


def write_securities_metadata(tickers_present: list[str]):
    """Generate securities_metadata.csv for the active universe + excluded list.
    Column name is `ticker` to match the live securities table column."""
    rows = []
    for t in tickers_present:
        rows.append({
            'ticker':           t,
            'gics_sector':      SECTORS.get(t, 'Other'),
            'gics_industry':    None,
            'sector_etf':       SECTOR_ETF_MAP.get(SECTORS.get(t, ''), 'SPY'),
            'active':           True,
            'excluded_reason':  None,
            'min_history_date': None,    # filled in downstream
        })
    for t, reason in EXCLUDED.items():
        rows.append({
            'ticker':           t,
            'gics_sector':      SECTORS.get(t, 'Other'),
            'gics_industry':    None,
            'sector_etf':       None,
            'active':           False,
            'excluded_reason':  reason,
            'min_history_date': None,
        })
    pd.DataFrame(rows).to_csv(EXPORT_DIR / 'securities_metadata.csv', index=False)


def write_run_manifest(run_id: int, n_tickers: int):
    """Write the manifest JSON for this run."""
    manifest = {
        'run_id':        run_id,
        'run_date':      pd.Timestamp.now().strftime('%Y-%m-%d'),
        'model_version': 'v10+',
        'spec_hash':     '0356b9d',  # latest commit hash
        'n_tickers':     n_tickers,
        'horizons':      [21, 63, 126],
        'notes':         'v10+ corpus run — exported via export_for_webapp.py',
        'generated_at':  pd.Timestamp.now().strftime('%Y-%m-%dT%H:%M:%SZ'),
    }
    (EXPORT_DIR / 'model_run_manifest.json').write_text(
        json.dumps(manifest, indent=2), encoding='utf-8'
    )


def write_event_history(tickers: list[str], ticker_to_security_id: dict[str, int] | None = None):
    """Populate event_history.csv from Compustat earnings + Compustat dividends.

    New schema (per lead-dev redesign):
      security_id (FK → securities.security_id), event_date, title, description,
      event_type, scope, source.

    Note: FOMC events are NOT written here — they live in macro_calendar
    (market-scope, no security_id). The new event_history is strictly
    per-security.

    If ticker_to_security_id is None, security_id is left NaN and the row will
    fail to UPSERT (FK violation). Caller should pass the dict from the live
    `securities` table for live writes; CSV-only writes can omit it.
    """
    from .config import load_config
    from .data_loader import ParquetStore

    dc, _, _ = load_config()
    store = ParquetStore(dc.base_dir)
    rows = []

    # Earnings
    try:
        e = store.load('earnings').copy()
        e['rdq'] = pd.to_datetime(e['rdq'], errors='coerce')
        e['datadate'] = pd.to_datetime(e['datadate'], errors='coerce')
        e = e[e['tic'].isin(tickers)].dropna(subset=['rdq'])
        for _, r in e.iterrows():
            q = ((r['datadate'].month - 1) // 3 + 1) if pd.notna(r['datadate']) else None
            title = f"{r['tic']} Q{q} Earnings" if q else f"{r['tic']} Earnings"
            rows.append({
                'security_id': ticker_to_security_id.get(r['tic']) if ticker_to_security_id else None,
                'event_date':  r['rdq'].strftime('%Y-%m-%d'),
                'title':       title,
                'description': None,
                'event_type':  'earnings',
                'scope':       'ticker',
                'source':      'Compustat',
            })
    except Exception as ex:
        print(f'  [events] earnings pull failed: {ex}')

    # Dividends — annual schema, datadate as approximate ex-date
    try:
        d = store.load('dividends').copy()
        d['datadate'] = pd.to_datetime(d['datadate'], errors='coerce')
        d = d[d['tic'].isin(tickers)].dropna(subset=['datadate'])
        for _, r in d.iterrows():
            rows.append({
                'security_id': ticker_to_security_id.get(r['tic']) if ticker_to_security_id else None,
                'event_date':  r['datadate'].strftime('%Y-%m-%d'),
                'title':       f"{r['tic']} annual dividend ${r['dvpsx_f']:.2f}",
                'description': 'Approximate ex-date — Compustat annual schema lacks ex-dates',
                'event_type':  'dividend',
                'scope':       'ticker',
                'source':      'Compustat',
            })
    except Exception as ex:
        print(f'  [events] dividends pull failed: {ex}')

    df = pd.DataFrame(rows)
    if df.empty:
        print('  event_history.csv: no rows generated')
        return
    df['event_date'] = pd.to_datetime(df['event_date'])
    df = df.sort_values(['security_id', 'event_date']).reset_index(drop=True)
    df.to_csv(EXPORT_DIR / 'event_history.csv', index=False)

    # Stats
    n_unmapped = df['security_id'].isna().sum() if ticker_to_security_id else len(df)
    n_earn = (df['event_type'] == 'earnings').sum()
    n_div  = (df['event_type'] == 'dividend').sum()
    print(f'  event_history.csv: {len(df):,} rows ({n_earn} earnings, {n_div} dividends'
          + (f', {n_unmapped} unmapped tickers' if n_unmapped > 0 else '') + ')')


# Backward-compat alias for any callers still using the old name.
write_events_history = write_event_history


def write_macro_calendar(start: str, end: str):
    """Forward-looking macro calendar.

    For every business day in [start, end], emit one row per event_type
    with the next event_date and days_to_event. Frontend uses this for
    'Next FOMC: 14 days' widgets.
    """
    from .utils import FOMC_DATES, CPI_DATES, NFP_DATES

    bdays = pd.bdate_range(start=start, end=end)
    sources = {'fomc': FOMC_DATES, 'cpi': CPI_DATES, 'nfp': NFP_DATES}

    rows = []
    for event_type, dates in sources.items():
        dates_ts = pd.to_datetime([pd.Timestamp(d) for d in dates]).sort_values()
        for d in bdays:
            idx = dates_ts.searchsorted(d, side='left')
            if idx >= len(dates_ts):
                continue
            event_date = dates_ts[idx]
            rows.append({
                'date': d.strftime('%Y-%m-%d'),
                'event_type': event_type,
                'event_date': event_date.strftime('%Y-%m-%d'),
                'days_to_event': int((event_date - d).days),
            })

    df = pd.DataFrame(rows)
    df.to_csv(EXPORT_DIR / 'macro_calendar.csv', index=False)
    print(f'  macro_calendar.csv: {len(df):,} rows '
          f'({len(bdays):,} business days × 3 event types)')


def write_placeholders_for_supporting_files():
    """Compatibility shim — calls real writers (deprecated name kept for now)."""
    pass


# ═════════════════════════════════════════════════════════════════════════════
# Supabase column groups — used to split the fat per-ticker file into the
# narrower table-specific frames before upserting.
# ═════════════════════════════════════════════════════════════════════════════

PRICES_COLS = ['date', 'open', 'high', 'low', 'close', 'adj_close', 'volume']

VOLATILITY_COLS = [
    'date', 'rv', 'ewma_vol',
    'iv_atm_30d', 'iv_atm_60d', 'iv_atm_91d', 'iv_atm_182d',
    'vrp_wedge', 'vrp_wedge_ewma_21d',
    'pfv_21', 'pfv_63', 'pfv_126',
    'pfv_q15_21', 'pfv_q15_63', 'pfv_q15_126',
    'pfv_cal_21', 'pfv_cal_63', 'pfv_cal_126',
    'fwd_premium_21d', 'fwd_premium_63d', 'fwd_premium_126d',
    'fwd_premium_21_to_63d', 'fwd_premium_63_to_126d',
    'fwd_premium_ewma_21d', 'fwd_premium_ewma_63d', 'fwd_premium_ewma_126d',
    'next_earnings_date', 'days_to_earnings',
    'next_dividend_date', 'days_to_dividend',
    'model_run_id',
]


def split_per_ticker_for_supabase(df: pd.DataFrame, security_id: int):
    """Take the fat per-ticker DataFrame and split into the column groups
    needed by Supabase tables. Adds security_id to each frame."""
    prices = df[PRICES_COLS].copy()
    prices['security_id'] = security_id
    prices = prices[['security_id'] + PRICES_COLS]

    vol = df[VOLATILITY_COLS].copy()
    vol['security_id'] = security_id
    vol = vol[['security_id'] + VOLATILITY_COLS]

    return prices, vol


def push_ticker_to_supabase(
    db,
    ticker: str,
    df: pd.DataFrame,
    run_id: int,
    append_only: bool = False,
):
    """Push a per-ticker fat DataFrame to Supabase.

    If append_only=True, queries the DB for the latest date already loaded
    and only pushes rows newer than that.
    """
    security_id = db.get_security_id(ticker)
    if security_id is None:
        print(f'  [supabase] {ticker}: no security_id in securities table — skipping. '
              f'Insert into securities first.')
        return

    push_df = df.copy()

    if append_only and not db.dry_run:
        last_date = db.get_last_volatility_date(security_id)
        if last_date is not None:
            push_df['date'] = pd.to_datetime(push_df['date'])
            push_df = push_df[push_df['date'] > last_date]
            print(f'  [supabase] {ticker}: appending {len(push_df)} new rows '
                  f'(last DB date: {last_date.date()})')
        else:
            print(f'  [supabase] {ticker}: no prior rows in DB — full upload')

    if push_df.empty:
        print(f'  [supabase] {ticker}: no new rows to push')
        return

    push_df['model_run_id'] = run_id
    prices, vol = split_per_ticker_for_supabase(push_df, security_id)

    db.upsert_prices_history(prices)
    db.upsert_volatility_history(vol, run_id=run_id)


def export_one_ticker(
    ticker: str,
    run_id: int = 1,
    db = None,
    append_only: bool = False,
):
    """Generate the per-ticker file for one symbol. Optionally push to Supabase."""
    EXPORT_DIR.mkdir(exist_ok=True)
    TICKERS_DIR.mkdir(exist_ok=True)

    print(f'\nLoading predictions...')
    preds = load_predictions()
    print(f'  {len(preds):,} prediction rows total')

    print(f'\nPivoting predictions for {ticker}...')
    wide = pivot_predictions(preds, ticker)
    print(f'  {len(wide):,} prediction days for {ticker}')

    start = wide['date'].min().strftime('%Y-%m-%d')
    end   = (wide['date'].max() + pd.Timedelta(days=2)).strftime('%Y-%m-%d')
    ohlcv = fetch_ohlcv(ticker, start, end)
    print(f'  {len(ohlcv):,} OHLCV rows from CRSP parquet (v6 split-fix methodology)')

    out = build_per_ticker_file(ticker, wide, ohlcv, run_id)
    out_path = TICKERS_DIR / f'predictions_{ticker}.csv'
    out.to_csv(out_path, index=False)
    print(f'\nWrote {len(out):,} rows -> {out_path}')
    print(f'  Columns ({len(out.columns)}): {list(out.columns)}')

    # Sample peek
    print(f'\nFirst 3 rows + last 3 rows (selected columns):')
    peek_cols = ['date','close','rv','iv_atm_30d','vrp_wedge',
                 'vrp_wedge_ewma_21d','pfv_cal_21','pfv_cal_63','pfv_cal_126','model_run_id']
    print(out[peek_cols].head(3).to_string(index=False))
    print('  ...')
    print(out[peek_cols].tail(3).to_string(index=False))

    if db is not None:
        print(f'\n[supabase] Pushing {ticker}...')
        push_ticker_to_supabase(db, ticker, out, run_id=run_id, append_only=append_only)

    return out_path


def export_all(
    run_id: int = 1,
    db = None,
    append_only: bool = False,
):
    """Generate the full handoff bundle for every ticker present in predictions.
    Optionally push to Supabase."""
    EXPORT_DIR.mkdir(exist_ok=True)
    TICKERS_DIR.mkdir(exist_ok=True)

    preds = load_predictions()
    tickers = sorted(preds['ticker'].unique())
    print(f'Exporting {len(tickers)} tickers...')

    # Insert a new model_runs row first (DB writes will FK to this)
    if db is not None and not append_only:
        manifest = {
            'run_date':      pd.Timestamp.now().strftime('%Y-%m-%d'),
            'model_version': 'v10+',
            'spec_hash':     '0356b9d',
            'n_tickers':     len(tickers),
            'horizons':      [21, 63, 126],
            'notes':         f'export_for_webapp.py corpus run ({len(tickers)} tickers)',
        }
        new_run_id = db.upsert_model_run(manifest)
        if new_run_id is not None:
            run_id = new_run_id
            print(f'[supabase] Using run_id={run_id} for this export')

    for i, t in enumerate(tickers, start=1):
        try:
            print(f'\n[{i}/{len(tickers)}] {t}')
            export_one_ticker(t, run_id=run_id, db=db, append_only=append_only)
        except Exception as e:
            print(f'  FAILED: {e}')

    # Pre-load ticker → security_id mapping from live DB so event_history
    # writes can resolve FKs. Empty dict if no DB connection (CSV-only mode).
    ticker_to_security_id = {}
    if db is not None and not append_only:
        try:
            sec_rows = db.client.table('securities').select('security_id,ticker').execute()
            ticker_to_security_id = {
                r['ticker']: r['security_id']
                for r in sec_rows.data if r.get('ticker')
            }
            print(f'[supabase] Loaded {len(ticker_to_security_id)} ticker→security_id mappings')
        except Exception as e:
            print(f'[supabase] WARNING — could not load ticker mappings: {e}')

    # Sparse files (CSV side always; DB side if not append-only)
    write_securities_metadata(tickers)
    write_event_history(tickers, ticker_to_security_id=ticker_to_security_id)
    # Macro calendar spans the prediction date range so the frontend can
    # serve "next FOMC: N days" on any historical date the user navigates to.
    macro_start = preds['date'].min().strftime('%Y-%m-%d')
    macro_end = (pd.Timestamp.now() + pd.Timedelta(days=730)).strftime('%Y-%m-%d')
    write_macro_calendar(macro_start, macro_end)
    write_run_manifest(run_id=run_id, n_tickers=len(tickers))

    if db is not None and not append_only:
        print(f'\n[supabase] Pushing supporting tables...')
        # securities — only updates existing rows (won't insert new IDs)
        try:
            sec_df = pd.read_csv(EXPORT_DIR / 'securities_metadata.csv')
            # Only push fields that won't conflict — we DON'T own security_id assignment
            sec_df = sec_df[sec_df['ticker'].isin(ticker_to_security_id.keys())].copy()
            sec_df['security_id'] = sec_df['ticker'].map(ticker_to_security_id)
            db.upsert_securities(sec_df)
        except Exception as e:
            print(f'  [supabase] securities upsert failed: {e}')
        # event_history — per-ticker earnings + dividends
        try:
            evt_path = EXPORT_DIR / 'event_history.csv'
            if evt_path.exists():
                evt_df = pd.read_csv(evt_path, parse_dates=['event_date'])
                db.upsert_event_history(evt_df)
        except Exception as e:
            print(f'  [supabase] event_history upsert failed: {e}')
        # macro_calendar — forward FOMC/CPI/NFP per business day
        try:
            macro_df = pd.read_csv(EXPORT_DIR / 'macro_calendar.csv',
                                   parse_dates=['date', 'event_date'])
            db.upsert_macro_calendar(macro_df)
        except Exception as e:
            print(f'  [supabase] macro_calendar upsert failed: {e}')

    print(f'\nBundle complete: {EXPORT_DIR}')


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--ticker', help='Single ticker to export')
    p.add_argument('--all',    action='store_true', help='Export all tickers')
    p.add_argument('--run-id', type=int, default=1, help='Model run ID (FK target)')
    p.add_argument('--push-to-supabase', action='store_true',
                   help='Also upsert rows into Supabase tables')
    p.add_argument('--append-only', action='store_true',
                   help='Only push rows newer than the latest date already in Supabase')
    p.add_argument('--dry-run', action='store_true',
                   help='With --push-to-supabase: log operations without sending them')
    args = p.parse_args()

    # Construct DB client only if push is requested
    db = None
    if args.push_to_supabase:
        from .db import SupabaseClient, SchemaMismatchError
        db = SupabaseClient(dry_run=args.dry_run)
        if not args.dry_run:
            try:
                missing = db.verify_schema()
                if missing:
                    print('\nSchema gaps detected. Apply migration 001 before pushing.')
                    sys.exit(2)
            except SchemaMismatchError as e:
                print(f'\nFATAL: {e}')
                sys.exit(2)

    if args.all:
        export_all(run_id=args.run_id, db=db, append_only=args.append_only)
    elif args.ticker:
        EXPORT_DIR.mkdir(exist_ok=True)
        TICKERS_DIR.mkdir(exist_ok=True)
        export_one_ticker(args.ticker, run_id=args.run_id, db=db,
                          append_only=args.append_only)
        # Supporting files in single-ticker mode (CSV side)
        write_securities_metadata([args.ticker])
        write_events_history([args.ticker])
        write_macro_calendar(
            start=(pd.Timestamp.now() - pd.Timedelta(days=365 * 12)).strftime('%Y-%m-%d'),
            end=(pd.Timestamp.now() + pd.Timedelta(days=730)).strftime('%Y-%m-%d'),
        )
        write_run_manifest(run_id=args.run_id, n_tickers=1)
    else:
        p.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()