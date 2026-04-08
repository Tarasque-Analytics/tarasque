import pandas as pd, numpy as np
from scipy import stats
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.dates import YearLocator, DateFormatter
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
import warnings
warnings.filterwarnings('ignore')

results_dir = Path('model/pipeline/results')
base = Path('D:/Tarasque_DB')

complete = [
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

named_events = {
    '2011-08-08': 'US Downgrade',
    '2015-08-24': 'China Flash',
    '2018-02-05': 'Volmageddon',
    '2018-12-24': 'Dec Selloff',
    '2020-02-24': 'COVID Start',
    '2020-03-16': 'COVID Bottom',
    '2020-11-09': 'Vaccine Day',
    '2022-01-24': 'Fed Pivot',
    '2022-06-13': 'CPI Shock',
    '2023-03-10': 'SVB',
    '2024-08-05': 'Yen Unwind',
}

# ── SPY returns & 3-sigma days ───────────────────────────────────────────────
print('Loading SPY...')
spy = pd.read_parquet(base / 'ohlcv/ticker=SPY')
spy['date'] = pd.to_datetime(spy['date'])
spy = spy.sort_values('date').set_index('date')
spy['ret'] = spy['prc'].pct_change()
spy_ret = spy['ret'].dropna()
roll_std = spy_ret.rolling(252).std()
roll_mean = spy_ret.rolling(252).mean()
z_spy = ((spy_ret - roll_mean) / roll_std).dropna()
shock_days = z_spy[z_spy.abs() >= 3].index

# ── Rolling beta per ticker ──────────────────────────────────────────────────
def rolling_beta(df, window=252):
    dates, betas = [], []
    df = df.dropna(subset=['y_true','y_pred']).sort_values('date')
    df['date'] = pd.to_datetime(df['date'])
    for i in range(window, len(df)):
        chunk = df.iloc[i-window:i]
        if len(chunk) < 100:
            continue
        sl, *_ = stats.linregress(chunk.y_pred, chunk.y_true)
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

# ── Market-average beta (median across all tickers, daily) ──────────────────
beta_panel = pd.concat(all_betas.values(), axis=1)
beta_panel.columns = list(all_betas.keys())
market_beta = beta_panel.median(axis=1).sort_index()
market_beta_smooth = market_beta.rolling(21, min_periods=5).mean()  # ~1mo smooth

# Daily delta of smoothed market beta
beta_delta = market_beta_smooth.diff()
# Smoothed delta (signal clarity)
beta_delta_smooth = beta_delta.rolling(21, min_periods=5).mean()

# ── Signal definition ────────────────────────────────────────────────────────
# Signal fires when smoothed beta_delta crosses above threshold (beta rising)
# Threshold = 1 rolling std of beta_delta (z-score approach)
delta_std = beta_delta_smooth.rolling(252, min_periods=63).std()
delta_mean = beta_delta_smooth.rolling(252, min_periods=63).mean()
beta_delta_z = (beta_delta_smooth - delta_mean) / (delta_std + 1e-9)

# Signal = beta rising sharply (z > 1.0 = 1-sigma above rolling avg delta)
SIGNAL_THRESH = 1.0
signal_days = beta_delta_z[beta_delta_z > SIGNAL_THRESH].index

# ── Event window analysis ─────────────────────────────────────────────────────
# For each 3-sigma event: was there a signal in prior 30 days? (hit)
# For each signal: was there a 3-sigma event in next 30 days? (precision)
LEAD_WINDOW = 30  # days signal leads event

events_series = pd.Series(0.0, index=market_beta_smooth.index)
for d in shock_days:
    if d in events_series.index:
        events_series[d] = 1.0

signal_series = pd.Series(0.0, index=market_beta_smooth.index)
for d in signal_days:
    if d in signal_series.index:
        signal_series[d] = 1.0

# Hit: event preceded by signal within LEAD_WINDOW days
hits, misses = [], []
for ed in shock_days:
    window_start = ed - pd.Timedelta(days=LEAD_WINDOW)
    pre = signal_series.loc[window_start:ed]
    if pre.sum() > 0:
        hits.append(ed)
    else:
        misses.append(ed)

# False alarms: signal NOT followed by event within LEAD_WINDOW days
false_alarms, true_signals = [], []
for sd in signal_days:
    window_end = sd + pd.Timedelta(days=LEAD_WINDOW)
    post = events_series.loc[sd:window_end]
    if post.sum() > 0:
        true_signals.append(sd)
    else:
        false_alarms.append(sd)

total_events = len(shock_days)
total_signals = len(signal_days)
n_hits = len(hits)
n_misses = len(misses)
n_fa = len(false_alarms)
n_ts = len(true_signals)

sensitivity = n_hits / total_events if total_events > 0 else 0
precision   = n_ts / total_signals if total_signals > 0 else 0
false_alarm_rate = n_fa / total_signals if total_signals > 0 else 0

print(f'\n--- Signal Performance (thresh={SIGNAL_THRESH}sigma, lead={LEAD_WINDOW}d) ---')
print(f'Total 3-sigma SPY events : {total_events}')
print(f'Total signals fired      : {total_signals}')
print(f'Hits (event preceded)    : {n_hits}  ({sensitivity*100:.0f}% sensitivity/recall)')
print(f'Misses                   : {n_misses}')
print(f'True signals             : {n_ts}  ({precision*100:.0f}% precision)')
print(f'False alarms (Type I)    : {n_fa}  ({false_alarm_rate*100:.0f}% of signals)')

# ── FIGURE ────────────────────────────────────────────────────────────────────
fig = plt.figure(figsize=(22, 18))
fig.patch.set_facecolor('#0f0f0f')
gs = gridspec.GridSpec(3, 1, figure=fig, hspace=0.35, height_ratios=[1.1, 1.1, 0.8])

# ── PANEL 1: Market-average rolling beta ─────────────────────────────────────
ax1 = fig.add_subplot(gs[0])
ax1.set_facecolor('#1a1a1a')

ax1.plot(market_beta_smooth.index, market_beta_smooth.values,
         color='#7dd3fc', lw=1.8, label='Market-avg beta (21d smooth)', alpha=0.9)
ax1.fill_between(market_beta_smooth.index, 1.0, market_beta_smooth.values,
                 where=market_beta_smooth > 1.0, color='#ef4444', alpha=0.18, label='Model underpredicting')
ax1.fill_between(market_beta_smooth.index, market_beta_smooth.values, 1.0,
                 where=market_beta_smooth < 1.0, color='#22c55e', alpha=0.18, label='Model overpredicting')
ax1.axhline(1.0, color='white', lw=1.5, linestyle='--', alpha=0.7)
ax1.axhline(1.15, color='#aaaaaa', lw=0.7, linestyle=':', alpha=0.4)
ax1.axhline(0.85, color='#aaaaaa', lw=0.7, linestyle=':', alpha=0.4)

for d in shock_days:
    if d in market_beta_smooth.index:
        ax1.axvline(d, color='#ff4444', lw=0.6, alpha=0.35)

for i, (ds, label) in enumerate(named_events.items()):
    dt = pd.Timestamp(ds)
    yp = 1.82 if i % 2 == 0 else 1.72
    ax1.axvline(dt, color='#fbbf24', lw=1.1, linestyle='--', alpha=0.75)
    ax1.text(dt, yp, label, color='#fbbf24', fontsize=6.5, rotation=68,
             ha='left', va='bottom')

ax1.set_ylim(0.3, 2.0)
ax1.set_title('Market-Average Rolling MZ Beta (H=21, median across 90 clean tickers)',
              color='white', fontsize=12, pad=7)
ax1.set_ylabel('Avg Beta', color='#cccccc')
ax1.tick_params(colors='#aaaaaa')
for sp in ax1.spines.values(): sp.set_color('#444')
ax1.grid(axis='y', color='#333', lw=0.5)
ax1.xaxis.set_major_locator(YearLocator())
ax1.xaxis.set_major_formatter(DateFormatter('%Y'))
ax1.legend(loc='upper left', fontsize=8.5, facecolor='#2a2a2a',
           edgecolor='#555', labelcolor='white', framealpha=0.85)

# ── PANEL 2: Beta delta (signal) ──────────────────────────────────────────────
ax2 = fig.add_subplot(gs[1])
ax2.set_facecolor('#1a1a1a')

ax2.plot(beta_delta_z.index, beta_delta_z.values,
         color='#a78bfa', lw=1.4, alpha=0.85, label='Beta-delta z-score (21d)')
ax2.axhline(0, color='white', lw=0.8, linestyle='-', alpha=0.4)
ax2.axhline(SIGNAL_THRESH, color='#fbbf24', lw=1.2, linestyle='--', alpha=0.75,
            label=f'Signal threshold (z>{SIGNAL_THRESH})')
ax2.axhline(-SIGNAL_THRESH, color='#64748b', lw=0.8, linestyle=':', alpha=0.4)

# Mark true signals (green) and false alarms (red) above threshold
for sd in true_signals:
    if sd in beta_delta_z.index:
        ax2.axvline(sd, color='#22c55e', lw=0.5, alpha=0.5)
for sd in false_alarms:
    if sd in beta_delta_z.index:
        ax2.axvline(sd, color='#ef4444', lw=0.5, alpha=0.35)

# 3-sigma events
for d in shock_days:
    if d in beta_delta_z.index:
        ax2.axvline(d, color='#ff4444', lw=1.2, alpha=0.5)

ax2.set_ylim(-4, 5)
ax2.set_title(
    f'Beta-Delta Signal  |  Green lines = true signals  |  Red lines = false alarms (Type I)  |  '
    f'Sensitivity={sensitivity*100:.0f}%  Precision={precision*100:.0f}%  False alarm rate={false_alarm_rate*100:.0f}%',
    color='white', fontsize=11, pad=7)
ax2.set_ylabel('Delta Z-score', color='#cccccc')
ax2.tick_params(colors='#aaaaaa')
for sp in ax2.spines.values(): sp.set_color('#444')
ax2.grid(axis='y', color='#333', lw=0.5)
ax2.xaxis.set_major_locator(YearLocator())
ax2.xaxis.set_major_formatter(DateFormatter('%Y'))
ax2.legend(loc='upper left', fontsize=8.5, facecolor='#2a2a2a',
           edgecolor='#555', labelcolor='white', framealpha=0.85)

# ── PANEL 3: ROC-style threshold sweep ───────────────────────────────────────
ax3 = fig.add_subplot(gs[2])
ax3.set_facecolor('#1a1a1a')

thresholds = np.linspace(0.0, 3.0, 60)
sens_arr, fpr_arr, prec_arr = [], [], []
for thr in thresholds:
    sig = beta_delta_z[beta_delta_z > thr].index
    if len(sig) == 0:
        sens_arr.append(0); fpr_arr.append(0); prec_arr.append(np.nan)
        continue
    s_series = pd.Series(0.0, index=market_beta_smooth.index)
    for d in sig:
        if d in s_series.index: s_series[d] = 1.0
    h = sum(1 for ed in shock_days if s_series.loc[
        max(s_series.index[0], ed - pd.Timedelta(days=LEAD_WINDOW)):ed].sum() > 0)
    ts_ = sum(1 for sd in sig if events_series.loc[
        sd:min(events_series.index[-1], sd + pd.Timedelta(days=LEAD_WINDOW))].sum() > 0)
    sens_arr.append(h / total_events)
    fpr_arr.append((len(sig) - ts_) / max(1, len(sig)))
    prec_arr.append(ts_ / len(sig) if len(sig) > 0 else 0)

ax3.plot(fpr_arr, sens_arr, color='#7dd3fc', lw=2.2, label='ROC curve (beta-delta signal)')
ax3.plot([0,1],[0,1], color='#555', lw=1, linestyle='--', label='Random baseline')
# Mark current threshold
ax3.scatter([false_alarm_rate], [sensitivity], color='#fbbf24', s=80, zorder=5,
            label=f'Current thresh (z>{SIGNAL_THRESH}): sens={sensitivity*100:.0f}% FAR={false_alarm_rate*100:.0f}%')
ax3.set_xlim(-0.02, 1.02); ax3.set_ylim(-0.02, 1.02)
ax3.set_xlabel('False Alarm Rate (1 - Precision)', color='#cccccc')
ax3.set_ylabel('Sensitivity (Recall)', color='#cccccc')
ax3.set_title('ROC Curve: Beta-Delta Signal vs 3-sigma SPY Events (lead window = 30 days)',
              color='white', fontsize=11, pad=7)
ax3.tick_params(colors='#aaaaaa')
for sp in ax3.spines.values(): sp.set_color('#444')
ax3.grid(color='#333', lw=0.5)
ax3.legend(loc='lower right', fontsize=8.5, facecolor='#2a2a2a',
           edgecolor='#555', labelcolor='white', framealpha=0.88)

fig.suptitle('Tarasque v4  —  Beta-Delta Signal Detection vs 3-sigma Market Events',
             color='white', fontsize=15, fontweight='bold', y=0.998)

outpath = 'model/pipeline/results/beta_signal_detection.png'
plt.savefig(outpath, dpi=150, bbox_inches='tight', facecolor='#0f0f0f')
print(f'\nSaved: {outpath}')
