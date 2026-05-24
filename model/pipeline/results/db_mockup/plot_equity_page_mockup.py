"""
plot_equity_page_mockup.py — Full equity-page UI mockup using real run data.

Renders what /equity/AAPL would look like as a single composite figure.
Each panel uses data from the corresponding mockup table to verify the
schema flows naturally into the visualizations.

Panels (top to bottom, left to right):
  A. Header card               — symbol, sector, AI headline, risk tier
  B. Stock price (1y)          — from prices_history (yfinance pull)
  C. VRP wedge + EWMA panel    — from volatility_history (vrp_wedge + ewma_21d)
  D. Vol term structure        — pfv_21/63/126 vs iv_atm_30/60/91/182 (splined)
  E. Options chart             — contract dots + Model RV band + IV band on strike axis
  F. Distribution panel        — histogram with current value marker
  G. SHAP force plot           — top 10 features ranked by abs_shap
  H. AI overview text card     — body, key drivers, confidence

Output:
  equity_page_mockup_AAPL.png

Run from repo root:
  python model/pipeline/results/db_mockup/plot_equity_page_mockup.py
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import json
import numpy as np
import pandas as pd
from pathlib import Path
from scipy.interpolate import CubicSpline
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.patches as mpatches
import matplotlib.dates as mdates
import warnings
warnings.filterwarnings('ignore')

MOCKUP = Path('model/pipeline/results/db_mockup')
OUT    = MOCKUP / 'equity_page_mockup_AAPL.png'

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
    for sp in ax.spines.values():
        sp.set_color('#333')
    ax.grid(color=GRID, lw=0.4, alpha=0.6)
    if title:
        ax.set_title(title, color=WHITE, fontsize=10, loc='left', pad=6, fontweight='bold')
    if ylabel:
        ax.set_ylabel(ylabel, color=DIM, fontsize=8)
    if xlabel:
        ax.set_xlabel(xlabel, color=DIM, fontsize=8)


# ── Load mockup tables ────────────────────────────────────────────────────────
print('Loading mockup tables...')
sec   = pd.read_csv(MOCKUP / '01_securities.csv')
vh    = pd.read_csv(MOCKUP / '02_volatility_history_sample.csv', parse_dates=['date'])
ph    = pd.read_csv(MOCKUP / '03_prices_history.csv', parse_dates=['date'])
ai    = pd.read_csv(MOCKUP / '05_ai_overview_equity.csv')
shap  = pd.read_csv(MOCKUP / '06_shap_snapshot.csv')
dist  = pd.read_csv(MOCKUP / '08_get_distribution_rpc_output.csv')

# Filter to AAPL (security_id = 1)
TICKER = 'AAPL'
SEC_ID = 1

# Pull more AAPL history from full predictions for richer panels
preds = pd.read_csv('model/pipeline/results/all_predictions_cal.csv')
preds['date'] = pd.to_datetime(preds['date'])
aapl_preds = preds[preds['ticker'] == TICKER].copy()

# Wide-pivot AAPL predictions
wide = aapl_preds.pivot_table(
    index='date', columns='horizon',
    values=['y_true','y_pred','y_pred_q15','y_cal','vrp_wedge','put_call_skew_30d']
)
wide.columns = [f'{a}_{b}' for a,b in wide.columns]
wide = wide.reset_index().sort_values('date').dropna(subset=['y_true_21'])

# Reconstruct iv_atm_30d (we have via vrp_wedge + y_true)
wide['iv_atm_30d'] = wide['vrp_wedge_21'] + wide['y_true_21']

# Synthesize IV term structure for the demo (in production these come from vsurfd ETL)
# A realistic AAPL term structure: 60d/91d/182d slightly above 30d in upward-sloping regime
rng = np.random.default_rng(42)
wide['iv_atm_60d']  = wide['iv_atm_30d'] * (1.04 + rng.normal(0, 0.015, len(wide)))
wide['iv_atm_91d']  = wide['iv_atm_30d'] * (1.07 + rng.normal(0, 0.018, len(wide)))
wide['iv_atm_182d'] = wide['iv_atm_30d'] * (1.10 + rng.normal(0, 0.022, len(wide)))

# EWMA of vrp_wedge
wide['vrp_wedge_ewma_21d'] = wide['vrp_wedge_21'].ewm(span=21, adjust=False).mean()

# Filter prices_history to AAPL
aapl_prices = ph[ph['security_id'] == SEC_ID].sort_values('date')

# Get latest snapshot for the term structure / options chart
latest = wide.iloc[-1]
spot = aapl_prices['close'].iloc[-1]

# AAPL AI overview row + SHAP for H=21
ai_row = ai[(ai['security_id']==SEC_ID)].iloc[0]
ai_content = json.loads(ai_row['content'])
shap_row = shap[(shap['security_id']==SEC_ID) & (shap['horizon']==21)].iloc[0]
shap_data = json.loads(shap_row['feature_data'])

# Distribution data (filter to one metric — current is RV)
dist_filtered = dist.copy()

print(f'  AAPL history: {len(wide)} rows')
print(f'  Latest spot:  ${spot:.2f}')
print(f'  Latest H=21:  RV={latest["y_true_21"]:.1%}, PFV={latest["y_pred_21"]:.1%}, IV30={latest["iv_atm_30d"]:.1%}')


# ═══════════════════════════════════════════════════════════════════════════════
# Build figure
# ═══════════════════════════════════════════════════════════════════════════════
print('\nRendering composite figure...')

fig = plt.figure(figsize=(22, 26))
fig.patch.set_facecolor(BG)

# Layout: header + 4 rows of varying heights
gs = gridspec.GridSpec(
    nrows=7, ncols=12, figure=fig,
    height_ratios=[0.6, 2.5, 1.0, 2.5, 2.5, 2.0, 1.5],
    hspace=0.55, wspace=0.6,
    left=0.04, right=0.97, top=0.97, bottom=0.03,
)

# ── A. Header card ────────────────────────────────────────────────────────────
ax_h = fig.add_subplot(gs[0, :])
ax_h.set_facecolor(PANEL_BG)
ax_h.set_xlim(0, 1); ax_h.set_ylim(0, 1)
ax_h.axis('off')

risk_color = {'Suppressed':GREEN,'Normal':ACCENT,'Elevated':AMBER,'Stress':RED,'Crisis':'#dc2626'}.get(ai_row['risk_tier'], ACCENT)

ax_h.text(0.005, 0.5, TICKER, color=WHITE, fontsize=36, fontweight='bold',
         va='center', transform=ax_h.transAxes, family='monospace')
sec_row = sec[sec['security_id']==SEC_ID].iloc[0]
ax_h.text(0.06, 0.65, sec_row['gics_sector'], color=DIM, fontsize=11, va='center',
         transform=ax_h.transAxes)
ax_h.text(0.06, 0.35, f"Spot ${spot:.2f}  |  H=21 PFV {latest['y_cal_21']:.1%}  |  IV30 {latest['iv_atm_30d']:.1%}  |  VRP {latest['vrp_wedge_21']:+.1%}",
         color=WHITE, fontsize=11, va='center', transform=ax_h.transAxes)

# Risk tier pill
ax_h.add_patch(plt.Rectangle((0.42, 0.28), 0.12, 0.42, facecolor=risk_color,
              alpha=0.18, transform=ax_h.transAxes, edgecolor=risk_color, linewidth=1.5))
ax_h.text(0.48, 0.49, ai_row['risk_tier'].upper(), color=risk_color, fontsize=14,
         fontweight='bold', va='center', ha='center', transform=ax_h.transAxes)

# AI Headline
ax_h.text(0.57, 0.49, ai_row['headline'], color=WHITE, fontsize=12, va='center',
         transform=ax_h.transAxes, style='italic')


# ── B. Stock price (left) + C. VRP EWMA (right under price) ──────────────────
ax_b = fig.add_subplot(gs[1, :8])
style_axes(ax_b, title='Price  (1Y)', ylabel='USD')
ax_b.plot(aapl_prices['date'], aapl_prices['close'], color=ACCENT, lw=1.8, label='Close')
ax_b.fill_between(aapl_prices['date'], aapl_prices['low'], aapl_prices['high'],
                  color=ACCENT, alpha=0.12, label='High/Low')
ax_b.scatter(aapl_prices['date'].iloc[-1:], [spot], s=80, color=WHITE,
             edgecolors=ACCENT, linewidths=2, zorder=5)
ax_b.legend(fontsize=8, facecolor='#1a1a1a', edgecolor='#333', labelcolor='white',
           loc='upper left')
ax_b.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))

# C. VRP wedge + EWMA (under price — same column as price chart, smaller height)
ax_c = fig.add_subplot(gs[2, :8], sharex=ax_b)
style_axes(ax_c, title='VRP Wedge + 21d EWMA', ylabel='vol')
last_year_mask = wide['date'] >= aapl_prices['date'].min()
sub = wide[last_year_mask]
ax_c.plot(sub['date'], sub['vrp_wedge_21'], color=PURPLE, lw=0.8, alpha=0.45, label='VRP raw')
ax_c.plot(sub['date'], sub['vrp_wedge_ewma_21d'], color=PURPLE, lw=2.0, label='VRP EWMA-21d')
ax_c.axhline(0, color='white', lw=0.8, linestyle='--', alpha=0.5)
ax_c.fill_between(sub['date'], 0, sub['vrp_wedge_ewma_21d'],
                  where=(sub['vrp_wedge_ewma_21d']>0), color=AMBER, alpha=0.12,
                  label='IV > RV (fear)')
ax_c.fill_between(sub['date'], 0, sub['vrp_wedge_ewma_21d'],
                  where=(sub['vrp_wedge_ewma_21d']<0), color=GREEN, alpha=0.12,
                  label='IV < RV')
ax_c.legend(fontsize=7, facecolor='#1a1a1a', edgecolor='#333',
           labelcolor='white', loc='upper left', ncol=4)
plt.setp(ax_c.get_xticklabels(), visible=False)


# ── D. Vol term structure: Forecast vs IV (splined) ──────────────────────────
ax_d = fig.add_subplot(gs[1:3, 8:])
style_axes(ax_d, title='Vol Term Structure  (model vs market, splined)',
           xlabel='DTE (trading days)', ylabel='Annualized vol')

# Model curve: 3 points
model_x = np.array([21, 63, 126])
model_y = np.array([latest['y_cal_21'], latest['y_cal_63'], latest['y_cal_126']])
# Quantile floor (lower band)
floor_y = np.array([latest['y_pred_q15_21'], latest['y_pred_q15_63'], latest['y_pred_q15_126']])

# IV curve: 4 points
iv_x = np.array([30, 60, 91, 182])
iv_y = np.array([latest['iv_atm_30d'], latest['iv_atm_60d'],
                 latest['iv_atm_91d'], latest['iv_atm_182d']])

xs_m = np.linspace(model_x.min(), model_x.max(), 100)
xs_i = np.linspace(iv_x.min(), iv_x.max(), 100)
spl_m = CubicSpline(model_x, model_y)
spl_f = CubicSpline(model_x, floor_y)
spl_i = CubicSpline(iv_x, iv_y)

ax_d.plot(xs_m, spl_m(xs_m), color=ACCENT, lw=2.5, label='Model PFV (calibrated)')
ax_d.scatter(model_x, model_y, color=ACCENT, s=80, zorder=5, edgecolors='white', linewidths=1)
for x,y in zip(model_x, model_y):
    ax_d.annotate(f'H={x}\n{y:.1%}', (x,y), textcoords='offset points',
                 xytext=(0,12), ha='center', color=ACCENT, fontsize=8, fontweight='bold')

ax_d.plot(xs_m, spl_f(xs_m), color=ACCENT, lw=1.0, linestyle='--', alpha=0.7,
         label='Q15 floor')
ax_d.fill_between(xs_m, spl_f(xs_m), spl_m(xs_m), color=ACCENT, alpha=0.08)

ax_d.plot(xs_i, spl_i(xs_i), color=AMBER, lw=2.5, label='Implied vol (ATM)')
ax_d.scatter(iv_x, iv_y, color=AMBER, s=80, zorder=5, edgecolors='white', linewidths=1)
for x,y in zip(iv_x, iv_y):
    ax_d.annotate(f'{x}d\n{y:.1%}', (x,y), textcoords='offset points',
                 xytext=(0,-22), ha='center', color=AMBER, fontsize=8, fontweight='bold')

ax_d.legend(fontsize=8, facecolor='#1a1a1a', edgecolor='#333', labelcolor='white',
           loc='upper left')


# ── E. Options chart: price vs strike with model + IV bands ───────────────────
ax_e = fig.add_subplot(gs[3, :8])
style_axes(ax_e, title='Options Chain  (nearest expiry, +21d)',
           xlabel='Strike', ylabel='Mid price ($)')

# Synthesize a plausible options chain centered on spot
# (production gets this from yfinance/Polygon ETL)
expiry_dte = 21
T = expiry_dte / 252
strikes = np.arange(round(spot*0.85, 0), round(spot*1.15, 0)+1, 2.5)

# Model RV at this DTE (interpolate)
model_vol_at_dte = float(spl_m(expiry_dte))
iv_at_dte        = float(np.interp(expiry_dte, iv_x, iv_y))

# Synthesize realistic option mid prices from the IV curve (for visual purposes only)
def bs_call(S, K, T, sigma, r=0.04):
    from scipy.stats import norm
    d1 = (np.log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*np.sqrt(T))
    d2 = d1 - sigma*np.sqrt(T)
    return S*norm.cdf(d1) - K*np.exp(-r*T)*norm.cdf(d2)

def bs_put(S, K, T, sigma, r=0.04):
    from scipy.stats import norm
    d1 = (np.log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*np.sqrt(T))
    d2 = d1 - sigma*np.sqrt(T)
    return K*np.exp(-r*T)*norm.cdf(-d2) - S*norm.cdf(-d1)

call_prices = np.array([bs_call(spot, K, T, iv_at_dte) for K in strikes])
put_prices  = np.array([bs_put(spot,  K, T, iv_at_dte) for K in strikes])

# Add a touch of bid-ask noise
call_prices += rng.normal(0, 0.05, len(strikes))
put_prices  += rng.normal(0, 0.05, len(strikes))

# Compute the two ±1σ bands (model and IV)
sigma_model = model_vol_at_dte * np.sqrt(T)
sigma_iv    = iv_at_dte * np.sqrt(T)

model_low  = spot * np.exp(-sigma_model)
model_high = spot * np.exp(+sigma_model)
iv_low     = spot * np.exp(-sigma_iv)
iv_high    = spot * np.exp(+sigma_iv)

# Render bands first (background)
ymax = max(call_prices.max(), put_prices.max()) * 1.15
ax_e.axvspan(iv_low,    iv_high,    color=AMBER,  alpha=0.15, label='IV ±1σ')
ax_e.axvspan(model_low, model_high, color=ACCENT, alpha=0.18, label='Model ±1σ')
ax_e.axvline(spot, color='white', lw=1.5, linestyle='--', alpha=0.7, label=f'Spot ${spot:.2f}')

# Contract dots
ax_e.scatter(strikes, call_prices, s=55, color=GREEN, alpha=0.85,
            label='Calls', edgecolors='white', linewidths=0.5, zorder=5)
ax_e.scatter(strikes, put_prices, s=55, color=RED, alpha=0.85,
            label='Puts',  edgecolors='white', linewidths=0.5, zorder=5)

ax_e.set_ylim(0, ymax)
ax_e.legend(fontsize=8, facecolor='#1a1a1a', edgecolor='#333', labelcolor='white',
           loc='upper center', ncol=5)

# Annotation: the visible premium gap
gap_high_pct = (iv_high - model_high) / spot * 100
ax_e.annotate(f'IV prices in {gap_high_pct:.1f}% extra upside vol vs model',
              xy=((model_high + iv_high)/2, ymax*0.9), ha='center', va='top',
              color=AMBER, fontsize=8, style='italic',
              bbox=dict(boxstyle='round,pad=0.3', facecolor='#1a1a1a',
                        edgecolor=AMBER, alpha=0.8))


# ── F. Distribution panel (stock toggle shown — others available via RPC) ─────
ax_f = fig.add_subplot(gs[3, 8:])
style_axes(ax_f, title='Realized Vol Distribution  (toggle: Stock | Sector | Market)',
           xlabel='Annualized RV', ylabel='Count')

stock_dist = dist_filtered[dist_filtered['scope']=='stock']
sector_dist = dist_filtered[dist_filtered['scope']=='sector']
market_dist = dist_filtered[dist_filtered['scope']=='market']

# Plot stock as primary, faded sector/market for context
widths = stock_dist['bin_high'] - stock_dist['bin_low']
ax_f.bar((stock_dist['bin_low']+stock_dist['bin_high'])/2, stock_dist['count'],
        width=widths*0.95, color=ACCENT, alpha=0.85, edgecolor='none', label=f'{TICKER}')

current_val = stock_dist['current_value'].iloc[0]
current_pct = stock_dist['current_percentile'].iloc[0]
ax_f.axvline(current_val, color=WHITE, lw=2.0, linestyle='--',
            label=f'Current = {current_val:.1%} (P{int(current_pct*100)})')

# Sector and market medians as faint reference lines
sector_med = sector_dist[(sector_dist['bin_low']<=current_val)&(sector_dist['bin_high']>=current_val)]
sector_med_val = (sector_dist['bin_low']*sector_dist['count']).sum() / sector_dist['count'].sum()
market_med_val = (market_dist['bin_low']*market_dist['count']).sum() / market_dist['count'].sum()
ax_f.axvline(sector_med_val, color=PURPLE, lw=1.0, linestyle=':', alpha=0.7,
            label=f'Sector mean ({sec_row["gics_sector"]}) = {sector_med_val:.1%}')
ax_f.axvline(market_med_val, color=AMBER, lw=1.0, linestyle=':', alpha=0.7,
            label=f'Market mean = {market_med_val:.1%}')

ax_f.legend(fontsize=7.5, facecolor='#1a1a1a', edgecolor='#333',
           labelcolor='white', loc='upper right')


# ── G. SHAP force plot (top features) ─────────────────────────────────────────
ax_g = fig.add_subplot(gs[4, :8])
style_axes(ax_g, title='SHAP: Top 10 features driving H=21 forecast',
           xlabel='SHAP contribution (log-vol space)')

features = shap_data['features'][:10]
features = sorted(features, key=lambda f: f['shap'])
y_pos = np.arange(len(features))
shap_vals = [f['shap'] for f in features]
labels = [f"{f['display']}  ({f['value']:+.2f})" for f in features]
colors = [GREEN if v < 0 else RED for v in shap_vals]

ax_g.barh(y_pos, shap_vals, color=colors, alpha=0.85, height=0.7,
         edgecolor='white', linewidth=0.4)
ax_g.set_yticks(y_pos)
ax_g.set_yticklabels(labels, color=WHITE, fontsize=8)
ax_g.axvline(0, color='white', lw=1, alpha=0.7)

# Annotate base value and prediction
ax_g.text(0.99, 0.02,
         f"base value: {shap_row['base_value']:.3f}  →  prediction: {shap_row['predicted_value']:.3f}",
         transform=ax_g.transAxes, ha='right', va='bottom',
         color=DIM, fontsize=8, style='italic',
         bbox=dict(boxstyle='round,pad=0.3', facecolor='#1a1a1a',
                   edgecolor='#333', alpha=0.9))


# ── H. AI overview text card ──────────────────────────────────────────────────
ax_h2 = fig.add_subplot(gs[4, 8:])
ax_h2.set_facecolor(PANEL_BG)
ax_h2.set_xlim(0,1); ax_h2.set_ylim(0,1); ax_h2.axis('off')

# Border
for sp_name in ('top','bottom','left','right'):
    ax_h2.spines[sp_name].set_color('#333')
    ax_h2.spines[sp_name].set_visible(True)
ax_h2.add_patch(plt.Rectangle((0,0), 1, 1, facecolor=PANEL_BG,
                              edgecolor='#333', linewidth=1, transform=ax_h2.transAxes))

ax_h2.text(0.04, 0.92, 'AI Overview', color=WHITE, fontsize=11, fontweight='bold',
          transform=ax_h2.transAxes)
ax_h2.text(0.96, 0.92, f"{ai_row['model_version']} · {ai_row['prompt_version']}",
          color=DIM, fontsize=8, ha='right', transform=ax_h2.transAxes)

# Body text
import textwrap
body_text = ai_content['body']
wrapped = textwrap.fill(body_text, width=72)
ax_h2.text(0.04, 0.78, wrapped, color=WHITE, fontsize=9.5, va='top',
          transform=ax_h2.transAxes, family='sans-serif')

# Key drivers section
ax_h2.text(0.04, 0.45, 'Key Drivers', color=DIM, fontsize=9, fontweight='bold',
          transform=ax_h2.transAxes)
for i, driver in enumerate(ai_content['key_drivers']):
    y = 0.38 - i * 0.08
    arrow = '↑' if driver['shap'] > 0 else '↓'
    arrow_col = RED if driver['shap'] > 0 else GREEN
    ax_h2.text(0.04, y, f"{driver['rank']}.", color=DIM, fontsize=9,
              transform=ax_h2.transAxes, family='monospace')
    ax_h2.text(0.10, y, driver['name'], color=WHITE, fontsize=9,
              transform=ax_h2.transAxes, family='monospace')
    ax_h2.text(0.50, y, f"value {driver['value']:+.2f}", color=DIM, fontsize=8.5,
              transform=ax_h2.transAxes)
    ax_h2.text(0.78, y, f"SHAP {driver['shap']:+.3f}", color=arrow_col, fontsize=8.5,
              transform=ax_h2.transAxes, fontweight='bold')

# Confidence + sentiment
ax_h2.text(0.04, 0.07, f"Confidence: {ai_content['confidence']:.0%}",
          color=DIM, fontsize=8.5, transform=ax_h2.transAxes)
ax_h2.text(0.50, 0.07, f"Sentiment: {ai_content['sentiment']}",
          color=DIM, fontsize=8.5, transform=ax_h2.transAxes)


# ── Sub-row: distribution toggles (visualizing the 3 scopes side-by-side) ────
ax_d1 = fig.add_subplot(gs[5, :4])
ax_d2 = fig.add_subplot(gs[5, 4:8])
ax_d3 = fig.add_subplot(gs[5, 8:])

for ax, scope_label, scope_data, color in [
    (ax_d1, f'{TICKER}',         stock_dist,  ACCENT),
    (ax_d2, sec_row['gics_sector'], sector_dist, PURPLE),
    (ax_d3, 'Market (91 tickers)',  market_dist, AMBER),
]:
    style_axes(ax, title=f'Distribution: {scope_label}', xlabel='Annualized RV')
    widths = scope_data['bin_high'] - scope_data['bin_low']
    ax.bar((scope_data['bin_low']+scope_data['bin_high'])/2, scope_data['count'],
          width=widths*0.95, color=color, alpha=0.8, edgecolor='none')
    cv = scope_data['current_value'].iloc[0]
    cp = scope_data['current_percentile'].iloc[0]
    ax.axvline(cv, color=WHITE, lw=1.8, linestyle='--')
    ax.text(0.97, 0.94, f'P{int(cp*100)}', transform=ax.transAxes,
           ha='right', va='top', color=WHITE, fontsize=10, fontweight='bold',
           bbox=dict(boxstyle='round,pad=0.3', facecolor=color, alpha=0.5,
                     edgecolor=color))


# ── Footer card: model run metadata ───────────────────────────────────────────
ax_foot = fig.add_subplot(gs[6, :])
ax_foot.set_facecolor(PANEL_BG)
ax_foot.set_xlim(0,1); ax_foot.set_ylim(0,1); ax_foot.axis('off')

mr = pd.read_csv(MOCKUP / '07_model_runs.csv').iloc[0]
ax_foot.text(0.01, 0.7,
            f"Model: {mr['model_version']}  ·  Run: {mr['run_date']}  ·  "
            f"Spec: {mr['spec_hash']}  ·  Tickers: {mr['n_tickers']}  ·  "
            f"Horizons: {mr['horizons']}",
            color=DIM, fontsize=9, va='center', transform=ax_foot.transAxes,
            family='monospace')
ax_foot.text(0.01, 0.3, mr['notes'], color=DIM, fontsize=8, va='center',
            style='italic', transform=ax_foot.transAxes)
ax_foot.text(0.99, 0.5, f"Tarasque  ·  /equity/{TICKER}",
            color=DIM, fontsize=9, va='center', ha='right', transform=ax_foot.transAxes,
            family='monospace')


# ── Save ──────────────────────────────────────────────────────────────────────
plt.savefig(OUT, dpi=130, bbox_inches='tight', facecolor=BG)
plt.close()
print(f'\nSaved: {OUT}')