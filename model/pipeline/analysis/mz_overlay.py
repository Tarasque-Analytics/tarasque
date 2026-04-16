"""
mz_overlay.py — MZ calibration overlay + term structure enforcement.

Applies two post-processing corrections to raw model predictions:

  1. MZ Calibration Overlay
     For each (ticker, horizon), fits an exponentially-weighted MZ regression:
         y_true = alpha + beta * y_pred
     using all walk-forward (out-of-sample) predictions, with most-recent
     observations weighted highest (lambda=0.003). Applies:
         y_cal = alpha_ew + beta_ew * y_pred
     This corrects systematic level bias without retraining.

  2. Term Structure Enforcement
     After per-horizon calibration, ensures H21 <= H63 <= H126 on each date.
     Uses a tolerance-based isotonic pass: inversions within `tol` fraction
     are left alone (genuine spike-regime inversions); inversions beyond `tol`
     are pooled to their average (calibration artifact).

Outputs
-------
  results/mz_calibration.csv        — alpha/beta/r2 per (ticker, horizon)
  results/all_predictions_cal.csv   — all_predictions with y_cal column
  results/payloads/*_Payload.json   — payloads updated in-place with
                                       calibrated series + forecast_rv

Usage
-----
    python -m model.pipeline.analysis.mz_overlay
    python -m model.pipeline.analysis.mz_overlay --lam 0.005 --tol 0.05
"""
import argparse
import json
from datetime import timezone, datetime
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
RESULTS_DIR = Path("model/pipeline/results")
PAYLOADS_DIR = RESULTS_DIR / "payloads"
EW_LAM   = 0.003   # exponential weighting decay (same as audit EW MZ)
TS_TOL   = 0.05    # inversion tolerance before enforcement kicks in (5%)
EW_BETA_CAP = 2.0  # maximum allowed EW beta — prevents extreme corrections for
                   # tickers with structural data breaks (e.g. VZ H126 ~2.6)
CAL_MAX  = 1.5     # hard ceiling on calibrated vol (150% ann.) — a sanity guard,
                   # not a normal constraint; values near this should be flagged


# ---------------------------------------------------------------------------
# EW MZ regression
# ---------------------------------------------------------------------------

def ew_mz(y_true: np.ndarray, y_pred: np.ndarray, lam: float):
    """
    Fit exponentially-weighted MZ regression: y_true = alpha + beta * y_pred.
    Weights increase from oldest (index 0) to newest (index n-1).

    Returns (alpha, beta, ew_r2, n).
    """
    n = len(y_true)
    idx = np.arange(n, dtype=float)
    w = np.exp(lam * idx)
    w /= w.sum()

    # Weighted means
    xbar = np.dot(w, y_pred)
    ybar = np.dot(w, y_true)

    # Weighted covariance / variance
    cov = np.dot(w, (y_pred - xbar) * (y_true - ybar))
    var = np.dot(w, (y_pred - xbar) ** 2)

    if var < 1e-12:
        return 0.0, 1.0, np.nan, n

    beta  = cov / var
    alpha = ybar - beta * xbar

    # EW R²
    ss_res = np.dot(w, (y_true - (alpha + beta * y_pred)) ** 2)
    ss_tot = np.dot(w, (y_true - ybar) ** 2)
    r2 = 1 - ss_res / ss_tot if ss_tot > 1e-12 else np.nan

    return float(alpha), float(beta), float(r2), int(n)


# ---------------------------------------------------------------------------
# Term structure enforcement (soft, tolerance-based isotonic pass)
# ---------------------------------------------------------------------------

def enforce_term_structure(h21: np.ndarray, h63: np.ndarray, h126: np.ndarray,
                           tol: float = TS_TOL):
    """
    Soft isotonic pass on (H21, H63, H126) arrays (element-wise per date).

    Inversions within `tol` fraction of the smaller value are left unchanged
    (treated as genuine spike-regime inversions). Inversions beyond `tol` are
    pooled to their weighted average — the longer horizon carries 60% weight
    since it has a smoother underlying signal.

    Returns (h21_out, h63_out, h126_out).
    """
    h21, h63, h126 = h21.copy(), h63.copy(), h126.copy()

    # H21 vs H63
    inv_mask = h21 > h63 * (1 + tol)
    if inv_mask.any():
        blend = 0.4 * h21[inv_mask] + 0.6 * h63[inv_mask]
        h21[inv_mask] = blend
        h63[inv_mask] = blend

    # H63 vs H126
    inv_mask = h63 > h126 * (1 + tol)
    if inv_mask.any():
        blend = 0.4 * h63[inv_mask] + 0.6 * h126[inv_mask]
        h63[inv_mask] = blend
        h126[inv_mask] = blend

    # Ensure positivity
    floor = 1e-4
    h21  = np.maximum(h21,  floor)
    h63  = np.maximum(h63,  floor)
    h126 = np.maximum(h126, floor)

    return h21, h63, h126


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(lam: float = EW_LAM, tol: float = TS_TOL):
    # ── Load all prediction files ────────────────────────────────────────────
    pred_files = sorted(RESULTS_DIR.glob("predictions_*_H*.csv"))
    print(f"[OVERLAY] Loading {len(pred_files)} prediction files...")

    # Build per-(ticker, horizon) dataframes
    data: dict[tuple, pd.DataFrame] = {}
    for f in pred_files:
        stem = f.stem  # predictions_AAPL_H21
        ticker_part, h_part = stem.rsplit("_H", 1)
        ticker  = ticker_part.replace("predictions_", "")
        horizon = int(h_part)
        df = pd.read_csv(f, parse_dates=["date"])
        df = df.sort_values("date").reset_index(drop=True)
        data[(ticker, horizon)] = df

    tickers  = sorted({t for t, _ in data})
    horizons = sorted({h for _, h in data})
    print(f"[OVERLAY] {len(tickers)} tickers  |  horizons {horizons}")

    # ── Fit EW MZ per (ticker, horizon) ─────────────────────────────────────
    cal_rows = []
    for (ticker, horizon), df in data.items():
        mask = np.isfinite(df["y_true"]) & np.isfinite(df["y_pred"]) & \
               (df["y_pred"] > 0) & (df["y_true"] > 0)
        yt = df.loc[mask, "y_true"].values
        yp = df.loc[mask, "y_pred"].values

        alpha, beta, r2, n = ew_mz(yt, yp, lam)

        # Cap beta to prevent extreme corrections from structural data breaks
        beta_capped = min(beta, EW_BETA_CAP)
        if beta_capped < beta:
            # Recompute alpha using capped beta so the weighted mean is still met
            xbar_ew = float(np.dot(np.exp(lam * np.arange(len(yt))) /
                                   np.exp(lam * np.arange(len(yt))).sum(), yp))
            ybar_ew = float(np.dot(np.exp(lam * np.arange(len(yt))) /
                                   np.exp(lam * np.arange(len(yt))).sum(), yt))
            alpha = ybar_ew - beta_capped * xbar_ew
        beta = beta_capped

        # Apply calibration; floor at small positive, ceiling at sanity cap
        y_cal = np.where(mask,
                         np.clip(alpha + beta * df["y_pred"].values, 1e-4, CAL_MAX),
                         np.nan)
        data[(ticker, horizon)] = df.assign(y_cal=y_cal)

        alpha_raw, beta_raw, _, _ = ew_mz(yt, yp, lam)  # uncapped, for reference
        cal_rows.append({
            "ticker": ticker, "horizon": horizon,
            "ew_alpha": alpha, "ew_beta": beta,
            "ew_beta_raw": round(beta_raw, 6),
            "ew_r2": r2, "n": n,
            "beta_capped": beta_raw > EW_BETA_CAP,
        })

    cal_df = pd.DataFrame(cal_rows).sort_values(["ticker", "horizon"])
    out_cal = RESULTS_DIR / "mz_calibration.csv"
    cal_df.to_csv(out_cal, index=False)
    print(f"[OVERLAY] Calibration params saved -> {out_cal}")
    print(f"          EW beta range: "
          f"{cal_df.ew_beta.min():.3f} – {cal_df.ew_beta.max():.3f}  "
          f"(mean {cal_df.ew_beta.mean():.3f})")

    # ── Term structure enforcement ───────────────────────────────────────────
    print(f"[OVERLAY] Applying term structure enforcement (tol={tol:.0%})...")
    inv_before = inv_after = 0

    for ticker in tickers:
        keys = [(ticker, h) for h in [21, 63, 126] if (ticker, h) in data]
        if len(keys) < 3:
            continue

        df21  = data[(ticker, 21)]
        df63  = data[(ticker, 63)]
        df126 = data[(ticker, 126)]

        # Align on date
        merged = df21[["date", "y_cal"]].rename(columns={"y_cal": "c21"}) \
            .merge(df63[["date",  "y_cal"]].rename(columns={"y_cal": "c63"}),  on="date") \
            .merge(df126[["date", "y_cal"]].rename(columns={"y_cal": "c126"}), on="date") \
            .dropna()

        if merged.empty:
            continue

        inv_before += ((merged.c21 > merged.c63) | (merged.c63 > merged.c126)).sum()

        c21_e, c63_e, c126_e = enforce_term_structure(
            merged.c21.values, merged.c63.values, merged.c126.values, tol)

        inv_after += ((c21_e > c63_e) | (c63_e > c126_e)).sum()

        # Write back enforced values via merge to avoid any datetime key issues
        enforced_df = pd.DataFrame({
            "date":  merged["date"].values,
            "c21":   c21_e,
            "c63":   c63_e,
            "c126":  c126_e,
        })
        for df_ref, ecol in [
            (data[(ticker, 21)],  "c21"),
            (data[(ticker, 63)],  "c63"),
            (data[(ticker, 126)], "c126"),
        ]:
            merged_back = df_ref.merge(
                enforced_df[["date", ecol]], on="date", how="left")
            df_ref["y_cal"] = merged_back[ecol].where(
                merged_back[ecol].notna(), df_ref["y_cal"].values)

    total_dates = sum(len(data[(t, 21)]) for t in tickers if (t, 21) in data)
    print(f"[OVERLAY] Term structure inversions: "
          f"{inv_before:,} -> {inv_after:,}  "
          f"({inv_before/total_dates:.1%} -> {inv_after/total_dates:.1%} of dates)")

    # ── Save calibrated predictions CSV ─────────────────────────────────────
    frames = []
    for (ticker, horizon), df in data.items():
        df = df.copy()
        df["ticker"]  = ticker
        df["horizon"] = horizon
        frames.append(df)
    combined = pd.concat(frames, ignore_index=True)
    out_combined = RESULTS_DIR / "all_predictions_cal.csv"
    combined.to_csv(out_combined, index=False)
    print(f"[OVERLAY] Calibrated predictions saved -> {out_combined}  "
          f"({len(combined):,} rows)")

    # ── Update payloads ──────────────────────────────────────────────────────
    print("[OVERLAY] Updating payloads...")
    updated = skipped = 0

    for ticker in tickers:
        payload_path = PAYLOADS_DIR / f"{ticker}_Payload.json"
        if not payload_path.exists():
            skipped += 1
            continue

        with open(payload_path, encoding="utf-8") as f:
            payload = json.load(f)

        vfs = payload.get("vol_forecast_series", {})
        dates_in_payload = vfs.get("dates", [])
        if not dates_in_payload:
            skipped += 1
            continue

        date_set = set(dates_in_payload)

        # Build date -> y_cal maps for each horizon
        cal_maps = {}
        for h in [21, 63, 126]:
            if (ticker, h) not in data:
                continue
            df = data[(ticker, h)]
            df["date_str"] = df["date"].dt.strftime("%Y-%m-%d")
            cal_maps[h] = dict(zip(df["date_str"], df["y_cal"]))

        # Update series in vol_forecast_series
        for h, key in [(21, "predicted_rv_21d"), (63, "predicted_rv_63d"),
                       (126, "predicted_rv_126d")]:
            if h not in cal_maps:
                continue
            vfs[key] = [cal_maps[h].get(d, raw)
                        for d, raw in zip(dates_in_payload, vfs.get(key, []))]

        # Update the scalar forecast_rv (most recent date)
        if "meta" in payload and "forecast_rv" in payload["meta"]:
            last_date = dates_in_payload[-1]
            for h in [21, 63, 126]:
                if h in cal_maps and last_date in cal_maps[h]:
                    payload["meta"]["forecast_rv"][str(h)] = cal_maps[h][last_date]

        # Add per-horizon calibration params
        h_cal = {}
        for row in cal_rows:
            if row["ticker"] == ticker:
                h_cal[row["horizon"]] = {
                    "ew_alpha": round(row["ew_alpha"], 6),
                    "ew_beta":  round(row["ew_beta"],  6),
                    "ew_r2":    round(row["ew_r2"],    6) if row["ew_r2"] == row["ew_r2"] else None,
                }
        if h_cal:
            payload["calibration"]["mz_overlay"] = h_cal
            payload["calibration"]["overlay_lam"] = lam
            payload["calibration"]["ts_tol"]      = tol

        payload["meta"]["timestamp"] = datetime.now(timezone.utc).isoformat()

        with open(payload_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, separators=(",", ":"))

        updated += 1

    print(f"[OVERLAY] Payloads updated: {updated}  |  skipped: {skipped}")

    # ── Summary stats ────────────────────────────────────────────────────────
    print()
    print("=" * 60)
    print("  MZ OVERLAY SUMMARY")
    print("=" * 60)
    for h in horizons:
        sub = cal_df[cal_df.horizon == h]
        print(f"  H={h:<3}  EW beta  mean={sub.ew_beta.mean():.3f}  "
              f"min={sub.ew_beta.min():.3f}  max={sub.ew_beta.max():.3f}  "
              f"|  passes (0.9-1.1): {((sub.ew_beta >= 0.9) & (sub.ew_beta <= 1.1)).sum()}/{len(sub)}")
    print()
    print(f"  Term structure inversion rate after overlay: "
          f"{inv_after / total_dates:.1%}  (was {inv_before/total_dates:.1%})")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="MZ calibration overlay")
    parser.add_argument("--lam",  type=float, default=EW_LAM,
                        help=f"EW decay lambda (default {EW_LAM})")
    parser.add_argument("--tol",  type=float, default=TS_TOL,
                        help=f"Term structure inversion tolerance (default {TS_TOL})")
    args = parser.parse_args()
    run(lam=args.lam, tol=args.tol)


if __name__ == "__main__":
    main()
