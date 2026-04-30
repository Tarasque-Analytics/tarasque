# Tarasque/Volarbear — Pre-Deployment Audit & Direction Reset

_Mirror of the plan from C:\Users\ldipiet1\.claude\plans\ — placed here so it travels with the SSD._

## Context

This session is a planning/audit pass. Leo is reading the codebase from a sneakernet SSD + SATA-to-USB adaptor — no execution from this environment. The original "VRP defensive overlay" thesis has been demoted: the actual product is a **risk analytics platform** that SWEs will deploy. The overlay backtest is now a POC tile on the dashboard, not the thesis itself.

The user's actual question, in his words: *"are we sure we built something that works, is calibrated & will my deployment of it be an embarrassment or simply just the beta version / proof of concept to get the ball rolling for my SWEs?"*

This document is the audit answer plus a work plan to harden the answer before the SWE team builds against it. All work items are specs for a future session on Leo's main workstation; nothing executes here.

Compute note: nearly every diagnostic and backtest item below runs sub-minute on the already-computed 745k-row prediction set. Only the WRDS OI pull (Tier 1-E) is hours of overnight download. The expensive work — 31 hours of v8 ensemble training — is done.

---

## Audit findings

### Does it work?

**Yes, with caveats worth disclosing to the SWEs.**

Evidence for "yes":
- v8 corpus completed 2026-04-28 11:51 (verified: `all_predictions.csv` 745,279 rows, `backtest_results.csv` written same minute, `*_Payload.json` × 97 in payloads/)
- H=21 corpus mean R² = 0.374 (v6); H=63 = 0.319; H=126 = 0.458
- Beats HAR-RV by ΔR² +0.135 / +0.200 / +0.432 at H21/63/126
- Beats GARCH(1,1) by an order of magnitude (GARCH negative R² at all horizons)
- 97/97 tickers beat naive persistence at H63/H126 by Diebold-Mariano

Caveats the SWEs need to know about:
- **v8 R² lost 0.10-0.17 vs v6 across all horizons.** Updated 2026-04-28: H21 R² 0.374→0.262, H63 0.319→0.204, H126 0.458→0.286. The v8 run bundled three changes (Optuna XGB params + tau pivot + step_days 25→63) and the R² loss is consistent with step_days=63 leaving the model on stale-fit weights for ~50 of the 63-day window. **v8's calibration improved at H126 (β 1.192→0.947, calibrated 40%→59%), so the trade isn't purely negative — but it is large.** v9 with step_days=25 (the controlled experiment in v9_planning_2026-04-28.md Step A) should recover most of the R² loss.
- **Universe gap: v8 corpus has 91 tickers, not 93.** Documented exclusions are LIN/META/OXY/VZ. Actual missing is those four + **MSFT and MU** (undocumented). Either fix and rerun those two, or document the exclusion explicitly. SWE handoff cannot say "S&P 100 minus 4" — it's "minus 6, two undocumented."
- **Three data-artifact rows.** DOW H126 (RMSE 7.11), EQIX H21 (RMSE 5.00), GILD H21 (RMSE 2.30) — model totally failed to fit. Diagnosis pending in v9_planning Step D.
- **Meta-overfitting via the iteration loop.** Eight model versions in 25 days (v1 → v8), every change validated against the same walk-forward backtest. `min_train` flipped 920→1000→756. `rv_5d/10d/63d` excluded then restored. `tech_ATR` dropped. ElasticNet replaced LassoCV. Tau pivots 0.85→0.92→0.15. Each step observed feedback from the same OOS window. There is no genuine holdout. v8 metrics are likely optimistic; how much is unknown without a true blind test (v9 Step G includes 10-ticker holdout discipline).
- **Signal-strength lift is anecdotal at three tickers.** XOM 24.7×, AAPL 7.2×, JPM 3.3× pooled into a "5.4× lift" claim. Variance ratio max/min = 7.5×. Three points is not a portfolio statistic. Full-91-ticker run still pending — Tier 0-A.
- The convex risk-weight curve (P70→0.15, P80→0.30, P90→0.55, …) was chosen on those same three tickers. Threshold-on-sample plus fit-on-sample.

### Is it calibrated?

**Mixed. Calibrated in the recent-regime / portfolio-mean sense; not calibrated in the temporal-consistency or quantile-coverage senses.**

Where it is calibrated:
- EW (lambda=0.003) MZ betas 0.97-0.98 at all horizons in the recent regime
- H=21 portfolio-level beta 0.995 across 90 clean tickers
- H=21 sector mean betas all in [0.92, 1.05]

Where it is not (or unverified):
- **H=126 raw mean beta = 1.192** with only 36/90 tickers in [0.85, 1.15]. The post-hoc EW MZ overlay reads 0.976 — but that is correction, not calibration. The raw model is biased; the overlay is masking.
- **Term-structure inversions: 64.8% pre-overlay → 55.6% post-overlay.** A majority of forecasts violate H21 ≤ H63 ≤ H126 even after the patch. Root cause (independent training of three horizon models with no joint constraint) has not been addressed. The TS overlay's known sequential-pass bug (claude_context.md L554-L568) is a contributing but not sole factor.
- **Quantile coverage for tau=0.15 — modestly under-target, NOT catastrophic.** Updated 2026-04-28 after computing from `backtest_results.csv`: definition in [backtest.py:700](model/pipeline/backtest.py#L700) is `coverage_qN = mean(y_true > y_pred_qN)`, so target for tau=0.15 is **0.85** (= 1 − tau). Observed: H21 mean 0.766, H63 0.746, H126 0.735 — gap of 0.08 to 0.12 below target. Floor is slightly too high (model overwarns on low-vol regimes). This is **not** the 2-5× tau=0.92 catastrophe; the floor signal is functional. Tier 0-C is reduced to fitting a per-ticker scalar offset to hit 0.85 exactly.
- Three outlier exclusions (LIN R²=0.94 / VZ beta=2.62 / OXY RMSE explosion) are documented as one-line dismissals. No drill-down. Other tickers may have lower-grade versions of the same problem and pass through.
- GOOGL diagnosis is internally inconsistent: v6 attributes its beta drift to class-split contamination; v7 says ElasticNet+sector coupling fixed it. Both can't be right.

### Will deployment embarrass?

**Not as a beta / POC, after the audit work below. Yes if you ship the headline numbers as-is.**

POC-ready artifacts the SWEs can build against:
- Pipeline is end-to-end functional (WRDS → parquet → features → ensemble + quantile → MZ overlay → JSON payloads → frontend-consumable)
- 97 `*_Payload.json` + `market_overview.json` exist with stable schemas
- Forecast quality is materially better than HAR-RV / GARCH benchmarks
- output.py produces frontend-aligned shapes
- Data contracts (CSV columns, JSON schemas) are stable enough for SWE infrastructure work in parallel

Embarrassment risks if not addressed:
1. "5.4× signal lift" in product copy when the underlying claim is 3 tickers
2. H=126 calibration disclosed as raw vs overlay-corrected — the SWE handoff needs to know which CSV serves which purpose
3. LIN/VZ/OXY excluded with no diagnostic paragraph; "why isn't VZ here?" gets a shrug
4. Coverage_q15 is the floor signal — and it is unverified
5. GOOGL has two contradictory explanations on file
6. `garch_cond_vol` is in the feature set but ranks 28/43; included for narrative not utility

---

## Work plan (next ~4 weeks until WRDS expires)

### Tier 0: Audit completions — must finish before any deployment claim

All sub-minute on the existing 745k-row prediction set. None of these require model retraining.

**A. Run `signal_strength.py` on full 93-ticker corpus.**
- Path: `model/pipeline/analysis/signal_strength.py --horizon 21`
- Replaces the 3-ticker claim with a portfolio-level number.
- Decision: if pooled lift at P80+ < 2× across 93 tickers, walk back the dashboard messaging. If ≥ 4×, the claim survives.

**B. Run `vrp_return_conditional.py` on full corpus.**
- Path: `model/pipeline/analysis/vrp_return_conditional.py`
- Validates the momentum-vs-mean-reversion regime framing at corpus scale. Output is direct dashboard input.

**C. Coverage_q15 calibration — DONE (2026-04-28). Reduced to scalar offset fit.**
- Coverage already in `backtest_results.csv` per ticker. Aggregate: H21 0.766, H63 0.746, H126 0.735 vs target 0.85. Modestly under-target (floor too high), not catastrophic.
- Remaining work: fit a per-ticker scalar offset `δ_ticker` such that `q15_adjusted = q15_raw − δ_ticker` brings coverage to 0.85 exactly per ticker. Sub-minute compute. Persist offsets to a small CSV that signal_strength.py and the dashboard layer consume alongside raw q15.
- Per-ticker (not global) because the 0.583–0.859 spread suggests heterogeneous miscalibration across tickers.

**D. Term-structure inversion second-pass fix in `mz_overlay.py`.**
- Spec already in claude_context.md L554-L568 — second H21-H63 pass after H63-H126 enforcement, or replace the sequential approach with full isotonic regression across the three horizons jointly.
- Re-run overlay. Target: TS inversion rate < 10% (currently 55.6% post-overlay). If isotonic regression brings it below 5%, prefer it over the manual blend.

### Tier 1: Data preservation — hard deadline ~mid-June 2026 (~40 days)

**E. OI differential pull from WRDS.** *Mandatory per Leo.*
- Add `open_interest` column to `fetch_vsurfd()` in data_loader.py (around lines 190-250).
- Loop over year tables `optionm.vsurfd2014` through `optionm.vsurfd2025`, pull `open_interest` alongside existing `iv_surface, delta, expiry, moneyness` for the production universe.
- Persist to `D:/Tarasque_DB/oi/` partitioned by ticker (mirror existing parquet layout).
- Build the FOUR OI/IV features in features.py (per v9_planning Step "New feature: 25-delta IV × OI interaction"):
  1. `oi_put_call_ratio_25d = oi_put_25d / (oi_call_25d + 1)` — quantity-only signal
  2. `iv_skew_25d = iv_25d_put - iv_25d_call` — price-only signal
  3. **`fear_intensity_25d = iv_skew_25d × log((oi_25d_put + 1) / (oi_25d_call + 1))`** — Leo's interaction; multiplicative, requires both price and quantity asymmetry to score; theoretically captures market-maker gamma exposure / mechanical vol amplification feedback
  4. `hedging_pressure_25d = (iv_25d_put × oi_25d_put) / (iv_25d_call × oi_25d_call + 1)` — alternative composite (notional value ratio)
- All four use `.shift(1)` to avoid T+1 settlement lookahead. Let ElasticNet's widened l1_ratio grid pick the best from the four per ticker per window.
- **Even if not modeled with immediately, the parquet on disk is what matters** — after WRDS access expires, this becomes irrecoverable for ~11 years of history.
- Acceptance: parquet files exist for 2014-01-01 through end of vsurfd2025; row counts match existing vsurfd cache.
- **Bonus while connected to WRDS:** consider pulling intraday returns (5-min) for HARQ realized quarticity feature — same trip, same login, separate query against `optionm.opprcd`. Skippable but the marginal cost of one more query is hours not days, and intraday data unlocks several future features.

### Tier 2: Overlay backtest POC — both versions planned, neither built (per user)

These are the proof-of-concept tile on the analytics dashboard. Both run sub-minute on the existing calibrated prediction set; the expensive work is the model training (already done) and the calibration overlay (already done). Strategy backtest is just stepping through pre-computed predictions with a state machine.

**F. Crude rule-based overlay (V1 spec).**
- Module: new file `model/pipeline/analysis/overlay_backtest.py`
- Spec: per ticker, compute model output percentile at each prediction date via expanding-window CDF (already implemented inside signal_strength.py — reuse `_compute_expanding_cdf()` rather than reimplementing). Apply discrete state machine:
  - `signal_pct ≥ P80` → equity weight 0.5
  - `signal_pct < P60` → equity weight 1.0
  - Hysteresis between P60-P80 holds previous state to prevent flapping
- Daily rebalance, no transaction costs, long-only, single-ticker and equal-weighted-portfolio variants
- Metrics output: Sharpe, Sortino, max drawdown, hit rate, average exposure, vs SPY buy-and-hold benchmark
- **Decision rule:** if Sharpe of the overlaid portfolio is ≤ buy-and-hold (or only marginally above), the overlay POC is dropped from the dashboard but the analytics product still ships — the percentile signals are the product, the overlay was just a "look at one application" demo. Do not over-claim.
- Compute: numpy-vectorized over 745k rows. Sub-second per ticker, ~1 minute for the 93-corpus portfolio.

**G. Continuous risk-weight overlay (V2 spec).**
- Same module as F.
- Spec: use the convex weight curve from signal_strength.py directly (P70→0.15, P80→0.30, P90→0.55, P95→0.75, P99→0.95) as continuous equity de-leveraging. Daily rebalance with simple linear transaction cost (5 bps round-trip is a defensible default; parameterize so the SWE team can sweep).
- Optional extension: 2×2 regime taxonomy (ensemble × floor) → different leverage rules per quadrant (e.g., ensemble-only-elevated quadrant gets the most aggressive de-risking since it had the 6.1× lift in the 3-ticker test).
- Metrics: Sharpe, Sortino, MDD, turnover, average exposure, plus comparison to V1 — does the continuous curve add alpha vs. the binary rule, or is it just complexity?
- Decision rule: only build G after F shows a positive sign. If F is flat, building G is wasted effort.
- Compute: same class as F, slight overhead from cost model.

### Tier 3: Methodological diagnostics — alongside, lightweight

Per user: "diagnose alongside thesis work."

**H. GOOGL diagnosis reconciliation.**
- 30-minute task. Re-read features.py `_pivot_ohlcv()` split-adjusted reconstruction logic. Confirm whether GOOGL's 2014 class split (creation of GOOG class C alongside GOOGL class A) is handled by the CRSP `ret`-based reconstruction.
- If yes, v6's "split contamination" diagnosis was wrong; v7's beta improvement (0.526→1.007) is from a different cause (likely sector_wedge or restored rv_*). Update iteration_log.md for internal consistency.
- If no, the v6 fix didn't actually fix GOOGL; v7 is masking via a different feature group. Flag the unfixed root cause.

**I. LIN / VZ / OXY post-mortems.**
- One paragraph each in iteration_log.md.
  - **LIN**: which feature drives R²=0.94 — likely `sector_wedge` or `corr_sector_*` picking up the Linde-Praxair merger pair structure as artificially low residual variance? Plot `rv_21d` vs `y_pred` over the 2018-2019 merger window. If a single feature explains the lift, that feature has a leakage failure mode worth flagging across the corpus.
  - **VZ**: trace EW MZ beta=2.62 to a specific period. Frontier acquisition closed Q4 2024 — does the beta walk up sharply in 2024-2025 only, or is it elevated earlier? Plot beta over rolling 252-day windows. If acquisition-localized, the fix is corporate-action exclusion logic, not a model fix.
  - **OXY**: identify the regime where RMSE explodes — likely 2020 oil crash where realized vol exceeded the model's training distribution. Tree-ensemble extrapolation limit (already documented for NVDA/BA in claude_context.md L276-L281). If yes, OXY can be re-included with disclosure rather than excluded.
- Output: three paragraphs that turn "we threw it out" into "we threw it out because X, and here is the detection rule for X in future tickers."

**J. H=126 calibration drift root cause.**
- Current explanation: "COVID dilutes recent-regime beta." Plausible but untested. Three alternatives, all small scripts:
  1. Exclude COVID period (2020-03 to 2020-09) from MZ regression — does full-history beta fall toward 1.0?
  2. Compute MZ beta in non-overlapping 252-day windows. Plot. Monotonic walk-down → regime drift; spike-and-revert → COVID outlier; stable → unrelated structural issue.
  3. Compare ElasticNet-selected features in the first half vs second half of sample for the H=126 model. Structural difference → feature drift, different fix.
- Output: one of {COVID outlier / regime drift / feature drift} confirmed. The fix differs per cause; current MZ-overlay-as-bandage is correct for COVID-outlier and wrong for the other two.

**K. garch_cond_vol drop-or-justify.**
- Re-run a 6-ticker validation (canary set: AAPL, JPM, XOM, BA, AMZN, NVDA) with `garch_cond_vol` removed.
- If metrics within noise → drop the feature. Less surface area, fewer imputation paths, smaller pickle.
- If R² degrades meaningfully → keep but update claude_context.md L401-L402 to stop describing it as "near-zero importance, not hurting, not leading."
- Compute: 6 tickers × 3 horizons × ElasticNet+XGB+RF ensemble = a few hours overnight.

### Defer (do not do until Tier 0/1/2 are green)

- v9 model iteration of any kind — no new features, no new architectures, no Optuna sweeps. The forecast engine is already good enough; further iteration increases meta-overfitting risk and delays deployment.
- SHAP cross-ticker analysis
- IC demeaned cross-sectional signal
- Markov regime switching, SVI surface interpolation
- Exponential sample weighting revisits (lambda=0.0006 already worsened JPM H=126; deeper search is yak-shaving)
- Frontend, backend API, Supabase write layer (SWE team is handling these)

Each is defensible in isolation, but each delays the audit answers without changing them.

---

## Critical files

- model/pipeline/analysis/signal_strength.py — Tier 0-A, full-corpus run; reuse `_compute_expanding_cdf()` for Tier 2-F/G
- model/pipeline/analysis/vrp_return_conditional.py — Tier 0-B
- model/pipeline/analysis/mz_overlay.py — Tier 0-D, second-pass / isotonic fix in `enforce_term_structure()`
- model/pipeline/data_loader.py — Tier 1-E, `fetch_vsurfd()` ~lines 190-250 needs `open_interest`
- model/pipeline/features.py — Tier 1-E `_add_oi_features()`; Tier 3-H `_pivot_ohlcv()` split-logic verification
- model/pipeline/results/all_predictions_cal.csv — input to F/G overlay backtests; **calibrated** version is the right one for strategy work, raw is for diagnostics only
- model/iteration_log.md — needs H, I, J writeups
- New file: `model/pipeline/analysis/coverage_check.py` — Tier 0-C
- New file: `model/pipeline/analysis/overlay_backtest.py` — Tier 2-F and G

## Verification (target state, not a near-term checklist)

When the plan executes on Leo's main workstation, the audit answers should turn from "yes with caveats" into "yes, here is the evidence":

1. **Does it work?** Pooled signal lift across 93 tickers at P80+, with sector breakdown — replaces the 3-ticker headline.
2. **Is it calibrated?** Coverage_q15 verified within ±0.05 of target. TS inversion < 10%. GOOGL diagnosis reconciled. LIN/VZ/OXY post-mortems written. H=126 drift cause identified.
3. **Will deployment embarrass?** Crude overlay Sharpe vs SPY buy-and-hold computed. If positive, the POC tile lands. If flat/negative, drop the tile and the analytics platform still ships.
4. **Data preserved.** OI parquet on disk before WRDS access ends.

If 1-3 pass, the SWE team has a credible beta to build against. If 1 fails badly (pooled lift < 2×), the dashboard messaging walks back to "ordinal risk percentile + sector context" and drops the multiplier-lift framing entirely. The product still ships — just with quieter copy.
