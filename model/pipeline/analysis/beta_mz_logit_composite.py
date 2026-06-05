"""
beta_mz_logit_composite.py -- Open Test A (+ folds in Test B's OOS concern).

Question: A naive AND/OR of beta_mz + HY spread did NOT beat HY alone (Test 10).
Does a *smart combiner* (logistic regression) of beta_mz level/slope + macro
z-scores (HY spread, yield curve, breakeven, dollar) beat HY-spread-alone at
predicting a forward drawdown shock?

HONESTY GUARDS (this is the whole point of the test):
  - Target is forward-looking (42-BD max DD < -10% on the equal-weight universe),
    so adjacent weekly rows share overlapping windows -> random k-fold would leak.
    We use a PURGED EXPANDING WALK-FORWARD: to score week i we train only on
    weeks [0 .. i - PURGE_WEEKS], so no training label can see into week i's
    forward window. Every reported number is OUT-OF-SAMPLE.
  - HY-alone and beta_mz-alone are scored on the SAME OOS rows with the SAME
    metrics (AUC + top-tercile lift). Apples-to-apples.
  - macro z-scores use trailing 252-BD rolling stats (causal, no lookahead);
    beta_mz is computed from rolling-252-BD WFA predictions (causal).

Outputs:
  results/validation/beta_mz_logit_composite.csv      -- OOS score comparison
  results/validation/beta_mz_logit_oos_predictions.csv -- per-week OOS probs
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# UTF-8 console guard (Windows cp1252 chokes on non-ascii)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.preprocessing import StandardScaler

from .beta_mz_deep_dive import compute_weekly_aggregate, add_slope_signs
from .beta_mz_defensive_overlay import load_macro
from .beta_mz_drawdown_value import (
    load_universe_equal_weighted_index, cumulative_index, forward_window_metrics,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = REPO_ROOT / "model" / "pipeline" / "results" / "validation"

START_DATE = pd.Timestamp("2015-01-01")
SHOCK_HORIZON_BD = 42        # forward window for the drawdown-shock label
SHOCK_DD = -0.10             # "shock" = forward 42-BD max DD < -10%
PURGE_WEEKS = 9              # ~42 BD / 5 -> purge gap so labels can't leak
MIN_TRAIN_WEEKS = 156        # ~3 yrs before we start scoring OOS
MIN_TRAIN_SHOCKS = 6         # need enough positive labels to fit anything sane

FEATURES = ["mean_bmz", "slope_w12", "hy_spread_z", "yield_curve_z",
            "breakeven_5y_z", "dollar_index_z"]


def build_panel() -> pd.DataFrame:
    """Weekly panel: beta_mz features + macro z-scores + forward-DD shock label."""
    daily_ret = load_universe_equal_weighted_index()
    daily_ret = daily_ret[daily_ret.index >= START_DATE]
    price = cumulative_index(daily_ret)

    agg = compute_weekly_aggregate()
    agg_12 = add_slope_signs(agg, window_weeks=12)
    macro = load_macro()

    panel = agg_12[["asof", "mean_bmz", "slope_w12"]].copy()
    # forward 42-BD max DD on the EW universe -> binary shock
    panel["fwd_dd_42"] = panel["asof"].apply(
        lambda d: forward_window_metrics(price, d, SHOCK_HORIZON_BD).get("max_dd", np.nan))
    panel["shock"] = (panel["fwd_dd_42"] < SHOCK_DD).astype(float)

    # attach trailing macro z-scores (causal), as-of each Friday
    macro_z = [c for c in macro.columns if c.endswith("_z")]
    panel = panel.set_index("asof").join(macro[macro_z], how="left").ffill().reset_index()

    panel = panel[panel["asof"] >= START_DATE].copy()
    # rows missing a forward label (recent weeks) can't be scored
    return panel


def _topq_lift(score: np.ndarray, label: np.ndarray, q: float = 2 / 3) -> float:
    """Lift = shock-rate among the top (1-q) fraction by score / base rate."""
    if len(score) == 0 or label.sum() == 0:
        return np.nan
    thresh = np.quantile(score, q)
    top = score >= thresh
    if top.sum() == 0:
        return np.nan
    base = label.mean()
    return float(label[top].mean() / base) if base > 0 else np.nan


def walk_forward_oos(panel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = panel.dropna(subset=FEATURES + ["shock"]).reset_index(drop=True)
    n = len(df)
    X_all = df[FEATURES].to_numpy(dtype=float)
    y_all = df["shock"].to_numpy(dtype=float)

    oos_rows = []
    for i in range(MIN_TRAIN_WEEKS, n):
        train_end = i - PURGE_WEEKS
        if train_end < MIN_TRAIN_WEEKS:
            continue
        ytr = y_all[:train_end]
        if ytr.sum() < MIN_TRAIN_SHOCKS or (len(ytr) - ytr.sum()) < MIN_TRAIN_SHOCKS:
            continue  # need both classes well-represented
        Xtr = X_all[:train_end]
        scaler = StandardScaler().fit(Xtr)
        clf = LogisticRegression(class_weight="balanced", max_iter=1000, C=1.0)
        clf.fit(scaler.transform(Xtr), ytr)
        prob = float(clf.predict_proba(scaler.transform(X_all[i:i + 1]))[0, 1])
        oos_rows.append({
            "asof": df.loc[i, "asof"],
            "shock": y_all[i],
            "composite_prob": prob,
            "hy_spread_z": df.loc[i, "hy_spread_z"],
            "beta_mz_level": df.loc[i, "mean_bmz"],
            "beta_mz_slope": df.loc[i, "slope_w12"],
        })

    oos = pd.DataFrame(oos_rows)

    # Score candidates on the SAME OOS rows.
    #   composite  -> predicted prob (higher = more shock)
    #   HY alone    -> hy_spread_z   (higher = more shock)
    #   beta level  -> -mean_bmz     (LOWER level = more shock, per Test 10)
    #   beta slope  -> slope_w12     (higher slope = more shock)
    candidates = {
        "composite_logit": oos["composite_prob"].to_numpy(),
        "hy_spread_alone": oos["hy_spread_z"].to_numpy(),
        "beta_mz_level_alone": -oos["beta_mz_level"].to_numpy(),
        "beta_mz_slope_alone": oos["beta_mz_slope"].to_numpy(),
    }
    label = oos["shock"].to_numpy()

    rows = []
    for name, score in candidates.items():
        ok = np.isfinite(score) & np.isfinite(label)
        s, l = score[ok], label[ok]
        auc = float(roc_auc_score(l, s)) if l.sum() > 0 and l.sum() < len(l) else np.nan
        rows.append({
            "signal": name,
            "n_oos": int(len(s)),
            "n_shocks": int(l.sum()),
            "base_rate": float(l.mean()),
            "auc": auc,
            "top_tercile_lift": _topq_lift(s, l),
        })
    return pd.DataFrame(rows), oos


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("[BMZ_LOGIT] Building weekly panel (beta_mz + macro + forward-DD label)...")
    panel = build_panel()
    n_lbl = panel["shock"].notna().sum()
    print(f"  {len(panel)} weekly rows, {int(panel['shock'].sum())} shock weeks "
          f"of {int(n_lbl)} labelled (base rate {panel['shock'].mean():.1%})")
    print(f"  shock = forward {SHOCK_HORIZON_BD}-BD max DD < {SHOCK_DD:.0%} on EW universe")

    print("\n[BMZ_LOGIT] Purged expanding walk-forward (OOS)...")
    print(f"  min train {MIN_TRAIN_WEEKS}w | purge {PURGE_WEEKS}w | "
          f"min shocks to fit {MIN_TRAIN_SHOCKS}")
    res, oos = walk_forward_oos(panel)

    print("\n" + "=" * 76)
    print(" OUT-OF-SAMPLE signal comparison (same rows, same metrics)")
    print("=" * 76)
    with pd.option_context("display.width", 200,
                           "display.float_format", lambda v: f"{v:+.3f}"):
        print(res.to_string(index=False))

    # verdict
    comp = res[res.signal == "composite_logit"].iloc[0]
    hy = res[res.signal == "hy_spread_alone"].iloc[0]
    print("\n  VERDICT:")
    if np.isfinite(comp["auc"]) and np.isfinite(hy["auc"]):
        d_auc = comp["auc"] - hy["auc"]
        d_lift = comp["top_tercile_lift"] - hy["top_tercile_lift"]
        print(f"    composite AUC {comp['auc']:+.3f} vs HY-alone {hy['auc']:+.3f} "
              f"(delta {d_auc:+.3f})")
        print(f"    composite lift {comp['top_tercile_lift']:+.2f}x vs HY-alone "
              f"{hy['top_tercile_lift']:+.2f}x (delta {d_lift:+.2f})")
        if d_auc > 0.02 and d_lift > 0:
            print("    => composite BEATS HY alone OOS. Smart combiner adds value.")
        elif d_auc < -0.02:
            print("    => composite LOSES to HY alone OOS. Combiner overfits / adds noise.")
        else:
            print("    => composite ~ HY alone OOS. No clear edge from combining.")
    print(f"\n  (n_oos={int(comp['n_oos'])}, n_shocks={int(comp['n_shocks'])} "
          f"-- small sample; treat as directional not definitive)")

    # descriptive (in-sample) full-fit coefficients for interpretability
    df = panel.dropna(subset=FEATURES + ["shock"])
    if df["shock"].sum() >= MIN_TRAIN_SHOCKS:
        sc = StandardScaler().fit(df[FEATURES])
        clf = LogisticRegression(class_weight="balanced", max_iter=1000).fit(
            sc.transform(df[FEATURES]), df["shock"])
        print("\n  Full-sample standardized coefficients (DESCRIPTIVE, in-sample):")
        for f, c in sorted(zip(FEATURES, clf.coef_[0]), key=lambda t: -abs(t[1])):
            print(f"    {f:18s}: {c:+.3f}")

    res.to_csv(OUT_DIR / "beta_mz_logit_composite.csv", index=False)
    oos.to_csv(OUT_DIR / "beta_mz_logit_oos_predictions.csv", index=False)
    print(f"\n[BMZ_LOGIT] Wrote outputs to {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
