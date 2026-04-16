# Optimized vs Standard Pipeline — Comparison Report

Horizon: H=21  |  Tickers: AAPL, MSFT

## Acceptance tier: calibration + ranking preserved

- RMSE / QLIKE relative delta within ±2%  |  |Δβ|<0.02, |Δα|<0.01, |ΔR²|<0.01  |  Spearman(y_pred) > 0.98  |  Event-flag Jaccard > 0.95

## AAPL (n=2816) — VERDICT: FAIL

- RMSE: std=0.06344  opt=0.06330  rel_delta=-0.2205%
- QLIKE: std=0.03795  opt=0.03790  rel_delta=-0.1444%
- MZ α: std=-0.00727  opt=-0.00456  Δ=+0.00271
- MZ β: std=1.07943  opt=1.06380  Δ=-0.01563
- MZ R²: std=0.29356  opt=0.29526  Δ=+0.00170
- Pearson(y_pred): 0.99657  |  Spearman(y_pred): 0.99646
- Event-flag Jaccard: 0.8626
- KS p-value (residuals): 0.9995
- Δy_pred: mean=+0.00033  std=0.00320  max|Δ|=0.02518  mean|Δ|=0.00202
- Optimized components vs standard y_pred (Pearson):  XGB=0.9441  RF=0.9189  LassoCV=0.5790

**Failures:**
  - Event Jaccard=0.8626 below 0.95

## MSFT (n=2676) — VERDICT: FAIL

- RMSE: std=0.06319  opt=0.06348  rel_delta=+0.4491%
- QLIKE: std=0.03528  opt=0.03636  rel_delta=+3.0413%
- MZ α: std=-0.00619  opt=-0.00735  Δ=-0.00116
- MZ β: std=1.08056  opt=1.10097  Δ=+0.02040
- MZ R²: std=0.30652  opt=0.30963  Δ=+0.00311
- Pearson(y_pred): 0.91219  |  Spearman(y_pred): 0.92105
- Event-flag Jaccard: 0.4264
- KS p-value (residuals): 0.0217
- Δy_pred: mean=-0.00241  std=0.01601  max|Δ|=0.15188  mean|Δ|=0.01035
- Optimized components vs standard y_pred (Pearson):  XGB=0.8692  RF=0.8147  LassoCV=0.8642

**Failures:**
  - QLIKE relative delta +0.0304 exceeds ±0.02
  - |Δβ|=0.0204 exceeds 0.02
  - Spearman=0.9211 below 0.98
  - Event Jaccard=0.4264 below 0.95

## OVERALL VERDICT: FAIL
