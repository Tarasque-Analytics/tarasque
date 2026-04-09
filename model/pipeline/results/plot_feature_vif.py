"""
plot_feature_vif.py  —  Feature multicollinearity analysis

Tests the 49-feature input space for redundancy before the quantile
regression layer is added. Correlated features split importance without
adding information.

Three analyses:
  1. VIF (Variance Inflation Factor) — how much each feature's variance
     is explained by all other features. VIF = 1/(1-R²) from regressing
     feature_i on all other features.
       VIF < 5   → clean
       VIF 5-10  → moderate, review
       VIF > 10  → problematic, drop or consolidate

  2. Pearson correlation matrix — linear redundancy
  3. Spearman correlation matrix — monotonic redundancy

Outputs:
  feature_vif.csv                 — VIF scores + recommendation
  feature_vif_bar.png             — ranked bar chart
  feature_corr_pearson.png        — Pearson heatmap
  feature_corr_spearman.png       — Spearman heatmap
  feature_high_corr_pairs.csv     — pairs with |r| > 0.80

Run from repo root:
  python model/pipeline/results/plot_feature_vif.py
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
import matplotlib.colors as mcolors
import warnings
warnings.filterwarnings('ignore')
from sklearn.linear_model import LinearRegression

RESULTS_DIR = Path('model/pipeline/results')
BG       = '#0f0f0f'
PANEL_BG = '#1a1a1a'
WHITE    = '#f0f0f0'
DIM      = '#888888'
GRID     = '#2e2e2e'
GOOD_COL = '#22c55e'
WARN_COL = '#f59e0b'
BAD_COL  = '#ef4444'

# Feature groups for coloring — mirrors features.py prefixes
FEATURE_GROUPS = {
    'rv':      '#4C72B0',   # Realized vol (GK windows)
    'ewma':    '#5A8FCC',   # EWMA vol
    'ret':     '#55A868',   # Returns + ETF returns
    'mom21':   '#66C27A',   # 21d momentum
    'tech':    '#C44E52',   # Technicals (RSI, ATR, MACD)
    'vol':     '#8172B2',   # Vol dynamics (trend, vel, regime)
    'event':   '#CCB974',   # Event gravity
    'iv':      '#FF8C00',   # Options IV
    'put_call':'#FF6B6B',   # Options skew
    'term':    '#FFB347',   # Term structure
    'vrp':     '#E377C2',   # VRP wedge
    'macro':   '#64B5CD',   # FRED macro
    'beta':    '#7F7F7F',   # Factor decomp beta
    'res':     '#BCBD22',   # Residual vol
    'price':   '#17BECF',   # Price regime
    'corr':    '#9467BD',   # Sector correlation
    'sector':  '#D62728',   # Sector coupling
}

def get_group_color(feat):
    for prefix, col in FEATURE_GROUPS.items():
        if feat.startswith(prefix + '_') or feat == prefix:
            return col
    return '#999999'


# ── Load all H=21 prediction files and reconstruct feature proxy ──────────────
# We don't have direct access to the feature matrix here, so we load the
# prediction CSVs which contain y_true and y_pred. For VIF we need the
# actual feature values — load from a sample of the cached parquet/csv
# if available, otherwise build proxy from what we have.
#
# Strategy: load any available feature CSV written during backtest, or
# reconstruct what we can from prediction file columns.

print('Scanning for feature data...')

# Check if a pooled features file exists from a recent run
feature_cache_paths = [
    RESULTS_DIR / 'features_pooled.parquet',
    RESULTS_DIR / 'features_pooled.csv',
    RESULTS_DIR.parent / 'features_pooled.parquet',
]

feat_df = None
for p in feature_cache_paths:
    if p.exists():
        print(f'  Found feature cache: {p}')
        feat_df = pd.read_parquet(p) if p.suffix == '.parquet' else pd.read_csv(p)
        break

if feat_df is None:
    # Fallback: reconstruct from prediction CSV columns
    # predictions_TICKER_H21.csv contains: date, y_true, y_pred, vrp_wedge, [others if saved]
    print('  No feature cache found. Building proxy from prediction CSV columns...')
    records = []
    for f in sorted(RESULTS_DIR.iterdir()):
        m = re.match(r'predictions_([A-Z]+)_H21\.csv', f.name)
        if m:
            df = pd.read_csv(f)
            records.append(df)

    if not records:
        print('ERROR: No prediction CSVs found in results/. Run backtest first.')
        sys.exit(1)

    combined = pd.concat(records, ignore_index=True)
    # Identify numeric feature-like columns (exclude date, ticker, y_true, y_pred, horizon)
    exclude = {'date', 'ticker', 'horizon', 'y_true', 'y_pred', 'fold',
               'y_pred_p10', 'y_pred_p50', 'y_pred_p90'}
    feat_cols = [c for c in combined.columns if c not in exclude
                 and pd.api.types.is_numeric_dtype(combined[c])]

    if len(feat_cols) < 3:
        print(f'\nPrediction CSVs only have columns: {list(combined.columns)}')
        print('Feature values are not stored in prediction CSVs — they are computed')
        print('on-the-fly during backtest. To run VIF analysis you need to either:')
        print('  (a) Add feature export to models.py train_wfa(), or')
        print('  (b) Re-run the feature builder directly here.')
        print('\nFalling back to direct feature reconstruction from OHLCV + macro cache...')
        feat_df = None
        feat_cols = []
    else:
        feat_df = combined[feat_cols + ['date']].dropna()
        print(f'  Reconstructed {len(feat_cols)} features from prediction CSVs')

# ── If still no data, build features directly ─────────────────────────────────
if feat_df is None or (isinstance(feat_df, pd.DataFrame) and len(feat_df.columns) < 5):
    print('\nAttempting direct feature reconstruction...')
    try:
        import sys as _sys
        _sys.path.insert(0, str(Path('model').resolve()))
        from pipeline.config import DataConfig, ModelConfig, load_config
        from pipeline.data_loader import fetch_dataset
        from pipeline.features import FeatureBuilder

        dc, mc, _ = load_config()
        builder = FeatureBuilder(dc, mc)

        # Build features for a representative cross-sector sample
        sample_tickers = ['AAPL', 'JPM', 'XOM', 'JNJ', 'MSFT', 'GS', 'NVDA',
                          'CVX', 'UNH', 'BAC', 'META', 'GOOGL', 'AMZN', 'PG', 'KO']
        # Override tickers to sample only (data is already cached)
        dc_sample = dc
        dc_sample.tickers = sample_tickers
        print(f'  Building features for {len(sample_tickers)} tickers...')

        raw_data = fetch_dataset(dc_sample, force_refresh=False)
        all_feats = []
        for ticker in sample_tickers:
            try:
                df = builder.build(ticker, raw_data)
                feat_cols = builder.get_predictor_columns(df)
                df_feat = df[feat_cols].copy()
                df_feat['ticker'] = ticker
                all_feats.append(df_feat)
                print(f'    {ticker}: {len(feat_cols)} features, {len(df_feat)} rows')
            except Exception as e:
                print(f'    {ticker}: FAILED — {e}')

        if all_feats:
            feat_df = pd.concat(all_feats, ignore_index=True)
            feat_cols = [c for c in feat_df.columns if c != 'ticker']
            print(f'  Built: {len(feat_cols)} features, {len(feat_df):,} rows')
        else:
            print('ERROR: Could not build any features. Check data paths.')
            sys.exit(1)

    except Exception as e:
        print(f'ERROR: Feature reconstruction failed — {e}')
        print('Ensure backtest has been run and data cache exists.')
        sys.exit(1)

# ── Prepare clean feature matrix ─────────────────────────────────────────────
print(f'\nFeature matrix: {feat_df.shape}')

# Get numeric feature columns only
if 'ticker' in feat_df.columns:
    feat_df = feat_df.drop(columns=['ticker'])
if 'date' in feat_df.columns:
    feat_df = feat_df.drop(columns=['date'])

feat_cols = [c for c in feat_df.columns if pd.api.types.is_numeric_dtype(feat_df[c])]
X = feat_df[feat_cols].copy()

# Drop columns that are entirely NaN or have < 50% valid rows
n = len(X)
X = X.loc[:, X.notna().sum() >= n * 0.5]
feat_cols = list(X.columns)

# Fill remaining NaN with column median (for VIF computation)
X = X.fillna(X.median())

# Remove zero-variance columns
variances = X.var()
zero_var = variances[variances < 1e-10].index.tolist()
if zero_var:
    print(f'  Dropping zero-variance features: {zero_var}')
    X = X.drop(columns=zero_var)
    feat_cols = list(X.columns)

print(f'  Clean feature matrix: {X.shape[0]:,} rows × {len(feat_cols)} features')


# ═══════════════════════════════════════════════════════════════════════════════
# VIF COMPUTATION
# ═══════════════════════════════════════════════════════════════════════════════
print('\nComputing VIF scores...')

# Sample for speed if very large
if len(X) > 50000:
    X_vif = X.sample(50000, random_state=42).reset_index(drop=True)
    print(f'  Sampled 50,000 rows for VIF computation')
else:
    X_vif = X.reset_index(drop=True)

X_arr = X_vif.values.astype(float)
n_features = X_arr.shape[1]

vif_scores = []
for i, col in enumerate(feat_cols):
    y_i = X_arr[:, i]
    X_rest = np.delete(X_arr, i, axis=1)
    try:
        reg = LinearRegression(fit_intercept=True).fit(X_rest, y_i)
        r2 = reg.score(X_rest, y_i)
        vif = 1.0 / (1.0 - r2) if r2 < 0.9999 else 9999.0
    except Exception:
        vif = np.nan
    vif_scores.append({'feature': col, 'vif': vif})
    if (i + 1) % 10 == 0:
        print(f'  {i+1}/{n_features} features done...')

vif_df = pd.DataFrame(vif_scores).sort_values('vif', ascending=False).reset_index(drop=True)

def vif_flag(v):
    if pd.isna(v): return 'unknown'
    if v > 10: return 'DROP'
    if v > 5:  return 'REVIEW'
    return 'OK'

vif_df['flag']  = vif_df['vif'].apply(vif_flag)
vif_df['group'] = vif_df['feature'].apply(lambda f: next(
    (g for g in FEATURE_GROUPS if f.startswith(g + '_') or f == g), 'other'
))

vif_df.to_csv(RESULTS_DIR / 'feature_vif.csv', index=False)
print(f'\nVIF results saved: feature_vif.csv')
print(f"  DROP (VIF>10):   {(vif_df['flag']=='DROP').sum()} features")
print(f"  REVIEW (VIF>5):  {(vif_df['flag']=='REVIEW').sum()} features")
print(f"  OK (VIF<5):      {(vif_df['flag']=='OK').sum()} features")
print('\nTop 20 highest VIF:')
print(vif_df.head(20)[['feature','vif','flag']].to_string(index=False))


# ═══════════════════════════════════════════════════════════════════════════════
# CHART 1 — VIF Bar Chart
# ═══════════════════════════════════════════════════════════════════════════════
print('\n[1/3] VIF bar chart...')

fig, ax = plt.subplots(figsize=(max(16, len(feat_cols) * 0.32), 8))
fig.patch.set_facecolor(BG)
ax.set_facecolor(PANEL_BG)

vif_plot = vif_df.copy()
# Cap display at 50 for readability (inf/9999 values stretch axis)
vif_plot['vif_display'] = vif_plot['vif'].clip(upper=50)

bar_colors = [
    BAD_COL  if f == 'DROP'   else
    WARN_COL if f == 'REVIEW' else
    GOOD_COL
    for f in vif_plot['flag']
]

x = np.arange(len(vif_plot))
bars = ax.bar(x, vif_plot['vif_display'], color=bar_colors, alpha=0.85, width=0.7)

ax.axhline(10, color=BAD_COL,  lw=1.5, linestyle='--', alpha=0.8, label='VIF=10 (drop threshold)')
ax.axhline(5,  color=WARN_COL, lw=1.2, linestyle=':', alpha=0.7, label='VIF=5  (review threshold)')
ax.axhline(1,  color=GOOD_COL, lw=0.8, linestyle=':', alpha=0.4, label='VIF=1  (perfect independence)')

ax.set_xticks(x)
ax.set_xticklabels(vif_plot['feature'], rotation=60, ha='right', fontsize=6.5, color=WHITE)
ax.set_ylabel('VIF Score  (capped at 50)', color=DIM, fontsize=10)
ax.set_title(
    f'Tarasque v4  —  Feature VIF Analysis  ({len(feat_cols)} features)\n'
    'Red > 10 = problematic collinearity  |  Amber 5–10 = review  |  Green < 5 = clean',
    color=WHITE, fontsize=12, pad=8,
)
ax.tick_params(colors=DIM)
for sp in ax.spines.values(): sp.set_color('#444')
ax.grid(axis='y', color=GRID, lw=0.5)
ax.legend(fontsize=9, facecolor='#2a2a2a', edgecolor='#555', labelcolor='white')

# Annotate exact VIF for problematic features
for bar, (_, row) in zip(bars, vif_plot.iterrows()):
    if row['flag'] in ('DROP', 'REVIEW'):
        val = row['vif']
        label = f'{val:.0f}' if val < 9990 else 'inf'
        ax.text(bar.get_x() + bar.get_width()/2,
                min(bar.get_height() + 0.3, 49),
                label, ha='center', va='bottom',
                color=WHITE, fontsize=5.5, rotation=90)

plt.tight_layout()
plt.savefig(RESULTS_DIR / 'feature_vif_bar.png', dpi=140, bbox_inches='tight', facecolor=BG)
plt.close()
print('  Saved: feature_vif_bar.png')


# ═══════════════════════════════════════════════════════════════════════════════
# CHART 2 & 3 — Correlation Heatmaps
# ═══════════════════════════════════════════════════════════════════════════════
print('[2/3] Correlation heatmaps...')

# Sample for correlation (50k rows is plenty)
X_corr = X.sample(min(50000, len(X)), random_state=42) if len(X) > 50000 else X

pearson  = X_corr[feat_cols].corr(method='pearson')
spearman = X_corr[feat_cols].corr(method='spearman')

# High-correlation pairs
high_corr_pairs = []
for i in range(len(feat_cols)):
    for j in range(i+1, len(feat_cols)):
        r_p = pearson.iloc[i, j]
        r_s = spearman.iloc[i, j]
        if abs(r_p) > 0.80 or abs(r_s) > 0.80:
            high_corr_pairs.append({
                'feature_a': feat_cols[i],
                'feature_b': feat_cols[j],
                'pearson':   round(r_p, 3),
                'spearman':  round(r_s, 3),
                'max_abs':   round(max(abs(r_p), abs(r_s)), 3),
            })

pairs_df = pd.DataFrame(high_corr_pairs).sort_values('max_abs', ascending=False)
pairs_df.to_csv(RESULTS_DIR / 'feature_high_corr_pairs.csv', index=False)
print(f'  High-correlation pairs (|r|>0.80): {len(pairs_df)}')
if len(pairs_df) > 0:
    print(pairs_df.head(20)[['feature_a','feature_b','pearson','spearman']].to_string(index=False))


def plot_corr_heatmap(corr_matrix, title, outpath):
    n = len(corr_matrix)
    figsize = max(14, n * 0.35)
    fig, ax = plt.subplots(figsize=(figsize, figsize * 0.85))
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(PANEL_BG)

    cmap = mcolors.LinearSegmentedColormap.from_list(
        'divRB', ['#4C9BE8', '#1a1a1a', '#ef4444'], N=256
    )

    im = ax.imshow(corr_matrix.values, cmap=cmap, vmin=-1, vmax=1,
                   aspect='auto', interpolation='nearest')

    # Feature group dividers
    group_order = [next((g for g in FEATURE_GROUPS if f.startswith(g + '_') or f == g), 'zzz')
                   for f in feat_cols]
    prev = group_order[0]
    for i, g in enumerate(group_order):
        if g != prev:
            ax.axhline(i - 0.5, color='#555', lw=0.6)
            ax.axvline(i - 0.5, color='#555', lw=0.6)
            prev = g

    # Only annotate if small enough
    if n <= 30:
        for i in range(n):
            for j in range(n):
                val = corr_matrix.iloc[i, j]
                if i != j and abs(val) > 0.5:
                    ax.text(j, i, f'{val:.2f}', ha='center', va='center',
                            color=WHITE, fontsize=5)

    ax.set_xticks(range(n))
    ax.set_xticklabels(feat_cols, rotation=60, ha='right', fontsize=6, color=WHITE)
    ax.set_yticks(range(n))
    ax.set_yticklabels(feat_cols, fontsize=6, color=WHITE)
    ax.tick_params(colors=DIM)
    for sp in ax.spines.values(): sp.set_color('#444')

    cbar = plt.colorbar(im, ax=ax, fraction=0.015, pad=0.01)
    cbar.set_label('Correlation', color=WHITE, fontsize=9)
    plt.setp(cbar.ax.yaxis.get_ticklabels(), color=WHITE, fontsize=7)

    ax.set_title(title, color=WHITE, fontsize=12, pad=8)
    plt.tight_layout()
    plt.savefig(outpath, dpi=120, bbox_inches='tight', facecolor=BG)
    plt.close()


plot_corr_heatmap(
    pearson,
    f'Tarasque v4  —  Pearson Correlation Matrix  ({len(feat_cols)} features)\n'
    'Red = positive linear correlation  |  Blue = negative  |  Lines = feature group boundaries',
    RESULTS_DIR / 'feature_corr_pearson.png'
)
print('  Saved: feature_corr_pearson.png')

plot_corr_heatmap(
    spearman,
    f'Tarasque v4  —  Spearman Rank Correlation Matrix  ({len(feat_cols)} features)\n'
    'Captures monotonic (nonlinear) redundancy  |  Differences from Pearson = nonlinear structure',
    RESULTS_DIR / 'feature_corr_spearman.png'
)
print('  Saved: feature_corr_spearman.png')


# ═══════════════════════════════════════════════════════════════════════════════
# Summary Report
# ═══════════════════════════════════════════════════════════════════════════════
print('\n' + '='*60)
print('MULTICOLLINEARITY SUMMARY')
print('='*60)

drop_features  = vif_df[vif_df['flag'] == 'DROP']['feature'].tolist()
review_features = vif_df[vif_df['flag'] == 'REVIEW']['feature'].tolist()

if drop_features:
    print(f'\nFEATURES TO DROP (VIF > 10):')
    for f in drop_features:
        v = vif_df[vif_df['feature'] == f]['vif'].values[0]
        print(f'  {f:<40} VIF={v:.1f}')
else:
    print('\nNo features with VIF > 10.')

if review_features:
    print(f'\nFEATURES TO REVIEW (VIF 5-10):')
    for f in review_features:
        v = vif_df[vif_df['feature'] == f]['vif'].values[0]
        print(f'  {f:<40} VIF={v:.1f}')

if len(pairs_df) > 0:
    print(f'\nHIGH-CORRELATION PAIRS (|r| > 0.80):  {len(pairs_df)} pairs')
    print('  Top pairs to consolidate:')
    for _, row in pairs_df.head(10).iterrows():
        print(f'  {row["feature_a"]:<35} ↔  {row["feature_b"]:<35}  r={row["max_abs"]:.3f}')

print('\nKnown structural relationships (by design):')
print('  rv_TARGET == rv_21d                    (literal alias — drop rv_TARGET from features)')
print('  vrp_wedge = iv_atm_30d - rv_TARGET     (linear combo — may inflate VIF of components)')
print('  vol_regime_zscore derived from rv_21d  (rolling zscore — highly correlated at short lag)')
print('  corr_sector_21d, _252d → sector_wedge  (three correlated cols from same underlying series)')
print('  macro_yield_curve_slope ~ treasury_10y (slope contains level as component)')

print('\n=== VIF analysis complete ===')
