# Quick Validation — Sanity Checks on v10+ R² Headline

_Generated 2026-05-05. n=55 tickers, in-sample WFA predictions._

## Test 1 — Naive long-window baseline (lagged 252d rolling mean)

| Horizon | n | Model R² | Naive R² | Δ R² | Verdict |
|---|---|---|---|---|---|
| H=21 | 150,859 | 0.528 | 0.287 | +0.240 | skill |
| H=63 | 148,549 | 0.560 | 0.251 | +0.309 | skill |
| H=126 | 145,084 | 0.672 | 0.196 | +0.476 | skill |

**Read:** Δ R² is the lift of the trained model over a naive lagged-252d-mean baseline.
>= 0.10 = real skill at that horizon. < 0.05 = the realized-vol mean-reverts and the headline R² is mostly horizon mechanics.

## Test 2 — Period-stratified R²

| Horizon | Period | n | R² | RMSE | y_true mean |
|---|---|---|---|---|---|
| H=21 | pre-2020 | 79,423 | 0.666 | 0.0505 | 0.1923 |
| H=21 | 2020-2021 | 26,980 | 0.260 | 0.1311 | 0.2677 |
| H=21 | post-2021 | 52,486 | 0.631 | 0.0516 | 0.2335 |
| H=63 | pre-2020 | 79,423 | 0.678 | 0.0483 | 0.1985 |
| H=63 | 2020-2021 | 26,980 | 0.232 | 0.1129 | 0.2729 |
| H=63 | post-2021 | 52,486 | 0.719 | 0.0404 | 0.2352 |
| H=126 | pre-2020 | 79,423 | 0.654 | 0.0529 | 0.2092 |
| H=126 | 2020-2021 | 26,980 | 0.538 | 0.0685 | 0.2622 |
| H=126 | post-2021 | 52,486 | 0.822 | 0.0301 | 0.2359 |

**Read:** Look for big swings in R² across periods. If post-2021 R² is much lower than full-sample R², the headline is mostly historical and the model isn't tracking the current regime.

## Test 4 — Calm vs stress regime R² (SPY 21d RV terciles)

Regime cutoffs (annualised SPY rolling 21d RV):

| Regime | RV lower | RV upper |
|---|---|---|
| calm | 0.000 | 0.093 |
| normal | 0.093 | 0.147 |
| stress | 0.147 | 0.937 |

| Horizon | Regime | n | R² | RMSE | y_true mean | Model bias (pred - true) |
|---|---|---|---|---|---|---|
| H=21 | calm | 52,405 | 0.634 | 0.0534 | 0.1976 | -0.0101 |
| H=21 | normal | 54,004 | 0.513 | 0.0618 | 0.2026 | -0.0059 |
| H=21 | stress | 52,480 | 0.437 | 0.0926 | 0.2563 | -0.0184 |
| H=63 | calm | 52,405 | 0.528 | 0.0672 | 0.2152 | -0.0195 |
| H=63 | normal | 54,004 | 0.566 | 0.0601 | 0.2111 | -0.0090 |
| H=63 | stress | 52,480 | 0.608 | 0.0590 | 0.2438 | -0.0146 |
| H=126 | calm | 52,405 | 0.661 | 0.0536 | 0.2238 | -0.0182 |
| H=126 | normal | 54,004 | 0.620 | 0.0540 | 0.2220 | -0.0139 |
| H=126 | stress | 52,480 | 0.768 | 0.0410 | 0.2355 | -0.0079 |

**Read:** Vol models typically deliver 0.55+ R² in calm regimes (vol is well-anchored to lagged vol) and 0.20-0.30 in stress (regime breaks). A flatter profile across regimes is exceptional. Bias column shows over- (+) or under-prediction (−) per regime.

## What this can't tell us

These tests all read the same in-sample WFA prediction set. They cannot diagnose CV leakage. To prove generalization we still need a true held-out OOS slice (Test 3 — see `claude_context.md` deferred validation block) where the model is trained on `< 2024-01-01` and scored cold on 2024-2025.