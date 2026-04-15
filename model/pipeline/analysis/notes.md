# Cross-Branch Analysis Notes

## Session: 2026-04-09

### Data Inventory
- **BA branch (Leo, 5950X/1070/Windows):** 94 tickers, 282 prediction CSVs, 89 payloads, 16 plots
- **Caleb branch (i7-11700K/3070Ti/WSL2):** 90 tickers, 270 prediction CSVs, 84 payloads, 6 monitoring files
- **Overlap:** 87 tickers (used for all comparisons)
- **BA only:** CAT, JNJ, LIN, MRK, MS, NVDA, WMT
- **Caleb only:** BKNG, MPC, PSX

### Key Context
- Model code was **identical at runtime** (both from commit 145908a)
- VIF feature pruning on BA branch was committed AFTER runs completed
- Differences expected from: RF stochasticity, data pull timing, hardware FP behavior
- BA ran faster — likely due to 5950X's 2x thread count (32 vs 16) dominating CPU-parallel LassoCV/RF

### User's Investigation Notes
1. Pinball loss — investigate as supplementary metric
2. QQ plot tailed errors — characterize extreme vol misses
3. LassoCV CPU time — profile (informational only, no spec changes)
4. Residual analysis — investigate asymmetry pattern (diagnostic only)
5. Ensemble weights (plot 08) — uniform ~33% splits, investigate per-horizon weighting

### Constraints
- Speed optimization: infrastructure only (no model spec changes)
- Phase 5 (git merge): deferred

---

## Key Findings Summary (2026-04-09)

### Phase 2: Cross-Branch Comparison
- **Excellent reproducibility:** All ICC > 0.94 (RMSE ICCs > 0.997)
- H=63 shows tiny systematic gap (0.004 R², d=-0.42) — likely data pull timing
- H=21 and H=126 statistically equivalent
- Recommendation: either result set is a valid baseline; caleb has slightly newer data

### Phase 3: Runtime
- XGBoost 57%, RF 36%, LassoCV 7% of model fit time
- CPU bottleneck (86% mean), GPU idle 38% of time
- Top optimizations: cuML RF on GPU (~30%), Arch Linux (~15%), parallelism tuning (~15%)
- Combined optimistic: 36.5h → ~20h on same hardware

### Phase 4: Diagnostics
- **Pinball:** Right-tail losses 1.6-2.5× larger (worsens with horizon)
- **QQ/Tails:** Student-t df≈2, extreme kurtosis (58+), 3σ events 6-9× normal
- **Tail errors concentrate in high-vol:** 13% of high-vol H=126 predictions are >2σ errors
- **LassoCV:** NOT a bottleneck (7%, 18ms per fit). RF is 5.4× costlier, XGB 8.5×
- **Residual asymmetry:** Under-predicts high vol by 5-6%, over-predicts low vol by 1-2%
  - Dangerous/safe miss ratio: 1.7× (H=21) to 5.2× (H=126)
  - Mean-reversion drag from shrinkage estimators
- **Ensemble weights:** All identical (0.33/0.33/0.33). Per-model preds not stored.
  - Need to save per-model predictions in future runs for proper investigation
