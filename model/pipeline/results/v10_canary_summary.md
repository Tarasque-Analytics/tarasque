# v10+ Canary Validation — Meeting Brief

_Generated 2026-05-05. Aggregated from local v10+ canary
predictions + v9 SSD canary (12 tickers). Total unique tickers analyzed: 55._

## Calibration Summary (raw OLS, log-vol space)

- **H=21**: n=55, mean β=0.980, std=0.094, in [0.7,1.3]: **54/55** (98%), mean R²=0.460
- **H=63**: n=55, mean β=1.066, std=0.117, in [0.7,1.3]: **54/55** (98%), mean R²=0.451
- **H=126**: n=55, mean β=1.117, std=0.124, in [0.7,1.3]: **50/55** (91%), mean R²=0.555

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
| **UPS** | 0.059 | 0.618 | +0.559 |
| **XOM** | 0.102 | 0.649 | +0.547 |
| **GE** | 0.152 | 0.673 | +0.521 |
| **INTC** | 0.127 | 0.642 | +0.516 |
| **SLB** | 0.180 | 0.686 | +0.506 |
| **QCOM** | 0.052 | 0.519 | +0.467 |
| **GILD** | 0.003 | 0.456 | +0.453 |
| **LLY** | 0.074 | 0.519 | +0.445 |
| **TXN** | 0.023 | 0.459 | +0.436 |


## Bottom Line

v10+ spec (step_days=20, ElasticNet+XGB+RF ensemble, MSE in log-vol, τ=0.15 floor)
generalizes the v9 calibration improvements across 55 sectorally
diverse stocks. The v8 over-forecast cluster (β<0.7 on most names at H=63/H=126)
is structurally fixed by the step_days change. Remaining residual β patterns are
the regime classifier signal — preserved as actionable diagnostic, not corrected away
at training time.

## Per-Ticker Detail

See `v10_canary_mz_calibration.csv` for raw numbers, `v10_vs_v8_comparison.csv` for
side-by-side deltas.
