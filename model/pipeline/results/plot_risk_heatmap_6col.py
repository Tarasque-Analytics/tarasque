"""
plot_risk_heatmap_6col.py  —  Focused 6-column Risk Heatmap

Columns (in order):
  rv_pct        — Realized vol percentile (own-history rank)
  iv_pct        — Implied vol percentile (options market fear)
  pred_pct      — Model forecast percentile
  ret_21d_pct   — 21-day price return percentile (own-history rank)
  mz_beta       — MZ calibration (1=perfect, >1=model underforecasts)
  model_beta    — Model-derived forward beta (MZ-adjusted forecast / market vol)

Adapted from _session_backup_2026-04-27/plot_risk_heatmap.py.
Adds 21d returns percentile via yfinance pull; drops VRP z-score and put-call skew.

Outputs:
  risk_heatmap_6col_full.png
  risk_heatmap_6col_sectors.png
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import numpy as np
import pandas as pd
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import warnings
warnings.filterwarnings('ignore')

RESULTS_DIR = Path('model/pipeline/results')
BG       = '#0f0f0f'
PANEL_BG = '#1a1a1a'
WHITE    = '#f0f0f0'
DIM      = '#888888'
GRID     = '#2e2e2e'

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

SECTOR_ORDER = ['Tech','Financials','Health Care','Energy','Industrials',
                'Cons Disc','Comm','Staples','Utilities','REIT','Materials']

SECTOR_COLORS = {
    'Tech':'#4C72B0','Financials':'#55A868','Energy':'#C44E52','Industrials':'#8172B2',
    'Health Care':'#CCB974','Staples':'#64B5CD','Comm':'#FF8C00','Cons Disc':'#E377C2',
    'Materials':'#7F7F7F','Utilities':'#BCBD22','REIT':'#17BECF',
}

# ── Load core data ────────────────────────────────────────────────────────────
print('Loading data...')
regime   = pd.read_csv(RESULTS_DIR / 'vol_regime_summary.csv')
backtest = pd.read_csv(RESULTS_DIR / 'backtest_results.csv')

mz = backtest[backtest['horizon'] == 21][['ticker','mz_beta']].copy()

df = regime.merge(mz, on='ticker', how='left')
df['sector'] = df['ticker'].map(SECTORS).fillna('Other')

# Model-derived beta: MZ-adjusted forecast / market median forecast
sigma_market = df['pred_current'].median()
df['sigma_adj']  = df['mz_beta'].fillna(1.0) * df['pred_current']
df['model_beta'] = df['sigma_adj'] / sigma_market

print(f'  {len(df)} tickers from regime + backtest data')

# ── Compute 21-day return percentile via yfinance ─────────────────────────────
print('Computing 21d return percentiles (yfinance)...')
import yfinance as yf

tickers = df['ticker'].tolist()
# Pull 5 years of history for percentile ranking; one pull is faster than per-ticker
prices = yf.download(tickers, period='5y', progress=False, auto_adjust=True)['Close']

ret_21d_pct = {}
ret_21d_raw = {}
for t in tickers:
    if t not in prices.columns:
        ret_21d_pct[t] = np.nan
        ret_21d_raw[t] = np.nan
        continue
    p = prices[t].dropna()
    if len(p) < 50:
        ret_21d_pct[t] = np.nan
        ret_21d_raw[t] = np.nan
        continue
    r21 = np.log(p / p.shift(21)).dropna()
    if len(r21) < 30:
        ret_21d_pct[t] = np.nan
        ret_21d_raw[t] = np.nan
        continue
    current = r21.iloc[-1]
    pct = (r21 < current).mean()  # empirical percentile
    ret_21d_pct[t] = pct
    ret_21d_raw[t] = current

df['ret_21d_pct'] = df['ticker'].map(ret_21d_pct)
df['ret_21d_raw'] = df['ticker'].map(ret_21d_raw)
n_valid = df['ret_21d_pct'].notna().sum()
print(f'  21d returns computed for {n_valid}/{len(df)} tickers')

# ── Sort ──────────────────────────────────────────────────────────────────────
sector_sort = {s: i for i, s in enumerate(SECTOR_ORDER)}
df['sector_order'] = df['sector'].map(sector_sort).fillna(99)
df = df.sort_values(['sector_order','ticker']).reset_index(drop=True)


# ── Build heatmap matrix ─────────────────────────────────────────────────────
COLUMNS = {
    'rv_pct':      'RV\nPercentile',
    'iv_pct':      'IV\nPercentile',
    'pred_pct':    'Forecast\nPercentile',
    'ret_21d_pct': '21d Return\nPercentile',
    'mz_beta':     'MZ Beta\n(Calibration)',
    'model_beta':  'Model\nBeta',
}
col_keys = list(COLUMNS.keys())

heat = pd.DataFrame(index=df.index)
raw  = pd.DataFrame(index=df.index)

# Percentile columns: 0=low risk (green), 1=high risk (red)
# Note: 21d return percentile colored neutral here — high return ≠ high risk per se,
# but we still color by percentile so it scans visually consistent. Annotation shows raw %.
for col in ['rv_pct','iv_pct','pred_pct','ret_21d_pct']:
    heat[col] = df[col].fillna(0.5)
    raw[col]  = df[col].fillna(np.nan)

# MZ beta: 1=calibrated (neutral), >1.15=underforecast (risk), <0.85=overforecast
mz_raw = df['mz_beta'].fillna(1.0)
heat['mz_beta'] = ((mz_raw - 0.5) / 1.0).clip(0,1)
raw['mz_beta']  = mz_raw

# Model beta: 1=market risk, >1=more risk (red), <1=less risk (green)
mb_raw = df['model_beta'].fillna(1.0)
heat['model_beta'] = ((mb_raw - 0.3) / 1.4).clip(0,1)
raw['model_beta']  = mb_raw

heat_matrix = heat[col_keys].values
raw_matrix  = raw[col_keys].values


# ── CHART 1 — Full heatmap ────────────────────────────────────────────────────
print('[1/2] Full risk heatmap...')

n_tickers = len(df)
n_cols    = len(COLUMNS)
fig_h     = max(20, n_tickers * 0.22)

fig, ax = plt.subplots(figsize=(15, fig_h))
fig.patch.set_facecolor(BG)
ax.set_facecolor(PANEL_BG)

cmap = mcolors.LinearSegmentedColormap.from_list(
    'risk', ['#22c55e', '#1a1a1a', '#ef4444'], N=256
)

im = ax.imshow(heat_matrix, aspect='auto', cmap=cmap, vmin=0, vmax=1,
               interpolation='nearest')

# Cell annotations
for i in range(n_tickers):
    for j, col in enumerate(col_keys):
        val = raw_matrix[i, j]
        if pd.isna(val):
            txt = 'N/A'
        elif col in ('rv_pct','iv_pct','pred_pct','ret_21d_pct'):
            txt = f'{val:.0%}'
        else:
            txt = f'{val:.2f}'
        heat_val = heat_matrix[i, j]
        txt_col = WHITE if abs(heat_val - 0.5) > 0.25 else DIM
        ax.text(j, i, txt, ha='center', va='center',
                color=txt_col, fontsize=6.5)

# Sector dividers + labels
sector_series = df['sector'].values
prev = sector_series[0]
sector_starts = [(prev, 0)]
for i, s in enumerate(sector_series):
    if s != prev:
        ax.axhline(i - 0.5, color='#555', lw=1.2)
        sector_starts.append((s, i))
        prev = s
sector_starts.append((None, n_tickers))

for k in range(len(sector_starts) - 1):
    sector, start_i = sector_starts[k]
    end_i = sector_starts[k+1][1]
    mid = (start_i + end_i - 1) / 2
    scol = SECTOR_COLORS.get(sector, '#999')
    ax.plot(-0.7, mid, 's', color=scol, markersize=8, clip_on=False)
    ax.text(-1.1, mid, sector, ha='right', va='center',
            color=scol, fontsize=7, fontweight='bold', clip_on=False)

ax.set_xticks(range(n_cols))
ax.set_xticklabels([COLUMNS[k] for k in col_keys],
                   color=WHITE, fontsize=8.5, ha='center')
ax.set_yticks(range(n_tickers))
ax.set_yticklabels(df['ticker'], color=WHITE, fontsize=6.5)
ax.tick_params(colors=DIM, length=0)
for sp in ax.spines.values(): sp.set_color('#333')
ax.xaxis.set_ticks_position('top')
ax.xaxis.set_label_position('top')

cbar = plt.colorbar(im, ax=ax, fraction=0.008, pad=0.01, orientation='vertical')
cbar.set_ticks([0, 0.5, 1])
cbar.set_ticklabels(['Low Risk', 'Neutral', 'High Risk'])
plt.setp(cbar.ax.yaxis.get_ticklabels(), color=WHITE, fontsize=8)
cbar.ax.yaxis.set_tick_params(color=DIM)

ax.set_title(
    'Tarasque  —  Risk Heatmap (6-Column Focus)\n'
    'RV / IV / Forecast / 21d Return Percentiles  |  MZ Beta Calibration  |  Model Beta',
    color=WHITE, fontsize=12, pad=30, loc='left',
)

plt.tight_layout()
plt.savefig(RESULTS_DIR / 'risk_heatmap_6col_full.png', dpi=130,
            bbox_inches='tight', facecolor=BG)
plt.close()
print('  Saved: risk_heatmap_6col_full.png')


# ── CHART 2 — Sector medians ──────────────────────────────────────────────────
print('[2/2] Sector compact heatmap...')

sector_med = df.groupby('sector')[col_keys].median()
sector_med = sector_med.reindex([s for s in SECTOR_ORDER if s in sector_med.index])

heat_s = pd.DataFrame(index=sector_med.index)
for col in ['rv_pct','iv_pct','pred_pct','ret_21d_pct']:
    heat_s[col] = sector_med[col].fillna(0.5)
heat_s['mz_beta']    = ((sector_med['mz_beta'].fillna(1.0) - 0.5) / 1.0).clip(0,1)
heat_s['model_beta'] = ((sector_med['model_beta'].fillna(1.0) - 0.3) / 1.4).clip(0,1)

fig, ax = plt.subplots(figsize=(15, 6.5))
fig.patch.set_facecolor(BG)
ax.set_facecolor(PANEL_BG)

im2 = ax.imshow(heat_s.values, aspect='auto', cmap=cmap, vmin=0, vmax=1,
                interpolation='nearest')

for i, sector in enumerate(heat_s.index):
    scol = SECTOR_COLORS.get(sector, '#999')
    ax.plot(-0.6, i, 's', color=scol, markersize=10, clip_on=False)
    for j, col in enumerate(col_keys):
        raw_val  = sector_med.loc[sector, col]
        heat_val = heat_s.iloc[i, j]
        if col in ('rv_pct','iv_pct','pred_pct','ret_21d_pct'):
            txt = f'{raw_val:.0%}'
        else:
            txt = f'{raw_val:.2f}'
        txt_col = WHITE if abs(heat_val - 0.5) > 0.2 else DIM
        ax.text(j, i, txt, ha='center', va='center',
                color=txt_col, fontsize=10, fontweight='bold')

ax.set_xticks(range(n_cols))
ax.set_xticklabels([COLUMNS[k] for k in col_keys], color=WHITE, fontsize=9.5)
ax.set_yticks(range(len(heat_s)))
ax.set_yticklabels(heat_s.index, color=WHITE, fontsize=10)
ax.tick_params(colors=DIM, length=0)
for sp in ax.spines.values(): sp.set_color('#333')
ax.xaxis.set_ticks_position('top')

cbar2 = plt.colorbar(im2, ax=ax, fraction=0.015, pad=0.01)
cbar2.set_ticks([0, 0.5, 1])
cbar2.set_ticklabels(['Low Risk', 'Neutral', 'High Risk'])
plt.setp(cbar2.ax.yaxis.get_ticklabels(), color=WHITE, fontsize=8)

ax.set_title(
    'Tarasque  —  Sector Risk Summary  (Median per Sector)',
    color=WHITE, fontsize=12, pad=20, loc='left',
)
plt.tight_layout()
plt.savefig(RESULTS_DIR / 'risk_heatmap_6col_sectors.png', dpi=140,
            bbox_inches='tight', facecolor=BG)
plt.close()
print('  Saved: risk_heatmap_6col_sectors.png')

print('=== Risk heatmap (6-col) complete ===')
