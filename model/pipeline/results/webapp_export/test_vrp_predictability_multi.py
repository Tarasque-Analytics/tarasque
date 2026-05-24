"""
test_vrp_predictability_multi.py — Cross-ticker test of VRP_ewma signal
+ reverse bucketing (returns -> VRP).

Tests:
  A. Per-ticker VRP_ewma -> forward outcomes (RV, returns) — same tests as
     the AAPL script, but pooled across 6 tickers spanning sectors.
  B. Reverse: bucket BY forward returns (Q1=worst -> Q5=best), then show
     the VRP distribution for each bucket. Asks "what did VRP look like
     BEFORE bad/good periods?"
  C. Pooled cross-ticker quintile test for statistical power.

Outputs:
  vrp_predictability_multi.png    — composite figure
  vrp_predictability_summary.csv  — table of pearson r per ticker per outcome
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import numpy as np
import pandas as pd
from pathlib import Path
from scipy import stats
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import warnings
warnings.filterwarnings('ignore')
import yfinance as yf

RESULTS = Path('model/pipeline/results')
EXPORT  = RESULTS / 'webapp_export'
OUT     = EXPORT / 'vrp_predictability_multi.png'

BG, PANEL_BG = '#0a0a0a', '#161616'
WHITE, DIM, GRID = '#f0f0f0', '#888888', '#262626'
ACCENT, GREEN, RED, AMBER, PURPLE, CYAN = '#4C9BE8','#22c55e','#ef4444','#f59e0b','#a78bfa','#22d3ee'

TICKERS = ['AAPL', 'JPM', 'XOM', 'TSLA', 'NVDA', 'AMZN']
SECTORS = {'AAPL':'Tech','JPM':'Fin','XOM':'Energy','TSLA':'CD','NVDA':'Tech','AMZN':'CD'}
TICKER_COLOR = {'AAPL':ACCENT,'JPM':GREEN,'XOM':RED,'TSLA':AMBER,'NVDA':PURPLE,'AMZN':CYAN}

def style_axes(ax, title='', xlabel='', ylabel=''):
    ax.set_facecolor(PANEL_BG)
    ax.tick_params(colors=DIM, labelsize=8)
    for sp in ax.spines.values(): sp.set_color('#333')
    ax.grid(color=GRID, lw=0.4, alpha=0.6)
    if title:  ax.set_title(title, color=WHITE, fontsize=10, loc='left', pad=6, fontweight='bold')
    if xlabel: ax.set_xlabel(xlabel, color=DIM, fontsize=8)
    if ylabel: ax.set_ylabel(ylabel, color=DIM, fontsize=8)


# ── Build per-ticker dataset ──────────────────────────────────────────────────
print('Loading consolidated predictions...')
preds = pd.read_csv(RESULTS / 'all_predictions_cal.csv')
preds['date'] = pd.to_datetime(preds['date'])

def build_ticker_df(ticker: str) -> pd.DataFrame:
    sub = preds[preds['ticker'] == ticker].copy()
    if sub.empty:
        return None

    # Pivot to wide
    wide = sub.pivot_table(
        index='date', columns='horizon',
        values=['y_true','y_pred','y_cal','vrp_wedge'],
    )
    wide.columns = [f'{a}_{b}' for a,b in wide.columns]
    wide = wide.reset_index().sort_values('date').dropna(subset=['y_true_21'])

    # VRP EWMA
    wide['vrp_wedge_ewma_21d'] = wide['vrp_wedge_21'].ewm(span=21, adjust=False).mean()

    # Forward returns from yfinance prices
    print(f'  yfinance pull for {ticker}...')
    start = wide['date'].min().strftime('%Y-%m-%d')
    end   = (wide['date'].max() + pd.Timedelta(days=2)).strftime('%Y-%m-%d')
    hist = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
    if isinstance(hist.columns, pd.MultiIndex):
        hist.columns = hist.columns.get_level_values(0)
    hist = hist.reset_index().rename(columns={'Date':'date','Close':'adj_close'})
    hist['date'] = pd.to_datetime(hist['date'])

    df = wide.merge(hist[['date','adj_close']], on='date', how='left')
    for h in [1, 5, 21, 63]:
        df[f'fwd_ret_{h}d'] = np.log(df['adj_close'].shift(-h) / df['adj_close'])
    for h in [5, 21, 63]:
        df[f'fwd_rv_{h}d'] = df['y_true_21'].shift(-h)

    df['rv'] = df['y_true_21']
    df['ticker'] = ticker
    df['sector'] = SECTORS[ticker]
    return df

dfs = {}
for t in TICKERS:
    dfs[t] = build_ticker_df(t)
    print(f'  {t}: {len(dfs[t]):,} rows')

# ═══════════════════════════════════════════════════════════════════════════════
# A. Per-ticker VRP_ewma -> forward outcomes correlation table
# ═══════════════════════════════════════════════════════════════════════════════
print('\n=== A. Per-ticker correlations VRP_ewma -> forward outcomes ===')
rows = []
for t, df in dfs.items():
    for h in [5, 21, 63]:
        for target in ['fwd_ret', 'fwd_rv']:
            col = f'{target}_{h}d'
            sub = df[['vrp_wedge_ewma_21d', col]].dropna()
            if len(sub) < 50: continue
            r, p = stats.pearsonr(sub['vrp_wedge_ewma_21d'], sub[col])
            rs, _ = stats.spearmanr(sub['vrp_wedge_ewma_21d'], sub[col])
            rows.append({'ticker':t,'sector':SECTORS[t],'horizon':f'{h}d','target':target,
                         'pearson_r':r,'pearson_p':p,'spearman_r':rs,'n':len(sub)})
summary = pd.DataFrame(rows)
summary.to_csv(EXPORT / 'vrp_predictability_summary.csv', index=False)
print(summary.round(3).to_string(index=False))

# Pooled pearson (cross-ticker, time-stacked)
pool = pd.concat([d.assign(t=k) for k,d in dfs.items()], ignore_index=True)
print('\n=== B. Pooled (all tickers stacked) ===')
for h in [5, 21, 63]:
    for target in ['fwd_ret','fwd_rv']:
        col = f'{target}_{h}d'
        sub = pool[['vrp_wedge_ewma_21d', col]].dropna()
        r, p = stats.pearsonr(sub['vrp_wedge_ewma_21d'], sub[col])
        print(f'  H={h:3d} {target:8s}: r={r:+.4f}  p={p:.4f}  n={len(sub):,}')


# ═══════════════════════════════════════════════════════════════════════════════
# C. Reverse bucketing: bucket by forward return -> show VRP_ewma distribution
# ═══════════════════════════════════════════════════════════════════════════════
print('\n=== C. Reverse bucketing: VRP_ewma distribution by forward return quintile ===')
for ticker_name, df in dfs.items():
    print(f'\n  {ticker_name}:')
    df_clean = df.dropna(subset=['vrp_wedge_ewma_21d','fwd_ret_21d']).copy()
    df_clean['fwd_ret_q'] = pd.qcut(df_clean['fwd_ret_21d'], q=5,
                                     labels=['Q1 (worst)','Q2','Q3','Q4','Q5 (best)'])
    grp = df_clean.groupby('fwd_ret_q', observed=True)['vrp_wedge_ewma_21d'].agg(['mean','std','count'])
    print(grp.round(4).to_string())


# ═══════════════════════════════════════════════════════════════════════════════
# Visualization
# ═══════════════════════════════════════════════════════════════════════════════
print('\nRendering...')
fig = plt.figure(figsize=(22, 18))
fig.patch.set_facecolor(BG)
gs = gridspec.GridSpec(3, 6, figure=fig, hspace=0.55, wspace=0.6,
                       left=0.04, right=0.97, top=0.96, bottom=0.04)

# ── Panel 1: per-ticker correlation barchart  (forward RV) ──────────────────
ax1 = fig.add_subplot(gs[0, :3])
style_axes(ax1, title='VRP_ewma -> Forward RV  Pearson r  (per ticker, 3 horizons)',
          ylabel='Pearson r')
piv = summary[summary['target']=='fwd_rv'].pivot(index='ticker',
            columns='horizon', values='pearson_r')
piv = piv.reindex(TICKERS)
x = np.arange(len(piv))
w = 0.27
for i, h in enumerate(['5d','21d','63d']):
    color = [GREEN, ACCENT, AMBER][i]
    ax1.bar(x + (i-1)*w, piv[h], w, color=color, alpha=0.85, label=h, edgecolor='white', linewidth=0.4)
ax1.axhline(0, color='white', lw=0.8, alpha=0.7)
ax1.axhline(0.05, color=DIM, lw=0.5, linestyle=':', alpha=0.5)
ax1.set_xticks(x); ax1.set_xticklabels(piv.index)
ax1.legend(fontsize=8, facecolor='#1a1a1a', edgecolor='#333', labelcolor='white')

# ── Panel 2: per-ticker correlation barchart  (forward returns) ─────────────
ax2 = fig.add_subplot(gs[0, 3:])
style_axes(ax2, title='VRP_ewma -> Forward RETURN  Pearson r  (per ticker, 3 horizons)',
          ylabel='Pearson r')
piv2 = summary[summary['target']=='fwd_ret'].pivot(index='ticker',
            columns='horizon', values='pearson_r')
piv2 = piv2.reindex(TICKERS)
for i, h in enumerate(['5d','21d','63d']):
    color = [GREEN, ACCENT, AMBER][i]
    ax2.bar(x + (i-1)*w, piv2[h], w, color=color, alpha=0.85, label=h, edgecolor='white', linewidth=0.4)
ax2.axhline(0, color='white', lw=0.8, alpha=0.7)
ax2.axhline(0.05, color=DIM, lw=0.5, linestyle=':', alpha=0.5)
ax2.axhline(-0.05, color=DIM, lw=0.5, linestyle=':', alpha=0.5)
ax2.set_xticks(x); ax2.set_xticklabels(piv2.index)
ax2.legend(fontsize=8, facecolor='#1a1a1a', edgecolor='#333', labelcolor='white')

# ── Panel 3: forward RV by quintile, pooled ────────────────────────────────
pool['vrp_q'] = pd.qcut(pool['vrp_wedge_ewma_21d'], q=5,
                       labels=['Q1','Q2','Q3','Q4','Q5'])
ax3 = fig.add_subplot(gs[1, :3])
style_axes(ax3, title='POOLED (all 6 tickers): Forward RV by VRP_ewma quintile',
          ylabel='Forward RV (annualized)', xlabel='VRP_ewma quintile')
for i, h in enumerate([5, 21, 63]):
    col = f'fwd_rv_{h}d'
    grp = pool.groupby('vrp_q', observed=True)[col].mean()
    color = [GREEN, ACCENT, AMBER][i]
    ax3.plot(range(len(grp)), grp.values, '-o', color=color, lw=2, label=f'H={h}d', markersize=8)
ax3.set_xticks(range(5)); ax3.set_xticklabels(['Q1','Q2','Q3','Q4','Q5'])
ax3.legend(fontsize=9, facecolor='#1a1a1a', edgecolor='#333', labelcolor='white')

# ── Panel 4: Reverse bucketing — VRP distribution by forward return quintile ──
ax4 = fig.add_subplot(gs[1, 3:])
style_axes(ax4, title='REVERSE: VRP_ewma distribution by forward return quintile  (POOLED, H=21d)',
          ylabel='VRP_ewma_21d', xlabel='Forward return quintile')
pool_clean = pool.dropna(subset=['vrp_wedge_ewma_21d','fwd_ret_21d']).copy()
pool_clean['fwd_ret_q'] = pd.qcut(pool_clean['fwd_ret_21d'], q=5,
                                  labels=['Q1\nworst','Q2','Q3','Q4','Q5\nbest'])

# Box plot — easier visual on distributions
data = [pool_clean[pool_clean['fwd_ret_q']==q]['vrp_wedge_ewma_21d'].values
        for q in ['Q1\nworst','Q2','Q3','Q4','Q5\nbest']]
bp = ax4.boxplot(data, patch_artist=True, widths=0.55,
                 boxprops=dict(facecolor=PURPLE, alpha=0.7, edgecolor='white'),
                 medianprops=dict(color='white', lw=2),
                 whiskerprops=dict(color=DIM),
                 capprops=dict(color=DIM),
                 flierprops=dict(marker='.', markersize=2, markerfacecolor=DIM, markeredgecolor='none'))
ax4.set_xticklabels(['Q1\nworst','Q2','Q3','Q4','Q5\nbest'])
ax4.axhline(pool_clean['vrp_wedge_ewma_21d'].median(), color=AMBER, lw=1, linestyle='--',
           alpha=0.7, label='Pooled median')
ax4.legend(fontsize=8, facecolor='#1a1a1a', edgecolor='#333', labelcolor='white')

# Annotate means
for i, q in enumerate(['Q1\nworst','Q2','Q3','Q4','Q5\nbest']):
    m = pool_clean[pool_clean['fwd_ret_q']==q]['vrp_wedge_ewma_21d'].mean()
    ax4.text(i+1, m, f'  μ={m:.3f}', ha='left', va='center', color=WHITE,
            fontsize=8, fontweight='bold')

# ── Panel 5: Per-ticker reverse bucketing  (mean VRP per return quintile) ────
ax5 = fig.add_subplot(gs[2, :3])
style_axes(ax5, title='Per-ticker: Mean VRP_ewma by forward return quintile (H=21d)',
          ylabel='Mean VRP_ewma', xlabel='Forward return quintile')
for t, df in dfs.items():
    df_c = df.dropna(subset=['vrp_wedge_ewma_21d','fwd_ret_21d']).copy()
    df_c['fwd_ret_q'] = pd.qcut(df_c['fwd_ret_21d'], q=5, labels=['Q1','Q2','Q3','Q4','Q5'])
    means = df_c.groupby('fwd_ret_q', observed=True)['vrp_wedge_ewma_21d'].mean()
    ax5.plot(range(5), means.values, '-o', color=TICKER_COLOR[t], lw=1.8,
            label=f'{t} ({SECTORS[t]})', markersize=6)
ax5.set_xticks(range(5)); ax5.set_xticklabels(['Q1\nworst','Q2','Q3','Q4','Q5\nbest'])
ax5.legend(fontsize=8, facecolor='#1a1a1a', edgecolor='#333', labelcolor='white', ncol=2)

# ── Panel 6: Information Coefficient time series ─────────────────────────────
ax6 = fig.add_subplot(gs[2, 3:])
style_axes(ax6, title='Rolling 252d Spearman IC: VRP_ewma -> fwd_rv_21d (per ticker)',
          ylabel='Rolling Spearman r', xlabel='Date')

for t, df in dfs.items():
    sub = df[['date','vrp_wedge_ewma_21d','fwd_rv_21d']].dropna().reset_index(drop=True)
    if len(sub) < 252: continue
    rolling_r = []
    dates = []
    for i in range(252, len(sub)):
        window = sub.iloc[i-252:i]
        r, _ = stats.spearmanr(window['vrp_wedge_ewma_21d'], window['fwd_rv_21d'])
        rolling_r.append(r); dates.append(sub['date'].iloc[i])
    ax6.plot(dates, rolling_r, color=TICKER_COLOR[t], lw=1.2, alpha=0.85,
            label=t)
ax6.axhline(0, color='white', lw=0.8, alpha=0.6)
ax6.axhline(0.1, color=DIM, lw=0.5, linestyle=':', alpha=0.5)
ax6.legend(fontsize=8, facecolor='#1a1a1a', edgecolor='#333', labelcolor='white', ncol=3)

fig.suptitle('VRP_ewma Predictability — Cross-Ticker Validation + Reverse Bucketing',
             color=WHITE, fontsize=13, fontweight='bold', y=0.995)

plt.savefig(OUT, dpi=130, bbox_inches='tight', facecolor=BG)
plt.close()
print(f'Saved: {OUT}')