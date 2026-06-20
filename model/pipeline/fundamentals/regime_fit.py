"""
regime_fit.py — Joint regime fit: valuation (RAFI divergence) × VRP percentile.

Spec (user-proposed):
  x-axis: valuation — divergence(t) vs RAFI, anchored at canonical 2014-01-02.
          Positive % = stock trading rich vs its fundamental footprint;
          negative % = cheap.
  y-axis: own-stock VRP percentile — trailing-252-BD rank of
          fwd_premium_ewma_21d. P50 = neutral fear, P90 = fear bid up,
          P10 = fear compressed (complacency).

Four quadrants:
  Cheap & Feared      (cheap × high VRP)   — capitulation. Value meeting
                                              vol bid-up = classic entry.
  Quietly Cheap       (cheap × low VRP)    — cheap with no fear. Compounder
                                              trading discounted; clean value.
  Priced for Perfection (rich × low VRP)   — rich with no fear. Most fragile.
  Rich & Anxious      (rich × high VRP)    — momentum + concern. Both legs
                                              flag caution.

Two deliverables:
  1. Current-snapshot scatter plot of all corpus tickers.
  2. Informativeness back-test: cross-sectional forward returns by quadrant
     across the joint-history panel. Tests whether quadrant assignment at
     date T predicts forward N-BD return at T+N.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[3]
DIV_DIR = REPO_ROOT / 'data_cache' / 'sec_fundamentals' / 'divergence'
PRED_DIR = REPO_ROOT / 'model' / 'pipeline' / 'results' / 'webapp_export' / 'tickers'
OUT_DIR = DIV_DIR / 'regime_fit'

VRP_WINDOW = 252        # trailing window for own-percentile
VRP_MIN_PERIODS = 63    # 3 months min before percentile is meaningful


def load_ticker_panel(ticker: str,
                       valuation_anchor_bd: int = 252) -> Optional[pd.DataFrame]:
    """Join divergence + VRP percentile + price for one ticker.

    valuation_anchor_bd controls the re-anchor for the valuation axis:
      0     -> raw divergence vs canonical 2014-01-02 (range can be ±2000%)
      252   -> "% richer/cheaper than 1yr ago" (range typically ±40%)
      63    -> "% change over the past quarter"
    The frontend-style "user picks a quarter" is exactly this knob.
    """
    div_path = DIV_DIR / f'{ticker}_divergence.csv'
    pred_path = PRED_DIR / f'predictions_{ticker}.csv'
    if not div_path.exists() or not pred_path.exists():
        return None

    div = pd.read_csv(div_path, parse_dates=['date'],
                       usecols=['date', 'divergence', 'price'])
    pred = pd.read_csv(pred_path, parse_dates=['date'],
                        usecols=['date', 'fwd_premium_ewma_21d'])

    df = div.merge(pred, on='date', how='inner').sort_values('date').reset_index(drop=True)
    df['ticker'] = ticker

    # Own-ticker VRP percentile (trailing-252-BD)
    df['vrp_own_pct'] = (
        df['fwd_premium_ewma_21d']
          .rolling(VRP_WINDOW, min_periods=VRP_MIN_PERIODS)
          .rank(pct=True)
    )

    # Valuation % vs RAFI fair value — RE-ANCHORED. The canonical-2014
    # divergence has enormous range (NVDA +2300%) which crushes the
    # display. Re-anchor to N business days ago: % = (div_now / div_then - 1) * 100.
    # Equivalent to the frontend's "compare to start day" operation.
    if valuation_anchor_bd > 0:
        anchor = df['divergence'].shift(valuation_anchor_bd)
        df['valuation_pct'] = (df['divergence'] / anchor - 1.0) * 100.0
    else:
        df['valuation_pct'] = (df['divergence'] - 1.0) * 100.0

    return df


def load_corpus_panel() -> pd.DataFrame:
    """Concat all tickers that have both divergence and VRP data."""
    panels = []
    for div_path in sorted(DIV_DIR.glob('*_divergence.csv')):
        ticker = div_path.stem.replace('_divergence', '')
        p = load_ticker_panel(ticker)
        if p is None or p.empty:
            continue
        panels.append(p)
    if not panels:
        return pd.DataFrame()
    return pd.concat(panels, ignore_index=True)


def latest_snapshot(panel: pd.DataFrame) -> pd.DataFrame:
    """One row per ticker: latest available joint observation."""
    snap = (
        panel.dropna(subset=['valuation_pct', 'vrp_own_pct'])
             .sort_values('date')
             .groupby('ticker', as_index=False)
             .last()
    )
    return snap


def _quadrant_label(val_pct: float, vrp_pct: float,
                     val_threshold: float = 0.0,
                     vrp_threshold: float = 0.5) -> str:
    rich = val_pct > val_threshold
    feared = vrp_pct > vrp_threshold
    if not rich and feared:   return 'Cheap & Feared'
    if not rich and not feared: return 'Quietly Cheap'
    if rich and feared:        return 'Rich & Anxious'
    return 'Priced for Perfection'


QUAD_COLORS = {
    'Cheap & Feared':        '#2ca02c',   # green-teal
    'Quietly Cheap':         '#1f7a4f',   # darker green
    'Rich & Anxious':        '#d4a83a',   # amber
    'Priced for Perfection': '#d62728',   # red
}


def plot_snapshot(snap: pd.DataFrame, out_path: Path, asof: pd.Timestamp):
    """One-time scatter of the current regime fit across the universe.

    X-axis: cross-sectional percentile of the firm's divergence-vs-canonical
            among today's universe. P50 = "fair vs the corpus median"; P95 =
            top-5% richest; P5 = bottom-5% cheapest. Bounded [0, 100] avoids
            NVDA / MU outliers visually crushing everything else.
    Y-axis: own-stock VRP percentile (trailing 252 BD).
    """
    fig, ax = plt.subplots(figsize=(14, 8))

    snap = snap.copy()
    # Cross-sectional divergence percentile within today's universe
    snap['valuation_cs_pct'] = snap['divergence'].rank(pct=True) * 100
    snap['quadrant'] = snap.apply(
        lambda r: _quadrant_label(r['valuation_cs_pct'] - 50,
                                    r['vrp_own_pct']), axis=1
    )

    for q, sub in snap.groupby('quadrant'):
        ax.scatter(sub['valuation_cs_pct'], sub['vrp_own_pct'] * 100,
                   c=QUAD_COLORS[q], s=80, alpha=0.75, edgecolor='white',
                   linewidth=0.5, label=f'{q} (n={len(sub)})')
        for _, r in sub.iterrows():
            ax.annotate(r['ticker'], (r['valuation_cs_pct'], r['vrp_own_pct'] * 100),
                        fontsize=7, alpha=0.8,
                        xytext=(4, 3), textcoords='offset points')

    # Quadrant lines at the cross-section median (50) and VRP P50
    ax.axhline(50, color='gray', linewidth=0.7, alpha=0.6, linestyle='--')
    ax.axvline(50, color='gray', linewidth=0.7, alpha=0.6, linestyle='--')
    ax.set_xlim(-3, 103)
    ax.set_ylim(-3, 103)

    # Quadrant labels in corners
    ax.text(0.02, 0.97, 'Cheap & Feared', transform=ax.transAxes,
            fontsize=11, color=QUAD_COLORS['Cheap & Feared'],
            fontweight='bold', va='top', ha='left')
    ax.text(0.98, 0.97, 'Rich & Anxious', transform=ax.transAxes,
            fontsize=11, color=QUAD_COLORS['Rich & Anxious'],
            fontweight='bold', va='top', ha='right')
    ax.text(0.02, 0.03, 'Quietly Cheap', transform=ax.transAxes,
            fontsize=11, color=QUAD_COLORS['Quietly Cheap'],
            fontweight='bold', va='bottom', ha='left')
    ax.text(0.98, 0.03, 'Priced for Perfection', transform=ax.transAxes,
            fontsize=11, color=QUAD_COLORS['Priced for Perfection'],
            fontweight='bold', va='bottom', ha='right')

    ax.set_xlabel('Cross-sectional valuation percentile (vs corpus today)  ->  rich',
                  fontsize=10)
    ax.set_ylabel('Own-stock VRP percentile (trailing 252 BD, fwd_premium_ewma_21d)  ↑  feared',
                  fontsize=10)
    ax.set_title(
        f'Regime fit: RAFI valuation × own-stock VRP percentile\n'
        f'as of {asof.date()}  |n={len(snap)} tickers',
        fontsize=12,
    )
    ax.grid(True, alpha=0.3)
    ax.legend(loc='lower right', fontsize=9, framealpha=0.9)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    plt.tight_layout()
    fig.savefig(out_path, dpi=110)
    plt.close(fig)


def informativeness_test(panel: pd.DataFrame,
                          forward_bd: int = 63,
                          val_threshold: float = 0.0,
                          vrp_threshold: float = 0.5) -> pd.DataFrame:
    """Bucket all (ticker, date) observations by quadrant; measure forward
    N-BD log return by quadrant.

    Compute return as log(price_T+N / price_T). Aggregate by quadrant:
    mean, median, std, n, hit-rate, annualized Sharpe-like ratio.
    """
    df = panel.copy()
    df = df.dropna(subset=['valuation_pct', 'vrp_own_pct', 'price']).copy()
    df = df.sort_values(['ticker', 'date']).reset_index(drop=True)

    # Forward log return per ticker
    df['fwd_price'] = df.groupby('ticker')['price'].shift(-forward_bd)
    df['fwd_log_ret'] = np.log(df['fwd_price'] / df['price'])

    df['quadrant'] = df.apply(
        lambda r: _quadrant_label(r['valuation_pct'], r['vrp_own_pct'],
                                    val_threshold, vrp_threshold), axis=1)

    df = df.dropna(subset=['fwd_log_ret'])
    g = df.groupby('quadrant')['fwd_log_ret']
    stats = pd.DataFrame({
        'n_obs':       g.size(),
        'mean':        g.mean(),
        'median':      g.median(),
        'std':         g.std(),
        'hit_rate':    g.apply(lambda x: float((x > 0).mean())),
        'ann_return':  g.mean() * (252.0 / forward_bd),
        'ann_vol':     g.std() * np.sqrt(252.0 / forward_bd),
    })
    stats['ann_sharpe'] = stats['ann_return'] / stats['ann_vol']
    return stats.reset_index()


def main():
    panel = load_corpus_panel()
    if panel.empty:
        print('No corpus data found.')
        sys.exit(1)
    print(f'Loaded joint panel: {len(panel):,} rows  ×  '
          f'{panel["ticker"].nunique()} tickers  |'
          f'{panel["date"].min().date()} -> {panel["date"].max().date()}')

    snap = latest_snapshot(panel)
    asof = snap['date'].max()
    print(f'\nLatest snapshot at {asof.date()}: {len(snap)} tickers')

    out_path = OUT_DIR / f'regime_fit_snapshot_{asof.date()}.png'
    plot_snapshot(snap, out_path, asof)
    print(f'  snapshot saved')

    print('\n--- Informativeness back-test ---')
    for h in (21, 63, 126):
        print(f'\nForward {h} BD log returns by quadrant:')
        stats = informativeness_test(panel, forward_bd=h)
        cols = ['quadrant','n_obs','mean','hit_rate','ann_return','ann_vol','ann_sharpe']
        print(stats[cols].to_string(index=False, formatters={
            'mean': '{:+.4f}'.format,
            'hit_rate': '{:.1%}'.format,
            'ann_return': '{:+.2%}'.format,
            'ann_vol': '{:.2%}'.format,
            'ann_sharpe': '{:+.2f}'.format,
        }))

    # Save snapshot CSV
    snap_csv = OUT_DIR / f'regime_fit_snapshot_{asof.date()}.csv'
    snap.to_csv(snap_csv, index=False)
    print(f'\nSnapshot CSV saved.')


if __name__ == '__main__':
    main()
