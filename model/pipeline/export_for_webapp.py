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
    wide = wide.reset_index().sort_values('date').dropna(subset=['y_true_21'])
    return wide


def fetch_ohlcv(ticker: str, start: str, end: str) -> pd.DataFrame:
    """Pull OHLCV for the prediction date range. Uses yfinance as a stand-in;
    production should pull from the CRSP parquet cache."""
    import yfinance as yf
    print(f'  Pulling OHLCV from yfinance for {ticker} {start} -> {end}...')
    h = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=False)
    if isinstance(h.columns, pd.MultiIndex):
        h.columns = h.columns.get_level_values(0)
    h = h.reset_index()
    h.columns = [c.lower() if c.lower() in ('open','high','low','close','volume') else c for c in h.columns]
    h = h.rename(columns={'Date':'date','Adj Close':'adj_close'})
    h['date'] = pd.to_datetime(h['date'])
    return h[['date','open','high','low','close','adj_close','volume']]


def synthesize_iv_term_structure(iv_atm_30d: pd.Series, seed: int = 42) -> dict:
    """Placeholder: production reads iv_atm_60d/91d/182d directly from vsurfd parquet.
    For the sample bundle we emit NULLs so the web dev can see the column structure
    but knows the true values come from the OptionMetrics ETL."""
    n = len(iv_atm_30d)
    return {
        'iv_atm_60d':  pd.Series([None] * n, index=iv_atm_30d.index),
        'iv_atm_91d':  pd.Series([None] * n, index=iv_atm_30d.index),
        'iv_atm_182d': pd.Series([None] * n, index=iv_atm_30d.index),
    }


def build_shap_blob_placeholder(horizon: int) -> str:
    """Placeholder SHAP JSON. Real values come from a SHAP run on the trained
    XGBoost model (TreeExplainer.shap_values on the day's feature row).
    Emit an empty-features blob so the web dev can see the shape."""
    payload = {
        'base_value': None,
        'predicted_value': None,
        'features': [],
        '_placeholder': True,
        '_note': 'Populated by SHAP step in production export. See SUPABASE_SCHEMA.md §2.',
    }
    return json.dumps(payload, separators=(',', ':'))


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

    # IV term structure: 30d reconstructable, others NULL until vsurfd ETL is wired
    out['iv_atm_30d']  = df['vrp_wedge_21'] + df['y_true_21']
    iv_extras = synthesize_iv_term_structure(out['iv_atm_30d'])
    out['iv_atm_60d']  = iv_extras['iv_atm_60d'].values
    out['iv_atm_91d']  = iv_extras['iv_atm_91d'].values
    out['iv_atm_182d'] = iv_extras['iv_atm_182d'].values

    # VRP
    out['vrp_wedge']           = df['vrp_wedge_21']
    out['vrp_wedge_ewma_21d']  = df['vrp_wedge_21'].ewm(span=21, adjust=False).mean()

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

    # SHAP placeholders (see note in build_shap_blob_placeholder)
    out['shap_h21_top10']  = build_shap_blob_placeholder(21)
    out['shap_h63_top10']  = build_shap_blob_placeholder(63)
    out['shap_h126_top10'] = build_shap_blob_placeholder(126)

    # Forward events: production reads from Compustat earnings/dividends.
    # Emit NULL placeholders.
    out['next_earnings_date'] = None
    out['days_to_earnings']   = None
    out['next_dividend_date'] = None
    out['days_to_dividend']   = None

    # Run reference
    out['model_run_id'] = run_id

    # Enforce column order from schema spec
    out = out[PER_TICKER_COLUMNS]
    return out


def write_securities_metadata(tickers_present: list[str]):
    """Generate securities_metadata.csv for the active universe + excluded list."""
    rows = []
    for t in tickers_present:
        rows.append({
            'symbol':           t,
            'gics_sector':      SECTORS.get(t, 'Other'),
            'gics_industry':    None,
            'sector_etf':       SECTOR_ETF_MAP.get(SECTORS.get(t, ''), 'SPY'),
            'active':           True,
            'excluded_reason':  None,
            'min_history_date': None,    # filled in downstream
        })
    for t, reason in EXCLUDED.items():
        rows.append({
            'symbol':           t,
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


def write_placeholders_for_supporting_files():
    """Empty-but-headed CSVs for the events/macro files so the web dev sees
    the schema. Production export populates from Compustat/FOMC sources."""
    pd.DataFrame(columns=['event_date','event_type','severity','scope',
                          'scope_value','title','description','source']).to_csv(
        EXPORT_DIR / 'events_history.csv', index=False)
    pd.DataFrame(columns=['date','event_type','event_date','days_to_event']).to_csv(
        EXPORT_DIR / 'macro_calendar.csv', index=False)


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
    print(f'  {len(ohlcv):,} OHLCV rows from yfinance')

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

    # Sparse files (CSV side always; DB side if not append-only)
    write_securities_metadata(tickers)
    write_placeholders_for_supporting_files()
    write_run_manifest(run_id=run_id, n_tickers=len(tickers))

    if db is not None and not append_only:
        print(f'\n[supabase] Pushing supporting tables...')
        try:
            sec_df = pd.read_csv(EXPORT_DIR / 'securities_metadata.csv')
            db.upsert_securities(sec_df)
        except Exception as e:
            print(f'  [supabase] securities upsert failed: {e}')

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
        write_placeholders_for_supporting_files()
        write_run_manifest(run_id=args.run_id, n_tickers=1)
    else:
        p.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()