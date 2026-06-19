"""
plot.py — Per-firm price-vs-RAFI divergence visualization.

For each per-ticker divergence CSV in data_cache/sec_fundamentals/divergence/,
draw a log-axis chart with:
  - blue line: split-adjusted price, indexed to 1.0 at canonical 2014-01-02
  - red line: RAFI fundamental composite, indexed to 1.0 at canonical
  - dotted gray verticals: structural breaks (real M&A only, splits filtered)
  - gold annotation: latest divergence value
  - title: range / median / latest / break count

Both series are already 1.0 at canonical date in the CSV (price_index and
rafi_composite columns from divergence.py); we plot them directly. The gap
between the two lines is the divergence itself — wide = price has run rich
vs the economic footprint; narrow = mean-reverted; below = cheap.

Run:
    python -m model.pipeline.fundamentals.plot              # all CSVs
    python -m model.pipeline.fundamentals.plot CVX AAPL     # specific tickers
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import matplotlib
matplotlib.use('Agg')  # headless backend
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[3]
DIV_DIR = REPO_ROOT / 'data_cache' / 'sec_fundamentals' / 'divergence'
PLOTS_DIR = DIV_DIR / 'plots'


def plot_one(csv_path: Path) -> Optional[Path]:
    """Render one divergence chart. Returns the saved PNG path, or None if skipped."""
    df = pd.read_csv(csv_path, parse_dates=['date'])
    df = df.dropna(subset=['divergence']).sort_values('date').reset_index(drop=True)
    if df.empty:
        return None

    ticker = (df['ticker'].iloc[0] if 'ticker' in df.columns
              else csv_path.stem.replace('_divergence', ''))

    fig, ax = plt.subplots(figsize=(12, 6))
    ax.set_yscale('log')

    ax.plot(df['date'], df['price_index'],
            label='Price (split-adjusted, =1 at 2014-01-02)',
            linewidth=1.8, color='#1f77b4')
    ax.plot(df['date'], df['rafi_composite'],
            label='RAFI composite (rev/ocf/book/dps, =1 at 2014-01-02)',
            linewidth=1.8, color='#d62728')

    # Horizontal reference at the canonical anchor
    ax.axhline(1.0, color='black', linewidth=0.6, linestyle='--', alpha=0.4)

    # Structural break markers (event days only, M&A signature)
    if 'structural_break' in df.columns:
        breaks = df[df['structural_break'].fillna(False).astype(bool)]
        for _, b in breaks.iterrows():
            ax.axvline(b['date'], color='gray', linewidth=1.0,
                       alpha=0.55, linestyle=':')

    # Annotate latest divergence value
    last = df.iloc[-1]
    div = df['divergence']
    ax.annotate(
        f"Div = {last['divergence']:.2f}",
        xy=(last['date'], last['price_index']),
        xytext=(8, 8), textcoords='offset points',
        fontsize=10, fontweight='bold',
        bbox=dict(boxstyle='round,pad=0.3',
                  facecolor='lightyellow', edgecolor='goldenrod', alpha=0.85),
    )

    title = (
        f'{ticker}: Price vs RAFI fundamental footprint  '
        f'(canonical 2014-01-02, log axis)\n'
        f'Divergence range [{div.min():.2f}, {div.max():.2f}], '
        f'median {div.median():.2f}, '
        f'latest {div.iloc[-1]:.2f}, '
        f'breaks {int(df["structural_break"].fillna(False).sum())}, '
        f'n_legs_latest {int(last.get("n_legs_present", 0))}'
    )
    ax.set_title(title, fontsize=11)
    ax.set_xlabel('Date')
    ax.set_ylabel('Index (log)')
    ax.legend(loc='upper left', fontsize=9, framealpha=0.9)
    ax.grid(True, alpha=0.3, which='both')

    PLOTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = PLOTS_DIR / f'{ticker}_divergence.png'
    plt.tight_layout()
    fig.savefig(out_path, dpi=100)
    plt.close(fig)
    return out_path


def main():
    tickers = [t.upper() for t in sys.argv[1:]] if len(sys.argv) > 1 else None
    if tickers:
        csvs = [DIV_DIR / f'{t}_divergence.csv' for t in tickers]
        csvs = [p for p in csvs if p.exists()]
    else:
        csvs = sorted(DIV_DIR.glob('*_divergence.csv'))

    print(f'Plotting {len(csvs)} divergence file(s)...')
    n_ok = n_skip = n_fail = 0
    for csv in csvs:
        try:
            path = plot_one(csv)
            if path is not None:
                n_ok += 1
            else:
                n_skip += 1
                print(f'  skip: {csv.stem} (no valid divergence rows)')
        except Exception as e:
            n_fail += 1
            print(f'  FAIL: {csv.stem}: {e}')
    print(f'Done: {n_ok} plots, {n_skip} skipped, {n_fail} failed -> {PLOTS_DIR.relative_to(REPO_ROOT)}')


if __name__ == '__main__':
    main()
