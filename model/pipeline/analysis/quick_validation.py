"""
quick_validation.py — three sanity checks on the v10+ corpus headline R² claims.

Test 1: naive long-window baseline (H=126).
    "Predict next 126d log-RV using rolling 252d mean of y_true (lagged 126d)."
    If model R² doesn't beat naive R² by >= 0.10, the H=126 number is mostly
    horizon mean-reversion, not skill.

Test 2: period-stratified R².
    Slice the prediction set into pre-2020 / 2020-2021 / post-2021 and recompute
    R² per chunk per horizon. Flags whether the headline R² is being carried by
    one regime.

Test 4: calm vs stress regime R².
    Stratify each prediction by SPY rolling 21d realized vol AT prediction date.
    Buckets: calm (< P33), normal (P33-P67), stress (> P67). Annualised SPY RV
    correlates ~0.95 with VIX so this is a clean substitute. Tells us whether
    the model performs uniformly or only in one regime.

All three tests read `model/pipeline/results/all_predictions.csv` (or the
per-ticker fallback) and SPY OHLCV from the parquet cache. Outputs:
  results/validation/test1_naive_baseline_h126.csv
  results/validation/test2_period_stratified_r2.csv
  results/validation/test4_regime_stratified_r2.csv
  results/validation/quick_validation_summary.md
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ..config import DataConfig
from ..data_loader import ParquetStore
from ..utils import DECIMAL_PRECISION, round_for_output


REPO_ROOT = Path(__file__).resolve().parents[3]
RESULTS = REPO_ROOT / "model" / "pipeline" / "results"
VALIDATION = RESULTS / "validation"
VALIDATION.mkdir(parents=True, exist_ok=True)


def _r2(y: np.ndarray, yhat: np.ndarray) -> float:
    y = np.asarray(y, dtype=float)
    yhat = np.asarray(yhat, dtype=float)
    mask = np.isfinite(y) & np.isfinite(yhat)
    if mask.sum() < 30:
        return float("nan")
    y, yhat = y[mask], yhat[mask]
    ss_res = float(((y - yhat) ** 2).sum())
    ss_tot = float(((y - y.mean()) ** 2).sum())
    if ss_tot == 0:
        return float("nan")
    return 1.0 - ss_res / ss_tot


def _rmse(y: np.ndarray, yhat: np.ndarray) -> float:
    y = np.asarray(y, dtype=float)
    yhat = np.asarray(yhat, dtype=float)
    mask = np.isfinite(y) & np.isfinite(yhat)
    if mask.sum() == 0:
        return float("nan")
    return float(np.sqrt(np.mean((y[mask] - yhat[mask]) ** 2)))


def load_predictions() -> pd.DataFrame:
    src = RESULTS / "all_predictions.csv"
    if src.exists():
        df = pd.read_csv(src, parse_dates=["date"])
    else:
        files = sorted(RESULTS.glob("predictions_*.csv"))
        files = [f for f in files if "_baseline" not in f.name]
        if not files:
            raise FileNotFoundError("No predictions found (all_predictions.csv or per-ticker)")
        df = pd.concat([pd.read_csv(f, parse_dates=["date"]) for f in files], ignore_index=True)
    df["horizon"] = df["horizon"].astype(int)
    return df


# ---------- Test 1: naive 252d baseline at H=126 ----------

def test1_naive_baseline(df: pd.DataFrame) -> pd.DataFrame:
    """Naive baseline: rolling 252d mean of y_true, lagged by H days.

    Lagging by H is required because at prediction date t we'd only know
    y_true[<= t - H] (since y_true at date t is the realized vol from t to t+H).
    Practically: shift by H BDays after the rolling mean.
    """
    rows = []
    for h in sorted(df["horizon"].unique()):
        sub = df[df["horizon"] == h].sort_values(["ticker", "date"]).copy()
        # rolling 252d mean of y_true per ticker, then lag by h to make it
        # information available at prediction date
        sub["naive"] = (
            sub.groupby("ticker", observed=True)["y_true"]
            .transform(lambda s: s.rolling(252, min_periods=126).mean().shift(h))
        )
        mask = sub[["y_true", "y_pred", "naive"]].notna().all(axis=1)
        s = sub[mask]
        rows.append({
            "horizon": int(h),
            "n": int(len(s)),
            "n_tickers": int(s["ticker"].nunique()),
            "model_r2": _r2(s["y_true"], s["y_pred"]),
            "naive_r2": _r2(s["y_true"], s["naive"]),
            "model_rmse": _rmse(s["y_true"], s["y_pred"]),
            "naive_rmse": _rmse(s["y_true"], s["naive"]),
        })
    out = pd.DataFrame(rows)
    out["delta_r2"] = out["model_r2"] - out["naive_r2"]
    return out


# ---------- Test 2: period-stratified R² ----------

def test2_period_stratified(df: pd.DataFrame) -> pd.DataFrame:
    bins = [
        ("pre-2020", "2014-01-01", "2019-12-31"),
        ("2020-2021", "2020-01-01", "2021-12-31"),
        ("post-2021", "2022-01-01", "2099-12-31"),
    ]
    rows = []
    for h in sorted(df["horizon"].unique()):
        sub = df[df["horizon"] == h]
        for label, start, end in bins:
            ts = pd.Timestamp(start)
            te = pd.Timestamp(end)
            s = sub[(sub["date"] >= ts) & (sub["date"] <= te)]
            mask = s[["y_true", "y_pred"]].notna().all(axis=1)
            s = s[mask]
            rows.append({
                "horizon": int(h),
                "period": label,
                "date_start": s["date"].min() if len(s) else pd.NaT,
                "date_end": s["date"].max() if len(s) else pd.NaT,
                "n": int(len(s)),
                "n_tickers": int(s["ticker"].nunique()),
                "r2": _r2(s["y_true"], s["y_pred"]),
                "rmse": _rmse(s["y_true"], s["y_pred"]),
                "y_true_mean": float(s["y_true"].mean()) if len(s) else float("nan"),
            })
    return pd.DataFrame(rows)


# ---------- Test 4: regime-stratified R² ----------

def _spy_rolling_rv(window: int = 21) -> pd.DataFrame:
    """Annualised rolling realized vol of SPY from the parquet cache.

    Uses log-returns on the adjusted close (cum-return implied close from CRSP
    returns when CRSP, raw close otherwise). Returns DataFrame (date, spy_rv).
    """
    dc = DataConfig()
    store = ParquetStore(dc.base_dir)
    spy = store.load("ohlcv", tickers=["SPY"]).copy()
    spy["date"] = pd.to_datetime(spy["date"], format="mixed")
    spy = spy.sort_values("date").reset_index(drop=True)
    # build adj close from ret if available, else fall back to prc
    if "ret" in spy.columns and spy["ret"].notna().any():
        spy["adj_close"] = (1.0 + spy["ret"].fillna(0.0)).cumprod()
    else:
        spy["adj_close"] = spy["prc"]
    spy["log_ret"] = np.log(spy["adj_close"]).diff()
    # rolling 21d std of daily log-ret, annualized
    spy["spy_rv"] = spy["log_ret"].rolling(window).std() * np.sqrt(252)
    return spy[["date", "spy_rv"]].dropna()


def test4_regime_stratified(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    spy = _spy_rolling_rv(window=21)
    df = df.merge(spy, on="date", how="left")
    # define regime by terciles of SPY 21d RV across full sample
    p33, p67 = df["spy_rv"].quantile([0.33, 0.67]).values
    df["regime"] = np.where(df["spy_rv"] < p33, "calm",
                    np.where(df["spy_rv"] < p67, "normal", "stress"))
    rows = []
    for h in sorted(df["horizon"].unique()):
        sub = df[df["horizon"] == h]
        for reg in ["calm", "normal", "stress"]:
            s = sub[sub["regime"] == reg]
            mask = s[["y_true", "y_pred"]].notna().all(axis=1)
            s = s[mask]
            rows.append({
                "horizon": int(h),
                "regime": reg,
                "n": int(len(s)),
                "n_tickers": int(s["ticker"].nunique()),
                "spy_rv_mean": float(s["spy_rv"].mean()) if len(s) else float("nan"),
                "r2": _r2(s["y_true"], s["y_pred"]),
                "rmse": _rmse(s["y_true"], s["y_pred"]),
                "y_true_mean": float(s["y_true"].mean()) if len(s) else float("nan"),
                "model_bias": float((s["y_pred"] - s["y_true"]).mean()) if len(s) else float("nan"),
            })
    cuts = pd.DataFrame({
        "regime": ["calm", "normal", "stress"],
        "spy_rv_lower": [float(df["spy_rv"].min()), float(p33), float(p67)],
        "spy_rv_upper": [float(p33), float(p67), float(df["spy_rv"].max())],
    })
    return pd.DataFrame(rows), cuts


# ---------- Driver ----------

def write_summary_md(test1: pd.DataFrame, test2: pd.DataFrame,
                     test4: pd.DataFrame, cuts: pd.DataFrame) -> None:
    today = pd.Timestamp.today().strftime("%Y-%m-%d")
    lines = [
        "# Quick Validation — Sanity Checks on v10+ R² Headline",
        "",
        f"_Generated {today}. n=55 tickers, in-sample WFA predictions._",
        "",
        "## Test 1 — Naive long-window baseline (lagged 252d rolling mean)",
        "",
        "| Horizon | n | Model R² | Naive R² | Δ R² | Verdict |",
        "|---|---|---|---|---|---|",
    ]
    for _, r in test1.iterrows():
        verdict = "skill" if r["delta_r2"] >= 0.10 else \
                  "thin" if r["delta_r2"] >= 0.05 else \
                  "horizon-driven (concern)"
        lines.append(
            f"| H={int(r['horizon'])} | {int(r['n']):,} | {r['model_r2']:.3f} | "
            f"{r['naive_r2']:.3f} | {r['delta_r2']:+.3f} | {verdict} |"
        )
    lines += [
        "",
        "**Read:** Δ R² is the lift of the trained model over a naive lagged-252d-mean baseline.",
        ">= 0.10 = real skill at that horizon. < 0.05 = the realized-vol mean-reverts and the headline R² is mostly horizon mechanics.",
        "",
        "## Test 2 — Period-stratified R²",
        "",
        "| Horizon | Period | n | R² | RMSE | y_true mean |",
        "|---|---|---|---|---|---|",
    ]
    for _, r in test2.iterrows():
        lines.append(
            f"| H={int(r['horizon'])} | {r['period']} | {int(r['n']):,} | "
            f"{r['r2']:.3f} | {r['rmse']:.4f} | {r['y_true_mean']:.4f} |"
        )
    lines += [
        "",
        "**Read:** Look for big swings in R² across periods. If post-2021 R² is much lower than full-sample R², the headline is mostly historical and the model isn't tracking the current regime.",
        "",
        "## Test 4 — Calm vs stress regime R² (SPY 21d RV terciles)",
        "",
        "Regime cutoffs (annualised SPY rolling 21d RV):",
        "",
        "| Regime | RV lower | RV upper |",
        "|---|---|---|",
    ]
    for _, r in cuts.iterrows():
        lines.append(f"| {r['regime']} | {r['spy_rv_lower']:.3f} | {r['spy_rv_upper']:.3f} |")
    lines += [
        "",
        "| Horizon | Regime | n | R² | RMSE | y_true mean | Model bias (pred - true) |",
        "|---|---|---|---|---|---|---|",
    ]
    for _, r in test4.iterrows():
        lines.append(
            f"| H={int(r['horizon'])} | {r['regime']} | {int(r['n']):,} | "
            f"{r['r2']:.3f} | {r['rmse']:.4f} | {r['y_true_mean']:.4f} | "
            f"{r['model_bias']:+.4f} |"
        )
    lines += [
        "",
        "**Read:** Vol models typically deliver 0.55+ R² in calm regimes (vol is well-anchored to lagged vol) and 0.20-0.30 in stress (regime breaks). A flatter profile across regimes is exceptional. Bias column shows over- (+) or under-prediction (−) per regime.",
        "",
        "## What this can't tell us",
        "",
        "These tests all read the same in-sample WFA prediction set. They cannot diagnose CV leakage. To prove generalization we still need a true held-out OOS slice (Test 3 — see `claude_context.md` deferred validation block) where the model is trained on `< 2024-01-01` and scored cold on 2024-2025.",
    ]
    out_path = VALIDATION / "quick_validation_summary.md"
    out_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    print("[QV] Loading predictions...")
    df = load_predictions()
    print(f"[QV] {len(df):,} rows, horizons={sorted(df['horizon'].unique())}, "
          f"tickers={df['ticker'].nunique()}, "
          f"dates={df['date'].min().date()} -> {df['date'].max().date()}")

    print("[QV] Test 1: naive baseline...")
    test1 = test1_naive_baseline(df)
    test1 = round_for_output(test1, DECIMAL_PRECISION)
    test1.to_csv(VALIDATION / "test1_naive_baseline.csv", index=False)
    print(test1.to_string(index=False))

    print()
    print("[QV] Test 2: period-stratified R²...")
    test2 = test2_period_stratified(df)
    test2 = round_for_output(test2, DECIMAL_PRECISION)
    test2.to_csv(VALIDATION / "test2_period_stratified_r2.csv", index=False)
    print(test2.to_string(index=False))

    print()
    print("[QV] Test 4: regime-stratified R² (SPY 21d RV terciles)...")
    test4, cuts = test4_regime_stratified(df)
    test4 = round_for_output(test4, DECIMAL_PRECISION)
    cuts = round_for_output(cuts, DECIMAL_PRECISION)
    test4.to_csv(VALIDATION / "test4_regime_stratified_r2.csv", index=False)
    cuts.to_csv(VALIDATION / "test4_regime_cutoffs.csv", index=False)
    print("Cutoffs:")
    print(cuts.to_string(index=False))
    print()
    print(test4.to_string(index=False))

    print()
    write_summary_md(test1, test2, test4, cuts)
    print(f"[QV] Wrote summary to {VALIDATION / 'quick_validation_summary.md'}")


if __name__ == "__main__":
    main()
