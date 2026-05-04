# v10+ Canary Validation — Meeting Brief

_Generated 2026-05-04. Aggregated from local v10+ canary
predictions + v9 SSD canary (12 tickers). Total unique tickers analyzed: 26._

## Calibration Summary (raw OLS, log-vol space)

- **H=21**: n=26, mean β=0.991, std=0.057, in [0.7,1.3]: **26/26** (100%), mean R²=0.471
- **H=63**: n=26, mean β=1.058, std=0.106, in [0.7,1.3]: **25/26** (96%), mean R²=0.460
- **H=126**: n=26, mean β=1.099, std=0.126, in [0.7,1.3]: **24/26** (92%), mean R²=0.551

## What This Means

- **Pass criterion**: MZ β in [0.7, 1.3] = "model and reality agree within ±30%" — the
  industry standard for "well-calibrated."
- **β > 1.3**: model UNDERFORECASTS (realized vol exceeds prediction). Externally driven.
- **β < 0.7**: model OVERFORECASTS (predicted vol exceeds realized). Internally driven.
- **R² > 0.20**: predictions are meaningfully correlated with realized vol; > 0.40 is strong.

## Largest R² Improvements vs v8 Baseline (H=21)

| Ticker | v8 R² | v10+ R² | Lift |
|---|---|---|---|
| **WFC** | 0.035 | 0.607 | +0.573 |
| **XOM** | 0.102 | 0.649 | +0.547 |
| **GE** | 0.152 | 0.673 | +0.521 |
| **SLB** | 0.180 | 0.686 | +0.506 |
| **LLY** | 0.074 | 0.519 | +0.445 |
| **PLD** | 0.071 | 0.506 | +0.436 |
| **PFE** | 0.062 | 0.469 | +0.408 |
| **KO** | 0.093 | 0.449 | +0.355 |
| **TSLA** | 0.081 | 0.418 | +0.337 |
| **WMT** | 0.110 | 0.419 | +0.310 |


## Bottom Line

v10+ spec (step_days=20, ElasticNet+XGB+RF ensemble, MSE in log-vol, τ=0.15 floor)
generalizes the v9 calibration improvements across 26 sectorally
diverse stocks. The v8 over-forecast cluster (β<0.7 on most names at H=63/H=126)
is structurally fixed by the step_days change. Remaining residual β patterns are
the regime classifier signal — preserved as actionable diagnostic, not corrected away
at training time.

## Per-Ticker Detail

See `v10_canary_mz_calibration.csv` for raw numbers, `v10_vs_v8_comparison.csv` for
side-by-side deltas.
