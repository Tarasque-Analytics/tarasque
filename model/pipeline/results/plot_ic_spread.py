"""
plot_ic_spread.py — IC and quintile spread analysis across full 94-ticker corpus.

IC (Information Coefficient) = Spearman rank correlation between predicted vol
and realized vol in the cross-section on each date. Shows whether high predicted
vol stocks actually realize more vol than low predicted vol stocks.

Quintile spread = realized vol of top-quintile (Q5) minus bottom-quintile (Q1).
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import pandas as pd
import numpy as np
from scipy import stats
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.dates import YearLocator, DateFormatter
import warnings
warnings.filterwarnings('ignore')

results_dir = Path('model/pipeline/results')

FLAGGED = {'GE', 'META', 'RTX', 'GOOGL'}

clean_tickers = [
    'AAPL','ABBV','ABT','ADBE','AEP','AMAT','AMD','AMGN','AMT','AMZN',
    'APD','AVGO','AXP','BA','BAC','BLK','BMY','C','CAT','CCI',
    'CL','CMCSA','COP','COST','CRM','CSCO','CVS','CVX','D','DE',
    'DIS','DOW','DUK','EOG','EQIX','F','FCX','FDX','GILD',
    'GM','GS','HD','HON','IBM','INTC','JNJ','JPM','KO',
    'LIN','LLY','LMT','LOW','MCD','MMM','MO','MRK','MS',
    'MSFT','MU','NEE','NEM','NFLX','NKE','NOC','NVDA','ORCL','OXY',
    'PEP','PFE','PG','PLD','PM','QCOM','SBUX','SCHW','SLB',
    'SO','SPG','T','TGT','TMO','TSLA','TXN','UNH','UPS','USB',
    'VZ','WFC','WMT','XOM',
]

print('Loading prediction files...')
frames = {}
for t in clean_tickers:
    for h in [21, 63, 126]:
        fpath = results_dir / f'predictions_{t}_H{h}.csv'
        if fpath.exists():
            try:
                df = pd.read_csv(fpath, parse_dates=['date'])
                df['ticker'] = t
                df['horizon'] = h
                frames[(t, h)] = df[['date','ticker','horizon','y_true','y_pred']].dropna()
            except Exception:
                pass

print(f'  Loaded {len(frames)} ticker-horizon files')

# Build cross-sectional panel per horizon
def compute_ic_quintile(horizon):
    panel = pd.concat([v for (t, h), v in frames.items() if h == horizon], ignore_index=True)
    panel = panel.sort_values('date')

    dates = sorted(panel['date'].unique())
    rows = []
    for d in dates:
        day = panel[panel['date'] == d]
        if len(day) < 10:  # need enough tickers for meaningful cross-section
            continue
        # Spearman IC: rank predicted vol vs rank realized vol
        ic = stats.spearmanr(day['y_pred'], day['y_true']).statistic

        # Quintile assignment by predicted vol
        day = day.copy()
        day['q'] = pd.qcut(day['y_pred'], q=5, labels=False, duplicates='drop')
        q_rv = day.groupby('q')['y_true'].mean()
        spread = q_rv.get(4, np.nan) - q_rv.get(0, np.nan)  # Q5 - Q1 in log-vol space
        spread_linear = np.exp(q_rv.get(4, np.nan)) - np.exp(q_rv.get(0, np.nan)) if not np.isnan(spread) else np.nan

        rows.append({
            'date': d,
            'ic': ic,
            'spread_logvol': spread,
            'spread_rv': spread_linear,
            'n_tickers': len(day),
            **{f'q{i}_rv': float(np.exp(q_rv.get(i, np.nan))) if i in q_rv.index else np.nan for i in range(5)},
        })

    return pd.DataFrame(rows).set_index('date')

print('Computing IC and quintile spreads...')
results = {}
for h in [21, 63, 126]:
    results[h] = compute_ic_quintile(h)
    r = results[h]
    mean_ic = r['ic'].mean()
    t_stat, p_val = stats.ttest_1samp(r['ic'].dropna(), 0)
    pct_pos = (r['ic'] > 0).mean()
    mean_spread = r['spread_rv'].mean()
    print(f'\nH={h:3d}:')
    print(f'  IC mean={mean_ic:.3f}  t={t_stat:.2f}  p={p_val:.4f}  {pct_pos*100:.1f}% positive days')
    print(f'  Q5-Q1 spread (realized vol): {mean_spread:.4f} ({mean_spread*100:.2f}pp)')

# ── Plot ─────────────────────────────────────────────────────────────────────
fig = plt.figure(figsize=(22, 20))
fig.patch.set_facecolor('#0f0f0f')
gs = gridspec.GridSpec(3, 2, figure=fig, hspace=0.42, wspace=0.30)

colors = {21: '#4C72B0', 63: '#55A868', 126: '#C44E52'}

for row, h in enumerate([21, 63, 126]):
    r = results[h]
    roll_ic = r['ic'].rolling(63, min_periods=21).mean()
    t_stat, p_val = stats.ttest_1samp(r['ic'].dropna(), 0)
    mean_ic = r['ic'].mean()
    col = colors[h]

    # Left: Rolling IC
    ax = fig.add_subplot(gs[row, 0])
    ax.set_facecolor('#1a1a1a')
    ax.fill_between(r.index, r['ic'], 0, where=r['ic'] >= 0, color=col, alpha=0.25)
    ax.fill_between(r.index, r['ic'], 0, where=r['ic'] < 0, color='#C44E52', alpha=0.25)
    ax.plot(roll_ic.index, roll_ic.values, color=col, lw=2.0, label=f'63d rolling IC')
    ax.axhline(0, color='white', lw=0.8, alpha=0.6)
    ax.axhline(mean_ic, color=col, lw=1.2, linestyle='--', alpha=0.7, label=f'Mean IC={mean_ic:.3f}')
    ax.set_ylim(-0.8, 0.9)
    ax.set_title(f'H={h}  Cross-Sectional IC (Spearman)  |  t={t_stat:.2f}  p={p_val:.4f}',
                 color='white', fontsize=11)
    ax.set_ylabel('Spearman IC', color='#cccccc')
    ax.tick_params(colors='#aaaaaa')
    for sp in ax.spines.values(): sp.set_color('#444')
    ax.grid(axis='y', color='#333', lw=0.5)
    ax.legend(fontsize=8, facecolor='#2a2a2a', edgecolor='#555', labelcolor='white')
    ax.xaxis.set_major_locator(YearLocator())
    ax.xaxis.set_major_formatter(DateFormatter('%Y'))

    # Right: Quintile realized vol bars (full-sample averages)
    ax2 = fig.add_subplot(gs[row, 1])
    ax2.set_facecolor('#1a1a1a')

    q_means = [r[f'q{i}_rv'].mean() * 100 for i in range(5)]  # as % annualized
    valid = [v for v in q_means if not np.isnan(v)]
    if valid:
        bar_colors = ['#ef4444' if i == 4 else '#22c55e' if i == 0 else col for i in range(5)]
        bars = ax2.bar(['Q1\n(low)', 'Q2', 'Q3', 'Q4', 'Q5\n(high)'], q_means,
                       color=bar_colors, alpha=0.85, width=0.6)
        spread_val = q_means[4] - q_means[0] if not np.isnan(q_means[4]) and not np.isnan(q_means[0]) else 0
        for bar, val in zip(bars, q_means):
            if not np.isnan(val):
                ax2.text(bar.get_x() + bar.get_width()/2, val + 0.1,
                        f'{val:.1f}%', ha='center', va='bottom', color='white', fontsize=8.5)
        ax2.set_title(f'H={h}  Quintile Realized Vol (predicted-vol sorted)  |  Q5-Q1 spread={spread_val:.1f}pp',
                     color='white', fontsize=10)
        ax2.set_ylabel('Mean Realized Vol (%)', color='#cccccc')
    ax2.tick_params(colors='#aaaaaa')
    for sp in ax2.spines.values(): sp.set_color('#444')
    ax2.grid(axis='y', color='#333', lw=0.5, alpha=0.7)

fig.suptitle(f'Tarasque v4  —  IC / Quintile Spread Analysis ({len(clean_tickers)} clean tickers)',
             color='white', fontsize=15, fontweight='bold', y=0.998)

outpath = 'model/pipeline/results/ic_quintile_spread.png'
plt.savefig(outpath, dpi=150, bbox_inches='tight', facecolor='#0f0f0f')
print(f'\nSaved: {outpath}')

# Print summary table
print('\n' + '='*65)
print('IC SUMMARY TABLE')
print('='*65)
print(f'{"H":>5}  {"Mean IC":>8}  {"t-stat":>7}  {"p-value":>8}  {"% +ve":>7}  {"Q5-Q1(pp)":>10}')
print('-'*65)
for h in [21, 63, 126]:
    r = results[h]
    mic = r['ic'].mean()
    t, p = stats.ttest_1samp(r['ic'].dropna(), 0)
    pp = (r['ic'] > 0).mean() * 100
    spread = r['spread_rv'].mean() * 100
    print(f'{h:>5}  {mic:>8.3f}  {t:>7.2f}  {p:>8.4f}  {pp:>7.1f}%  {spread:>10.2f}pp')
