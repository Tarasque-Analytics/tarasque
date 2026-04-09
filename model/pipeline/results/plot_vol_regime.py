"""
plot_vol_regime.py  —  Current volatility regime dashboard

Three regime lenses, each answering a different question:

  1. RV Percentile  ("What is the market DOING right now?")
     Recent realized vol vs each stock's full history.
     Pure backward-looking. Tells you where actual vol has landed.
     Regime labels: Suppressed / Normal / Elevated / Stress / Crisis

  2. Forecast Percentile  ("What does the model EXPECT next 21 days?")
     Model's current prediction vs its own historical forecast distribution.
     Forward-looking signal. Tells you where the model thinks vol is headed.
     Divergence from RV percentile = regime transition signal.

  3. IV Percentile  ("What is the OPTIONS MARKET pricing?")
     Implied vol (reconstructed as vrp_wedge + y_true) vs historical IV.
     Market's risk premium. When IV pct >> RV pct = fear premium / hedging demand.
     When IV pct << RV pct = complacency / vol selling regime.

All three together on the macro page: each number tells a different story.
The page write-up explains this below each chart.

Outputs:
  vol_regime_market.png      — market heatmap: all 3 lenses, all tickers ranked
  vol_regime_sectors.png     — sector-level regime bar chart
  vol_regime_divergence.png  — IV vs RV percentile scatter (fear premium map)
  vol_regime_summary.csv     — machine-readable, feeds Supabase

Run from repo root:
  python model/pipeline/results/plot_vol_regime.py
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import re
import numpy as np
import pandas as pd
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.colors import LinearSegmentedColormap
import warnings
warnings.filterwarnings('ignore')

RESULTS_DIR = Path('model/pipeline/results')
HORIZON     = 21          # Use H=21 as primary regime signal
RECENT_DAYS = 21          # "current" RV = trailing 21-day average

BG       = '#0f0f0f'
PANEL_BG = '#1a1a1a'
WHITE    = '#f0f0f0'
DIM      = '#777777'
GRID     = '#2e2e2e'

# Regime color scale: green (suppressed) -> yellow (normal) -> orange (elevated) -> red (stress/crisis)
REGIME_CMAP = LinearSegmentedColormap.from_list(
    'regime', ['#16a34a', '#84cc16', '#fbbf24', '#f97316', '#dc2626'], N=256
)

REGIME_BINS   = [0.0, 0.25, 0.50, 0.75, 0.90, 1.0]
REGIME_LABELS = ['Suppressed', 'Normal', 'Elevated', 'Stress', 'Crisis']
REGIME_COLORS = ['#16a34a',   '#84cc16', '#fbbf24',  '#f97316', '#dc2626']

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

def regime_label(pct):
    for i, (lo, hi) in enumerate(zip(REGIME_BINS[:-1], REGIME_BINS[1:])):
        if pct <= hi:
            return REGIME_LABELS[i], REGIME_COLORS[i]
    return REGIME_LABELS[-1], REGIME_COLORS[-1]

# ── Load all H=21 data ────────────────────────────────────────────────────────
print('Loading data...')
ticker_data = {}
for f in sorted(RESULTS_DIR.iterdir()):
    m = re.match(rf'predictions_([A-Z]+)_H{HORIZON}\.csv', f.name)
    if m:
        ticker = m.group(1)
        df = pd.read_csv(f)
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date')
        if len(df) >= 100:
            ticker_data[ticker] = df

print(f'  {len(ticker_data)} tickers loaded')

# ── Compute regime percentiles per ticker ─────────────────────────────────────
print('Computing regime percentiles...')
regime_rows = []

for ticker, df in ticker_data.items():
    full  = df.dropna(subset=['y_true', 'y_pred'])
    iv_df = df.dropna(subset=['y_true', 'y_pred', 'vrp_wedge'])

    if len(full) < 50:
        continue

    # Reconstruct IV
    iv_df = iv_df.copy()
    iv_df['iv_implied'] = iv_df['vrp_wedge'] + iv_df['y_true']

    # Current values: trailing RECENT_DAYS mean of y_true (smoothed RV),
    # most recent single prediction and IV
    recent_rv   = full['y_true'].tail(RECENT_DAYS).mean()
    current_pred = full['y_pred'].iloc[-1]
    current_iv   = iv_df['iv_implied'].iloc[-1] if len(iv_df) > 0 else np.nan
    current_vrp  = iv_df['vrp_wedge'].iloc[-1]  if len(iv_df) > 0 else np.nan
    current_skew = full['put_call_skew_30d'].iloc[-1] if 'put_call_skew_30d' in full.columns else np.nan
    last_date    = full['date'].iloc[-1].strftime('%Y-%m-%d')

    # Percentile: where does current value sit in full history
    rv_pct   = (full['y_true'] <= recent_rv).mean()
    pred_pct = (full['y_pred'] <= current_pred).mean()
    iv_pct   = (iv_df['iv_implied'] <= current_iv).mean() if not np.isnan(current_iv) else np.nan

    regime_rows.append({
        'ticker':      ticker,
        'sector':      SECTORS.get(ticker, 'Other'),
        'last_date':   last_date,
        'rv_current':  recent_rv,
        'rv_pct':      rv_pct,
        'pred_current': current_pred,
        'pred_pct':    pred_pct,
        'iv_current':  current_iv,
        'iv_pct':      iv_pct,
        'vrp_current': current_vrp,
        'skew_current': current_skew,
    })

reg = pd.DataFrame(regime_rows)
reg = reg.sort_values('rv_pct', ascending=False).reset_index(drop=True)
print(f'  {len(reg)} tickers with regime data')

# Save CSV for Supabase
reg.to_csv(RESULTS_DIR / 'vol_regime_summary.csv', index=False)
print('  Saved: vol_regime_summary.csv')


# ═══════════════════════════════════════════════════════════════════════════════
# CHART 1 — Market heatmap: all 3 lenses ranked by RV pct
# ═══════════════════════════════════════════════════════════════════════════════
print('\n[1/3] Market regime heatmap...')

n = len(reg)
fig = plt.figure(figsize=(22, max(12, n * 0.22 + 4)))
fig.patch.set_facecolor(BG)
gs  = gridspec.GridSpec(1, 3, figure=fig, wspace=0.05)

lens_cols  = ['rv_pct', 'pred_pct', 'iv_pct']
lens_labels = [
    'RV Percentile\n(What vol IS doing)',
    'Forecast Percentile\n(What model EXPECTS)',
    'IV Percentile\n(What market PRICES)',
]

for col_idx, (col, label) in enumerate(zip(lens_cols, lens_labels)):
    ax = fig.add_subplot(gs[col_idx])
    ax.set_facecolor(PANEL_BG)

    vals = reg[col].values
    tickers_sorted = reg['ticker'].values
    sectors_sorted = reg['sector'].values

    for row_idx, (ticker, sector, val) in enumerate(zip(tickers_sorted, sectors_sorted, vals)):
        y = n - row_idx - 1
        if np.isnan(val):
            color = '#333333'
            txt_val = 'N/A'
        else:
            color = REGIME_CMAP(val)
            txt_val = f'{val:.2f}'

        ax.barh(y, 1, left=0, color=color, height=0.82, alpha=0.9)

        # Ticker label (left column only)
        if col_idx == 0:
            scol = SECTOR_COLORS.get(sector, '#999')
            ax.text(-0.02, y, ticker, color=scol, fontsize=6.2,
                    va='center', ha='right', fontweight='bold')

        # Value label inside bar
        ax.text(0.5, y, txt_val, color='white', fontsize=6,
                va='center', ha='center', fontweight='bold')

    ax.set_xlim(0, 1)
    ax.set_ylim(-0.5, n - 0.5)
    ax.set_yticks([])
    ax.set_xticks([0, 0.25, 0.5, 0.75, 1.0])
    ax.set_xticklabels(['0', 'P25', 'P50', 'P75', 'P100'], color=DIM, fontsize=7)
    ax.set_title(label, color=WHITE, fontsize=9, pad=6)
    for sp in ax.spines.values(): sp.set_color('#444')
    ax.tick_params(colors=DIM)

    # Regime zone lines
    for boundary in [0.25, 0.50, 0.75, 0.90]:
        ax.axvline(boundary, color='#555', lw=0.6, linestyle=':')

# Colorbar legend
cax = fig.add_axes([0.92, 0.15, 0.012, 0.70])
sm  = plt.cm.ScalarMappable(cmap=REGIME_CMAP)
sm.set_array([])
cb  = fig.colorbar(sm, cax=cax)
cb.set_ticks([0, 0.25, 0.50, 0.75, 0.90, 1.0])
cb.set_ticklabels(
    ['Suppressed\n(0)', 'Normal\n(P25)', 'Elevated\n(P50)', 'Stress\n(P75)', 'Crisis\n(P90)', ''],
    color=WHITE, fontsize=7,
)
cb.outline.set_edgecolor('#444')

fig.suptitle(
    f'Tarasque v4  —  Current Volatility Regime  |  {len(reg)} Tickers  |  H={HORIZON}d\n'
    'Ranked by RV percentile (left).  Three independent regime lenses.',
    color=WHITE, fontsize=13, fontweight='bold', x=0.46,
)
plt.savefig(RESULTS_DIR / 'vol_regime_market.png', dpi=130, bbox_inches='tight', facecolor=BG)
plt.close()
print('  Saved: vol_regime_market.png')


# ═══════════════════════════════════════════════════════════════════════════════
# CHART 2 — Sector-level regime bar chart
# ═══════════════════════════════════════════════════════════════════════════════
print('[2/3] Sector regime chart...')

sect_reg = reg.groupby('sector')[['rv_pct','pred_pct','iv_pct']].median().reset_index()
sect_reg = sect_reg.sort_values('rv_pct', ascending=True)

n_s  = len(sect_reg)
fig, axes = plt.subplots(1, 3, figsize=(20, max(6, n_s * 0.55 + 2.5)), sharey=True)
fig.patch.set_facecolor(BG)

for ax, col, label in zip(axes, lens_cols, lens_labels):
    ax.set_facecolor(PANEL_BG)
    vals = sect_reg[col].values
    sects = sect_reg['sector'].values

    bars = ax.barh(range(n_s), vals, color=[REGIME_CMAP(v) if not np.isnan(v) else '#333' for v in vals],
                   alpha=0.88, height=0.65)

    for i, (bar, val) in enumerate(zip(bars, vals)):
        if not np.isnan(val):
            ax.text(val + 0.01, i, f'{val:.2f}', color=WHITE, fontsize=8.5, va='center')

    for boundary, rlabel in zip([0.25, 0.50, 0.75, 0.90],
                                 ['Normal', 'Elevated', 'Stress', 'Crisis']):
        ax.axvline(boundary, color='#555', lw=0.8, linestyle=':')
        ax.text(boundary, n_s - 0.3, rlabel, color='#666', fontsize=6.5,
                ha='center', va='top', rotation=90)

    ax.set_xlim(0, 1.12)
    ax.set_yticks(range(n_s))
    ax.set_yticklabels(sects, color=WHITE, fontsize=9)
    ax.set_title(label, color=WHITE, fontsize=10, pad=6)
    ax.tick_params(colors=DIM)
    for sp in ax.spines.values(): sp.set_color('#444')
    ax.grid(axis='x', color=GRID, lw=0.5)
    ax.set_xlabel('Percentile', color=DIM, fontsize=8)

fig.suptitle(
    'Tarasque v4  —  Sector Median Regime Percentiles  |  H=21d\n'
    'Sector = median of member firm percentiles',
    color=WHITE, fontsize=13, fontweight='bold',
)
plt.tight_layout()
plt.savefig(RESULTS_DIR / 'vol_regime_sectors.png', dpi=140, bbox_inches='tight', facecolor=BG)
plt.close()
print('  Saved: vol_regime_sectors.png')


# ═══════════════════════════════════════════════════════════════════════════════
# CHART 3 — Divergence scatter: IV pct vs RV pct  (fear premium map)
# ═══════════════════════════════════════════════════════════════════════════════
print('[3/3] IV vs RV divergence scatter...')

fig, ax = plt.subplots(figsize=(13, 11))
fig.patch.set_facecolor(BG)
ax.set_facecolor(PANEL_BG)

plot_df = reg.dropna(subset=['rv_pct', 'iv_pct'])

for _, row in plot_df.iterrows():
    scol = SECTOR_COLORS.get(row['sector'], '#999')
    ax.scatter(row['rv_pct'], row['iv_pct'], color=scol, s=55, alpha=0.85, zorder=3)
    ax.annotate(row['ticker'], (row['rv_pct'], row['iv_pct']),
                xytext=(4, 3), textcoords='offset points',
                color=scol, fontsize=6.2, alpha=0.9)

# 45-degree line: IV pct == RV pct (no premium)
ax.plot([0, 1], [0, 1], color='white', lw=1.2, linestyle='--', alpha=0.5, label='IV pct = RV pct (no premium)')

# Quadrant shading and labels
ax.fill_between([0, 0.5], [0.5, 0.5], [1, 1], color='#ef4444', alpha=0.04)   # High fear
ax.fill_between([0.5, 1], [0, 0], [0.5, 0.5], color='#22c55e', alpha=0.04)   # Complacency
ax.text(0.05, 0.96, 'Fear Premium Zone\n(IV elevated, RV calm)', color='#f87171',
        fontsize=9, transform=ax.transAxes, va='top')
ax.text(0.60, 0.06, 'Complacency Zone\n(RV elevated, IV cheap)', color='#4ade80',
        fontsize=9, transform=ax.transAxes, va='bottom')
ax.text(0.05, 0.06, 'Both Suppressed\n(calm regime)', color=DIM,
        fontsize=9, transform=ax.transAxes, va='bottom')
ax.text(0.60, 0.96, 'Stress / Crisis\n(both elevated)', color='#fca5a5',
        fontsize=9, transform=ax.transAxes, va='top')

# Sector legend
from matplotlib.lines import Line2D
handles = [Line2D([0],[0], marker='o', color='w', markerfacecolor=c, markersize=8, label=s)
           for s, c in SECTOR_COLORS.items() if s in plot_df['sector'].values]
ax.legend(handles=handles, fontsize=7.5, facecolor='#1a1a1a', edgecolor='#555',
          labelcolor=WHITE, loc='center right', ncol=1)

ax.set_xlim(-0.02, 1.05)
ax.set_ylim(-0.02, 1.05)
ax.set_xlabel('RV Percentile  (realized vol vs history)', color=WHITE, fontsize=11)
ax.set_ylabel('IV Percentile  (implied vol vs history)', color=WHITE, fontsize=11)
ax.tick_params(colors=DIM)
for sp in ax.spines.values(): sp.set_color('#444')
ax.grid(color=GRID, lw=0.5, alpha=0.7)

# Regime boundary lines
for v in [0.25, 0.50, 0.75, 0.90]:
    ax.axvline(v, color='#444', lw=0.6, linestyle=':')
    ax.axhline(v, color='#444', lw=0.6, linestyle=':')

fig.suptitle(
    'Tarasque v4  —  IV vs RV Regime Divergence Map  |  H=21d\n'
    'Points above diagonal = market pricing fear premium  |  Below = complacency / vol selling',
    color=WHITE, fontsize=13, fontweight='bold',
)
plt.tight_layout()
plt.savefig(RESULTS_DIR / 'vol_regime_divergence.png', dpi=140, bbox_inches='tight', facecolor=BG)
plt.close()
print('  Saved: vol_regime_divergence.png')

# ── Print market summary ──────────────────────────────────────────────────────
print('\n=== Market Regime Summary ===')
for lens, col in [('RV', 'rv_pct'), ('Forecast', 'pred_pct'), ('IV', 'iv_pct')]:
    vals = reg[col].dropna()
    med  = vals.median()
    lbl, _ = regime_label(med)
    in_stress = (vals >= 0.75).mean() * 100
    print(f'  {lens:10s}: median pct={med:.2f} ({lbl}) | {in_stress:.0f}% of tickers in Stress/Crisis')

print(f'\n  Top 5 highest RV regime tickers:')
print(reg[['ticker','sector','rv_pct','pred_pct','iv_pct']].head(5).to_string(index=False))
print(f'\n  Highest IV-RV divergence (fear premium):')
reg['iv_rv_gap'] = reg['iv_pct'] - reg['rv_pct']
top_fear = reg.nlargest(5, 'iv_rv_gap')[['ticker','sector','rv_pct','iv_pct','iv_rv_gap']]
print(top_fear.to_string(index=False))

print('\n=== Vol regime analysis complete ===')
print('Output files:')
print('  vol_regime_market.png      — full heatmap: all tickers x 3 lenses')
print('  vol_regime_sectors.png     — sector median regime bars')
print('  vol_regime_divergence.png  — IV vs RV scatter (fear premium map)')
print('  vol_regime_summary.csv     — Supabase-ready data')
