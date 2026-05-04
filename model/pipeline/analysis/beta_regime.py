"""
beta_regime.py — 2x2 regime visualization: market beta x MZ beta.

Conceptual frame:
  - beta_mkt < 1 + beta_mz <= 1 : "Genuinely calm" — model and reality agree.
  - beta_mkt < 1 + beta_mz  > 1 : "Stealth event-risk" — model misses idiosyncratic shocks
                                  on names that look defensive on traditional metrics.
                                  Most actionable quadrant — pharma readouts, utility rate
                                  cases, regulatory cycles.
  - beta_mkt >= 1 + beta_mz <= 1: "Mega-cap liquidity buffer" — features expect spikes,
                                  realized vol muted by depth (AMZN, GOOGL, NEE).
  - beta_mkt >= 1 + beta_mz  > 1: "Idiosyncratic + systematic" — already cyclical, plus
                                  unmodeled shock clustering (AAPL, BA-737, RTX-merger).

Inputs:
  - mz_calibration.csv         (per ticker, per horizon — ew_beta column)
  - data_cache/ohlcv parquet   (for rolling 252d market beta vs SPY)

Outputs:
  - regime_2x2.csv             (ticker, beta_mkt, beta_mz_h21/63/126, quadrant_h21)
  - regime_2x2_h{21,63,126}.png

Run:
    python -m model.pipeline.analysis.beta_regime
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from ..config import load_config
from ..data_loader import ParquetStore
from ..utils import DECIMAL_PRECISION, round_for_output


REPO_ROOT = Path(__file__).resolve().parents[3]
RESULTS_DIR = REPO_ROOT / "model" / "pipeline" / "results"
WINDOW = 252  # rolling window for market beta


def compute_market_beta(closes: pd.DataFrame, ticker: str, mkt: str = "SPY") -> float:
    """Final-window 252d market beta vs SPY using log returns."""
    if ticker not in closes.columns or mkt not in closes.columns:
        return np.nan
    ret_t = np.log(closes[ticker] / closes[ticker].shift(1))
    ret_m = np.log(closes[mkt] / closes[mkt].shift(1))
    common = ret_t.dropna().index.intersection(ret_m.dropna().index)
    if len(common) < WINDOW:
        return np.nan
    rt = ret_t.loc[common].iloc[-WINDOW:]
    rm = ret_m.loc[common].iloc[-WINDOW:]
    cov = np.cov(rt, rm, ddof=1)[0, 1]
    var_m = rm.var(ddof=1)
    return float(cov / var_m) if var_m > 0 else np.nan


def classify(beta_mkt: float, beta_mz: float) -> str:
    if pd.isna(beta_mkt) or pd.isna(beta_mz):
        return "n/a"
    if beta_mkt < 1.0 and beta_mz <= 1.0:
        return "Q3-genuinely-calm"
    if beta_mkt < 1.0 and beta_mz > 1.0:
        return "Q1-stealth-event-risk"
    if beta_mkt >= 1.0 and beta_mz <= 1.0:
        return "Q4-mega-cap-buffer"
    return "Q2-idiosync-plus-systematic"


def build_panel(mz_source: str = "mz_calibration.csv",
                beta_col: str = "ew_beta") -> pd.DataFrame:
    """Join MZ betas with market betas; classify each ticker into quadrant.

    mz_source: filename within RESULTS_DIR. Default mz_calibration.csv (post-
    overlay, full corpus). Pass v9_canary_mz_calibration.csv to use the v9
    canary 12-ticker numbers instead.
    beta_col: column in the MZ csv to pivot on. "ew_beta" (default), "ols_beta"
    (raw OLS, no exp-weighting), or any other column present in the source.
    """
    mz_path = RESULTS_DIR / mz_source
    if not mz_path.exists():
        raise FileNotFoundError(f"Need {mz_path}; run mz_overlay or stack first.")
    mz = pd.read_csv(mz_path)
    if beta_col not in mz.columns:
        raise ValueError(f"Column {beta_col!r} not in {mz_source}: "
                         f"have {list(mz.columns)}")

    # Pivot MZ betas to ticker x horizon
    mz_wide = mz.pivot(index="ticker", columns="horizon", values=beta_col)
    mz_wide.columns = [f"beta_mz_h{h}" for h in mz_wide.columns]

    # Compute market beta per ticker from cached OHLCV
    dc, _, _ = load_config()
    store = ParquetStore(dc.base_dir)
    ohlcv = store.load("ohlcv")
    ohlcv["date"] = pd.to_datetime(ohlcv["date"], format="mixed")
    closes = ohlcv.pivot(index="date", columns="ticker", values="prc").ffill()

    rows = []
    for tk in mz_wide.index:
        rows.append({
            "ticker": tk,
            "beta_mkt": compute_market_beta(closes, tk),
        })
    mkt = pd.DataFrame(rows).set_index("ticker")

    panel = mz_wide.join(mkt, how="left")
    for h in (21, 63, 126):
        panel[f"quadrant_h{h}"] = [
            classify(b_mkt, b_mz)
            for b_mkt, b_mz in zip(panel["beta_mkt"], panel[f"beta_mz_h{h}"])
        ]
    return panel.reset_index()


def plot_panel(panel: pd.DataFrame, horizon: int, out_path: Path) -> None:
    """Single-panel scatter for the given horizon."""
    fig, ax = plt.subplots(figsize=(10, 8))

    bm = panel["beta_mkt"].values
    bz = panel[f"beta_mz_h{horizon}"].values
    tk = panel["ticker"].values

    # Quadrant shading
    ax.axhline(1.0, color="gray", linewidth=0.8, alpha=0.7)
    ax.axvline(1.0, color="gray", linewidth=0.8, alpha=0.7)

    # Color by quadrant
    color_map = {
        "Q1-stealth-event-risk":          "#d62728",  # red
        "Q2-idiosync-plus-systematic":    "#ff7f0e",  # orange
        "Q3-genuinely-calm":              "#2ca02c",  # green
        "Q4-mega-cap-buffer":             "#1f77b4",  # blue
        "n/a":                            "#999999",
    }
    quadrants = panel[f"quadrant_h{horizon}"].values
    colors = [color_map[q] for q in quadrants]

    ax.scatter(bm, bz, c=colors, s=70, alpha=0.7, edgecolor="black", linewidth=0.5)
    for x, y, t in zip(bm, bz, tk):
        if pd.notna(x) and pd.notna(y):
            ax.annotate(t, (x, y), fontsize=7, alpha=0.85,
                        xytext=(3, 3), textcoords="offset points")

    ax.set_xlabel("Market beta (252d rolling, vs SPY)")
    ax.set_ylabel(f"MZ beta H={horizon} (EW from prior corpus run)")
    ax.set_title(
        f"Regime 2x2: Market beta vs MZ beta (H={horizon})\n"
        "Q1=stealth-event-risk | Q2=idiosync+systematic | "
        "Q3=genuinely-calm | Q4=mega-cap-buffer"
    )

    # Quadrant labels in corners
    xlim, ylim = ax.get_xlim(), ax.get_ylim()
    ax.text(xlim[0] + 0.02 * (xlim[1] - xlim[0]),
            ylim[1] - 0.04 * (ylim[1] - ylim[0]),
            "Q1: Stealth event-risk", fontsize=10,
            color="#d62728", fontweight="bold", verticalalignment="top")
    ax.text(xlim[1] - 0.02 * (xlim[1] - xlim[0]),
            ylim[1] - 0.04 * (ylim[1] - ylim[0]),
            "Q2: Idiosync + systematic", fontsize=10,
            color="#ff7f0e", fontweight="bold",
            horizontalalignment="right", verticalalignment="top")
    ax.text(xlim[0] + 0.02 * (xlim[1] - xlim[0]),
            ylim[0] + 0.04 * (ylim[1] - ylim[0]),
            "Q3: Genuinely calm", fontsize=10,
            color="#2ca02c", fontweight="bold")
    ax.text(xlim[1] - 0.02 * (xlim[1] - xlim[0]),
            ylim[0] + 0.04 * (ylim[1] - ylim[0]),
            "Q4: Mega-cap buffer", fontsize=10,
            color="#1f77b4", fontweight="bold",
            horizontalalignment="right")

    ax.grid(True, alpha=0.25)
    plt.tight_layout()
    plt.savefig(out_path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    print(f"[BETA_REGIME] Wrote {out_path}")


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--mz-source", default="mz_calibration.csv",
                    help="Filename within results/ (default: mz_calibration.csv)")
    ap.add_argument("--beta-col", default="ew_beta",
                    help="Column to pivot on (default: ew_beta; use ols_beta "
                         "for raw uncalibrated)")
    ap.add_argument("--label-suffix", default="",
                    help="Suffix appended to output filenames (e.g. '_v9')")
    args = ap.parse_args()

    panel = build_panel(mz_source=args.mz_source, beta_col=args.beta_col)
    panel = round_for_output(panel, DECIMAL_PRECISION)

    suffix = args.label_suffix
    out_csv = RESULTS_DIR / f"regime_2x2{suffix}.csv"
    panel.to_csv(out_csv, index=False)
    print(f"[BETA_REGIME] Wrote {out_csv.name} ({len(panel)} tickers)")

    for h in (21, 63, 126):
        plot_panel(panel, h, RESULTS_DIR / f"regime_2x2{suffix}_h{h}.png")

    # Quadrant counts summary (H=21 primary)
    print()
    print(f"Quadrant distribution (H=21, mz_source={args.mz_source}, "
          f"beta_col={args.beta_col}):")
    print(panel["quadrant_h21"].value_counts().to_string())


if __name__ == "__main__":
    main()
