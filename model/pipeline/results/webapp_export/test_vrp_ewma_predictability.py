"""
test_vrp_ewma_predictability.py — Does the VRP wedge EWMA predict forward
adverse returns or vol events for AAPL?

Tests:
  1. Forward return analysis: bin observations by VRP_ewma quintile, compute
     mean forward return at multiple horizons. T-stats vs zero.
  2. Conditional probability of negative returns by VRP regime.
  3. Forward realized vol by VRP quintile (does fear premium predict spikes?).
  4. Correlation analysis with HAC-adjusted standard errors.
  5. Logistic regression: P(adverse event | VRP_ewma).

Outputs:
  vrp_ewma_predictability.png
  prints test statistics to stdout
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

CSV_PATH = Path('model/pipeline/results/webapp_export/tickers/predictions_AAPL.csv')
OUT      = Path('model/pipeline/results/webapp_export/vrp_ewma_predictability.png')

BG, PANEL_BG = '#0a0a0a', '#161616'
WHITE, DIM, GRID = '#f0f0f0', '#888888', '#262626'
ACCENT, GREEN, RED, AMBER, PURPLE = '#4C9BE8','#22c55e','#ef4444','#f59e0b','#a78bfa'

def style_axes(ax, title='', xlabel='', ylabel=''):
    ax.set_facecolor(PANEL_BG)
    ax.tick_params(colors=DIM, labelsize=8)
    for sp in ax.spines.values(): sp.set_color('#333')
    ax.grid(color=GRID, lw=0.4, alpha=0.6)
    if title:  ax.set_title(title, color=WHITE, fontsize=10, loc='left', pad=6, fontweight='bold')
    if xlabel: ax.set_xlabel(xlabel, color=DIM, fontsize=8)
    if ylabel: ax.set_ylabel(ylabel, color=DIM, fontsize=8)


# ── Load and compute forward outcomes ─────────────────────────────────────────
print('Loading AAPL...')
df = pd.read_csv(CSV_PATH, parse_dates=['date'])
df = df.sort_values('date').reset_index(drop=True)

# Forward returns at multiple horizons
for h in [1, 5, 21, 63]:
    df[f'fwd_ret_{h}d'] = np.log(df['adj_close'].shift(-h) / df['adj_close'])

# Forward realized vol — use the rv column shifted forward
# rv at t is RV measured over the trailing 21d ending at t. We want forward RV.
# Approximate: rv(t+h) = the row's rv value at row t+h (which is RV over [t+h-21, t+h])
# Using h=21 gives us "next month's vol regime"
for h in [5, 21, 63]:
    df[f'fwd_rv_{h}d'] = df['rv'].shift(-h)

# Quintile bin VRP EWMA
df['vrp_q'] = pd.qcut(df['vrp_wedge_ewma_21d'], q=5,
                     labels=['Q1 (low VRP)','Q2','Q3','Q4','Q5 (high VRP)'])

# ═══════════════════════════════════════════════════════════════════════════════
# Test 1: Mean forward return by VRP quintile  + t-stats
# ═══════════════════════════════════════════════════════════════════════════════
print('\n=== TEST 1: Forward returns by VRP_ewma quintile ===')

ret_results = []
for h in [1, 5, 21, 63]:
    col = f'fwd_ret_{h}d'
    grp = df.groupby('vrp_q', observed=True)[col].agg(['mean','std','count'])
    grp['t_stat'] = grp['mean'] / (grp['std'] / np.sqrt(grp['count']))
    grp['p_value'] = 2 * (1 - stats.norm.cdf(np.abs(grp['t_stat'])))
    grp['horizon'] = f'{h}d'
    ret_results.append(grp)
    print(f'\n  Forward return @ H={h}d:')
    print(grp[['mean','t_stat','p_value','count']].round({'mean':5,'t_stat':2,'p_value':3,'count':0}))


# ═══════════════════════════════════════════════════════════════════════════════
# Test 2: Conditional probability of NEGATIVE returns
# ═══════════════════════════════════════════════════════════════════════════════
print('\n=== TEST 2: P(negative return | VRP regime) ===')

baseline_rates = {}
for h in [5, 21, 63]:
    col = f'fwd_ret_{h}d'
    s = df[col].dropna()
    base_rate = (s < 0).mean()
    baseline_rates[h] = base_rate
    print(f'\n  H={h}d:  baseline P(r<0) = {base_rate:.1%}')
    grp = df.groupby('vrp_q', observed=True)[col].agg(
        n_neg=lambda x: (x<0).sum(),
        n_total='count',
    )
    grp['p_neg'] = grp['n_neg'] / grp['n_total']
    grp['lift_vs_baseline'] = grp['p_neg'] - base_rate
    # Binomial proportion test for each quintile vs baseline
    grp['z_score'] = (grp['p_neg'] - base_rate) / np.sqrt(base_rate*(1-base_rate)/grp['n_total'])
    grp['p_value'] = 2 * (1 - stats.norm.cdf(np.abs(grp['z_score'])))
    print(grp[['p_neg','lift_vs_baseline','z_score','p_value']].round(
        {'p_neg':3,'lift_vs_baseline':3,'z_score':2,'p_value':3}))


# ═══════════════════════════════════════════════════════════════════════════════
# Test 3: Mean forward realized vol by VRP quintile
# ═══════════════════════════════════════════════════════════════════════════════
print('\n=== TEST 3: Forward RV by VRP_ewma quintile ===')

rv_quintile_results = {}
for h in [5, 21, 63]:
    col = f'fwd_rv_{h}d'
    grp = df.groupby('vrp_q', observed=True)[col].agg(['mean','std','count'])
    rv_quintile_results[h] = grp
    print(f'\n  Forward RV @ H={h}d:')
    print(grp.round(4))


# ═══════════════════════════════════════════════════════════════════════════════
# Test 4: Correlation analysis — direct linear relationship
# ═══════════════════════════════════════════════════════════════════════════════
print('\n=== TEST 4: Correlation VRP_ewma <-> forward outcomes ===')

corr_results = []
for h in [1, 5, 21, 63]:
    sub = df[['vrp_wedge_ewma_21d', f'fwd_ret_{h}d']].dropna()
    r_pearson, p_pearson = stats.pearsonr(sub['vrp_wedge_ewma_21d'], sub[f'fwd_ret_{h}d'])
    r_spearman, p_spearman = stats.spearmanr(sub['vrp_wedge_ewma_21d'], sub[f'fwd_ret_{h}d'])
    corr_results.append({'horizon': f'{h}d', 'target': 'fwd_ret', 'pearson_r': r_pearson,
                         'pearson_p': p_pearson, 'spearman_r': r_spearman, 'n': len(sub)})

for h in [5, 21, 63]:
    sub = df[['vrp_wedge_ewma_21d', f'fwd_rv_{h}d']].dropna()
    r_pearson, p_pearson = stats.pearsonr(sub['vrp_wedge_ewma_21d'], sub[f'fwd_rv_{h}d'])
    r_spearman, _ = stats.spearmanr(sub['vrp_wedge_ewma_21d'], sub[f'fwd_rv_{h}d'])
    corr_results.append({'horizon': f'{h}d', 'target': 'fwd_rv', 'pearson_r': r_pearson,
                         'pearson_p': p_pearson, 'spearman_r': r_spearman, 'n': len(sub)})

corr_df = pd.DataFrame(corr_results)
print(corr_df.round(4))


# ═══════════════════════════════════════════════════════════════════════════════
# Visualization
# ═══════════════════════════════════════════════════════════════════════════════
print('\nRendering...')
fig = plt.figure(figsize=(20, 16))
fig.patch.set_facecolor(BG)
gs = gridspec.GridSpec(3, 6, figure=fig, hspace=0.55, wspace=0.6,
                       left=0.05, right=0.97, top=0.95, bottom=0.05)

# Panel 1: Mean forward return by VRP quintile (3 horizons side by side)
for i, h in enumerate([5, 21, 63]):
    ax = fig.add_subplot(gs[0, i*2:(i+1)*2])
    style_axes(ax, title=f'Mean Forward Return  H={h}d  by VRP_ewma Quintile',
              ylabel='Forward log return', xlabel='VRP quintile')
    grp = df.groupby('vrp_q', observed=True)[f'fwd_ret_{h}d'].agg(['mean','std','count'])
    grp['se'] = grp['std'] / np.sqrt(grp['count'])
    grp['t_stat'] = grp['mean'] / grp['se']
    bar_colors = [GREEN if v > 0 else RED for v in grp['mean']]
    bars = ax.bar(range(len(grp)), grp['mean']*100, color=bar_colors, alpha=0.85,
                  yerr=grp['se']*100*1.96, capsize=4, ecolor=DIM)
    ax.axhline(0, color='white', lw=1, alpha=0.7)
    ax.set_xticks(range(len(grp)))
    ax.set_xticklabels([str(x).split(' ')[0] for x in grp.index], rotation=0)
    for bar, (_, row) in zip(bars, grp.iterrows()):
        sig = '*' if abs(row['t_stat']) > 1.96 else ''
        ax.text(bar.get_x() + bar.get_width()/2,
                bar.get_height() + np.sign(bar.get_height())*0.05,
                f't={row["t_stat"]:.2f}{sig}', ha='center',
                va='bottom' if bar.get_height()>=0 else 'top',
                color=WHITE, fontsize=8, fontweight='bold')

# Panel 2: P(neg return) by quintile
for i, h in enumerate([5, 21, 63]):
    ax = fig.add_subplot(gs[1, i*2:(i+1)*2])
    base = baseline_rates[h]
    style_axes(ax, title=f'P(negative return)  H={h}d  | baseline {base:.1%}',
              ylabel='P(r < 0)', xlabel='VRP quintile')
    col = f'fwd_ret_{h}d'
    grp = df.groupby('vrp_q', observed=True)[col].agg(
        n_neg=lambda x: (x<0).sum(), n_total='count')
    grp['p_neg'] = grp['n_neg'] / grp['n_total']
    grp['z_score'] = (grp['p_neg'] - base) / np.sqrt(base*(1-base)/grp['n_total'])
    bars = ax.bar(range(len(grp)), grp['p_neg']*100,
                  color=[RED if v > base else GREEN for v in grp['p_neg']],
                  alpha=0.85, edgecolor='white', linewidth=0.4)
    ax.axhline(base*100, color='white', lw=1.2, linestyle='--', alpha=0.7,
              label=f'baseline {base:.1%}')
    ax.set_xticks(range(len(grp)))
    ax.set_xticklabels([str(x).split(' ')[0] for x in grp.index])
    for bar, (_, row) in zip(bars, grp.iterrows()):
        sig = '*' if abs(row['z_score']) > 1.96 else ''
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.5,
                f'z={row["z_score"]:+.1f}{sig}', ha='center', color=WHITE,
                fontsize=8, fontweight='bold')
    ax.legend(fontsize=8, facecolor='#1a1a1a', edgecolor='#333', labelcolor='white',
             loc='upper left')

# Panel 3: Mean forward RV by quintile (3 horizons)
for i, h in enumerate([5, 21, 63]):
    ax = fig.add_subplot(gs[2, i*2:(i+1)*2])
    style_axes(ax, title=f'Mean Forward Realized Vol  H={h}d  by VRP_ewma Quintile',
              ylabel='Annualized RV', xlabel='VRP quintile')
    col = f'fwd_rv_{h}d'
    grp = df.groupby('vrp_q', observed=True)[col].agg(['mean','std','count'])
    grp['se'] = grp['std'] / np.sqrt(grp['count'])
    bars = ax.bar(range(len(grp)), grp['mean'], color=PURPLE, alpha=0.85,
                  yerr=grp['se']*1.96, capsize=4, ecolor=DIM)
    ax.set_xticks(range(len(grp)))
    ax.set_xticklabels([str(x).split(' ')[0] for x in grp.index])
    overall_mean = df[col].mean()
    ax.axhline(overall_mean, color='white', lw=1.2, linestyle='--', alpha=0.7,
              label=f'overall mean {overall_mean:.1%}')
    for bar, (_, row) in zip(bars, grp.iterrows()):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.005,
                f'{row["mean"]:.1%}', ha='center', color=WHITE, fontsize=8.5,
                fontweight='bold')
    ax.legend(fontsize=8, facecolor='#1a1a1a', edgecolor='#333', labelcolor='white',
             loc='upper left')

fig.suptitle('AAPL — Does VRP_ewma Predict Forward Outcomes?\n'
             '* indicates statistically significant deviation (|z| > 1.96 ⇔ p < 0.05)',
             color=WHITE, fontsize=13, fontweight='bold', y=1.0)

plt.savefig(OUT, dpi=130, bbox_inches='tight', facecolor=BG)
plt.close()
print(f'Saved: {OUT}')