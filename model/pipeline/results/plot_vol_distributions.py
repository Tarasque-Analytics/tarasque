"""
plot_vol_distributions.py

Four chart outputs:
  1. vol_dist_individual/  — one PNG per ticker (H=21 shown):
       KDE of y_true (RV) + KDE of y_pred (forecast IV proxy)
       Vertical dotted line = most-recent y_true and y_pred values

  2. vol_dist_sector_full.png  — one panel per sector:
       KDE of all member RV observations pooled
       Vertical dotted line per ticker = that firm's most-recent RV

  3. vol_dist_market.png  — single KDE of all 94 tickers' RV observations
       (each firm treated as equal draw from the population)

  4. vol_dist_sector_grid.png  — compact grid version of (2) for quick review

Run from repo root:
    python model/pipeline/results/plot_vol_distributions.py
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
from scipy.stats import gaussian_kde
import warnings
warnings.filterwarnings('ignore')

# ── Config ────────────────────────────────────────────────────────────────────

RESULTS_DIR = Path('model/pipeline/results')
OUT_INDIV   = RESULTS_DIR / 'vol_dist_individual'
HORIZON     = 21          # H=21 is the reliable horizon; used for all charts

BG        = '#0f0f0f'
PANEL_BG  = '#1a1a1a'
GRID_COL  = '#2e2e2e'
WHITE     = '#f0f0f0'
DIM       = '#888888'
RV_COL    = '#4C9BE8'    # blue  — realized vol (y_true)
PRED_COL  = '#E87C4C'    # orange — model forecast (y_pred)
VLINE_RV   = '#7DD3FC'   # lighter blue dotted line
VLINE_PRED = '#FCA97D'   # lighter orange dotted line

# Sectors pulled directly from plot_beta_full.py to stay consistent
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

# ── Load all data ─────────────────────────────────────────────────────────────

print(f'Loading H={HORIZON} prediction files...')
ticker_data = {}
for f in sorted(RESULTS_DIR.iterdir()):
    m = re.match(rf'predictions_([A-Z]+)_H{HORIZON}\.csv', f.name)
    if m:
        ticker = m.group(1)
        df = pd.read_csv(f).dropna(subset=['y_true', 'y_pred'])
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date')
        if len(df) >= 50:
            ticker_data[ticker] = df

print(f'  Loaded {len(ticker_data)} tickers')

# Current (most recent) value per ticker
current = {t: df.iloc[-1] for t, df in ticker_data.items()}

# ── Helper: draw a single KDE panel ──────────────────────────────────────────

def kde_panel(ax, rv_vals, pred_vals, vline_rv=None, vline_pred=None,
              title='', show_pred=True, sector_color=None):
    """
    rv_vals   : array of realized vol observations
    pred_vals : array of model forecast observations (optional)
    vline_rv  : current RV value — draws dotted vertical line
    vline_pred: current pred value — draws dotted vertical line
    sector_color: if set, use for the RV KDE instead of default blue
    """
    ax.set_facecolor(PANEL_BG)

    rv_col   = sector_color if sector_color else RV_COL
    xlim_max = min(np.percentile(rv_vals, 99) * 1.3, 1.8)
    x_grid   = np.linspace(0, xlim_max, 500)

    # RV KDE
    if len(rv_vals) > 5:
        kde_rv = gaussian_kde(rv_vals, bw_method='scott')
        ax.fill_between(x_grid, kde_rv(x_grid), alpha=0.25, color=rv_col)
        ax.plot(x_grid, kde_rv(x_grid), color=rv_col, lw=1.8, label='Realized Vol')

    # Forecast KDE
    if show_pred and pred_vals is not None and len(pred_vals) > 5:
        kde_pred = gaussian_kde(pred_vals, bw_method='scott')
        ax.fill_between(x_grid, kde_pred(x_grid), alpha=0.18, color=PRED_COL)
        ax.plot(x_grid, kde_pred(x_grid), color=PRED_COL, lw=1.5,
                linestyle='--', label='Model Forecast')

    # Current-value vertical lines
    if vline_rv is not None and 0 < vline_rv < xlim_max:
        ax.axvline(vline_rv, color=VLINE_RV, lw=1.4, linestyle=':', alpha=0.9)
        ax.text(vline_rv, ax.get_ylim()[1] * 0.92, f' {vline_rv:.2f}',
                color=VLINE_RV, fontsize=6.5, va='top')

    if show_pred and vline_pred is not None and 0 < vline_pred < xlim_max:
        ax.axvline(vline_pred, color=VLINE_PRED, lw=1.4, linestyle=':', alpha=0.9)
        ax.text(vline_pred, ax.get_ylim()[1] * 0.75, f' {vline_pred:.2f}',
                color=VLINE_PRED, fontsize=6.5, va='top')

    ax.set_xlim(0, xlim_max)
    ax.set_title(title, color=WHITE, fontsize=8.5, pad=4)
    ax.tick_params(colors=DIM, labelsize=6.5)
    for sp in ax.spines.values():
        sp.set_color('#444')
    ax.grid(axis='x', color=GRID_COL, lw=0.5)
    ax.set_yticks([])


# ═══════════════════════════════════════════════════════════════════════════════
# CHART 1 — Individual ticker distributions
# ═══════════════════════════════════════════════════════════════════════════════

OUT_INDIV.mkdir(parents=True, exist_ok=True)
print('\n[1/4] Individual ticker charts...')

for ticker, df in ticker_data.items():
    fig, ax = plt.subplots(figsize=(7, 3.5))
    fig.patch.set_facecolor(BG)

    cur = current[ticker]
    sector = SECTORS.get(ticker, 'Other')
    scol = SECTOR_COLORS.get(sector, '#999999')

    kde_panel(
        ax,
        rv_vals    = df['y_true'].values,
        pred_vals  = df['y_pred'].values,
        vline_rv   = float(cur['y_true']),
        vline_pred = float(cur['y_pred']),
        show_pred  = True,
        sector_color = scol,
    )

    # Percentile annotation
    pct_rv = (df['y_true'] <= cur['y_true']).mean() * 100
    ax.text(0.97, 0.95,
            f'Current RV: {cur["y_true"]:.3f}  ({pct_rv:.0f}th pct)\n'
            f'Model forecast: {cur["y_pred"]:.3f}\n'
            f'Sector: {sector}\n'
            f'n={len(df)} obs  |  H={HORIZON}d',
            transform=ax.transAxes, ha='right', va='top', color=WHITE,
            fontsize=7.5, bbox=dict(fc='#111', ec='#444', alpha=0.85, pad=4))

    ax.legend(fontsize=7.5, facecolor='#222', edgecolor='#555',
              labelcolor=WHITE, loc='upper left')
    ax.set_xlabel('Annualized Realized Vol', color=DIM, fontsize=8)

    fig.suptitle(f'{ticker}  —  Vol Distribution  (H={HORIZON}d, 2013–2025)',
                 color=WHITE, fontsize=11, fontweight='bold')
    plt.tight_layout()
    outpath = OUT_INDIV / f'{ticker}_vol_dist.png'
    plt.savefig(outpath, dpi=130, bbox_inches='tight', facecolor=BG)
    plt.close()
    print(f'  {ticker}', end='  ', flush=True)

print(f'\n  Saved {len(ticker_data)} charts -> {OUT_INDIV}')


# ═══════════════════════════════════════════════════════════════════════════════
# CHART 2 — Sector distributions (full — one panel per sector)
# ═══════════════════════════════════════════════════════════════════════════════

print('\n[2/4] Sector distribution chart...')

# Group tickers by sector, keep only those with data
sector_groups = {}
for t, df in ticker_data.items():
    s = SECTORS.get(t, 'Other')
    sector_groups.setdefault(s, []).append(t)

sector_list = sorted(sector_groups.keys())
n_sectors   = len(sector_list)
ncols = 3
nrows = (n_sectors + ncols - 1) // ncols

fig = plt.figure(figsize=(22, nrows * 4.5))
fig.patch.set_facecolor(BG)
gs  = gridspec.GridSpec(nrows, ncols, figure=fig, hspace=0.55, wspace=0.25)

for idx, sector in enumerate(sector_list):
    row, col = divmod(idx, ncols)
    ax = fig.add_subplot(gs[row, col])

    tickers_in_sector = [t for t in sector_groups[sector] if t in ticker_data]
    if not tickers_in_sector:
        ax.set_visible(False)
        continue

    scol = SECTOR_COLORS.get(sector, '#999999')

    # Pool all RV observations for this sector
    all_rv = np.concatenate([ticker_data[t]['y_true'].values for t in tickers_in_sector])

    kde_panel(
        ax,
        rv_vals   = all_rv,
        pred_vals = None,
        show_pred = False,
        sector_color = scol,
        title     = f'{sector}  ({len(tickers_in_sector)} tickers)',
    )

    # Per-ticker current RV dotted lines
    ymax = ax.get_ylim()[1] if ax.get_ylim()[1] > 0 else 1.0
    xlim_max = ax.get_xlim()[1]
    for t in tickers_in_sector:
        cur_rv = float(current[t]['y_true'])
        if 0 < cur_rv < xlim_max:
            tc = SECTOR_COLORS.get(SECTORS.get(t, 'Other'), '#999')
            ax.axvline(cur_rv, color=tc, lw=1.1, linestyle=':', alpha=0.85)
            ax.text(cur_rv, ymax * 0.97, f'{t}', color=WHITE,
                    fontsize=5.5, rotation=90, va='top', ha='right')

    ax.set_xlabel('Annualized RV', color=DIM, fontsize=7.5)

fig.suptitle(
    f'Tarasque v4  —  Sector RV Distributions  (H={HORIZON}d, 2013–2025)\n'
    'Solid KDE = pooled sector RV  |  Dotted lines = each firm\'s current RV',
    color=WHITE, fontsize=14, fontweight='bold', y=1.01,
)

outpath = RESULTS_DIR / 'vol_dist_sector_full.png'
plt.savefig(outpath, dpi=140, bbox_inches='tight', facecolor=BG)
plt.close()
print(f'  Saved: {outpath}')


# ═══════════════════════════════════════════════════════════════════════════════
# CHART 3 — Market distribution (all 94 tickers, equal-weighted)
# ═══════════════════════════════════════════════════════════════════════════════

print('\n[3/4] Market distribution chart...')

fig, ax = plt.subplots(figsize=(12, 5))
fig.patch.set_facecolor(BG)
ax.set_facecolor(PANEL_BG)

# Concatenate all RV observations — each ticker equally represented
all_market_rv = np.concatenate([df['y_true'].values for df in ticker_data.values()])
xlim_max = min(np.percentile(all_market_rv, 99.5) * 1.2, 2.0)
x_grid   = np.linspace(0, xlim_max, 600)

# Market KDE
kde_mkt = gaussian_kde(all_market_rv, bw_method='scott')
ax.fill_between(x_grid, kde_mkt(x_grid), alpha=0.2, color='#aaaaaa')
ax.plot(x_grid, kde_mkt(x_grid), color=WHITE, lw=2.2, label='Market RV distribution')

# Sector-median current RV lines
sector_current_rv = {}
for s, tickers_in_s in sector_groups.items():
    vals = [float(current[t]['y_true']) for t in tickers_in_s if t in current]
    if vals:
        sector_current_rv[s] = np.median(vals)

ymax = ax.get_ylim()[1] if ax.get_ylim()[1] > 0 else 1.0
for s, med_rv in sorted(sector_current_rv.items(), key=lambda x: x[1]):
    scol = SECTOR_COLORS.get(s, '#999999')
    if 0 < med_rv < xlim_max:
        ax.axvline(med_rv, color=scol, lw=1.4, linestyle=':', alpha=0.9)
        ax.text(med_rv, ymax * 0.98, f' {s}', color=scol,
                fontsize=7, rotation=90, va='top', ha='left')

# Annotate market stats
mkt_median = np.median(all_market_rv)
mkt_p75    = np.percentile(all_market_rv, 75)
mkt_p90    = np.percentile(all_market_rv, 90)
ax.axvline(mkt_median, color='#fbbf24', lw=1.6, linestyle='--', alpha=0.8, label=f'Market median ({mkt_median:.3f})')

ax.text(0.97, 0.95,
        f'n = {len(all_market_rv):,} obs  |  {len(ticker_data)} tickers\n'
        f'Median: {mkt_median:.3f}   P75: {mkt_p75:.3f}   P90: {mkt_p90:.3f}',
        transform=ax.transAxes, ha='right', va='top', color=WHITE,
        fontsize=9, bbox=dict(fc='#111', ec='#444', alpha=0.85, pad=5))

ax.legend(fontsize=9, facecolor='#222', edgecolor='#555', labelcolor=WHITE, loc='upper right')
ax.set_xlim(0, xlim_max)
ax.set_yticks([])
ax.set_xlabel('Annualized Realized Vol', color=DIM, fontsize=10)
ax.tick_params(colors=DIM)
for sp in ax.spines.values():
    sp.set_color('#444')
ax.grid(axis='x', color=GRID_COL, lw=0.5)

fig.suptitle(
    f'Tarasque v4  —  Market RV Distribution  ({len(ticker_data)} tickers, H={HORIZON}d, 2013–2025)\n'
    'Dotted lines = each sector\'s current median RV',
    color=WHITE, fontsize=13, fontweight='bold',
)
plt.tight_layout()
outpath = RESULTS_DIR / 'vol_dist_market.png'
plt.savefig(outpath, dpi=140, bbox_inches='tight', facecolor=BG)
plt.close()
print(f'  Saved: {outpath}')


# ═══════════════════════════════════════════════════════════════════════════════
# CHART 4 — Compact sector grid (2-col layout, RV + forecast overlay)
# ═══════════════════════════════════════════════════════════════════════════════

print('\n[4/4] Compact sector grid...')

ncols2 = 2
nrows2 = (n_sectors + ncols2 - 1) // ncols2

fig2 = plt.figure(figsize=(18, nrows2 * 3.8))
fig2.patch.set_facecolor(BG)
gs2  = gridspec.GridSpec(nrows2, ncols2, figure=fig2, hspace=0.60, wspace=0.22)

for idx, sector in enumerate(sector_list):
    row, col = divmod(idx, ncols2)
    ax = fig2.add_subplot(gs2[row, col])

    tickers_in_sector = [t for t in sector_groups[sector] if t in ticker_data]
    if not tickers_in_sector:
        ax.set_visible(False)
        continue

    scol = SECTOR_COLORS.get(sector, '#999999')

    all_rv   = np.concatenate([ticker_data[t]['y_true'].values  for t in tickers_in_sector])
    all_pred = np.concatenate([ticker_data[t]['y_pred'].values  for t in tickers_in_sector])

    # median current RV for this sector (single dotted line)
    med_cur_rv   = np.median([float(current[t]['y_true']) for t in tickers_in_sector])
    med_cur_pred = np.median([float(current[t]['y_pred']) for t in tickers_in_sector])

    kde_panel(
        ax,
        rv_vals    = all_rv,
        pred_vals  = all_pred,
        vline_rv   = med_cur_rv,
        vline_pred = med_cur_pred,
        show_pred  = True,
        sector_color = scol,
        title      = f'{sector}  ({len(tickers_in_sector)} tickers)',
    )
    ax.set_xlabel('Annualized Vol', color=DIM, fontsize=7.5)

    # Small legend only on first panel
    if idx == 0:
        ax.legend(fontsize=7, facecolor='#222', edgecolor='#555',
                  labelcolor=WHITE, loc='upper right')

fig2.suptitle(
    f'Tarasque v4  —  Sector Vol Distributions (RV vs Forecast)  |  H={HORIZON}d\n'
    'Blue = Realized Vol  |  Orange dashed = Model Forecast  |  Dotted lines = sector median current',
    color=WHITE, fontsize=13, fontweight='bold', y=1.01,
)
outpath2 = RESULTS_DIR / 'vol_dist_sector_grid.png'
plt.savefig(outpath2, dpi=140, bbox_inches='tight', facecolor=BG)
plt.close()
print(f'  Saved: {outpath2}')

print('\n=== Done ===')
print(f'  vol_dist_individual/   — {len(ticker_data)} per-ticker PNGs')
print(f'  vol_dist_sector_full.png  — per-sector KDE with firm current markers')
print(f'  vol_dist_market.png       — full market KDE with sector current markers')
print(f'  vol_dist_sector_grid.png  — compact 2-col sector grid (RV + forecast)')
