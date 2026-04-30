"""Volatility-forecast curve for AAPL — model PCHIP spline vs market IV term structure.

Reads the most recent AAPL prediction date from all_predictions.csv, picks the
y_pred at H=21/63/126, fits a monotonic cubic (PCHIP) spline through them, and
compares against the same-day IV term structure (delta=50, days=30/60/91/182)
from data_cache/vsurfd. Layout follows model/mockup_apr2/specific_ticker_page.png.

Output: aapl_vol_forecast.png in this directory.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.interpolate import PchipInterpolator

HERE = Path(__file__).resolve().parent
PRED_CSV = HERE / "all_predictions.csv"
VSURFD_DIR = HERE.parents[2] / "data_cache" / "vsurfd"
OUT_PNG = HERE / "aapl_vol_forecast.png"

TICKER = "AAPL"
HORIZONS = [21, 63, 126]
IV_DAYS = [30, 60, 91, 182]
ATM_DELTA = 50.0


def _last_pred_per_horizon(df: pd.DataFrame) -> pd.DataFrame:
    aapl = df[df["ticker"] == TICKER].copy()
    aapl["date"] = pd.to_datetime(aapl["date"])
    last_date = aapl["date"].max()
    snap = aapl[aapl["date"] == last_date].set_index("horizon").loc[HORIZONS]
    return last_date, snap


def _iv_term_structure(ticker: str, asof: pd.Timestamp) -> pd.DataFrame:
    parts = list((VSURFD_DIR / f"ticker={ticker}").glob("*.parquet"))
    if not parts:
        raise FileNotFoundError(f"no vsurfd parquet for {ticker}")
    vs = pd.concat([pd.read_parquet(p) for p in parts], ignore_index=True)
    vs["date"] = pd.to_datetime(vs["date"])
    asof_ts = pd.Timestamp(asof)
    on_or_before = vs[vs["date"] <= asof_ts]
    if on_or_before.empty:
        raise ValueError(f"no vsurfd rows on or before {asof_ts.date()}")
    snap_date = on_or_before["date"].max()
    snap = (
        on_or_before[on_or_before["date"] == snap_date]
        .query("delta == @ATM_DELTA and days in @IV_DAYS")
        .drop_duplicates(subset=["days"])
        .set_index("days")
        .reindex(IV_DAYS)
    )
    return snap_date, snap["impl_volatility"]


def main() -> None:
    preds = pd.read_csv(PRED_CSV)
    asof, snap = _last_pred_per_horizon(preds)
    iv_date, iv = _iv_term_structure(TICKER, asof)

    model_x = np.array(HORIZONS, dtype=float)
    model_y = snap["y_pred"].to_numpy(dtype=float)
    q15_y = snap["y_pred_q15"].to_numpy(dtype=float)

    iv_x = np.array(IV_DAYS, dtype=float)
    iv_y = iv.to_numpy(dtype=float)

    grid_x = np.linspace(1, 126, 252)
    model_curve = PchipInterpolator(model_x, model_y, extrapolate=True)(grid_x)
    q15_curve = PchipInterpolator(model_x, q15_y, extrapolate=True)(grid_x)
    iv_grid = np.linspace(max(grid_x.min(), iv_x.min()), grid_x.max(), 252)
    iv_curve = PchipInterpolator(iv_x, iv_y, extrapolate=True)(iv_grid)

    fig, ax = plt.subplots(figsize=(11, 5.5), dpi=140)

    ax.text(
        0.04, 0.92, "[Future]", transform=ax.transAxes,
        fontsize=42, color="#d6d6d6", ha="left", va="top",
        fontweight="bold", zorder=0,
    )

    market_color = "#2f9e44"
    model_color = "#1c7ed6"
    q15_color = "#94a3b8"

    ax.plot(iv_grid, iv_curve, color=market_color, lw=2.2,
            label="Market Implied Vol (ATM)")
    ax.scatter(iv_x, iv_y, color=market_color, s=42, zorder=5,
               edgecolor="white", linewidth=1.0)

    ax.plot(grid_x, model_curve, color=model_color, lw=2.2,
            label="Model Baseline Vol (PCHIP)")
    ax.scatter(model_x, model_y, color=model_color, s=58, zorder=6,
               edgecolor="white", linewidth=1.2)

    ax.plot(grid_x, q15_curve, color=q15_color, lw=1.4, ls="--",
            label="Model P15 Floor")
    ax.scatter(model_x, q15_y, color=q15_color, s=30, zorder=4,
               edgecolor="white", linewidth=0.8)

    for x, y in zip(model_x, model_y):
        ax.annotate(
            f"H{int(x)}\n{y * 100:.2f}%",
            xy=(x, y), xytext=(8, 14), textcoords="offset points",
            color=model_color, fontsize=8.5, fontweight="bold",
        )
    for x, y in zip(iv_x, iv_y):
        ax.annotate(
            f"{int(x)}d\n{y * 100:.2f}%",
            xy=(x, y), xytext=(8, -20), textcoords="offset points",
            color=market_color, fontsize=8.5, fontweight="bold",
        )

    wedge_x = 126
    wedge_top = float(PchipInterpolator(iv_x, iv_y, extrapolate=True)(wedge_x))
    wedge_bot = float(model_curve[-1])
    wedge_pct = (wedge_top - wedge_bot) * 100
    ax.annotate(
        "",
        xy=(wedge_x + 1.5, wedge_top),
        xytext=(wedge_x + 1.5, wedge_bot),
        arrowprops=dict(arrowstyle="<->", color="#444", lw=1.3),
    )
    ax.text(
        wedge_x + 4.5, (wedge_top + wedge_bot) / 2,
        f"{wedge_pct:.1f}%\nWedge",
        fontsize=9, fontweight="bold", color="#222", va="center",
    )

    title = f"Volatility Forecast {TICKER}"
    subtitle = (
        f"Forecast as of {asof.date()}  ·  IV snap {iv_date.date()}  ·  "
        f"H21={model_y[0] * 100:.2f}%  H63={model_y[1] * 100:.2f}%  "
        f"H126={model_y[2] * 100:.2f}%"
    )
    ax.set_title(title, loc="left", fontsize=15, fontweight="bold", pad=14)
    ax.text(0.0, 1.015, subtitle, transform=ax.transAxes,
            fontsize=9.5, color="#555")

    ax.set_xlabel("Trading days forward")
    ax.set_ylabel("Annualized volatility")
    ax.set_xlim(0, 138)
    ax.set_ylim(
        min(min(model_y.min(), q15_y.min()), iv_y.min()) - 0.015,
        max(model_y.max(), iv_y.max()) + 0.025,
    )
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v * 100:.0f}%"))
    ax.grid(True, ls=":", lw=0.6, color="#d0d0d0", alpha=0.7)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)

    ax.legend(loc="upper left", frameon=False, fontsize=9.5)

    fig.tight_layout()
    fig.savefig(OUT_PNG, bbox_inches="tight")
    print(f"wrote {OUT_PNG}")


if __name__ == "__main__":
    main()
