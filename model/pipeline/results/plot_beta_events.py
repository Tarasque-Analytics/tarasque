import pandas as pd, numpy as np, os
from scipy import stats
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.dates import YearLocator, DateFormatter
from matplotlib.lines import Line2D
import warnings
warnings.filterwarnings('ignore')

results_dir = Path('model/pipeline/results')
base = Path('D:/Tarasque_DB')

complete = [
    'AAPL','ABBV','ABT','AMZN','APD','AVGO','AXP','BA','BAC','BMY','C','CAT',
    'CMCSA','COP','COST','CVX','DE','DIS','EOG','FCX','FDX','GE','GILD',
    'GS','HD','HON','IBM','INTC','JNJ','JPM','KO','LIN','LLY','LMT','MCD',
    'MMM','MRK','MS','MSFT','NEE','NEM','NFLX','NKE','NVDA','OXY','PEP','PFE',
    'PG','PLD','PM','QCOM','SBUX','SCHW','SLB','T','TSLA','TXN','UNH',
    'WFC','WMT','XOM'
]

sectors = {
    'AAPL':'Tech','MSFT':'Tech','NVDA':'Tech','AVGO':'Tech','TXN':'Tech',
    'INTC':'Tech','QCOM':'Tech','IBM':'Tech',
    'AMZN':'Consumer Disc','HD':'Consumer Disc','NKE':'Consumer Disc','TSLA':'Consumer Disc',
    'DIS':'Comm','NFLX':'Comm','CMCSA':'Comm','T':'Comm',
    'JPM':'Financials','GS':'Financials','MS':'Financials','BAC':'Financials',
    'WFC':'Financials','C':'Financials','SCHW':'Financials','AXP':'Financials',
    'XOM':'Energy','CVX':'Energy','COP':'Energy','EOG':'Energy','SLB':'Energy','OXY':'Energy',
    'JNJ':'Health Care','UNH':'Health Care','LLY':'Health Care','MRK':'Health Care',
    'ABT':'Health Care','GILD':'Health Care','BMY':'Health Care','PFE':'Health Care','ABBV':'Health Care',
    'PG':'Staples','KO':'Staples','PEP':'Staples','WMT':'Staples','COST':'Staples',
    'PM':'Staples','MCD':'Staples','SBUX':'Staples',
    'NEE':'Utilities','T':'Utilities',
    'CAT':'Industrials','HON':'Industrials','GE':'Industrials','LMT':'Industrials',
    'DE':'Industrials','MMM':'Industrials','FDX':'Industrials','BA':'Industrials',
    'NEM':'Materials','FCX':'Materials','APD':'Materials','LIN':'Materials',
    'PLD':'REIT',
}

sector_colors = {
    'Tech':'#4C72B0','Financials':'#55A868','Energy':'#C44E52','Industrials':'#8172B2',
    'Health Care':'#CCB974','Staples':'#64B5CD','Comm':'#FF8C00','Consumer Disc':'#E377C2',
    'Materials':'#7F7F7F','Utilities':'#BCBD22','REIT':'#17BECF','Other':'#999999'
}

# ── Load SPY returns for event detection ────────────────────────────────────
print('Loading SPY for event detection...')
spy = pd.read_parquet(base / 'ohlcv/ticker=SPY')
spy['date'] = pd.to_datetime(spy['date'])
spy = spy.sort_values('date').set_index('date')
spy['ret'] = spy['prc'].pct_change()
spy_ret = spy['ret'].dropna()

# 3-sigma threshold (rolling 252d)
roll_std = spy_ret.rolling(252).std()
roll_mean = spy_ret.rolling(252).mean()
z = (spy_ret - roll_mean) / roll_std
shock_days = spy_ret[z.abs() >= 3].index  # 3-sigma market days

# Named events to annotate
named_events = {
    '2011-08-08': 'US Downgrade',
    '2015-08-24': 'China Flash',
    '2018-02-05': 'Volmageddon',
    '2018-12-24': 'Dec Selloff',
    '2020-02-24': 'COVID Crash',
    '2020-03-16': 'COVID Bottom',
    '2020-11-09': 'Vaccine Day',
    '2022-01-24': 'Fed Pivot',
    '2022-06-13': 'CPI Shock',
    '2023-03-10': 'SVB Failure',
    '2024-08-05': 'Yen Unwind',
}

# ── Rolling beta ─────────────────────────────────────────────────────────────
def rolling_beta(df, window=252):
    dates, betas = [], []
    df = df.dropna(subset=['y_true','y_pred']).sort_values('date')
    df['date'] = pd.to_datetime(df['date'])
    for i in range(window, len(df)):
        chunk = df.iloc[i-window:i]
        if len(chunk) < 100:
            continue
        sl, ic, r, p, se = stats.linregress(chunk.y_pred, chunk.y_true)
        dates.append(df.iloc[i]['date'])
        betas.append(sl)
    return pd.Series(betas, index=dates)

print('Computing rolling betas...')
all_betas = {}
for t in complete:
    try:
        df = pd.read_csv(results_dir / f'predictions_{t}_H21.csv')
        rb = rolling_beta(df)
        if len(rb) > 50:
            all_betas[t] = rb
    except Exception:
        pass
print(f'  Done: {len(all_betas)} tickers')

# ── Sector medians ───────────────────────────────────────────────────────────
sect_betas = {}
for t, rb in all_betas.items():
    s = sectors.get(t, 'Other')
    sect_betas.setdefault(s, []).append(rb)

sect_median = {}
for s, series_list in sect_betas.items():
    sect_median[s] = pd.concat(series_list, axis=1).median(axis=1).rolling(42, min_periods=10).mean()

# ── Exponentially-weighted beta ──────────────────────────────────────────────
# Uses all backtest data but weights recent observations more heavily
# lambda=0.003/day => half-life ~230 days (~1 year)
def exp_weighted_beta(df, lam=0.003):
    df = df.dropna(subset=['y_true','y_pred']).sort_values('date').reset_index(drop=True)
    n = len(df)
    if n < 100:
        return np.nan, np.nan, np.nan
    w = np.exp(lam * np.arange(n))
    w = w / w.mean()
    x = df.y_pred.values
    y = df.y_true.values
    xw = np.sqrt(w) * x
    yw = np.sqrt(w) * y
    sl, ic, r, p, se = stats.linregress(xw, yw)
    resid = y - (ic + sl * x)
    ss_res = np.sum(w * resid**2)
    ss_tot = np.sum(w * (y - np.average(y, weights=w))**2)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else np.nan
    return round(sl, 4), round(ic, 4), round(r2, 4)

print('Computing exp-weighted betas...')
ew_rows = []
for t in complete:
    row = {'ticker': t, 'sector': sectors.get(t, 'Other')}
    for h in [21, 63, 126]:
        try:
            df = pd.read_csv(results_dir / f'predictions_{t}_H{h}.csv')
            b, a, r2 = exp_weighted_beta(df, lam=0.003)
            row[f'H{h}_beta'] = b
            row[f'H{h}_alpha'] = a
            row[f'H{h}_R2'] = r2
        except Exception:
            row[f'H{h}_beta'] = np.nan
            row[f'H{h}_alpha'] = np.nan
            row[f'H{h}_R2'] = np.nan
    ew_rows.append(row)

ew_df = pd.DataFrame(ew_rows)

# ── FIGURE ───────────────────────────────────────────────────────────────────
fig = plt.figure(figsize=(22, 20))
fig.patch.set_facecolor('#0f0f0f')
gs = gridspec.GridSpec(2, 1, figure=fig, hspace=0.38, height_ratios=[1.4, 1.0])

# ── PANEL 1: Sector medians + event overlay ──────────────────────────────────
ax1 = fig.add_subplot(gs[0])
ax1.set_facecolor('#1a1a1a')

for s, series in sorted(sect_median.items()):
    col = sector_colors.get(s, '#999')
    ax1.plot(series.index, series.values, color=col, lw=2.2, label=s, alpha=0.9)

ax1.axhline(1.0, color='white', lw=1.5, linestyle='--', alpha=0.7)
ax1.axhline(0.85, color='#aaaaaa', lw=0.7, linestyle=':', alpha=0.45)
ax1.axhline(1.15, color='#aaaaaa', lw=0.7, linestyle=':', alpha=0.45)

# Shade 3-sigma days (vertical lines, clustered by month to avoid overplotting)
shock_months = pd.DatetimeIndex(shock_days).to_period('M').unique()
for m in shock_months:
    ms = m.to_timestamp()
    me = (m + 1).to_timestamp()
    ax1.axvspan(ms, me, color='#ff2222', alpha=0.12, lw=0)

# Named event annotations — alternate top/bottom to avoid overlap
y_positions = [2.05, 1.92, 2.05, 1.92, 2.05, 1.92, 2.05, 1.92, 2.05, 1.92, 2.05]
for i, (date_str, label) in enumerate(named_events.items()):
    dt = pd.Timestamp(date_str)
    yp = y_positions[i % len(y_positions)]
    ax1.axvline(dt, color='#ffcc00', lw=0.9, linestyle='--', alpha=0.6)
    ax1.text(dt, yp, label, color='#ffcc00', fontsize=6.5, rotation=70,
             ha='left', va='bottom', alpha=0.9)

ax1.set_ylim(0.1, 2.3)
ax1.legend(loc='upper left', fontsize=8.5, ncol=4, facecolor='#2a2a2a',
           edgecolor='#555', labelcolor='white', framealpha=0.85)

from matplotlib.patches import Patch
ax1.legend(
    [Line2D([0],[0], color=sector_colors.get(s,'#999'), lw=2.5) for s in sorted(sect_median.keys())] +
    [Patch(fc='#ff2222', alpha=0.35), Line2D([0],[0], color='#ffcc00', lw=1.2, linestyle='--')],
    list(sorted(sect_median.keys())) + ['3-sigma SPY day', 'Named event'],
    loc='upper left', fontsize=8, ncol=4, facecolor='#2a2a2a',
    edgecolor='#555', labelcolor='white', framealpha=0.88
)

ax1.set_title('Sector-Median Rolling MZ Beta (H=21)  |  Red = 3-sigma SPY days  |  Yellow = named events',
              color='white', fontsize=12, pad=8)
ax1.set_ylabel('MZ Beta', color='#cccccc')
ax1.tick_params(colors='#aaaaaa')
for sp in ax1.spines.values():
    sp.set_color('#444')
ax1.grid(axis='y', color='#333', lw=0.5)
ax1.xaxis.set_major_locator(YearLocator())
ax1.xaxis.set_major_formatter(DateFormatter('%Y'))

# ── PANEL 2: Exp-weighted beta printout as grouped bar ───────────────────────
ax2 = fig.add_subplot(gs[1])
ax2.set_facecolor('#1a1a1a')

ew_plot = ew_df.dropna(subset=['H21_beta']).sort_values('H21_beta').reset_index(drop=True)
x = np.arange(len(ew_plot))
w = 0.28

def bc(b):
    if pd.isna(b): return '#555'
    return '#22c55e' if abs(b - 1.0) <= 0.15 else '#ef4444'

ax2.bar(x - w, ew_plot['H21_beta'],  w, color=[bc(b) for b in ew_plot['H21_beta']],  alpha=0.9)
ax2.bar(x,     ew_plot['H63_beta'],  w, color=[bc(b) for b in ew_plot['H63_beta']],  alpha=0.9)
ax2.bar(x + w, ew_plot['H126_beta'], w, color=[bc(b) for b in ew_plot['H126_beta']], alpha=0.9)

ax2.axhline(1.0, color='white', lw=1.5, linestyle='--', alpha=0.8)
ax2.axhline(0.85, color='#aaaaaa', lw=0.8, linestyle=':', alpha=0.5)
ax2.axhline(1.15, color='#aaaaaa', lw=0.8, linestyle=':', alpha=0.5)
ax2.set_xticks(x)
ax2.set_xticklabels(ew_plot['ticker'], rotation=55, ha='right', fontsize=7.5, color='#cccccc')
ax2.set_ylim(-0.3, 2.3)
ax2.set_title('Exp-Weighted MZ Beta (half-life ~1yr)  |  Green = calibrated  |  Red = miscalibrated  |  Left=H21, Mid=H63, Right=H126',
              color='white', fontsize=11, pad=8)
ax2.set_ylabel('Exp-Wtd MZ Beta', color='#cccccc')
ax2.tick_params(colors='#aaaaaa')
for sp in ax2.spines.values():
    sp.set_color('#444')
ax2.grid(axis='y', color='#333', lw=0.5, alpha=0.6)
ax2.legend(
    [plt.Rectangle((0,0),1,1,fc='#6366f1'), plt.Rectangle((0,0),1,1,fc='#8b5cf6'),
     plt.Rectangle((0,0),1,1,fc='#a855f7'),
     Line2D([0],[0],color='#22c55e',lw=3), Line2D([0],[0],color='#ef4444',lw=3)],
    ['H=21','H=63','H=126','Calibrated','Miscalibrated'],
    loc='upper left', fontsize=8, facecolor='#2a2a2a', edgecolor='#555', labelcolor='white'
)

fig.suptitle('Tarasque v4  —  Sector Beta vs Events  +  Regime-Weighted Beta', color='white',
             fontsize=15, fontweight='bold', y=0.998)

outpath = 'model/pipeline/results/beta_events.png'
plt.savefig(outpath, dpi=150, bbox_inches='tight', facecolor='#0f0f0f')
print(f'Saved: {outpath}')

# ── PRINT exp-weighted beta table ────────────────────────────────────────────
print()
print('=' * 85)
print('EXP-WEIGHTED BETA (half-life ~1yr, recent regime dominant)')
print('=' * 85)
print(f'{"Ticker":<7}{"Sector":<16} {"H21_b":>7} {"H21_R2":>7} {"H63_b":>7} {"H63_R2":>7} {"H126_b":>8} {"H126_R2":>8}')
print('-' * 85)
for _, r in ew_df.sort_values(['sector','ticker']).iterrows():
    print(f'{r.ticker:<7}{r.sector:<16} '
          f'{r.H21_beta:>7.3f} {r.H21_R2:>7.3f} '
          f'{r.H63_beta:>7.3f} {r.H63_R2:>7.3f} '
          f'{r.H126_beta:>8.3f} {r.H126_R2:>8.3f}')

print()
print('PORTFOLIO SUMMARY (exp-weighted):')
for h in ['H21','H63','H126']:
    col = f'{h}_beta'
    sub = ew_df[col].dropna()
    well = ((sub >= 0.85) & (sub <= 1.15)).sum()
    print(f'  {h}: mean={sub.mean():.3f}  median={sub.median():.3f}  std={sub.std():.3f}  '
          f'well-cal={well}/{len(sub)} ({well/len(sub)*100:.0f}%)')
