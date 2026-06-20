"""
regime_compare.py -- Head-to-head: RAFI x VRP vs beta_mkt x beta_mz.

Two 2x2 regime fits, same universe, same forward-return methodology.
Compare which is more INFORMATIVE for cross-sectional forward returns.

System A: RAFI valuation x VRP percentile (this branch)
  x: cross-sectional valuation percentile (vs corpus today)
  y: own-stock VRP percentile (trailing 252 BD)
  Quadrants: Cheap&Feared, Quietly Cheap, Rich&Anxious, Priced for Perfection

System B: beta_mkt x beta_mz (existing Macro 2x2 Regime Modeler)
  x: 252-BD rolling CAPM beta vs SPY (gauge: market beta)
  y: rolling MZ calibration slope at H=126d (gauge: model forecast bias)
  Quadrants:
    Q1 stealth-event-risk (low_mkt x high_mz)  - low CAPM beta but model
                                                  under-forecasts vol
    Q2 idiosync+systematic (high_mkt x high_mz) - high beta + model
                                                  under-forecasts
    Q3 genuinely-calm    (low_mkt x low_mz)   - defensive + model
                                                  over-forecasts
    Q4 mega-cap buffer   (high_mkt x low_mz)  - high beta but model
                                                  over-forecasts vol

Comparison metrics:
  - Best vs worst quadrant spread (annualized return, Sharpe)
  - Cross-tab of agreement between systems (when system A says X,
    what does system B say?)
  - Forward IC of each system's quadrant-rank against forward returns
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[3]
DIV_DIR = REPO_ROOT / 'data_cache' / 'sec_fundamentals' / 'divergence'
PRED_DIR = REPO_ROOT / 'model' / 'pipeline' / 'results' / 'webapp_export' / 'tickers'
OUT_DIR = DIV_DIR / 'regime_fit'

VRP_WINDOW = 252
VRP_MIN_PERIODS = 63


def load_joint_panel() -> pd.DataFrame:
    """One row per (ticker, date) with both systems' inputs + price."""
    rows = []
    for div_path in sorted(DIV_DIR.glob('*_divergence.csv')):
        ticker = div_path.stem.replace('_divergence', '')
        pred_path = PRED_DIR / f'predictions_{ticker}.csv'
        if not pred_path.exists():
            continue
        div = pd.read_csv(div_path, parse_dates=['date'],
                           usecols=['date', 'divergence', 'price'])
        pred = pd.read_csv(
            pred_path, parse_dates=['date'],
            usecols=['date', 'fwd_premium_ewma_21d',
                     'beta_mkt_252d', 'beta_mz_h21', 'beta_mz_h63', 'beta_mz_h126'],
        )
        df = div.merge(pred, on='date', how='inner').sort_values('date').reset_index(drop=True)
        df['ticker'] = ticker
        # VRP percentile
        df['vrp_own_pct'] = (
            df['fwd_premium_ewma_21d']
              .rolling(VRP_WINDOW, min_periods=VRP_MIN_PERIODS).rank(pct=True)
        )
        rows.append(df)
    if not rows:
        return pd.DataFrame()
    return pd.concat(rows, ignore_index=True)


def _assign_quadrants(panel: pd.DataFrame) -> pd.DataFrame:
    """Cross-sectional quadrant assignment per (date) for both systems.

    System A: cheap/rich on the divergence median THAT DAY; feared/calm on
              the VRP-percentile median THAT DAY (P50 baseline).
    System B: low/high beta_mkt on the THAT-DAY corpus median; same for
              beta_mz at h=126 (longest horizon, lowest noise).
    """
    df = panel.copy()
    df = df.dropna(subset=['divergence', 'vrp_own_pct',
                            'beta_mkt_252d', 'beta_mz_h126'])

    # Cross-sectional per-date ranks (0..1)
    g = df.groupby('date')
    df['div_cs_rank'] = g['divergence'].rank(pct=True)
    df['vrp_cs_rank'] = g['vrp_own_pct'].rank(pct=True)
    df['bmkt_cs_rank'] = g['beta_mkt_252d'].rank(pct=True)
    df['bmz_cs_rank'] = g['beta_mz_h126'].rank(pct=True)

    # System A quadrant
    rich_a = df['div_cs_rank'] > 0.5
    feared_a = df['vrp_cs_rank'] > 0.5
    df['sysA'] = np.where(
        rich_a & feared_a, 'A: Rich & Anxious',
        np.where(rich_a & ~feared_a, 'A: Priced for Perfection',
                  np.where(~rich_a & feared_a, 'A: Cheap & Feared',
                                                 'A: Quietly Cheap')))

    # System B quadrant
    hb = df['bmkt_cs_rank'] > 0.5
    hm = df['bmz_cs_rank'] > 0.5
    df['sysB'] = np.where(
        ~hb & hm, 'B: Stealth event-risk',
        np.where(hb & hm, 'B: Idiosync+systematic',
                  np.where(~hb & ~hm, 'B: Genuinely calm',
                                       'B: Mega-cap buffer')))
    return df


def _forward_returns(df: pd.DataFrame, h: int) -> pd.DataFrame:
    df = df.sort_values(['ticker', 'date']).copy()
    df['fwd_price'] = df.groupby('ticker')['price'].shift(-h)
    df['fwd_ret'] = np.log(df['fwd_price'] / df['price'])
    return df.dropna(subset=['fwd_ret'])


def compare_systems(panel: pd.DataFrame, forward_bd: int = 63) -> dict:
    """Bucket and measure forward returns under both systems."""
    df = _assign_quadrants(panel)
    df = _forward_returns(df, forward_bd)

    def _stats(sub):
        return pd.Series({
            'n':           len(sub),
            'mean':        sub['fwd_ret'].mean(),
            'std':         sub['fwd_ret'].std(),
            'hit':         float((sub['fwd_ret'] > 0).mean()),
            'ann_ret':     sub['fwd_ret'].mean() * (252.0 / forward_bd),
            'ann_vol':     sub['fwd_ret'].std() * np.sqrt(252.0 / forward_bd),
        })

    sysA = df.groupby('sysA').apply(_stats, include_groups=False).reset_index()
    sysA['ann_sharpe'] = sysA['ann_ret'] / sysA['ann_vol']
    sysB = df.groupby('sysB').apply(_stats, include_groups=False).reset_index()
    sysB['ann_sharpe'] = sysB['ann_ret'] / sysB['ann_vol']

    return {
        'h': forward_bd,
        'sysA': sysA.sort_values('ann_sharpe', ascending=False).reset_index(drop=True),
        'sysB': sysB.sort_values('ann_sharpe', ascending=False).reset_index(drop=True),
        'cross_tab': pd.crosstab(df['sysA'], df['sysB']),
        'n_obs': len(df),
    }


def cross_sectional_ic(panel: pd.DataFrame, forward_bd: int = 63) -> pd.DataFrame:
    """Per-date Spearman rank correlation between each system's "richness
    rank" and forward return. Lower rank should pair with higher forward
    return for a value signal (negative IC).

    A system that ranks stocks meaningfully shows |mean IC| > 0 with
    t-stat above ~2.
    """
    df = _assign_quadrants(panel)
    df = _forward_returns(df, forward_bd)

    # System A "richness score" = div_cs_rank + (1 - vrp_cs_rank)
    #   - cheap (low div) + feared (high vrp) -> low score (= bullish)
    #   - rich + calm -> high score (= bearish)
    # System B "richness score" = bmkt_cs_rank + (1 - bmz_cs_rank)
    #   - low beta + high bmz -> low score (stealth)
    #   - high beta + low bmz -> high score (mega-cap buffer)
    df['scoreA'] = df['div_cs_rank'] + (1.0 - df['vrp_cs_rank'])
    df['scoreB'] = df['bmkt_cs_rank'] + (1.0 - df['bmz_cs_rank'])

    out = []
    for d, sub in df.groupby('date'):
        if len(sub) < 5:
            continue
        out.append({
            'date': d,
            'ic_A': sub['scoreA'].corr(sub['fwd_ret'], method='spearman'),
            'ic_B': sub['scoreB'].corr(sub['fwd_ret'], method='spearman'),
            'n': len(sub),
        })
    ic = pd.DataFrame(out)
    return ic


def layered_cell_analysis(panel: pd.DataFrame, forward_bd: int = 63) -> dict:
    """4x4 cell analysis: forward returns in every (sysA, sysB) intersection.

    Each cell is a stricter regime classification ("Cheap & Feared on RAFI/VRP
    AND Mega-cap buffer on beta_mkt/beta_mz"). With ~245k obs across 16
    cells, each cell has ~15k obs — enough for stable forward-return stats.

    Returns:
      'cells': DataFrame indexed by (sysA, sysB) with n, ann_ret, ann_vol,
               ann_sharpe, hit, plus 'excess_ret' = ann_ret minus corpus mean
               (= cell-vs-average alpha).
      'best':  the top-Sharpe cell + the bottom-Sharpe cell
      'long_short_spread': annualized spread between best and worst cells
    """
    df = _assign_quadrants(panel)
    df = _forward_returns(df, forward_bd)

    overall_mean_ann = df['fwd_ret'].mean() * (252.0 / forward_bd)
    overall_std_ann = df['fwd_ret'].std() * np.sqrt(252.0 / forward_bd)

    cells = []
    for (a, b), sub in df.groupby(['sysA', 'sysB']):
        cells.append({
            'sysA': a, 'sysB': b,
            'n': len(sub),
            'ann_ret': sub['fwd_ret'].mean() * (252.0 / forward_bd),
            'ann_vol': sub['fwd_ret'].std() * np.sqrt(252.0 / forward_bd),
            'hit':     float((sub['fwd_ret'] > 0).mean()),
        })
    cells_df = pd.DataFrame(cells)
    cells_df['ann_sharpe'] = cells_df['ann_ret'] / cells_df['ann_vol']
    cells_df['excess_ret'] = cells_df['ann_ret'] - overall_mean_ann
    cells_df = cells_df.sort_values('ann_sharpe', ascending=False).reset_index(drop=True)

    best = cells_df.iloc[0]
    worst = cells_df.iloc[-1]
    return {
        'h': forward_bd,
        'corpus_mean_ann': overall_mean_ann,
        'cells': cells_df,
        'best': best,
        'worst': worst,
        'ls_spread_ann_ret': best['ann_ret'] - worst['ann_ret'],
    }


def plot_layered_heatmap(result: dict, out_path: Path):
    """4x4 heatmap of annualized Sharpe per (sysA, sysB) cell."""
    cells = result['cells']
    h = result['h']

    sysA_order = ['A: Cheap & Feared', 'A: Quietly Cheap',
                  'A: Rich & Anxious', 'A: Priced for Perfection']
    sysB_order = ['B: Stealth event-risk', 'B: Genuinely calm',
                  'B: Mega-cap buffer', 'B: Idiosync+systematic']

    grid_sharpe = np.full((4, 4), np.nan)
    grid_ret = np.full((4, 4), np.nan)
    grid_n = np.zeros((4, 4), dtype=int)
    for _, r in cells.iterrows():
        i = sysA_order.index(r['sysA'])
        j = sysB_order.index(r['sysB'])
        grid_sharpe[i, j] = r['ann_sharpe']
        grid_ret[i, j] = r['ann_ret']
        grid_n[i, j] = int(r['n'])

    fig, ax = plt.subplots(figsize=(13, 7))
    vmax = float(np.nanmax(np.abs(grid_sharpe - np.nanmean(grid_sharpe))))
    centered = grid_sharpe - np.nanmean(grid_sharpe)
    im = ax.imshow(centered, cmap='RdYlGn', vmin=-vmax, vmax=vmax, aspect='auto')

    for i in range(4):
        for j in range(4):
            if np.isnan(grid_sharpe[i, j]):
                continue
            text = (f"Sharpe {grid_sharpe[i,j]:+.2f}\n"
                    f"ann {grid_ret[i,j]:+.1%}\n"
                    f"n={grid_n[i,j]:,}")
            color = 'black' if abs(centered[i, j]) < vmax * 0.6 else 'white'
            ax.text(j, i, text, ha='center', va='center',
                    fontsize=10, color=color, fontweight='bold')

    ax.set_xticks(range(4))
    ax.set_yticks(range(4))
    ax.set_xticklabels([s.replace('B: ', '') for s in sysB_order],
                       rotation=15, ha='right')
    ax.set_yticklabels([s.replace('A: ', '') for s in sysA_order])
    ax.set_xlabel('System B: beta_mkt x beta_mz_h126')
    ax.set_ylabel('System A: RAFI x VRP')
    ax.set_title(
        f'Layered regime fit -- forward {h}BD Sharpe by intersection cell\n'
        f'centered on corpus mean Sharpe  |  '
        f'corpus mean ann_ret {result["corpus_mean_ann"]:+.1%}',
        fontsize=11,
    )
    fig.colorbar(im, ax=ax, label='Sharpe - corpus mean Sharpe')
    out_path.parent.mkdir(parents=True, exist_ok=True)
    plt.tight_layout()
    fig.savefig(out_path, dpi=110)
    plt.close(fig)


def current_layered_snapshot(panel: pd.DataFrame) -> pd.DataFrame:
    """For each ticker at latest date: which combined cell does it sit in?"""
    df = _assign_quadrants(panel)
    asof = df['date'].max()
    snap = (df.sort_values('date')
              .groupby('ticker', as_index=False)
              .last()
              [['ticker', 'date', 'sysA', 'sysB',
                'divergence', 'vrp_own_pct',
                'beta_mkt_252d', 'beta_mz_h126']])
    snap['cell'] = snap['sysA'].astype(str) + '  |  ' + snap['sysB'].astype(str)
    return snap, asof


def main():
    print('Loading joint panel (RAFI + VRP + beta_mkt + beta_mz)...')
    panel = load_joint_panel()
    print(f'  {len(panel):,} rows | {panel["ticker"].nunique()} tickers')

    for h in (21, 63, 126):
        r = compare_systems(panel, forward_bd=h)
        print(f'\n=== Forward {h} BD ===')
        print(f'\nSystem A: RAFI x VRP  (n_obs={r["n_obs"]:,})')
        print(r['sysA'][['sysA','n','ann_ret','ann_vol','ann_sharpe','hit']]
              .to_string(index=False, formatters={
                  'ann_ret': '{:+.2%}'.format,
                  'ann_vol': '{:.2%}'.format,
                  'ann_sharpe': '{:+.2f}'.format,
                  'hit': '{:.1%}'.format}))
        sa = r['sysA']
        spread_A = sa['ann_ret'].max() - sa['ann_ret'].min()
        sharpe_spread_A = sa['ann_sharpe'].max() - sa['ann_sharpe'].min()

        print(f'\nSystem B: beta_mkt x beta_mz_h126')
        print(r['sysB'][['sysB','n','ann_ret','ann_vol','ann_sharpe','hit']]
              .to_string(index=False, formatters={
                  'ann_ret': '{:+.2%}'.format,
                  'ann_vol': '{:.2%}'.format,
                  'ann_sharpe': '{:+.2f}'.format,
                  'hit': '{:.1%}'.format}))
        sb = r['sysB']
        spread_B = sb['ann_ret'].max() - sb['ann_ret'].min()
        sharpe_spread_B = sb['ann_sharpe'].max() - sb['ann_sharpe'].min()

        print(f'\nSpreads (best-worst quadrant):')
        print(f'  System A: ann_ret spread {spread_A:+.2%}  sharpe spread {sharpe_spread_A:+.2f}')
        print(f'  System B: ann_ret spread {spread_B:+.2%}  sharpe spread {sharpe_spread_B:+.2f}')

    # IC at h=63 (one horizon for paper)
    print('\n=== Cross-sectional IC (Spearman, per-date) at h=63 BD ===')
    ic = cross_sectional_ic(panel, forward_bd=63)
    print(f'Number of dates: {len(ic)}')
    print(f'IC A (RAFI x VRP):    mean={ic["ic_A"].mean():+.4f}  '
          f't={ic["ic_A"].mean() / (ic["ic_A"].std()/np.sqrt(len(ic))):+.2f}  '
          f'hit_rate={(ic["ic_A"] > 0).mean():.1%}')
    print(f'IC B (bmkt x bmz):    mean={ic["ic_B"].mean():+.4f}  '
          f't={ic["ic_B"].mean() / (ic["ic_B"].std()/np.sqrt(len(ic))):+.2f}  '
          f'hit_rate={(ic["ic_B"] > 0).mean():.1%}')
    print()
    print('Reading: lower richness score = "this regime fit says BULLISH on this stock."')
    print('NEGATIVE IC = the score predicts forward returns (lower score -> higher return).')

    # Cross-tab of agreement at h=63
    r = compare_systems(panel, forward_bd=63)
    print('\n=== Quadrant agreement (system A rows x system B cols) ===')
    print(r['cross_tab'].to_string())

    # Save IC series for later
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ic.to_csv(OUT_DIR / 'regime_compare_ic_h63.csv', index=False)

    # 4x4 layered cell analysis
    print('\n=== Layered 4x4 cell analysis ===')
    for h in (21, 63, 126):
        lr = layered_cell_analysis(panel, forward_bd=h)
        print(f'\nForward {h} BD - corpus mean {lr["corpus_mean_ann"]:+.2%} ann')
        print('Top 4 cells by Sharpe:')
        print(lr['cells'].head(4)[['sysA','sysB','n','ann_ret','ann_vol','ann_sharpe','hit']]
              .to_string(index=False, formatters={
                  'ann_ret': '{:+.2%}'.format,
                  'ann_vol': '{:.2%}'.format,
                  'ann_sharpe': '{:+.2f}'.format,
                  'hit': '{:.1%}'.format}))
        print('Bottom 4 cells by Sharpe:')
        print(lr['cells'].tail(4)[['sysA','sysB','n','ann_ret','ann_vol','ann_sharpe','hit']]
              .to_string(index=False, formatters={
                  'ann_ret': '{:+.2%}'.format,
                  'ann_vol': '{:.2%}'.format,
                  'ann_sharpe': '{:+.2f}'.format,
                  'hit': '{:.1%}'.format}))
        print(f'L/S spread (best - worst ann_ret): {lr["ls_spread_ann_ret"]:+.2%}')

        if h == 63:
            heatmap_path = OUT_DIR / 'regime_compare_heatmap_h63.png'
            plot_layered_heatmap(lr, heatmap_path)
            print(f'  heatmap saved')
            lr['cells'].to_csv(OUT_DIR / 'regime_compare_cells_h63.csv', index=False)

    snap, asof = current_layered_snapshot(panel)
    snap_path = OUT_DIR / f'regime_compare_current_cells_{asof.date()}.csv'
    snap.to_csv(snap_path, index=False)
    print(f'\nCurrent cell snapshot ({asof.date()}): {len(snap)} tickers')
    print('\nCell membership (sorted by cell):')
    by_cell = snap.groupby('cell')['ticker'].apply(lambda s: ', '.join(sorted(s))).reset_index()
    by_cell['n'] = snap.groupby('cell').size().values
    by_cell = by_cell.sort_values('n', ascending=False)
    for _, r in by_cell.iterrows():
        print(f'  [{r["n"]:>2}] {r["cell"]}')
        print(f'        {r["ticker"]}')


if __name__ == '__main__':
    main()
