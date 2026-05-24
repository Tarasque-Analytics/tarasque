"""
plot_aapl_verification.py — Verify the per-ticker export file produces meaningful,
correct charts. Uses the actual predictions_AAPL.csv from the export bundle.

Two purposes:
  (1) Data verification — confirm columns are populated correctly, no alignment bugs
  (2) Interpretation — does the data tell a story consistent with what we know
      about AAPL's vol history (2018Q4, COVID, 2022 rate shock, etc.)?

Outputs:
  aapl_verification.png — single composite figure with 9 panels
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import json
import numpy as np
import pandas as pd
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.dates as mdates
import warnings
warnings.filterwarnings('ignore')

EXPORT_DIR = Path('model/pipeline/results/webapp_export')
CSV_PATH   = EXPORT_DIR / 'tickers' / 'predictions_AAPL.csv'
OUT_PATH   = EXPORT_DIR / 'aapl_verification.png'

# ── Theme ─────────────────────────────────────────────────────────────────────
BG       = '#0a0a0a'
PANEL_BG = '#161616'
WHITE    = '#f0f0f0'
DIM      = '#888888'
GRID     = '#262626'
ACCENT   = '#4C9BE8'
GREEN    = '#22c55e'
RED      = '#ef4444'
AMBER    = '#f59e0b'
PURPLE   = '#a78bfa'
CYAN     = '#22d3ee'

def style_axes(ax, title='', ylabel='', xlabel=''):
    ax.set_facecolor(PANEL_BG)
    ax.tick_params(colors=DIM, labelsize=8)
    for sp in ax.spines.values(): sp.set_color('#333')
    ax.grid(color=GRID, lw=0.4, alpha=0.6)
    if title:  ax.set_title(title, color=WHITE, fontsize=10, loc='left', pad=6, fontweight='bold')
    if ylabel: ax.set_ylabel(ylabel, color=DIM, fontsize=8)
    if xlabel: ax.set_xlabel(xlabel, color=DIM, fontsize=8)


# ── Load the actual export file ───────────────────────────────────────────────
print(f'Loading: {CSV_PATH}')
df = pd.read_csv(CSV_PATH, parse_dates=['date'])
df = df.sort_values('date').reset_index(drop=True)
print(f'  {len(df):,} rows, {len(df.columns)} columns')
print(f'  Date range: {df.date.min().date()} -> {df.date.max().date()}')


# ── Build figure ──────────────────────────────────────────────────────────────
fig = plt.figure(figsize=(22, 26))
fig.patch.set_facecolor(BG)
gs = gridspec.GridSpec(
    nrows=6, ncols=12, figure=fig,
    height_ratios=[0.7, 2.5, 2.0, 2.0, 2.5, 2.5],
    hspace=0.5, wspace=0.6,
    left=0.04, right=0.97, top=0.97, bottom=0.03,
)

# ── 0. Header ────────────────────────────────────────────────────────────────
ax_h = fig.add_subplot(gs[0, :])
ax_h.set_facecolor(PANEL_BG)
ax_h.set_xlim(0,1); ax_h.set_ylim(0,1); ax_h.axis('off')
ax_h.text(0.005, 0.65, 'AAPL', color=WHITE, fontsize=32, fontweight='bold',
         va='center', transform=ax_h.transAxes, family='monospace')
n_pop = sum(1 for c in df.columns if df[c].notna().any())
ax_h.text(0.08, 0.7, f'predictions_AAPL.csv  |  {len(df):,} rows  |  {len(df.columns)} columns  '
          f'({n_pop} populated, {len(df.columns)-n_pop} placeholder)',
          color=DIM, fontsize=10, va='center', transform=ax_h.transAxes)
ax_h.text(0.08, 0.4, f'Date range: {df.date.min().date()}  to  {df.date.max().date()}  '
          f'|  Spot ${df.close.iloc[-1]:.2f}  |  Latest RV {df.rv.iloc[-1]:.1%}  '
          f'|  Latest VRP {df.vrp_wedge.iloc[-1]:+.1%}',
          color=WHITE, fontsize=10, va='center', transform=ax_h.transAxes)


# ── 1. Price + Volume (verifies OHLCV) ───────────────────────────────────────
ax_p  = fig.add_subplot(gs[1, :8])
ax_pv = ax_p.twinx()
style_axes(ax_p, title='Price + Volume — full history (verifies OHLCV alignment)', ylabel='Adj Close ($)')

ax_p.plot(df['date'], df['adj_close'], color=ACCENT, lw=1.2, label='adj_close')
ax_p.plot(df['date'], df['close'], color='#666', lw=0.5, alpha=0.5, label='close (raw)')
ax_p.fill_between(df['date'], df['low'], df['high'], color=ACCENT, alpha=0.10)

ax_pv.set_facecolor((0,0,0,0))
ax_pv.bar(df['date'], df['volume']/1e6, color='white', alpha=0.10, width=2)
ax_pv.set_ylabel('Volume (M)', color=DIM, fontsize=8)
ax_pv.tick_params(colors=DIM, labelsize=7)
ax_pv.set_ylim(0, df['volume'].max()/1e6 * 4)  # squash to bottom 25%
for sp in ax_pv.spines.values(): sp.set_color('#333')

# Mark known regime breaks
for date_str, label in [('2018-12-24','2018Q4 selloff'),('2020-03-23','COVID low'),
                        ('2022-10-13','Rate shock low'),('2024-08-05','Yen unwind')]:
    d = pd.Timestamp(date_str)
    if df['date'].min() <= d <= df['date'].max():
        ax_p.axvline(d, color=AMBER, lw=0.5, alpha=0.5, linestyle='--')

ax_p.legend(fontsize=8, facecolor='#1a1a1a', edgecolor='#333', labelcolor='white', loc='upper left')


# ── 2. RV / IV / Calibrated forecast over time ────────────────────────────────
ax_v = fig.add_subplot(gs[1, 8:])
style_axes(ax_v, title='RV vs IV(30d) vs Forecast(H=21, calibrated)', ylabel='Annualized vol')
ax_v.plot(df['date'], df['rv'],         color=GREEN,  lw=0.8, alpha=0.7, label='Realized (GK)')
ax_v.plot(df['date'], df['iv_atm_30d'], color=AMBER,  lw=0.8, alpha=0.7, label='IV ATM 30d')
ax_v.plot(df['date'], df['pfv_cal_21'], color=ACCENT, lw=0.8, alpha=0.9, label='PFV cal H=21')
ax_v.legend(fontsize=7.5, facecolor='#1a1a1a', edgecolor='#333', labelcolor='white', loc='upper left')


# ── 3. VRP wedge raw + EWMA  (the fear cycle) ─────────────────────────────────
ax_vrp = fig.add_subplot(gs[2, :8])
style_axes(ax_vrp, title='VRP wedge (raw) + 21d EWMA — fear premium cycle', ylabel='IV30d - RV')
ax_vrp.plot(df['date'], df['vrp_wedge'], color=PURPLE, lw=0.7, alpha=0.4, label='Raw VRP')
ax_vrp.plot(df['date'], df['vrp_wedge_ewma_21d'], color=PURPLE, lw=2.0, label='EWMA-21d')
ax_vrp.axhline(0, color='white', lw=0.8, linestyle='--', alpha=0.5)
ax_vrp.fill_between(df['date'], 0, df['vrp_wedge_ewma_21d'],
                    where=(df['vrp_wedge_ewma_21d']>0), color=AMBER, alpha=0.15, label='IV>RV (fear)')
ax_vrp.fill_between(df['date'], 0, df['vrp_wedge_ewma_21d'],
                    where=(df['vrp_wedge_ewma_21d']<0), color=GREEN, alpha=0.15, label='IV<RV')
ax_vrp.legend(fontsize=7.5, facecolor='#1a1a1a', edgecolor='#333', labelcolor='white', loc='upper left', ncol=4)


# ── 4. Forecast residuals over time (where does the model break?) ─────────────
ax_res = fig.add_subplot(gs[2, 8:])
style_axes(ax_res, title='Forecast residual: realized - calibrated', ylabel='RV - PFV_cal', xlabel='date')
res = df['rv'] - df['pfv_cal_21']
ax_res.plot(df['date'], res, color=CYAN, lw=0.6, alpha=0.7)
ax_res.axhline(0, color='white', lw=0.8, alpha=0.7)
mean_res, std_res = res.mean(), res.std()
ax_res.axhline(mean_res + 2*std_res, color=RED, lw=0.5, linestyle=':', alpha=0.6)
ax_res.axhline(mean_res - 2*std_res, color=RED, lw=0.5, linestyle=':', alpha=0.6)
ax_res.text(0.99, 0.97, f'mean {mean_res:+.4f}  std {std_res:.4f}',
            transform=ax_res.transAxes, ha='right', va='top', color=DIM, fontsize=8,
            bbox=dict(boxstyle='round,pad=0.3', facecolor='#1a1a1a', edgecolor='#333'))


# ── 5. Calibration scatter: forecast vs realized (MZ-style) ───────────────────
ax_cal = fig.add_subplot(gs[3, :4])
style_axes(ax_cal, title='Calibration: PFV_cal H=21 vs Realized RV',
           xlabel='PFV_cal_21 (predicted)', ylabel='Realized RV')
sub = df.dropna(subset=['rv','pfv_cal_21'])
ax_cal.scatter(sub['pfv_cal_21'], sub['rv'], s=4, alpha=0.25, color=ACCENT, edgecolors='none')

# Identity + OLS line
lo = min(sub['pfv_cal_21'].min(), sub['rv'].min())
hi = max(sub['pfv_cal_21'].max(), sub['rv'].max())
ax_cal.plot([lo,hi],[lo,hi], color='white', lw=1, linestyle='--', alpha=0.6, label='y=x')
beta, alpha = np.polyfit(sub['pfv_cal_21'], sub['rv'], 1)
xs = np.linspace(lo, hi, 100)
ax_cal.plot(xs, alpha + beta*xs, color=AMBER, lw=1.5,
            label=f'OLS  beta={beta:.3f}  alpha={alpha:+.4f}')
r2 = np.corrcoef(sub['pfv_cal_21'], sub['rv'])[0,1]**2
ax_cal.text(0.04, 0.96, f'R^2 = {r2:.3f}\nn = {len(sub):,}',
            transform=ax_cal.transAxes, va='top', color=WHITE, fontsize=9,
            bbox=dict(boxstyle='round,pad=0.3', facecolor='#1a1a1a', edgecolor='#333'))
ax_cal.legend(fontsize=7.5, facecolor='#1a1a1a', edgecolor='#333', labelcolor='white', loc='lower right')


# ── 6. Term structure of forecasts (latest snapshot) ─────────────────────────
ax_ts = fig.add_subplot(gs[3, 4:8])
style_axes(ax_ts, title='Latest term structure  (only 30d IV available — others pending vsurfd ETL)',
           xlabel='DTE (trading days)', ylabel='Annualized vol')

latest = df.iloc[-1]
hor = [21, 63, 126]
pfv_cal  = [latest['pfv_cal_21'], latest['pfv_cal_63'], latest['pfv_cal_126']]
pfv_q15  = [latest['pfv_q15_21'], latest['pfv_q15_63'], latest['pfv_q15_126']]
pfv_raw  = [latest['pfv_21'], latest['pfv_63'], latest['pfv_126']]

ax_ts.plot(hor, pfv_cal, color=ACCENT, lw=2, marker='o', markersize=8, label='PFV calibrated', zorder=3)
ax_ts.plot(hor, pfv_raw, color=ACCENT, lw=1, alpha=0.5, marker='s', markersize=6, label='PFV raw')
ax_ts.plot(hor, pfv_q15, color=ACCENT, lw=1, alpha=0.5, marker='v', markersize=6, linestyle='--', label='Q15 floor')
ax_ts.fill_between(hor, pfv_q15, pfv_cal, color=ACCENT, alpha=0.10)

# Add the one IV point we have
ax_ts.scatter([30], [latest['iv_atm_30d']], color=AMBER, s=100, marker='X',
              edgecolors='white', linewidths=1.5, zorder=4, label=f'IV 30d = {latest["iv_atm_30d"]:.1%}')
ax_ts.legend(fontsize=8, facecolor='#1a1a1a', edgecolor='#333', labelcolor='white', loc='upper left')


# ── 7. Quantile floor coverage check ──────────────────────────────────────────
ax_qc = fig.add_subplot(gs[3, 8:])
style_axes(ax_qc, title='Q15 floor coverage by horizon  (target: ~15%)',
           ylabel='% of realized below floor')

cov_results = []
for h in [21, 63, 126]:
    rv_col   = 'rv'  # rv at H=21 is what we have
    pfv_col  = f'pfv_q15_{h}'
    sub = df.dropna(subset=[rv_col, pfv_col])
    pct_below = (sub[rv_col] < sub[pfv_col]).mean() * 100
    cov_results.append((f'H={h}', pct_below))

bars = ax_qc.bar([r[0] for r in cov_results], [r[1] for r in cov_results],
                 color=[GREEN if 12<=v<=18 else AMBER if 8<=v<=22 else RED for _,v in cov_results],
                 alpha=0.85, width=0.5)
ax_qc.axhline(15, color='white', lw=1.5, linestyle='--', alpha=0.7, label='Target 15%')
for bar, (label, val) in zip(bars, cov_results):
    ax_qc.text(bar.get_x() + bar.get_width()/2, bar.get_height()+0.3,
              f'{val:.1f}%', ha='center', va='bottom', color=WHITE, fontsize=10, fontweight='bold')
ax_qc.legend(fontsize=8, facecolor='#1a1a1a', edgecolor='#333', labelcolor='white', loc='upper right')


# ── 8. Distributions: rv, iv, vrp_wedge ───────────────────────────────────────
ax_d1 = fig.add_subplot(gs[4, :4])
ax_d2 = fig.add_subplot(gs[4, 4:8])
ax_d3 = fig.add_subplot(gs[4, 8:])

for ax, col, label, color in [
    (ax_d1, 'rv',         'Realized Vol (GK 21d)', GREEN),
    (ax_d2, 'iv_atm_30d', 'IV ATM 30d',            AMBER),
    (ax_d3, 'vrp_wedge',  'VRP wedge (IV - RV)',   PURPLE),
]:
    style_axes(ax, title=f'Distribution: {label}', xlabel=col)
    vals = df[col].dropna()
    ax.hist(vals, bins=50, color=color, alpha=0.85, edgecolor='none')
    cv = vals.iloc[-1]
    pct = (vals < cv).mean()
    ax.axvline(cv, color=WHITE, lw=2.0, linestyle='--', label=f'Current = {cv:.4f} (P{int(pct*100)})')
    ax.axvline(vals.mean(), color=DIM, lw=1, linestyle=':', alpha=0.7,
              label=f'Mean = {vals.mean():.4f}')
    ax.legend(fontsize=8, facecolor='#1a1a1a', edgecolor='#333', labelcolor='white', loc='upper right')


# ── 9. Forecast curve overlay across full history (final panel) ──────────────
ax_full = fig.add_subplot(gs[5, :])
style_axes(ax_full, title='Full history: Realized vs Calibrated forecasts at all 3 horizons',
           ylabel='Annualized vol', xlabel='date')

ax_full.plot(df['date'], df['rv'], color=GREEN, lw=0.6, alpha=0.6, label='Realized (GK 21d)')
ax_full.plot(df['date'], df['pfv_cal_21'],  color=ACCENT, lw=0.7, alpha=0.85, label='PFV cal H=21')
ax_full.plot(df['date'], df['pfv_cal_63'],  color=PURPLE, lw=0.7, alpha=0.85, label='PFV cal H=63')
ax_full.plot(df['date'], df['pfv_cal_126'], color=CYAN,   lw=0.7, alpha=0.85, label='PFV cal H=126')

# Mark regime events on the full panel for context
for date_str, label, sev_color in [
    ('2018-12-24','Q4 2018', AMBER),
    ('2020-03-23','COVID',   RED),
    ('2022-10-13','Rates',   AMBER),
    ('2024-08-05','Yen',     AMBER),
]:
    d = pd.Timestamp(date_str)
    if df['date'].min() <= d <= df['date'].max():
        ax_full.axvline(d, color=sev_color, lw=0.6, alpha=0.5, linestyle='--')
        ax_full.text(d, 0.02, label, color=sev_color, fontsize=7, ha='center',
                    transform=ax_full.get_xaxis_transform(),
                    bbox=dict(boxstyle='round,pad=0.2', facecolor='#1a1a1a',
                              edgecolor=sev_color, alpha=0.8))

ax_full.legend(fontsize=8, facecolor='#1a1a1a', edgecolor='#333', labelcolor='white',
              loc='upper left', ncol=4)


plt.savefig(OUT_PATH, dpi=130, bbox_inches='tight', facecolor=BG)
plt.close()
print(f'\nSaved: {OUT_PATH}')

# ── Print a verification summary ──────────────────────────────────────────────
print('\n=== Verification summary ===')
print(f'OHLCV alignment: {df[["open","high","low","close","adj_close","volume"]].notna().all(axis=1).sum():,}/{len(df):,} rows fully populated')
print(f'RV / IV / VRP:    {df[["rv","iv_atm_30d","vrp_wedge"]].notna().all(axis=1).sum():,}/{len(df):,} rows')
print(f'All 9 forecasts:  {df[["pfv_21","pfv_63","pfv_126","pfv_q15_21","pfv_q15_63","pfv_q15_126","pfv_cal_21","pfv_cal_63","pfv_cal_126"]].notna().all(axis=1).sum():,}/{len(df):,} rows')

# Calibration check
sub = df.dropna(subset=['rv','pfv_cal_21'])
beta, alpha = np.polyfit(sub['pfv_cal_21'], sub['rv'], 1)
r2 = np.corrcoef(sub['pfv_cal_21'], sub['rv'])[0,1]**2
print(f'\nCalibration H=21:  beta={beta:.3f}  alpha={alpha:+.4f}  R^2={r2:.3f}')

# Quantile floor coverage
for h in [21, 63, 126]:
    sub = df.dropna(subset=['rv', f'pfv_q15_{h}'])
    pct = (sub['rv'] < sub[f'pfv_q15_{h}']).mean() * 100
    print(f'Q15 coverage H={h}: {pct:.1f}% of realized below floor (target ~15%)')

# VRP cycle check
print(f'\nVRP wedge stats:')
print(f'  mean: {df["vrp_wedge"].mean():+.4f}')
print(f'  std:  {df["vrp_wedge"].std():.4f}')
print(f'  pct of days IV>RV: {(df["vrp_wedge"]>0).mean()*100:.1f}%')