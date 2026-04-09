"""
plot_coverage_test.py  —  Prediction Interval Coverage Test

What this tells you:
  The model's historical forecast distribution implies prediction bands.
  We ask: does the P90 band actually contain 90% of realized values?

  Coverage < nominal → fat tails, model underestimates extremes (UNDERCOVERS)
                       → risk limits built on model output are too tight
  Coverage > nominal → model is too conservative, bands too wide (OVERCOVERS)
                       → opportunity cost, excess margin

Bands tested: P50, P70, P80, P90, P95

Outputs:
  coverage_test_market.png     — market-wide coverage curve vs ideal diagonal
  coverage_test_by_sector.png  — sector coverage curves
  coverage_test_summary.csv    — per-ticker coverage at each quantile
  coverage_test_by_ticker.png  — 94-ticker heatmap of coverage deficit

Run from repo root:
  python model/pipeline/results/plot_coverage_test.py
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import os, re
import numpy as np
import pandas as pd
from pathlib import Path
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
IDEAL_COL = '#ffffff'

NOMINAL_BANDS = [0.50, 0.70, 0.80, 0.90, 0.95]  # symmetric around median

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

# ── Load all per-ticker H=21 files ────────────────────────────────────────────
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
h21 = all_df[all_df['horizon'] == 21].copy()
print(f'  {len(h21):,} rows | {h21["ticker"].nunique()} tickers')


def compute_coverage(df, nominal_bands=NOMINAL_BANDS):
    """
    For each nominal coverage level (e.g. 0.90), compute the empirical coverage:
    what fraction of y_true fell within the band implied by the central
    [lo_pct, hi_pct] quantiles of y_pred?

    We use the TICKER-LEVEL prediction distribution as the band source,
    then measure coverage across all observations.
    """
    results = []
    for band in nominal_bands:
        lo_q = (1 - band) / 2
        hi_q = 1 - lo_q
        in_band = 0
        total   = 0
        for _, grp in df.groupby(['ticker', 'horizon']):
            lo = grp['y_pred'].quantile(lo_q)
            hi = grp['y_pred'].quantile(hi_q)
            hits = ((grp['y_true'] >= lo) & (grp['y_true'] <= hi)).sum()
            in_band += hits
            total   += len(grp)
        results.append({'nominal': band, 'empirical': in_band / total if total else np.nan})
    return pd.DataFrame(results)


def compute_coverage_per_ticker(ticker_df, nominal_bands=NOMINAL_BANDS):
    """Per-ticker coverage at each nominal band."""
    rows = []
    for ticker, grp in ticker_df.groupby('ticker'):
        row = {'ticker': ticker, 'sector': SECTORS.get(ticker, 'Other'), 'n': len(grp)}
        for band in nominal_bands:
            lo_q = (1 - band) / 2
            hi_q = 1 - lo_q
            lo = grp['y_pred'].quantile(lo_q)
            hi = grp['y_pred'].quantile(hi_q)
            emp = ((grp['y_true'] >= lo) & (grp['y_true'] <= hi)).mean()
            row[f'cov_{int(band*100)}'] = emp
            row[f'def_{int(band*100)}'] = band - emp  # positive = undercoverage
        rows.append(row)
    return pd.DataFrame(rows)


def coverage_ax_style(ax, title=''):
    ax.set_facecolor(PANEL_BG)
    ax.set_xlim(0.45, 1.0)
    ax.set_ylim(0.30, 1.05)
    # Ideal diagonal
    ax.plot([0, 1], [0, 1], color=IDEAL_COL, lw=1.5, linestyle='--', alpha=0.6, label='Ideal (perfect calibration)')
    # Undercoverage / overcoverage shading
    ax.fill_between([0.45, 1.0], [0.45, 1.0], [0.30, 0.85],
                    color=BAD_COL, alpha=0.06, label='Undercoverage zone')
    ax.fill_between([0.45, 1.0], [0.45, 1.0], [0.55, 1.05],
                    color=GOOD_COL, alpha=0.04, label='Overcoverage zone')
    ax.set_xlabel('Nominal Coverage', color=DIM, fontsize=9)
    ax.set_ylabel('Empirical Coverage', color=DIM, fontsize=9)
    ax.set_title(title, color=WHITE, fontsize=10, pad=6)
    ax.tick_params(colors=DIM, labelsize=8)
    for sp in ax.spines.values(): sp.set_color('#444')
    ax.grid(color=GRID, lw=0.5, alpha=0.6)
    # Mark 90% line
    ax.axvline(0.90, color='#666', lw=0.8, linestyle=':', alpha=0.5)
    ax.axhline(0.90, color='#666', lw=0.8, linestyle=':', alpha=0.5)


# ═══════════════════════════════════════════════════════════════════════════════
# CHART 1 — Market-wide coverage curve
# ═══════════════════════════════════════════════════════════════════════════════
print('\n[1/4] Market-wide coverage...')

cov_market = compute_coverage(h21)

fig, axes = plt.subplots(1, 3, figsize=(20, 6))
fig.patch.set_facecolor(BG)

# Panel 1: market-wide curve
ax = axes[0]
coverage_ax_style(ax, title=f'Market-Wide (H=21, n={len(h21):,})')
ax.plot(cov_market['nominal'], cov_market['empirical'],
        color='#4C9BE8', lw=2.5, marker='o', markersize=7, label='Tarasque v4')
# Annotate each point with deficit
for _, row in cov_market.iterrows():
    deficit = row['nominal'] - row['empirical']
    col = BAD_COL if deficit > 0.03 else WARN_COL if deficit > 0.01 else GOOD_COL
    ax.annotate(
        f"−{deficit*100:.1f}%",
        (row['nominal'], row['empirical']),
        textcoords='offset points', xytext=(6, -10),
        color=col, fontsize=7.5,
    )
ax.legend(fontsize=8, facecolor='#2a2a2a', edgecolor='#555', labelcolor='white')

# Panel 2: H=21 vs H=63 comparison
ax = axes[1]
coverage_ax_style(ax, title='Coverage by Horizon')
colors_h = {21: '#4C9BE8', 63: '#E87C4C', 126: '#22c55e'}
for h, col in colors_h.items():
    sub = all_df[all_df['horizon'] == h]
    if len(sub) == 0:
        continue
    cov_h = compute_coverage(sub)
    ax.plot(cov_h['nominal'], cov_h['empirical'],
            color=col, lw=2.2, marker='o', markersize=6, label=f'H={h}d')
ax.legend(fontsize=9, facecolor='#2a2a2a', edgecolor='#555', labelcolor='white')

# Panel 3: Market-wide coverage deficit bar
ax = axes[2]
ax.set_facecolor(PANEL_BG)
bands_pct = [int(b*100) for b in NOMINAL_BANDS]
deficits   = [(row['nominal'] - row['empirical']) * 100
              for _, row in cov_market.iterrows()]
bar_colors = [BAD_COL if d > 3 else WARN_COL if d > 1 else GOOD_COL for d in deficits]
bars = ax.bar([f'P{b}' for b in bands_pct], deficits, color=bar_colors, alpha=0.85, width=0.5)
ax.axhline(0, color='white', lw=1.2, linestyle='--', alpha=0.6)
ax.axhline(3, color=BAD_COL, lw=0.8, linestyle=':', alpha=0.5, label='3% threshold')
for bar, d in zip(bars, deficits):
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.1,
            f'{d:+.1f}%', ha='center', va='bottom', color=WHITE, fontsize=8.5)
ax.set_title('Coverage Deficit by Band (nominal − empirical)', color=WHITE, fontsize=10, pad=6)
ax.set_ylabel('Deficit (pp)', color=DIM, fontsize=9)
ax.tick_params(colors=DIM, labelsize=8.5)
for sp in ax.spines.values(): sp.set_color('#444')
ax.grid(axis='y', color=GRID, lw=0.5)
ax.legend(fontsize=8, facecolor='#2a2a2a', edgecolor='#555', labelcolor='white')

fig.suptitle(
    'Tarasque v4  —  Prediction Interval Coverage Test  |  Market-Wide\n'
    'Curve below diagonal = undercoverage (fat tails, underestimates extremes)  |  Deficit = nominal − empirical',
    color=WHITE, fontsize=13, fontweight='bold',
)
plt.tight_layout()
plt.savefig(RESULTS_DIR / 'coverage_test_market.png', dpi=140, bbox_inches='tight', facecolor=BG)
plt.close()
print('  Saved: coverage_test_market.png')
print('  Market coverage:')
for _, row in cov_market.iterrows():
    deficit = row['nominal'] - row['empirical']
    flag = ' *** UNDERCOVERAGE' if deficit > 0.05 else ' ** moderate' if deficit > 0.03 else ''
    print(f"    P{int(row['nominal']*100):3d}: nominal={row['nominal']:.0%}  empirical={row['empirical']:.1%}  deficit={deficit:+.1%}{flag}")


# ═══════════════════════════════════════════════════════════════════════════════
# CHART 2 — Coverage by sector
# ═══════════════════════════════════════════════════════════════════════════════
print('\n[2/4] Coverage by sector...')

sector_list = sorted(h21['sector'].unique())
ncols = 3
nrows = (len(sector_list) + ncols - 1) // ncols

fig = plt.figure(figsize=(21, nrows * 5.5))
fig.patch.set_facecolor(BG)
gs = gridspec.GridSpec(nrows, ncols, figure=fig, hspace=0.55, wspace=0.3)

for idx, sector in enumerate(sector_list):
    row, col = divmod(idx, ncols)
    ax = fig.add_subplot(gs[row, col])
    sub = h21[h21['sector'] == sector]
    cov_s = compute_coverage(sub)
    coverage_ax_style(ax, title=f'{sector}  ({sub["ticker"].nunique()} tickers, n={len(sub):,})')
    scol = SECTOR_COLORS.get(sector, '#999')
    ax.plot(cov_s['nominal'], cov_s['empirical'],
            color=scol, lw=2.2, marker='o', markersize=6)
    # Annotate worst deficit
    worst = cov_s.loc[(cov_s['nominal'] - cov_s['empirical']).idxmax()]
    ax.annotate(
        f"P{int(worst['nominal']*100)} deficit: {(worst['nominal']-worst['empirical'])*100:.1f}pp",
        (0.5, 0.08), xycoords='axes fraction',
        ha='center', color=WARN_COL, fontsize=7.5,
    )

fig.suptitle(
    'Tarasque v4  —  Coverage Test by Sector  (H=21d)\n'
    'Curves below diagonal indicate fat-tail undercoverage in that sector',
    color=WHITE, fontsize=14, fontweight='bold', y=1.01,
)
plt.savefig(RESULTS_DIR / 'coverage_test_by_sector.png', dpi=140, bbox_inches='tight', facecolor=BG)
plt.close()
print('  Saved: coverage_test_by_sector.png')


# ═══════════════════════════════════════════════════════════════════════════════
# CHART 3 — Per-ticker heatmap of coverage deficit
# ═══════════════════════════════════════════════════════════════════════════════
print('\n[3/4] Per-ticker coverage heatmap...')

ticker_cov = compute_coverage_per_ticker(h21)
ticker_cov = ticker_cov.sort_values(['sector', 'ticker'])

# Build heatmap matrix: rows=tickers, cols=bands
band_cols = [f'def_{int(b*100)}' for b in NOMINAL_BANDS]
heat_data  = ticker_cov[band_cols].values * 100  # in percentage points
row_labels = ticker_cov['ticker'].values
col_labels  = [f'P{int(b*100)}' for b in NOMINAL_BANDS]

fig, ax = plt.subplots(figsize=(12, max(10, len(row_labels) * 0.28)))
fig.patch.set_facecolor(BG)
ax.set_facecolor(PANEL_BG)

import matplotlib.colors as mcolors
# Diverging: green=overcoverage, red=undercoverage, white=perfect
cmap = mcolors.LinearSegmentedColormap.from_list(
    'cov', [GOOD_COL, '#2a2a2a', BAD_COL], N=256
)
# Center at 0, range [-10, +15]
vmin, vmax = -8, 15
im = ax.imshow(heat_data, aspect='auto', cmap=cmap, vmin=vmin, vmax=vmax,
               interpolation='nearest')

# Annotate cells
for i in range(len(row_labels)):
    for j in range(len(col_labels)):
        val = heat_data[i, j]
        txt_col = WHITE if abs(val) > 4 else DIM
        ax.text(j, i, f'{val:+.1f}', ha='center', va='center',
                color=txt_col, fontsize=6.0)

# Sector dividers
sector_order = ticker_cov['sector'].values
prev_sector = sector_order[0]
for i, s in enumerate(sector_order):
    if s != prev_sector:
        ax.axhline(i - 0.5, color='#555', lw=0.8)
        prev_sector = s

ax.set_xticks(range(len(col_labels)))
ax.set_xticklabels(col_labels, color=WHITE, fontsize=9)
ax.set_yticks(range(len(row_labels)))
ax.set_yticklabels(row_labels, color=WHITE, fontsize=6.5)
ax.tick_params(colors=DIM)
for sp in ax.spines.values(): sp.set_color('#444')

cbar = plt.colorbar(im, ax=ax, fraction=0.02, pad=0.01)
cbar.set_label('Coverage Deficit (pp)\n+ = undercoverage, − = overcoverage',
               color=WHITE, fontsize=8)
cbar.ax.yaxis.set_tick_params(color=DIM, labelsize=7)
plt.setp(cbar.ax.yaxis.get_ticklabels(), color=WHITE)

ax.set_title(
    f'Tarasque v4  —  Per-Ticker Coverage Deficit Heatmap  (H=21, {len(row_labels)} tickers)\n'
    'Red = undercoverage (fat tails)  |  Green = overcoverage (conservative)  |  Values in percentage points',
    color=WHITE, fontsize=11, pad=8,
)
plt.tight_layout()
plt.savefig(RESULTS_DIR / 'coverage_test_by_ticker.png', dpi=130, bbox_inches='tight', facecolor=BG)
plt.close()
print('  Saved: coverage_test_by_ticker.png')


# ═══════════════════════════════════════════════════════════════════════════════
# CHART 4 — P90 deficit ranking (most under-covered tickers)
# ═══════════════════════════════════════════════════════════════════════════════
print('\n[4/4] P90 deficit ranking...')

ticker_cov_sorted = ticker_cov.sort_values('def_90', ascending=False).reset_index(drop=True)

fig, ax = plt.subplots(figsize=(20, 7))
fig.patch.set_facecolor(BG)
ax.set_facecolor(PANEL_BG)

x = np.arange(len(ticker_cov_sorted))
bar_cols = [
    BAD_COL if d > 0.08 else WARN_COL if d > 0.04 else GOOD_COL
    for d in ticker_cov_sorted['def_90']
]
bars = ax.bar(x, ticker_cov_sorted['def_90'] * 100,
              color=bar_cols, alpha=0.85, width=0.7)

ax.axhline(0, color='white', lw=1.2, linestyle='--', alpha=0.7)
ax.axhline(5, color=BAD_COL, lw=0.8, linestyle=':', alpha=0.5, label='5pp threshold (actionable)')
ax.axhline(3, color=WARN_COL, lw=0.8, linestyle=':', alpha=0.5, label='3pp threshold (watch)')

ax.set_xticks(x)
ax.set_xticklabels(ticker_cov_sorted['ticker'], rotation=55, ha='right', fontsize=7, color=WHITE)
ax.set_ylabel('P90 Coverage Deficit (pp)', color=DIM, fontsize=10)
ax.set_title(
    f'Tarasque v4  —  P90 Coverage Deficit by Ticker  (H=21)\n'
    'Red > 8pp = significant undercoverage | tail risk underestimated | candidates for macro-context augmentation',
    color=WHITE, fontsize=12, pad=8,
)
ax.tick_params(colors=DIM, labelsize=8)
for sp in ax.spines.values(): sp.set_color('#444')
ax.grid(axis='y', color=GRID, lw=0.5)
ax.legend(fontsize=8.5, facecolor='#2a2a2a', edgecolor='#555', labelcolor='white')

# Sector color dots on x-axis
for i, (_, trow) in enumerate(ticker_cov_sorted.iterrows()):
    scol = SECTOR_COLORS.get(trow['sector'], '#999')
    ax.plot(i, -1.5, 's', color=scol, markersize=5, clip_on=False)

plt.tight_layout()
plt.savefig(RESULTS_DIR / 'coverage_test_p90_ranking.png', dpi=140, bbox_inches='tight', facecolor=BG)
plt.close()
print('  Saved: coverage_test_p90_ranking.png')


# ── Summary CSV ───────────────────────────────────────────────────────────────
ticker_cov.to_csv(RESULTS_DIR / 'coverage_test_summary.csv', index=False)
print('\nCoverage summary saved: coverage_test_summary.csv')

# Print worst offenders
print('\nWorst P90 undercoverage (deficit > 5pp):')
bad = ticker_cov_sorted[ticker_cov_sorted['def_90'] > 0.05][['ticker','sector','n','def_90','def_95']]
bad = bad.copy()
bad['def_90'] = (bad['def_90'] * 100).round(1)
bad['def_95'] = (bad['def_95'] * 100).round(1)
bad.columns = ['ticker','sector','n','P90_deficit_pp','P95_deficit_pp']
print(bad.to_string(index=False))

# Print well-covered tickers
print('\nBest covered (P90 deficit < 2pp):')
good = ticker_cov_sorted[ticker_cov_sorted['def_90'] < 0.02][['ticker','sector','def_90']].tail(15)
good['def_90'] = (good['def_90'] * 100).round(1)
print(good.to_string(index=False))

print('\n=== Coverage test complete ===')
