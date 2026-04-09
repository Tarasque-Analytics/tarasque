"""
plot_pit_test.py  —  Probability Integral Transform calibration tests

What this tells you:
  A perfectly calibrated model's prediction errors, when converted to percentiles
  of the empirical error distribution, should be UNIFORM (flat histogram).
  Deviations reveal HOW the model misfits:
    - U-shaped: fat tails — model underestimates extreme moves
    - Hump-shaped: thin tails — model overestimates extremes, too conservative
    - Left-skewed mass: systematic overforecast
    - Right-skewed mass: systematic underforecast

Outputs:
  pit_test_market.png          — market-wide PIT histogram + KS test
  pit_test_by_sector.png       — PIT per sector
  pit_test_by_horizon.png      — PIT for H21 / H63 / H126
  pit_test_by_ticker_full.png  — 94-ticker grid

Run from repo root:
  python model/pipeline/results/plot_pit_test.py
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import os, re
import numpy as np
import pandas as pd
from pathlib import Path
from scipy import stats
from scipy.stats import uniform as sp_uniform
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import warnings
warnings.filterwarnings('ignore')

RESULTS_DIR = Path('model/pipeline/results')
BG       = '#0f0f0f'
PANEL_BG = '#1a1a1a'
WHITE    = '#f0f0f0'
DIM      = '#888888'
GRID     = '#2e2e2e'
GOOD_COL = '#22c55e'
WARN_COL = '#f59e0b'
BAD_COL  = '#ef4444'
UNI_COL  = '#4C9BE8'

SECTORS = {
    'AAPL':'Tech','MSFT':'Tech','NVDA':'Tech','AVGO':'Tech','TXN':'Tech',
    'INTC':'Tech','QCOM':'Tech','IBM':'Tech','ADBE':'Tech','CRM':'Tech',
    'AMAT':'Tech','AMD':'Tech','ORCL':'Tech','CSCO':'Tech',
    'AMZN':'Consumer Disc','HD':'Consumer Disc','NKE':'Consumer Disc','TSLA':'Consumer Disc',
    'LOW':'Consumer Disc','TGT':'Consumer Disc',
    'DIS':'Comm','NFLX':'Comm','CMCSA':'Comm','T':'Comm','GOOGL':'Comm',
    'META':'Comm','VZ':'Comm',
    'JPM':'Financials','GS':'Financials','MS':'Financials','BAC':'Financials',
    'WFC':'Financials','C':'Financials','SCHW':'Financials','AXP':'Financials',
    'BLK':'Financials','USB':'Financials',
    'XOM':'Energy','CVX':'Energy','COP':'Energy','EOG':'Energy','SLB':'Energy',
    'OXY':'Energy',
    'JNJ':'Health Care','UNH':'Health Care','LLY':'Health Care','MRK':'Health Care',
    'ABT':'Health Care','GILD':'Health Care','BMY':'Health Care','PFE':'Health Care',
    'ABBV':'Health Care','TMO':'Health Care','AMGN':'Health Care','CVS':'Health Care',
    'PG':'Staples','KO':'Staples','PEP':'Staples','WMT':'Staples','COST':'Staples',
    'PM':'Staples','MCD':'Staples','SBUX':'Staples','MO':'Staples','CL':'Staples',
    'NEE':'Utilities','DUK':'Utilities','D':'Utilities','SO':'Utilities','AEP':'Utilities',
    'CAT':'Industrials','HON':'Industrials','GE':'Industrials','LMT':'Industrials',
    'DE':'Industrials','MMM':'Industrials','FDX':'Industrials','BA':'Industrials',
    'NOC':'Industrials','UPS':'Industrials','RTX':'Industrials',
    'NEM':'Materials','FCX':'Materials','APD':'Materials','LIN':'Materials','DOW':'Materials',
    'AMT':'REIT','EQIX':'REIT','CCI':'REIT','SPG':'REIT','PLD':'REIT',
    'F':'Auto/Other','GM':'Auto/Other','MU':'Semicon',
}

SECTOR_COLORS = {
    'Tech':'#4C72B0','Financials':'#55A868','Energy':'#C44E52','Industrials':'#8172B2',
    'Health Care':'#CCB974','Staples':'#64B5CD','Comm':'#FF8C00','Consumer Disc':'#E377C2',
    'Materials':'#7F7F7F','Utilities':'#BCBD22','REIT':'#17BECF',
    'Auto/Other':'#D62728','Semicon':'#9467BD','Other':'#999999',
}

# ── Load all per-ticker files ─────────────────────────────────────────────────
print('Loading prediction files...')
records = []
for f in sorted(RESULTS_DIR.iterdir()):
    m = re.match(r'predictions_([A-Z]+)_H(\d+)\.csv', f.name)
    if m:
        ticker, h = m.group(1), int(m.group(2))
        df = pd.read_csv(f).dropna(subset=['y_true', 'y_pred'])
        df['ticker']  = ticker
        df['horizon'] = h
        df['sector']  = SECTORS.get(ticker, 'Other')
        records.append(df)

all_df = pd.concat(records, ignore_index=True)
all_df['date'] = pd.to_datetime(all_df['date'])
print(f'  {len(all_df):,} rows | {all_df["ticker"].nunique()} tickers | horizons {sorted(all_df["horizon"].unique())}')


def compute_pit(group_df):
    """
    For each observation, compute what percentile its realized value (y_true)
    falls in within the empirical distribution of y_pred for that ticker/horizon.

    The idea: the model's full prediction history defines an implicit forecast
    distribution. We ask: where does today's realized vol sit in that distribution?
    If well-calibrated, these ranks should be uniform on [0,1].
    """
    pit_vals = []
    for _, grp in group_df.groupby(['ticker', 'horizon']):
        pred_sorted = np.sort(grp['y_pred'].values)
        for rv in grp['y_true'].values:
            pct = np.searchsorted(pred_sorted, rv, side='right') / len(pred_sorted)
            pit_vals.append(pct)
    return np.array(pit_vals)


def ks_label(pit_vals):
    """KS test against uniform. Returns (stat, p, verdict_str, color)."""
    stat, p = stats.kstest(pit_vals, 'uniform')
    if p > 0.05:
        verdict, col = f'KS p={p:.3f}  UNIFORM (well-calibrated)', GOOD_COL
    elif p > 0.01:
        verdict, col = f'KS p={p:.3f}  MARGINAL', WARN_COL
    else:
        verdict, col = f'KS p={p:.4f}  NON-UNIFORM (miscalibrated)', BAD_COL
    return stat, p, verdict, col


def pit_panel(ax, pit_vals, title='', color=UNI_COL, n_bins=20):
    ax.set_facecolor(PANEL_BG)
    if len(pit_vals) < 10:
        ax.text(0.5, 0.5, 'insufficient data', color=DIM,
                ha='center', va='center', transform=ax.transAxes)
        ax.set_title(title, color=WHITE, fontsize=8, pad=3)
        return

    ax.hist(pit_vals, bins=n_bins, range=(0, 1), density=True,
            color=color, alpha=0.75, edgecolor='#333', linewidth=0.4)
    ax.axhline(1.0, color='white', lw=1.4, linestyle='--', alpha=0.7, label='Uniform (ideal)')

    # Shade deviation from uniform
    counts, edges = np.histogram(pit_vals, bins=n_bins, range=(0, 1), density=True)
    for i, (c, e) in enumerate(zip(counts, edges[:-1])):
        if c > 1.0:
            ax.fill_between([e, edges[i+1]], [1.0, 1.0], [c, c],
                             color=BAD_COL, alpha=0.25)
        else:
            ax.fill_between([e, edges[i+1]], [c, c], [1.0, 1.0],
                             color=GOOD_COL, alpha=0.15)

    stat, p, verdict, vcol = ks_label(pit_vals)
    ax.text(0.5, 0.96, verdict, transform=ax.transAxes,
            ha='center', va='top', color=vcol, fontsize=6.5,
            bbox=dict(fc='#111', ec='#333', alpha=0.8, pad=2))

    ax.set_xlim(0, 1)
    ax.set_ylim(0, max(counts.max() * 1.3, 2.0))
    ax.set_title(title, color=WHITE, fontsize=8, pad=3)
    ax.tick_params(colors=DIM, labelsize=6.5)
    for sp in ax.spines.values(): sp.set_color('#444')
    ax.set_xlabel('PIT quantile', color=DIM, fontsize=7)
    ax.set_ylabel('Density', color=DIM, fontsize=7)
    ax.grid(axis='y', color=GRID, lw=0.5)


# ═══════════════════════════════════════════════════════════════════════════════
# CHART 1 — Market-wide PIT
# ═══════════════════════════════════════════════════════════════════════════════
print('\n[1/4] Market-wide PIT...')

pit_market = compute_pit(all_df)

fig, axes = plt.subplots(1, 3, figsize=(18, 5))
fig.patch.set_facecolor(BG)

# All horizons combined
pit_panel(axes[0], pit_market,
          title=f'All Horizons Combined  (n={len(pit_market):,})', n_bins=25)

# Breakdown by horizon
for ax, h, col in zip(axes[1:], [21, 63], ['#4C9BE8', '#E87C4C']):
    sub = all_df[all_df['horizon'] == h]
    pit_h = compute_pit(sub)
    pit_panel(ax, pit_h,
              title=f'H={h}d  (n={len(pit_h):,})', color=col, n_bins=20)

fig.suptitle(
    'Tarasque v4  —  PIT Calibration Test  |  Market-Wide\n'
    'Flat histogram = uniform = well-calibrated  |  Red bars = excess mass (fat tail / bias)',
    color=WHITE, fontsize=13, fontweight='bold',
)
plt.tight_layout()
plt.savefig(RESULTS_DIR / 'pit_test_market.png', dpi=140, bbox_inches='tight', facecolor=BG)
plt.close()
print('  Saved: pit_test_market.png')


# ═══════════════════════════════════════════════════════════════════════════════
# CHART 2 — PIT by horizon (H21 / H63 / H126 side by side)
# ═══════════════════════════════════════════════════════════════════════════════
print('[2/4] PIT by horizon...')

fig, axes = plt.subplots(1, 3, figsize=(18, 5))
fig.patch.set_facecolor(BG)
colors_h = {21: '#4C9BE8', 63: '#E87C4C', 126: '#22c55e'}

for ax, h in zip(axes, [21, 63, 126]):
    sub = all_df[all_df['horizon'] == h]
    pit_h = compute_pit(sub)
    pit_panel(ax, pit_h,
              title=f'H={h}d  ({sub["ticker"].nunique()} tickers, n={len(pit_h):,})',
              color=colors_h[h], n_bins=20)

fig.suptitle(
    'Tarasque v4  —  PIT Calibration by Forecast Horizon\n'
    'H=21 is the primary reliability horizon — H=63/126 expected to show more deviation',
    color=WHITE, fontsize=13, fontweight='bold',
)
plt.tight_layout()
plt.savefig(RESULTS_DIR / 'pit_test_by_horizon.png', dpi=140, bbox_inches='tight', facecolor=BG)
plt.close()
print('  Saved: pit_test_by_horizon.png')


# ═══════════════════════════════════════════════════════════════════════════════
# CHART 3 — PIT by sector (H=21 only)
# ═══════════════════════════════════════════════════════════════════════════════
print('[3/4] PIT by sector...')

h21 = all_df[all_df['horizon'] == 21]
sector_list = sorted(h21['sector'].unique())
ncols = 3
nrows = (len(sector_list) + ncols - 1) // ncols

fig = plt.figure(figsize=(20, nrows * 4))
fig.patch.set_facecolor(BG)
gs  = gridspec.GridSpec(nrows, ncols, figure=fig, hspace=0.55, wspace=0.3)

for idx, sector in enumerate(sector_list):
    row, col = divmod(idx, ncols)
    ax = fig.add_subplot(gs[row, col])
    sub = h21[h21['sector'] == sector]
    pit_s = compute_pit(sub)
    scol  = SECTOR_COLORS.get(sector, '#999')
    n_t   = sub['ticker'].nunique()
    pit_panel(ax, pit_s,
              title=f'{sector}  ({n_t} tickers, n={len(pit_s):,})',
              color=scol, n_bins=15)

fig.suptitle(
    'Tarasque v4  —  PIT Calibration by Sector  (H=21d)\n'
    'Sectors with fat-tail excess (red right bars) = model underestimates spike risk',
    color=WHITE, fontsize=14, fontweight='bold', y=1.01,
)
plt.savefig(RESULTS_DIR / 'pit_test_by_sector.png', dpi=140, bbox_inches='tight', facecolor=BG)
plt.close()
print('  Saved: pit_test_by_sector.png')


# ═══════════════════════════════════════════════════════════════════════════════
# CHART 4 — Per-ticker PIT grid (H=21, all 93 tickers)
# ═══════════════════════════════════════════════════════════════════════════════
print('[4/4] Per-ticker PIT grid...')

tickers = sorted(h21['ticker'].unique())
ncols_t = 10
nrows_t = (len(tickers) + ncols_t - 1) // ncols_t

fig = plt.figure(figsize=(30, nrows_t * 3.2))
fig.patch.set_facecolor(BG)
gs  = gridspec.GridSpec(nrows_t, ncols_t, figure=fig, hspace=0.65, wspace=0.3)

# Compute all KS stats for summary
ks_results = []
for idx, ticker in enumerate(tickers):
    row, col = divmod(idx, ncols_t)
    ax = fig.add_subplot(gs[row, col])
    sub = h21[h21['ticker'] == ticker]
    pit_t = compute_pit(sub)
    scol  = SECTOR_COLORS.get(SECTORS.get(ticker, 'Other'), '#999')
    pit_panel(ax, pit_t, title=ticker, color=scol, n_bins=10)
    ax.set_xlabel('')
    ax.set_ylabel('')

    if len(pit_t) >= 10:
        stat, p, _, _ = ks_label(pit_t)
        ks_results.append({'ticker': ticker, 'sector': SECTORS.get(ticker,'Other'),
                           'ks_stat': stat, 'ks_p': p,
                           'calibrated': p > 0.05})

fig.suptitle(
    f'Tarasque v4  —  Per-Ticker PIT Test  (H=21d, {len(tickers)} tickers)\n'
    'Green KS = uniform (calibrated)  |  Red KS = non-uniform (miscalibrated)',
    color=WHITE, fontsize=15, fontweight='bold', y=1.005,
)
plt.savefig(RESULTS_DIR / 'pit_test_by_ticker_full.png', dpi=110, bbox_inches='tight', facecolor=BG)
plt.close()
print('  Saved: pit_test_by_ticker_full.png')

# ── Summary table ─────────────────────────────────────────────────────────────
ks_df = pd.DataFrame(ks_results).sort_values('ks_stat', ascending=False)
n_cal = ks_df['calibrated'].sum()
print(f'\nCalibration summary (H=21):')
print(f'  Calibrated (KS p>0.05): {n_cal}/{len(ks_df)} ({n_cal/len(ks_df)*100:.0f}%)')
print(f'  Worst-calibrated tickers:')
print(ks_df.head(10)[['ticker','sector','ks_stat','ks_p','calibrated']].to_string(index=False))
ks_df.to_csv(RESULTS_DIR / 'pit_ks_results.csv', index=False)
print(f'  Saved: pit_ks_results.csv')

print('\n=== PIT tests complete ===')
