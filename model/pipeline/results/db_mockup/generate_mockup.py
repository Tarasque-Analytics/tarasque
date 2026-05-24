"""
generate_mockup.py — Generate mockup rows for each Supabase table proposed
in the equity-page schema design, using actual recent run data.

Output: per-table CSVs in db_mockup/ that show what each table would look like
populated. Lets us verify the schema reflects the data we have before any
migrations are written.

Tables mocked:
  1. securities                  — extended metadata
  2. volatility_history          — daily model outputs + IV term structure + EWMA
  3. prices_history              — equity OHLCV (yfinance proxy for CRSP)
  4. options_chain               — options snapshot for one ticker (yfinance)
  5. ai_overview_equity          — daily LLM commentary (synthetic — placeholder)
  6. shap_snapshot               — SHAP feature contributions (synthetic from feature importances)
  7. model_runs                  — registry of retrains
  8. get_distribution_rpc_output — sample RPC return shape

Run from repo root:
  python model/pipeline/results/db_mockup/generate_mockup.py
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import json
import hashlib
import numpy as np
import pandas as pd
from pathlib import Path
import warnings
warnings.filterwarnings('ignore')

RESULTS_DIR = Path('model/pipeline/results')
MOCKUP_DIR  = RESULTS_DIR / 'db_mockup'
MOCKUP_DIR.mkdir(exist_ok=True)

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

# ── Load source data ──────────────────────────────────────────────────────────
print('Loading source data...')
preds = pd.read_csv(RESULTS_DIR / 'all_predictions_cal.csv')
preds['date'] = pd.to_datetime(preds['date'])
backtest = pd.read_csv(RESULTS_DIR / 'backtest_results.csv')
mz_cal   = pd.read_csv(RESULTS_DIR / 'mz_calibration.csv')

print(f'  predictions: {len(preds):,} rows')
print(f'  backtest:    {len(backtest):,} rows')

# Pivot predictions wide so each (ticker, date) has columns for h21/h63/h126
print('\nPivoting predictions to wide format...')
pivoted = preds.pivot_table(
    index=['ticker','date'],
    columns='horizon',
    values=['y_true','y_pred','y_pred_q15','y_cal','vrp_wedge','put_call_skew_30d']
).reset_index()
pivoted.columns = ['_'.join(str(c) for c in col).strip('_') for col in pivoted.columns.values]
print(f'  pivoted shape: {pivoted.shape}')

# ═══════════════════════════════════════════════════════════════════════════════
# 1. securities  — extended metadata
# ═══════════════════════════════════════════════════════════════════════════════
print('\n[1/8] securities table...')

tickers_in_data = sorted(preds['ticker'].unique())
securities = []
for i, t in enumerate(tickers_in_data, start=1):
    sector = SECTORS.get(t, 'Other')
    sub = preds[preds['ticker'] == t]
    securities.append({
        'security_id':       i,
        'symbol':            t,
        'gics_sector':       sector,
        'gics_industry':     None,           # would come from Compustat in production
        'sector_etf':        SECTOR_ETF_MAP.get(sector, 'SPY'),
        'active':            True,
        'excluded_reason':   None,
        'min_history_date':  sub['date'].min().strftime('%Y-%m-%d'),
        'last_model_run':    '2026-05-04 07:14:09',
    })
# Add exclusion examples
for t, reason in [('LIN','R²=0.94 leakage from Linde-Praxair merger'),
                   ('OXY','RMSE explosion'),
                   ('VZ','Frontier Communications acquisition β=2.6 at H=126'),
                   ('META','Insufficient post-IPO history')]:
    securities.append({
        'security_id': len(securities) + 1, 'symbol': t,
        'gics_sector': SECTORS.get(t,'Other'), 'gics_industry': None,
        'sector_etf': None, 'active': False, 'excluded_reason': reason,
        'min_history_date': None, 'last_model_run': None,
    })
sec_df = pd.DataFrame(securities)
sec_df.to_csv(MOCKUP_DIR / '01_securities.csv', index=False)
print(f'  {len(sec_df)} rows → 01_securities.csv')

ticker_to_id = dict(zip(sec_df['symbol'], sec_df['security_id']))


# ═══════════════════════════════════════════════════════════════════════════════
# 2. volatility_history — the core time series table
# ═══════════════════════════════════════════════════════════════════════════════
print('\n[2/8] volatility_history (sample: AAPL last 20 days + 3 other tickers tail)...')

# Build wide volatility_history rows
vh_records = []
for ticker, grp in pivoted.groupby('ticker'):
    if ticker not in ticker_to_id:
        continue
    sec_id = ticker_to_id[ticker]
    grp = grp.sort_values('date')

    # Compute 21d EWMA of vrp_wedge_21 (the H=21 wedge)
    vrp = grp['vrp_wedge_21'] if 'vrp_wedge_21' in grp.columns else None
    ewma = vrp.ewm(span=21, adjust=False).mean() if vrp is not None else None

    for i, row in grp.iterrows():
        # IV reconstruction: vrp_wedge = iv_atm_30d - rv_TARGET
        # so iv_atm_30d = vrp_wedge + y_true (rv at H=21 is the TARGET window)
        iv30 = (row.get('vrp_wedge_21', np.nan) + row.get('y_true_21', np.nan)
                if not pd.isna(row.get('vrp_wedge_21')) else None)
        # 60/91/182 not in current data — leave NaN, populated by IV surface ETL in prod
        vh_records.append({
            'security_id':       sec_id,
            'date':              row['date'].strftime('%Y-%m-%d'),
            'rv':                row.get('y_true_21'),
            'iv_atm_30d':        iv30,
            'iv_atm_60d':        None,
            'iv_atm_91d':        None,
            'iv_atm_182d':       None,
            'vrp_wedge':         row.get('vrp_wedge_21'),
            'vrp_wedge_ewma_21d':ewma.loc[i] if ewma is not None and i in ewma.index else None,
            'pfv_21':            row.get('y_pred_21'),
            'pfv_63':            row.get('y_pred_63'),
            'pfv_126':           row.get('y_pred_126'),
            'pfv_q15_21':        row.get('y_pred_q15_21'),
            'pfv_q15_63':        row.get('y_pred_q15_63'),
            'pfv_q15_126':       row.get('y_pred_q15_126'),
            'pfv_cal_21':        row.get('y_cal_21'),
            'pfv_cal_63':        row.get('y_cal_63'),
            'pfv_cal_126':       row.get('y_cal_126'),
            'model_run_id':      1,
        })

vh_df = pd.DataFrame(vh_records)
# Sample: last 20 days of AAPL + tail of 3 other tickers
sample_idx = []
for t in ['AAPL','JPM','XOM','TSLA']:
    sec_id = ticker_to_id.get(t)
    if sec_id is None: continue
    rows = vh_df[vh_df['security_id'] == sec_id].tail(20 if t == 'AAPL' else 5)
    sample_idx.extend(rows.index.tolist())
vh_sample = vh_df.loc[sample_idx]
vh_sample.to_csv(MOCKUP_DIR / '02_volatility_history_sample.csv', index=False)
print(f'  full: {len(vh_df):,} rows | sample written: {len(vh_sample)} rows → 02_volatility_history_sample.csv')


# ═══════════════════════════════════════════════════════════════════════════════
# 3. prices_history — equity OHLCV (yfinance proxy)
# ═══════════════════════════════════════════════════════════════════════════════
print('\n[3/8] prices_history (yfinance pull for AAPL, JPM, XOM, TSLA)...')

import yfinance as yf
sample_tickers = ['AAPL','JPM','XOM','TSLA']
prices_records = []
for t in sample_tickers:
    sec_id = ticker_to_id.get(t)
    if sec_id is None: continue
    hist = yf.download(t, period='1mo', progress=False, auto_adjust=False)
    if hist.empty: continue
    if isinstance(hist.columns, pd.MultiIndex):
        hist.columns = hist.columns.get_level_values(0)
    for date, row in hist.iterrows():
        prices_records.append({
            'security_id': sec_id,
            'date':        date.strftime('%Y-%m-%d'),
            'open':        round(float(row['Open']), 4),
            'high':        round(float(row['High']), 4),
            'low':         round(float(row['Low']), 4),
            'close':       round(float(row['Close']), 4),
            'adj_close':   round(float(row['Adj Close']), 4),
            'volume':      int(row['Volume']),
        })
ph_df = pd.DataFrame(prices_records)
ph_df.to_csv(MOCKUP_DIR / '03_prices_history.csv', index=False)
print(f'  {len(ph_df)} rows → 03_prices_history.csv')


# ═══════════════════════════════════════════════════════════════════════════════
# 4. options_chain — yfinance options snapshot for AAPL
# ═══════════════════════════════════════════════════════════════════════════════
print('\n[4/8] options_chain (AAPL nearest expiry)...')

oc_records = []
try:
    aapl = yf.Ticker('AAPL')
    expiries = aapl.options[:2]  # nearest 2 expiries
    for expiry in expiries:
        chain = aapl.option_chain(expiry)
        snapshot_date = pd.Timestamp.now().strftime('%Y-%m-%d')
        for opt_type_letter, df in [('C', chain.calls), ('P', chain.puts)]:
            for _, row in df.iterrows():
                oc_records.append({
                    'security_id':   ticker_to_id['AAPL'],
                    'snapshot_date': snapshot_date,
                    'expiry':        expiry,
                    'strike':        round(float(row['strike']), 2),
                    'option_type':   opt_type_letter,
                    'bid':           round(float(row.get('bid', 0)), 2),
                    'ask':           round(float(row.get('ask', 0)), 2),
                    'mid':           round((float(row.get('bid',0)) + float(row.get('ask',0))) / 2, 2),
                    'last':          round(float(row.get('lastPrice', 0)), 2),
                    'volume':        int(row.get('volume', 0) or 0),
                    'open_interest': int(row.get('openInterest', 0) or 0),
                    'iv':            round(float(row.get('impliedVolatility', 0) or 0), 4),
                    'delta':         None,  # yfinance doesn't expose
                })
    oc_df = pd.DataFrame(oc_records)
    oc_sample = oc_df.head(40)  # representative sample
    oc_sample.to_csv(MOCKUP_DIR / '04_options_chain_sample.csv', index=False)
    print(f'  full: {len(oc_df)} rows | sample: {len(oc_sample)} rows → 04_options_chain_sample.csv')
except Exception as e:
    print(f'  yfinance options pull failed: {e}; writing placeholder')
    placeholder = pd.DataFrame([{
        'security_id': 1, 'snapshot_date': '2026-05-07', 'expiry': '2026-05-16',
        'strike': 200.00, 'option_type': 'C', 'bid': 2.40, 'ask': 2.50,
        'mid': 2.45, 'last': 2.47, 'volume': 5421, 'open_interest': 12880,
        'iv': 0.2814, 'delta': None,
    }])
    placeholder.to_csv(MOCKUP_DIR / '04_options_chain_sample.csv', index=False)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. ai_overview_equity  (synthetic LLM commentary structure)
# ═══════════════════════════════════════════════════════════════════════════════
print('\n[5/8] ai_overview_equity (synthetic — illustrating shape only)...')

# Pull current values from regime to make plausible commentary
regime = pd.read_csv(RESULTS_DIR / 'vol_regime_summary.csv')
regime_lookup = {r['ticker']: r for _, r in regime.iterrows()}

def risk_tier_from_pct(pct):
    if pct < 0.25:   return 'Suppressed'
    if pct < 0.50:   return 'Normal'
    if pct < 0.75:   return 'Elevated'
    if pct < 0.90:   return 'Stress'
    return 'Crisis'

ai_records = []
for ai_id, t in enumerate(['AAPL','JPM','XOM','TSLA','META','NVDA'], start=1):
    sec_id = ticker_to_id.get(t)
    if sec_id is None: continue
    r = regime_lookup.get(t)
    if r is None: continue

    rv_pct, iv_pct, vrp = r['rv_pct'], r['iv_pct'], r['vrp_current']
    tier = risk_tier_from_pct(iv_pct)

    headline = f"{t}: {tier.lower()} regime — IV at P{int(iv_pct*100)}, VRP {vrp:+.1%}"
    body = (f"Implied vol ranks at the {int(iv_pct*100)}th percentile of {t}'s "
            f"own history while realized vol sits at P{int(rv_pct*100)}, leaving "
            f"a VRP wedge of {vrp:+.1%}. Model forecasts {r['pred_current']:.1%} "
            f"21-day vol vs. current implied of {r['iv_current']:.1%}.")
    drivers = [
        {'name': 'iv_atm_z_score',  'value': 1.42, 'shap': 0.024,  'rank': 1},
        {'name': 'vrp_wedge',       'value': vrp,  'shap': -0.012, 'rank': 2},
        {'name': 'macro_yield_curve_slope', 'value': 0.84, 'shap': 0.009, 'rank': 3},
    ]
    content = {
        'body':         body,
        'key_drivers':  drivers,
        'confidence':   0.82,
        'sentiment':    'cautious' if iv_pct > 0.6 else 'neutral',
    }
    payload_str = json.dumps(content, sort_keys=True)
    input_hash  = hashlib.sha256(payload_str.encode()).hexdigest()[:16]

    ai_records.append({
        'id':              ai_id,
        'security_id':     sec_id,
        'date':            '2026-05-06',
        'model_version':   'claude-opus-4-7',
        'prompt_version':  'v3',
        'headline':        headline,
        'risk_tier':       tier,
        'content':         payload_str,
        'input_hash':      input_hash,
        'input_tokens':    485,
        'output_tokens':   312,
        'generated_at':    '2026-05-07 06:32:18+00',
        'flagged':         False,
        'flagged_reason':  None,
    })
ai_df = pd.DataFrame(ai_records)
ai_df.to_csv(MOCKUP_DIR / '05_ai_overview_equity.csv', index=False)
print(f'  {len(ai_df)} rows → 05_ai_overview_equity.csv')


# ═══════════════════════════════════════════════════════════════════════════════
# 6. shap_snapshot
# ═══════════════════════════════════════════════════════════════════════════════
print('\n[6/8] shap_snapshot (illustrative shape — feature contributions as JSONB)...')

# Synthetic SHAP values calibrated to known feature importance ranks
shap_records = []
SAMPLE_FEATURES = [
    ('iv_atm_z_score',          'IV Z-Score'),
    ('vrp_wedge',               'VRP Wedge'),
    ('macro_yield_curve_slope', 'Yield Curve Slope'),
    ('rv_21d',                  'Realized Vol 21d'),
    ('vol_regime_zscore',       'Vol Regime Z-Score'),
    ('garch_cond_vol',          'GARCH Conditional Vol'),
    ('macro_hy_spread',         'HY Credit Spread'),
    ('event_earn_gravity',      'Earnings Proximity'),
    ('put_call_skew_30d',       '25Δ Put-Call Skew'),
    ('mom21_VIXY',              'VIXY 21d Momentum'),
]

for t in ['AAPL','JPM','XOM','TSLA','META','NVDA']:
    sec_id = ticker_to_id.get(t)
    if sec_id is None: continue
    for h in [21, 63, 126]:
        # Synthetic SHAP — rank top features with realistic magnitudes
        rng = np.random.default_rng(seed=hash((t,h)) & 0xFFFF)
        base_value = -1.4 + rng.normal(0, 0.05)
        contributions = []
        total_shap = 0.0
        for name, display in SAMPLE_FEATURES:
            shap_val = float(rng.normal(0, 0.05))
            contributions.append({
                'name':      name,
                'display':   display,
                'value':     round(float(rng.normal(0, 1.0)), 4),
                'shap':      round(shap_val, 4),
                'abs_shap':  round(abs(shap_val), 4),
            })
            total_shap += shap_val
        contributions.sort(key=lambda c: c['abs_shap'], reverse=True)
        feature_data = {'features': contributions}

        shap_records.append({
            'security_id':     sec_id,
            'retrain_date':    '2026-05-04',
            'horizon':         h,
            'snapshot_date':   '2026-05-06',
            'base_value':      round(base_value, 4),
            'predicted_value': round(base_value + total_shap, 4),
            'feature_data':    json.dumps(feature_data),
        })
shap_df = pd.DataFrame(shap_records)
shap_df.to_csv(MOCKUP_DIR / '06_shap_snapshot.csv', index=False)
print(f'  {len(shap_df)} rows → 06_shap_snapshot.csv (each row contains JSONB blob)')


# ═══════════════════════════════════════════════════════════════════════════════
# 7. model_runs
# ═══════════════════════════════════════════════════════════════════════════════
print('\n[7/8] model_runs registry...')

mr_records = [
    {'id': 1, 'run_date': '2026-05-04', 'model_version': 'v10',
     'spec_hash': '0356b9d', 'n_tickers': 24, 'horizons': '{21,63,126}',
     'notes': 'v10+ 24 ticker test finished & analytics',
     'created_at': '2026-05-04 07:14:09+00'},
    {'id': 2, 'run_date': '2026-04-30', 'model_version': 'v9',
     'spec_hash': 'e49e488', 'n_tickers': 12, 'horizons': '{21,63,126}',
     'notes': 'preliminary apply volatility graph viz',
     'created_at': '2026-04-30 19:34:11+00'},
    {'id': 3, 'run_date': '2026-04-23', 'model_version': 'v8',
     'spec_hash': '4cc522e', 'n_tickers': 93, 'horizons': '{21,63,126}',
     'notes': 'old payload removal; 20-day data increments; csv output format setup',
     'created_at': '2026-04-30 19:21:12+00'},
    {'id': 4, 'run_date': '2026-04-16', 'model_version': 'v7',
     'spec_hash': '486d5a7', 'n_tickers': 97, 'horizons': '{21,63,126}',
     'notes': 'ElasticNet replaces LassoCV; sector coupling restored',
     'created_at': '2026-04-16 17:47:19+00'},
]
mr_df = pd.DataFrame(mr_records)
mr_df.to_csv(MOCKUP_DIR / '07_model_runs.csv', index=False)
print(f'  {len(mr_df)} rows → 07_model_runs.csv')


# ═══════════════════════════════════════════════════════════════════════════════
# 8. get_distribution RPC output (sample)
# ═══════════════════════════════════════════════════════════════════════════════
print('\n[8/8] get_distribution RPC sample output (AAPL, metric=rv)...')

# Compute actual histograms for AAPL rv vs sector pool vs market pool
metric = 'rv'
target_ticker = 'AAPL'
sec_id = ticker_to_id[target_ticker]
sector = SECTORS[target_ticker]

# Stock distribution
stock_vals = vh_df[vh_df['security_id'] == sec_id]['rv'].dropna().values

# Sector pool (other Tech tickers)
sector_tickers = [t for t,s in SECTORS.items() if s == sector and t in ticker_to_id]
sector_ids = [ticker_to_id[t] for t in sector_tickers]
sector_vals = vh_df[vh_df['security_id'].isin(sector_ids)]['rv'].dropna().values

# Market pool (all 91)
market_vals = vh_df['rv'].dropna().values

current_value = stock_vals[-1] if len(stock_vals) > 0 else None

def histogram_records(values, scope_label, current_val):
    if len(values) == 0:
        return []
    counts, edges = np.histogram(values, bins=30)
    pct = float((values < current_val).mean()) if current_val is not None else None
    rows = []
    for i in range(len(counts)):
        rows.append({
            'scope':              scope_label,
            'bin_low':            round(float(edges[i]), 4),
            'bin_high':           round(float(edges[i+1]), 4),
            'count':              int(counts[i]),
            'current_value':      round(float(current_val), 4) if current_val else None,
            'current_percentile': round(pct, 4) if pct is not None else None,
        })
    return rows

dist_records = (
    histogram_records(stock_vals,  'stock',  current_value) +
    histogram_records(sector_vals, 'sector', current_value) +
    histogram_records(market_vals, 'market', current_value)
)
dist_df = pd.DataFrame(dist_records)
dist_df.to_csv(MOCKUP_DIR / '08_get_distribution_rpc_output.csv', index=False)
print(f'  {len(dist_df)} rows → 08_get_distribution_rpc_output.csv')

# ── README ────────────────────────────────────────────────────────────────────
readme = """# Tarasque Equity Page — Database Mockup

Generated from real recent run data (v10 24-ticker, v9 canary, v6 corpus) to
verify the schema design supports every visualization on /equity/:symbol.

## Tables

| File | Table | Notes |
|---|---|---|
| 01_securities.csv | securities | Extended with sector, exclusion reason, history bounds. 91 active + 4 excluded. |
| 02_volatility_history_sample.csv | volatility_history | Wide format: rv, iv (4 DTEs), vrp_wedge + EWMA, pfv at 3 horizons (raw/q15/calibrated). Sample shows AAPL last 20d + others. |
| 03_prices_history.csv | prices_history | Equity OHLCV; backend cache, daily ETL. Pulled fresh from yfinance for the mockup. |
| 04_options_chain_sample.csv | options_chain | Snapshot per (security, snapshot_date, expiry, strike, type). Daily backend pull. |
| 05_ai_overview_equity.csv | ai_overview_equity | Hybrid storage — top-level (headline, risk_tier) + JSONB content blob. |
| 06_shap_snapshot.csv | shap_snapshot | Feature contributions as JSONB; one row per (security, retrain, horizon). |
| 07_model_runs.csv | model_runs | Registry — every prediction row references a model_run_id. |
| 08_get_distribution_rpc_output.csv | get_distribution() RPC | Sample output: histogram bins for stock/sector/market in one call. |

## Reading the volatility_history sample

Each row is one (ticker, date) snapshot. The 16 vol-related columns answer
every chart on the equity page:

- VRP EWMA panel below price       → vrp_wedge_ewma_21d
- Term-structure overlay           → pfv_21/63/126 + iv_atm_30d/60d/91d/182d
- Distribution charts              → any of the columns, ranked over history
- Forecast bands (options chart)   → pfv_21 + dte interpolation
- Calibration overlay (production) → pfv_cal_*

## Notes on this mockup

- iv_atm_30d in volatility_history is reconstructed as `vrp_wedge + y_true` since
  the prediction CSVs don't carry raw IV. In production the IV ETL writes it directly.
- iv_atm_60d/91d/182d are NULL in the sample — they require pulling from the
  OptionMetrics vsurfd surface ETL, not yet wired into the prediction CSV path.
- AI overview content is synthetic but its structure (headline + risk_tier
  top-level, content as JSONB) reflects the production schema.
- SHAP feature_data is synthetic — actual SHAP runs on the model would replace it.
- Options chain is a real yfinance pull for AAPL nearest expiries, capped at 40 rows.

## How a frontend page load consumes this

`GET /api/equity/AAPL` → backend issues:
1. `SELECT * FROM securities WHERE symbol = 'AAPL'`
2. `SELECT * FROM volatility_history WHERE security_id = 1 AND date >= NOW() - INTERVAL '5 years' ORDER BY date`
3. `SELECT * FROM prices_history WHERE security_id = 1 AND date >= NOW() - INTERVAL '1 year' ORDER BY date`
4. `SELECT * FROM options_chain WHERE security_id = 1 AND snapshot_date = (SELECT MAX(snapshot_date) FROM options_chain) ORDER BY expiry, strike`
5. `SELECT * FROM ai_overview_equity WHERE security_id = 1 AND model_version = $current AND prompt_version = $current AND flagged = FALSE ORDER BY date DESC LIMIT 1`
6. `SELECT * FROM shap_snapshot WHERE security_id = 1 AND retrain_date = (SELECT MAX(retrain_date) FROM shap_snapshot)`
7. `SELECT get_distribution(1, 'rv')` — and similar for iv/vrp/pfv on metric toggle

All seven assemble into one composite payload. Single React-Query hook on the page mount.
"""
(MOCKUP_DIR / 'README.md').write_text(readme, encoding='utf-8')
print(f'\n=== Mockup complete ===')
print(f'All files in: {MOCKUP_DIR}')