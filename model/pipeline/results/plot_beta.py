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

fig = plt.figure(figsize=(22, 28))
fig.patch.set_facecolor('#0f0f0f')
gs = gridspec.GridSpec(3, 1, figure=fig, hspace=0.40)

# ── PANEL 1: All tickers colored by sector ──────────────────────────────────
ax1 = fig.add_subplot(gs[0])
ax1.set_facecolor('#1a1a1a')

for t, rb in sorted(all_betas.items(), key=lambda x: sectors.get(x[0], 'Other')):
    sect = sectors.get(t, 'Other')
    col = sector_colors.get(sect, '#999999')
    smooth = rb.rolling(63, min_periods=21).mean()
    ax1.plot(smooth.index, smooth.values, color=col, alpha=0.55, lw=0.9)

ax1.axhline(1.0, color='white', lw=1.5, linestyle='--', alpha=0.7)
ax1.axhline(0.85, color='#aaaaaa', lw=0.8, linestyle=':', alpha=0.5)
ax1.axhline(1.15, color='#aaaaaa', lw=0.8, linestyle=':', alpha=0.5)
ax1.axvspan(pd.Timestamp('2020-02-01'), pd.Timestamp('2020-06-01'), color='red', alpha=0.08)
ax1.axvspan(pd.Timestamp('2022-01-01'), pd.Timestamp('2022-12-31'), color='orange', alpha=0.08)

legend_handles = [Line2D([0],[0], color=sector_colors.get(s,'#999'), lw=2.5, label=s)
                  for s in sorted(set(sectors.values()))]
legend_handles.append(Line2D([0],[0], color='white', lw=1.5, linestyle='--', label='beta=1.0'))
ax1.legend(handles=legend_handles, loc='upper left', fontsize=7.5, ncol=4,
           facecolor='#2a2a2a', edgecolor='#555', labelcolor='white', framealpha=0.85)
ax1.set_ylim(-0.3, 2.8)
ax1.set_title('Rolling 252-Day MZ Beta — All 61 Tickers by Sector (H=21)', color='white', fontsize=13, pad=8)
ax1.set_ylabel('MZ Beta', color='#cccccc')
ax1.tick_params(colors='#aaaaaa')
for sp in ax1.spines.values():
    sp.set_color('#444')
ax1.grid(axis='y', color='#333', lw=0.5)
ax1.xaxis.set_major_locator(YearLocator())
ax1.xaxis.set_major_formatter(DateFormatter('%Y'))

# ── PANEL 2: Sector-median rolling beta ──────────────────────────────────────
ax2 = fig.add_subplot(gs[1])
ax2.set_facecolor('#1a1a1a')

sect_betas = {}
for t, rb in all_betas.items():
    s = sectors.get(t, 'Other')
    sect_betas.setdefault(s, []).append(rb)

for s, series_list in sorted(sect_betas.items()):
    combined = pd.concat(series_list, axis=1).median(axis=1).rolling(63, min_periods=10).mean()
    col = sector_colors.get(s, '#999')
    ax2.plot(combined.index, combined.values, color=col, lw=2.2, label=s, alpha=0.9)

ax2.axhline(1.0, color='white', lw=1.5, linestyle='--', alpha=0.7)
ax2.axhline(0.85, color='#aaaaaa', lw=0.8, linestyle=':', alpha=0.4)
ax2.axhline(1.15, color='#aaaaaa', lw=0.8, linestyle=':', alpha=0.4)
ax2.axvspan(pd.Timestamp('2020-02-01'), pd.Timestamp('2020-06-01'), color='red', alpha=0.08)
ax2.axvspan(pd.Timestamp('2022-01-01'), pd.Timestamp('2022-12-31'), color='orange', alpha=0.08)
ax2.legend(loc='upper left', fontsize=8.5, ncol=4, facecolor='#2a2a2a',
           edgecolor='#555', labelcolor='white', framealpha=0.85)
ax2.set_ylim(0.0, 2.2)
ax2.set_title('Sector-Median Rolling MZ Beta (H=21)', color='white', fontsize=13, pad=8)
ax2.set_ylabel('MZ Beta', color='#cccccc')
ax2.tick_params(colors='#aaaaaa')
for sp in ax2.spines.values():
    sp.set_color('#444')
ax2.grid(axis='y', color='#333', lw=0.5)
ax2.xaxis.set_major_locator(YearLocator())
ax2.xaxis.set_major_formatter(DateFormatter('%Y'))

# ── PANEL 3: Terminal beta bar chart ──────────────────────────────────────────
ax3 = fig.add_subplot(gs[2])
ax3.set_facecolor('#1a1a1a')

terminal_data = []
for t in complete:
    row = {'ticker': t, 'sector': sectors.get(t, 'Other')}
    for h in [21, 63, 126]:
        try:
            df = pd.read_csv(results_dir / f'predictions_{t}_H{h}.csv').dropna(subset=['y_true','y_pred'])
            df = df.sort_values('date').tail(252)
            if len(df) < 100:
                row[f'H{h}'] = np.nan
                continue
            sl, ic, r, p, se = stats.linregress(df.y_pred, df.y_true)
            row[f'H{h}'] = sl
        except Exception:
            row[f'H{h}'] = np.nan
    terminal_data.append(row)

td = pd.DataFrame(terminal_data).dropna(subset=['H21'])
td = td.sort_values('H21').reset_index(drop=True)

x = np.arange(len(td))
w = 0.28

def bar_color(b, ref=1.0, tol=0.15):
    if pd.isna(b):
        return '#666666'
    return '#22c55e' if abs(b - ref) <= tol else '#ef4444'

c21  = [bar_color(b) for b in td['H21']]
c63  = [bar_color(b) for b in td['H63']]
c126 = [bar_color(b) for b in td['H126']]

ax3.bar(x - w, td['H21'],  w, color=c21,  alpha=0.85)
ax3.bar(x,     td['H63'],  w, color=c63,  alpha=0.85)
ax3.bar(x + w, td['H126'], w, color=c126, alpha=0.85)

ax3.axhline(1.0, color='white', lw=1.5, linestyle='--', alpha=0.8)
ax3.axhline(0.85, color='#aaaaaa', lw=0.8, linestyle=':', alpha=0.5)
ax3.axhline(1.15, color='#aaaaaa', lw=0.8, linestyle=':', alpha=0.5)
ax3.set_xticks(x)
ax3.set_xticklabels(td['ticker'], rotation=55, ha='right', fontsize=7.5, color='#cccccc')
ax3.set_ylim(-0.3, 2.3)
ax3.set_title('Terminal Beta by Ticker & Horizon (last 252 days)  |  Green = calibrated [0.85–1.15]  |  Red = miscalibrated',
              color='white', fontsize=11, pad=8)
ax3.set_ylabel('MZ Beta', color='#cccccc')
ax3.tick_params(colors='#aaaaaa')
for sp in ax3.spines.values():
    sp.set_color('#444')
ax3.grid(axis='y', color='#333', lw=0.5, alpha=0.6)

legend_items = [
    plt.Rectangle((0,0),1,1, fc='#6366f1', alpha=0.85),
    plt.Rectangle((0,0),1,1, fc='#8b5cf6', alpha=0.85),
    plt.Rectangle((0,0),1,1, fc='#a855f7', alpha=0.85),
    Line2D([0],[0], color='#22c55e', lw=3),
    Line2D([0],[0], color='#ef4444', lw=3),
]
ax3.legend(legend_items, ['H=21','H=63','H=126','Calibrated','Miscalibrated'],
           loc='upper left', fontsize=8, facecolor='#2a2a2a',
           edgecolor='#555', labelcolor='white', framealpha=0.85)

fig.suptitle('Tarasque v4  —  MZ Beta Analysis  (61 Tickers)', color='white',
             fontsize=16, fontweight='bold', y=0.995)

outpath = 'model/pipeline/results/beta_over_time.png'
plt.savefig(outpath, dpi=150, bbox_inches='tight', facecolor='#0f0f0f')
print(f'Saved: {outpath}')
