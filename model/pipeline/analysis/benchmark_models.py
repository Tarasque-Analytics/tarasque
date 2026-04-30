"""
benchmark_models.py — HAR-RV and GARCH(1,1) benchmark comparison.

Runs walk-forward HAR-RV and GARCH(1,1) on every ticker/horizon and
compares R², RMSE, and QLIKE against the ensemble model stored in
the prediction files.

Models
------
  HAR-RV      Corsi (2009): RV_{t+h} = β0 + βd·RV_d + βw·RV_w + βm·RV_m
              RV_d = daily |ret|·√252, RV_w = 5-day avg, RV_m = 22-day avg.
              Expanding-window OLS, refit every step_days.

  GARCH(1,1)  σ²_t = ω + α·ε²_{t-1} + β·σ²_{t-1}
              h-step-ahead vol = √(mean(σ²_1..h)·252), expanding window,
              refit every step_days.

  Ensemble    y_pred from existing predictions_{ticker}_H{h}.csv.

Walk-forward
------------
  min_train = 252 (1 calendar year) — benchmarks need fewer obs than ensemble
  step_days = 25  (matching BacktestConfig)
  window    = expanding

Usage
-----
    python -m model.pipeline.analysis.benchmark_models
    python -m model.pipeline.analysis.benchmark_models --tickers AAPL JPM XOM
    python -m model.pipeline.analysis.benchmark_models --workers 6
"""
import argparse
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from ..utils import DECIMAL_PRECISION, round_for_output

warnings.filterwarnings("ignore")

RESULTS_DIR  = Path("model/pipeline/results")
OHLCV_DIR    = Path("data_cache/ohlcv")
MIN_TRAIN    = 252    # ~1 year — benchmarks need far fewer obs
STEP_DAYS    = 20    # matches BacktestConfig.step_days
HORIZONS     = [21, 63, 126]
QLIKE_FLOOR  = 1e-6  # prevent div-by-zero in QLIKE


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _qlike(y: np.ndarray, yhat: np.ndarray) -> float:
    yhat = np.maximum(yhat, QLIKE_FLOOR)
    y    = np.maximum(y,    QLIKE_FLOOR)
    return float(np.mean(y / yhat - np.log(y / yhat) - 1))


def _r2(y: np.ndarray, yhat: np.ndarray) -> float:
    ss_res = np.sum((y - yhat) ** 2)
    ss_tot = np.sum((y - np.mean(y)) ** 2)
    return float(1 - ss_res / ss_tot) if ss_tot > 1e-12 else np.nan


def _rmse(y: np.ndarray, yhat: np.ndarray) -> float:
    return float(np.sqrt(np.mean((y - yhat) ** 2)))


def load_ohlcv_returns(ticker: str) -> pd.Series:
    """Load daily log returns for ticker from OHLCV parquet."""
    d = OHLCV_DIR / f"ticker={ticker}"
    files = list(d.glob("*.parquet"))
    if not files:
        return pd.Series(dtype=float)
    df = pd.read_parquet(files[0]).sort_values("date").reset_index(drop=True)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")["ret"].dropna()
    return df


def compute_har_features(ret: pd.Series) -> pd.DataFrame:
    """
    Daily absolute-return RV proxy and HAR cascade features.

    rv_1d  = |ret_t| * sqrt(252)
    rv_5d  = mean(rv_1d_{t-4:t}) * sqrt(252)  [weekly avg]
    rv_22d = mean(rv_1d_{t-21:t}) * sqrt(252)  [monthly avg]
    """
    rv = ret.abs() * np.sqrt(252)
    feats = pd.DataFrame({
        "rv_1d":  rv,
        "rv_5d":  rv.rolling(5,  min_periods=5).mean(),
        "rv_22d": rv.rolling(22, min_periods=22).mean(),
    })
    return feats


# ---------------------------------------------------------------------------
# Per-ticker walk-forward
# ---------------------------------------------------------------------------

def _garch_h_forecast(omega: float, alpha: float, beta: float,
                      sigma2: float, epsilon2: float, h: int) -> float:
    """
    GARCH(1,1) h-step-ahead mean variance from current state.

    σ²_{t+1}   = ω + α·ε²_t + β·σ²_t
    σ²_{t+k}   = ω + (α+β)·σ²_{t+k-1}   for k > 1
    Returns annualized vol: sqrt(mean(σ²_1..h) * 252) / 100  (pct→fraction).
    """
    sig2 = np.empty(h)
    sig2[0] = omega + alpha * epsilon2 + beta * sigma2
    ab = alpha + beta
    for k in range(1, h):
        sig2[k] = omega + ab * sig2[k - 1]
    return float(np.sqrt(np.mean(sig2) * 252) / 100)


def run_ticker(ticker: str) -> list[dict]:
    """
    Run HAR-RV and GARCH(1,1) WFA for one ticker across all horizons.
    Returns list of result dicts.
    """
    from arch import arch_model as garch_model
    from sklearn.linear_model import LinearRegression

    # ── Load returns & precompute HAR features ───────────────────────────
    ret = load_ohlcv_returns(ticker)
    if len(ret) < MIN_TRAIN + max(HORIZONS):
        return []
    har_feats = compute_har_features(ret)
    ret_arr   = ret.values                # fraction returns
    ret_pct   = ret_arr * 100             # percent returns for arch

    # ── Load ensemble predictions (y_true + y_pred) per horizon ─────────
    # New schema: per-ticker CSV with all horizons stacked. Split by horizon
    # in-memory and keep the same {h: DataFrame} shape for downstream code.
    pred_data = {}
    fp = RESULTS_DIR / f"predictions_{ticker}.csv"
    if fp.exists():
        full = pd.read_csv(fp, parse_dates=["date"])
        if "horizon" in full.columns:
            for h in HORIZONS:
                sub = full[full["horizon"] == h]
                if not sub.empty:
                    pred_data[h] = sub.drop(columns=["horizon"]).set_index("date")

    if not pred_data:
        return []

    # ── Build a date→return index to retrieve returns by prediction date ──
    ret_date_idx = {d: i for i, d in enumerate(ret.index)}

    results = []

    for h in HORIZONS:
        if h not in pred_data:
            continue
        pred_df = pred_data[h]

        # Align HAR features to prediction dates
        aligned_feats = har_feats.reindex(pred_df.index).ffill()

        dates  = pred_df.index.to_numpy()
        y_true = pred_df["y_true"].values
        y_ens  = pred_df["y_pred"].values

        har_preds   = np.full(len(dates), np.nan)
        garch_preds = np.full(len(dates), np.nan)

        # WFA step boundaries
        step_idxs = list(range(MIN_TRAIN, len(dates), STEP_DAYS))
        if not step_idxs or step_idxs[-1] < len(dates) - 1:
            step_idxs.append(len(dates))

        last_har_model    = None
        garch_omega       = None
        garch_alpha       = None
        garch_beta        = None
        garch_cond_vol    = None  # fitted conditional volatility series (pct)

        for si, step_end in enumerate(step_idxs):
            step_start = step_idxs[si - 1] if si > 0 else MIN_TRAIN
            if step_start >= len(dates):
                break

            # ── Fit HAR on data up to step_start ─────────────────────────
            X_train = aligned_feats.iloc[:step_start].dropna()
            if len(X_train) > 10:
                yt_train = pred_df["y_true"].reindex(X_train.index).dropna()
                Xt = X_train.reindex(yt_train.index).dropna()
                yt = yt_train.reindex(Xt.index)
                if len(Xt) > 10:
                    lr = LinearRegression()
                    lr.fit(Xt.values, yt.values)
                    last_har_model = lr

            # ── Fit GARCH on returns up to step_start ────────────────────
            # Map step boundary date to return index
            boundary_date = dates[step_start - 1]
            if boundary_date in ret_date_idx:
                ri = ret_date_idx[boundary_date]
                train_ret_pct = ret_pct[:ri + 1]
                if len(train_ret_pct) > 50:
                    try:
                        am = garch_model(train_ret_pct, vol="GARCH", p=1, q=1,
                                         dist="normal", mean="Constant")
                        res = am.fit(disp="off", show_warning=False)
                        garch_omega     = float(res.params["omega"])
                        garch_alpha     = float(res.params["alpha[1]"])
                        garch_beta      = float(res.params["beta[1]"])
                        garch_cond_vol  = np.asarray(res.conditional_volatility)  # σ_t in pct
                    except Exception:
                        pass

            # ── Predict for current step window ──────────────────────────
            step_slice = slice(step_start, min(step_end, len(dates)))
            step_dates = dates[step_slice]

            # HAR
            if last_har_model is not None:
                X_test = aligned_feats.reindex(pd.DatetimeIndex(step_dates)).ffill()
                valid  = X_test.notna().all(axis=1)
                if valid.any():
                    preds = last_har_model.predict(X_test[valid].values)
                    preds = np.maximum(preds, 1e-4)
                    idxs  = np.where(valid)[0] + step_slice.start
                    har_preds[idxs] = preds

            # GARCH: update conditional variance day-by-day with actual returns
            if garch_omega is not None and garch_cond_vol is not None:
                # Initial sigma² at boundary (last fitted value, in pct²)
                if len(garch_cond_vol) > 0:
                    cur_sigma2  = garch_cond_vol[-1] ** 2
                    cur_eps2    = (train_ret_pct[-1] - float(res.params["mu"]) if "mu" in res.params.index else 0.0) ** 2

                    for row_i, test_date in enumerate(step_dates):
                        abs_idx = step_slice.start + row_i
                        # h-step ahead vol from current GARCH state
                        ann_vol = _garch_h_forecast(
                            garch_omega, garch_alpha, garch_beta,
                            cur_sigma2, cur_eps2, h)
                        garch_preds[abs_idx] = max(ann_vol, 1e-4)

                        # Update sigma² with actual next-day return (no look-ahead)
                        if test_date in ret_date_idx:
                            ri_next = ret_date_idx[test_date]
                            r_next  = ret_pct[ri_next]
                            mu      = float(float(res.params["mu"]) if "mu" in res.params.index else 0.0)
                            next_sig2 = garch_omega + garch_alpha * cur_eps2 + \
                                        garch_beta  * cur_sigma2
                            cur_sigma2 = next_sig2
                            cur_eps2   = (r_next - mu) ** 2

        # ── Compute metrics ───────────────────────────────────────────────
        mask = (np.isfinite(y_true) & np.isfinite(y_ens) &
                (y_true > 0) & (y_ens > 0))
        har_mask  = mask & np.isfinite(har_preds)  & (har_preds  > 0)
        garch_mask = mask & np.isfinite(garch_preds) & (garch_preds > 0)

        def metrics(yt, yp, name):
            return {
                "ticker": ticker, "horizon": h, "model": name,
                "r2":   _r2(yt, yp),
                "rmse": _rmse(yt, yp),
                "qlike": _qlike(yt, yp),
                "n":    len(yt),
            }

        if mask.sum() > 20:
            results.append(metrics(y_true[mask], y_ens[mask], "Ensemble"))
        if har_mask.sum() > 20:
            results.append(metrics(y_true[har_mask], har_preds[har_mask], "HAR-RV"))
        if garch_mask.sum() > 20:
            results.append(metrics(y_true[garch_mask], garch_preds[garch_mask], "GARCH(1,1)"))

    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="HAR / GARCH benchmark")
    parser.add_argument("--tickers", nargs="+", default=None,
                        help="Subset of tickers (default: all with prediction files)")
    parser.add_argument("--workers", type=int, default=4,
                        help="Parallel workers (default: 4)")
    args = parser.parse_args()

    # Discover tickers from prediction files (new long-form per-ticker schema)
    all_tickers = sorted({
        f.stem.replace("predictions_", "")
        for f in RESULTS_DIR.glob("predictions_*.csv")
        if f.name != "all_predictions.csv"
        and not f.stem.endswith("_cal")
    })
    tickers = args.tickers if args.tickers else all_tickers
    print(f"[BENCH] {len(tickers)} tickers  |  horizons {HORIZONS}  |  "
          f"{args.workers} workers")
    print(f"[BENCH] Models: Ensemble vs HAR-RV vs GARCH(1,1)\n")

    all_results = []
    done = 0

    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(run_ticker, t): t for t in tickers}
        for fut in as_completed(futures):
            ticker = futures[fut]
            try:
                rows = fut.result()
                all_results.extend(rows)
            except Exception as e:
                print(f"  [WARN] {ticker}: {e}")
            done += 1
            if done % 10 == 0:
                print(f"  {done}/{len(tickers)} tickers done...")

    if not all_results:
        print("[BENCH] No results. Check OHLCV data availability.")
        return

    df = pd.DataFrame(all_results)

    # Save full results
    out_path = RESULTS_DIR / "benchmark_comparison.csv"
    round_for_output(df, DECIMAL_PRECISION).to_csv(out_path, index=False)
    print(f"\n[BENCH] Full results saved -> {out_path}")

    # ── Summary table ────────────────────────────────────────────────────
    print()
    print("=" * 72)
    print("  BENCHMARK SUMMARY  —  mean R² across all tickers")
    print("=" * 72)
    summary = df.groupby(["horizon", "model"])[["r2", "rmse", "qlike"]].mean()
    print(summary.round(4).to_string())

    print()
    print("=" * 72)
    print("  R² BY HORIZON  (ticker median / mean)")
    print("=" * 72)
    for h in HORIZONS:
        sub = df[df.horizon == h].pivot(index="ticker", columns="model", values="r2")
        print(f"\n  H={h}")
        for model in ["Ensemble", "HAR-RV", "GARCH(1,1)"]:
            if model in sub.columns:
                col = sub[model].dropna()
                print(f"    {model:<14}  median={col.median():.3f}  "
                      f"mean={col.mean():.3f}  "
                      f"p10={col.quantile(0.1):.3f}  p90={col.quantile(0.9):.3f}")

    print()
    print("=" * 72)
    print("  ENSEMBLE LIFT OVER HAR-RV  (mean ΔR² = Ensemble − HAR)")
    print("=" * 72)
    for h in HORIZONS:
        sub = df[df.horizon == h].pivot(index="ticker", columns="model", values="r2")
        if "Ensemble" in sub and "HAR-RV" in sub:
            delta = (sub["Ensemble"] - sub["HAR-RV"]).dropna()
            beats = (delta > 0).sum()
            print(f"  H={h}:  mean ΔR²={delta.mean():+.3f}  "
                  f"beats HAR in {beats}/{len(delta)} tickers")

    print()
    print("=" * 72)
    print("  ENSEMBLE LIFT OVER GARCH  (mean ΔR² = Ensemble − GARCH)")
    print("=" * 72)
    for h in HORIZONS:
        sub = df[df.horizon == h].pivot(index="ticker", columns="model", values="r2")
        if "Ensemble" in sub and "GARCH(1,1)" in sub:
            delta = (sub["Ensemble"] - sub["GARCH(1,1)"]).dropna()
            beats = (delta > 0).sum()
            print(f"  H={h}:  mean ΔR²={delta.mean():+.3f}  "
                  f"beats GARCH in {beats}/{len(delta)} tickers")
    print("=" * 72)


if __name__ == "__main__":
    main()
