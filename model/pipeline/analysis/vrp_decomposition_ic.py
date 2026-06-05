"""
vrp_decomposition_ic.py — How much of VRP_ewma's +0.40 IC is the CLASSICAL
                           backward VRP vs a FORWARD-looking variant?

Background
----------
Current `vrp_wedge` in features.py is the classical academic definition:
    vrp_wedge = iv_atm_30d - rv_21d           # IV minus PAST realized vol

The user's question (and §3 of RESEARCH_TODO): would a forward-looking VRP
carry more signal? Specifically:

  VRP_classical    = IV - rv_21d_backward      # current vrp_wedge
  VRP_model_fwd    = IV - σ̂_model              # uses our forecast as expected fwd vol
  VRP_oracle_fwd   = IV - σ̂_oracle              # uses ACTUAL realized fwd vol (lookahead)

If oracle has materially higher IC than classical, a forward-looking VRP is
the better signal. If oracle ≈ classical, the classical definition was right
all along.

IV reconstruction: vrp_wedge = IV − rv_21d, and rv_21d at date D equals
y_true at date (D − 21 BD). So IV(D) = vrp_wedge(D) + y_true(D − 21 BD).

Predictors tested (3, then EWMA-smoothed):
  vrp_classical_ewma  = EWMA21(IV - rv_21d_backward)
  vrp_model_fwd_ewma  = EWMA21(IV - y_pred)
  vrp_oracle_fwd_ewma = EWMA21(IV - y_true)

Targets (forward, from CRSP closes):
  fwd_vol_h{21,63,126} · fwd_absret_h{21,63,126} · fwd_ret_h{21,63,126}
  · fwd_dd_h{21,63,126}

Outputs:
  results/validation/vrp_decomp_ic.csv
  results/validation/vrp_decomp_summary.md

Usage:
  python -m model.pipeline.analysis.vrp_decomposition_ic
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ..config import load_config
from ..data_loader import ParquetStore

REPO_ROOT = Path(__file__).resolve().parents[3]
RESULTS_DIR = REPO_ROOT / "model" / "pipeline" / "results"
OUT_DIR = RESULTS_DIR / "validation"

HORIZONS = (21, 63, 126)
METRICS = ("vol", "absret", "ret", "dd")
PREDICTORS = ("vrp_classical_ewma", "vrp_model_fwd_ewma", "vrp_oracle_fwd_ewma")
EWMA_HALFLIFE = 21
ROLL_TARGET_HORIZON = 21        # use H=21 rows for IV reconstruction (vrp_wedge derived from rv_21d)
MIN_OBS_FOR_IC_POOLED = 200
MIN_OBS_FOR_IC_PERTICKER = 100


def load_predictions_for_ticker(path: Path) -> pd.DataFrame | None:
    try:
        df = pd.read_csv(path, parse_dates=["date"],
                         usecols=["date", "y_true", "y_pred",
                                  "vrp_wedge", "horizon"])
    except Exception:
        return None
    df = df[df["horizon"] == ROLL_TARGET_HORIZON].drop(columns=["horizon"])
    df = df.sort_values("date").drop_duplicates(subset=["date"], keep="last")
    df = df.dropna(subset=["vrp_wedge"]).reset_index(drop=True)
    return df


def add_three_vrps(df: pd.DataFrame) -> pd.DataFrame:
    """Reconstruct IV + compute the three VRP variants + their EWMAs."""
    df = df.copy()
    # rv_21d_backward at date D = y_true at date (D - 21 BD) since y_true for
    # H=21 looks forward 21 BD; the same realized window viewed at its endpoint
    # IS the trailing rv_21d.
    df["rv_21d_back"] = df["y_true"].shift(21)
    # IV reconstruction: vrp_wedge = IV − rv_21d  →  IV = vrp_wedge + rv_21d_back
    df["iv_reconstructed"] = df["vrp_wedge"] + df["rv_21d_back"]

    # Three VRP variants
    df["vrp_classical"]   = df["vrp_wedge"]                          # = IV − rv_21d_back
    df["vrp_model_fwd"]   = df["iv_reconstructed"] - df["y_pred"]    # IV − model forecast
    df["vrp_oracle_fwd"]  = df["iv_reconstructed"] - df["y_true"]    # IV − actual fwd RV (lookahead)

    # EWMA smoothed versions
    for col in ("vrp_classical", "vrp_model_fwd", "vrp_oracle_fwd"):
        df[f"{col}_ewma"] = df[col].ewm(halflife=EWMA_HALFLIFE,
                                         adjust=False).mean()
    return df


def load_closes() -> pd.DataFrame:
    dc, _, _ = load_config()
    s = ParquetStore(dc.base_dir)
    ohlcv = s.load("ohlcv")
    ohlcv["date"] = pd.to_datetime(ohlcv["date"], format="mixed")
    ohlcv = ohlcv.drop_duplicates(subset=["date", "ticker"], keep="last")
    return ohlcv.pivot(index="date", columns="ticker", values="prc").ffill()


def add_forward_outcomes(df: pd.DataFrame, ticker: str,
                          closes: pd.DataFrame) -> pd.DataFrame:
    if ticker not in closes.columns:
        return df
    series = closes[ticker].dropna()
    if series.empty:
        return df
    df = df.copy().reset_index(drop=True)

    snap_close = np.full(len(df), np.nan)
    snap_idx   = np.full(len(df), -1, dtype=int)
    for i, d in enumerate(df["date"].values):
        d = pd.Timestamp(d)
        idx = series.index.searchsorted(d, side="right") - 1
        if 0 <= idx < len(series):
            snap_idx[i]   = idx
            snap_close[i] = series.iloc[idx]
    df["close"] = snap_close
    log_close = np.log(snap_close.astype(float))

    for h in HORIZONS:
        fwd_close = np.full(len(df), np.nan)
        fwd_min   = np.full(len(df), np.nan)
        fwd_vol   = np.full(len(df), np.nan)
        for i in range(len(df)):
            idx = snap_idx[i]
            if idx < 0:
                continue
            j_end = idx + h
            if j_end >= len(series):
                continue
            window = series.iloc[idx + 1: j_end + 1]
            if window.dropna().empty:
                continue
            fwd_close[i] = window.iloc[-1]
            fwd_min[i]   = window.min()
            log_returns  = np.log(window).diff().dropna().values
            if len(log_returns) > 5:
                fwd_vol[i] = float(np.std(log_returns) * np.sqrt(252))

        log_end = np.log(fwd_close)
        log_min = np.log(fwd_min)
        df[f"fwd_ret_h{h}"]    = log_end - log_close
        df[f"fwd_absret_h{h}"] = np.abs(log_end - log_close)
        df[f"fwd_dd_h{h}"]     = log_min - log_close
        df[f"fwd_vol_h{h}"]    = fwd_vol
    return df


def pooled_ic_table(full: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for pred in PREDICTORS:
        for metric in METRICS:
            for h in HORIZONS:
                col = f"fwd_{metric}_h{h}"
                if col not in full.columns:
                    continue
                sub = full.dropna(subset=[pred, col])
                if len(sub) < MIN_OBS_FOR_IC_POOLED:
                    continue
                ic = float(sub[pred].corr(sub[col], method="spearman"))
                rows.append({"predictor": pred, "metric": metric,
                             "horizon": h, "n": len(sub), "ic_pooled": ic})
    return pd.DataFrame(rows)


def perticker_ic_table(full: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for pred in PREDICTORS:
        for metric in METRICS:
            for h in HORIZONS:
                col = f"fwd_{metric}_h{h}"
                if col not in full.columns:
                    continue
                ics = []
                for tk, g in full.groupby("ticker"):
                    sub = g.dropna(subset=[pred, col])
                    if len(sub) < MIN_OBS_FOR_IC_PERTICKER:
                        continue
                    ic = float(sub[pred].corr(sub[col], method="spearman"))
                    if np.isfinite(ic):
                        ics.append(ic)
                if len(ics) < 10:
                    continue
                ics = np.asarray(ics)
                rows.append({"predictor": pred, "metric": metric, "horizon": h,
                             "n_tickers": int(len(ics)),
                             "ic_median": float(np.median(ics)),
                             "ic_mean": float(np.mean(ics)),
                             "frac_abs_above_010": float(np.mean(np.abs(ics) > 0.10))})
    return pd.DataFrame(rows)


def write_summary(pooled: pd.DataFrame, perticker: pd.DataFrame, out: Path) -> None:
    lines = ["# VRP Decomposition IC Test",
             "",
             "Three VRP variants tested. All EWMA(halflife=21)-smoothed.",
             "",
             "- **VRP_classical** = IV − rv_21d_backward (current `vrp_wedge`; +0.40 baseline)",
             "- **VRP_model_fwd** = IV − σ̂_model (uses our ensemble forecast)",
             "- **VRP_oracle_fwd** = IV − σ̂_oracle (uses actual realized fwd vol — LOOKAHEAD, theoretical ceiling)",
             "",
             "## Verdict logic",
             "",
             "- If `vrp_oracle_fwd` IC ≈ `vrp_classical` IC → classical definition is fine,",
             "  no upside from forward framing.",
             "- If `vrp_oracle_fwd` IC > `vrp_classical` IC → forward-looking VRP has a",
             "  higher ceiling; our model just isn't accurate enough to claim it.",
             "- If `vrp_model_fwd` IC > `vrp_classical` IC → our forecast IS good enough",
             "  to construct a better VRP signal than the classical definition.",
             "- If `vrp_model_fwd` < `vrp_classical` < `vrp_oracle_fwd` → forward framing",
             "  is theoretically better but our forecast isn't there yet (room to grow).",
             "",
             "## Pooled IC (all tickers × dates)", ""]
    for metric in METRICS:
        sub = pooled[pooled["metric"] == metric]
        if sub.empty:
            continue
        piv = sub.pivot_table(index="predictor", columns="horizon",
                              values="ic_pooled").reset_index()
        lines += [f"### Forward {metric.upper()}", "",
                  "| predictor | " + " | ".join(f"h={h}" for h in HORIZONS) + " |",
                  "|---|" + "|".join(["---"] * len(HORIZONS)) + "|"]
        for _, r in piv.iterrows():
            cells = [r["predictor"]] + [f"{r.get(h, float('nan')):+.3f}"
                                        for h in HORIZONS]
            lines.append("| " + " | ".join(cells) + " |")
        lines.append("")

    lines += ["## Per-ticker median IC", ""]
    for metric in METRICS:
        sub = perticker[perticker["metric"] == metric]
        if sub.empty:
            continue
        lines += [f"### Forward {metric.upper()}", "",
                  "| predictor | h | n_tickers | ic_median | ic_mean | frac>0.10 |",
                  "|---|---|---|---|---|---|"]
        for _, r in sub.iterrows():
            lines.append(
                f"| {r['predictor']} | {r['horizon']} | {int(r['n_tickers'])} | "
                f"{r['ic_median']:+.3f} | {r['ic_mean']:+.3f} | "
                f"{r['frac_abs_above_010']:.2f} |")
        lines.append("")

    out.write_text("\n".join(lines), encoding="utf-8")


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("[VRP_DECOMP] Loading per-ticker predictions...")
    per_t = {}
    for f in sorted(RESULTS_DIR.glob("predictions_*.csv")):
        ticker = f.stem.replace("predictions_", "")
        df = load_predictions_for_ticker(f)
        if df is None or len(df) < 200:
            continue
        per_t[ticker] = df
    print(f"  {len(per_t)} tickers with sufficient history")

    print("[VRP_DECOMP] Reconstructing IV + computing three VRP variants per ticker...")
    for tk in per_t:
        per_t[tk] = add_three_vrps(per_t[tk])

    print("[VRP_DECOMP] Loading closes for forward outcomes...")
    closes = load_closes()

    print("[VRP_DECOMP] Computing forward outcomes per ticker...")
    pieces = []
    for i, tk in enumerate(sorted(per_t), 1):
        d = add_forward_outcomes(per_t[tk], tk, closes)
        d["ticker"] = tk
        pieces.append(d)
        if i % 20 == 0:
            print(f"  {i}/{len(per_t)}")
    full = pd.concat(pieces, ignore_index=True)
    print(f"[VRP_DECOMP] {len(full):,} total (ticker, date) observations")

    # Quick sanity check on IV reconstruction
    iv_stats = full["iv_reconstructed"].describe()
    print(f"\n[VRP_DECOMP] Reconstructed IV stats (sanity check, should be 0.1-0.8):")
    print(f"  min={iv_stats['min']:.3f}  p25={iv_stats['25%']:.3f}  "
          f"median={iv_stats['50%']:.3f}  p75={iv_stats['75%']:.3f}  "
          f"max={iv_stats['max']:.3f}")

    print("\n[VRP_DECOMP] Pooled IC...")
    pooled = pooled_ic_table(full)
    pooled.to_csv(OUT_DIR / "vrp_decomp_ic.csv", index=False)

    print("[VRP_DECOMP] Per-ticker IC distribution...")
    perticker = perticker_ic_table(full)
    perticker.to_csv(OUT_DIR / "vrp_decomp_perticker.csv", index=False)

    write_summary(pooled, perticker, OUT_DIR / "vrp_decomp_summary.md")
    print(f"\n[VRP_DECOMP] Wrote 3 files to {OUT_DIR}")

    print("\n=== POOLED IC vs forward VOL (the answer) ===")
    sub = pooled[pooled.metric == "vol"]
    piv = sub.pivot_table(index="predictor", columns="horizon",
                          values="ic_pooled")
    with pd.option_context("display.width", 200,
                           "display.float_format", lambda v: f"{v:+.3f}"):
        print(piv.to_string())

    print("\n=== POOLED IC vs forward ABSRET ===")
    sub = pooled[pooled.metric == "absret"]
    piv = sub.pivot_table(index="predictor", columns="horizon",
                          values="ic_pooled")
    with pd.option_context("display.width", 200,
                           "display.float_format", lambda v: f"{v:+.3f}"):
        print(piv.to_string())

    print("\n=== PER-TICKER MEDIAN IC vs forward VOL, h=21 ===")
    sub = perticker[(perticker.metric == "vol") & (perticker.horizon == 21)]
    out = sub[["predictor", "n_tickers", "ic_median", "ic_mean",
               "frac_abs_above_010"]].sort_values("ic_median", ascending=False)
    with pd.option_context("display.width", 200,
                           "display.float_format", lambda v: f"{v:+.3f}"):
        print(out.to_string(index=False))

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
