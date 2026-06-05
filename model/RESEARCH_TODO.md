# Tarasque — Research TODO

Holding bin for promising research and modeling directions surfaced during
development. Not active work, but worth keeping the analysis intact for later.

Last updated: 2026-05-10.

---

## 1. VRP EWMA Predictability — Validated Findings, Pending Productization

### What we tested

For AAPL + 5 cross-sector tickers (JPM, XOM, TSLA, NVDA, AMZN), we tested
whether the 21-day EWMA of the VRP wedge (`vrp_wedge_ewma_21d`) predicts:
- Forward returns at H=1/5/21/63 days
- Forward realized vol at H=5/21/63 days

Methods: quintile binning + t-stats, conditional probability of negative
returns, Pearson + Spearman correlations, rolling 252d IC time series,
reverse bucketing (returns → VRP distribution).

### Key results (validated, ready to claim)

**Forward RV prediction holds robustly cross-sector:**
- Pooled correlation across 6 tickers: **r = +0.349 at H=21d** (n = 16,966, p < 1e-30)
- Top-quintile VRP_ewma days have 25–28% higher forward RV than bottom quintile
- Works on AAPL (+0.224), JPM (+0.120), XOM (+0.281), TSLA (+0.201)
- Fails on NVDA (+0.024 — noise) and inverts on AMZN (−0.114 — split contamination)

**Forward return prediction is cross-sectionally heterogeneous:**
- JPM, TSLA, NVDA, XOM all show statistically significant POSITIVE r between
  VRP_ewma and forward returns at H=21d or H=63d
- XOM 63d: r = +0.215, p < 0.0001
- NVDA 63d: r = +0.127, p < 0.0001
- AAPL inverts: r = −0.077 at H=63d (negative, the only negative-correlation ticker)

**Reverse bucketing reveals a U-shape:**
- VRP_ewma is HIGHEST in the BEST forward-return quintile for 5 of 6 tickers
- The market prices the most fear right before the biggest rallies (fear → reversion)
- Middle return quintile (normal markets) has the LOWEST VRP

### What this means

**Robust narrative:**
> VRP_ewma is a reliable forward-vol indicator (P25 lift in forward RV cross-ticker).
> Use this for risk regime classification on the equity page.

**Cautious narrative:**
> VRP_ewma is conditionally predictive of forward returns on 4 of 6 names tested.
> AAPL inverts. Need ticker-specific calibration before claiming directional signal.

### Pending work

1. **Partial correlation control**: test whether VRP_ewma still predicts after
   controlling for current `vol_regime_zscore`. Right now we don't know if
   it's incremental signal or just a noisy proxy for current vol level.

2. **Conditional regime test**: does signal strength vary by vol percentile?
   Hypothesis: VRP_ewma predicts most strongly in P40–P80 vol regimes (the
   "transitional" zone), and is uninformative in extreme regimes (P0–P20 too
   compressed, P95+ everyone is panicking).

3. **Cross-ticker meta-model**: train a small model to weight VRP_ewma signal
   confidence per ticker. Inputs: ticker characteristics (sector, market cap,
   beta, retail-flow proxy). Output: how reliable is VRP_ewma for THIS name.

4. **Productization**: VRP_ewma + own-history percentile as a UI gauge on the
   equity page. Already proven robust enough cross-sector to feature in product.

### Files / artifacts

- `webapp_export/test_vrp_ewma_predictability.py` — AAPL deep dive
- `webapp_export/test_vrp_predictability_multi.py` — cross-sector validation
- `webapp_export/vrp_predictability_multi.png` — composite figure
- `webapp_export/vrp_predictability_summary.csv` — per-ticker correlation table

---

## 2. Skew Slope as Tail Insurance Premium — Proposed Feature

### The idea

Current feature: `put_call_skew_30d = IV(δ=−25) − IV(δ=+25)` measures the LEVEL
of skew at 25-delta strikes.

Proposed addition: the SLOPE of the put-side smile beyond 25-delta:

```
put_smile_slope_30d   = IV(δ=−10) − IV(δ=−25)    # tail insurance cost
call_smile_slope_30d  = IV(δ=+10) − IV(δ=+25)    # speculative upside cost
smile_asymmetry       = put_smile_slope − call_smile_slope
tail_premium_ratio    = IV(δ=−10) / IV(δ=−25)    # dimensionless, regime-stable
```

### Why this is different from existing skew level

- **Level** answers a directional sentiment question (downside vs upside in moderate moves)
- **Slope** answers a tail-fear question (cost of catastrophe protection beyond moderate)

Markets can have flat skew + steep slope (no directional bias, but fearing tails),
or steep skew + flat slope (directional bearish without tail panic). The two
separate meaningfully.

### Data availability

We pull `vsurfd_deltas = [10, 25, 50, -25, -10]` per config — the data is
already in the parquet cache. Just need to surface columns alongside the
existing 30d extraction. No new WRDS pulls needed.

### Prior art (must engage with for any paper)

- **CBOE SKEW Index (^SKEW)** — exact same concept at SPX index level since 1990
- **Bakshi, Kapadia, Madan (2003)** — risk-neutral skewness extraction methodology
- **Bollerslev, Todorov (2011)** — "Tails, Fears, and Risk Premia" (JF) — closest paper
- **Bollen & Whaley (2004)** — demand pressure → smile shape

This is well-trodden ground at the SPX/index level. The single-stock,
own-history-percentile, prosumer-product framing IS underserved.

### Pending tests

1. **VIF check** against existing `put_call_skew_30d` — expected r ~0.5–0.7
2. **Liquidity check** — % of trading days with valid (non-ffilled) 10-delta IV
3. **Univariate predictability** — does slope predict forward RV / returns?
4. **Conditional predictability** — does signal strengthen at vol percentile P60+?
5. **OI interaction** — `put_smile_slope × put_oi_25delta` (demand-pressure
   framework, Garleanu-Pedersen-Poteshman 2009)

### Proposed UI

Component name: **"Tail Insurance Premium"** (avoid "smile slope" in copy)

Display: percentile gauge with regime colors:
- 0–25th pct of own history → "Cheap" (green)
- 25–75th → "Normal"
- 75–95th → "Elevated" (amber)
- 95+ → "Extreme" (red)

Tooltip: "Cost of going from 25Δ to 10Δ put protection, in IV percentage points.
Currently at P{N} of this name's history. When elevated, options market is
pricing fear of catastrophic moves."

Pairs naturally with the VRP wedge gauge on the equity page — VRP says "is the
market broadly fearful?" and Tail Premium says "is the fear concentrated at
the tails?"

---

## 3. Paper Concept: Forward-Looking Decomposition of the VRP

### Working titles
- "A Forward-Looking Decomposition of the Variance Risk Premium"
- "Disentangling Insurance Markup from Forecast Error in the VRP"
- "Cross-Sectional Decomposition of Demand-Side Vol Risk Premium"

### The methodological hook

Standard VRP definition: `IV − RV_realized` measures how much IV exceeded what
DID happen. This conflates two distinct quantities:
1. The insurance markup (premium for bearing risk)
2. The model's forecast error (statistical mistake)

Using our forward conditional forecast as a benchmark:

```
VRP_insurance  = IV − pfv_cal       # insurance markup over fundamental risk
VRP_forecast   = pfv_cal − rv       # ex-post forecast error
VRP_total      = VRP_insurance + VRP_forecast
```

If model R² is reasonable (we have 0.37 at H=21), VRP_insurance is a cleaner
measure of insurance pricing than the standard backward-looking VRP.

### Where the real edge lives

1. **Forward benchmark** — methodologically novel decomposition. Most cited
   literature (Carr-Wu 2009, Bollerslev-Todorov 2011) uses backward-looking RV.

2. **Cross-sectional 91-ticker single-stock data** — Carr-Wu did cross-section
   with smaller universe. Most other literature is SPX-only.

3. **OI-weighted skew** — the demand-pressure framework
   (Garleanu-Pedersen-Poteshman 2009) at single-stock level using OI data.

### Honest scope decision (S/D framing)

**Functionally** treating supply as constant works in normal regimes (85% of
days). It breaks in crisis regimes (March 2020, Aug 2024, SVB) when dealer
balance sheets contract.

**For the paper**, this means two valid positionings:

**Option A — narrow**: "A DEMAND-SIDE Decomposition of the VRP". Easier scope,
defensible claims, useful contribution. Don't claim S/D, claim D-only.

**Option B — full**: solve the S/D identification using term structure
curvature, VIX-of-VIX, dealer-stress proxies. Bigger paper, harder, more impact.

Option A is the right first paper. Option B is a follow-up.

### Proposed paper structure (Option A)

1. Introduction — frame VRP as price of insurance, motivate forward benchmark
2. Related Literature — GPP 2009, Bollen-Whaley, Bollerslev-Todorov, Carr-Wu
3. Data and Methodology — universe, walk-forward model, feature set
4. Decomposing VRP into Insurance and Forecast Error
5. Identifying Demand-Side Signals — skew level, slope, OI interaction
6. Cross-Sectional Predictability Tests
7. Robustness — conditional on macro regime, model R², subsample stability
8. Conclusion

### Target venues

- Journal of Financial Economics
- Review of Financial Studies
- Journal of Financial Markets
- WFA / SFS conference presentations

### Practical first steps

1. Read Garleanu-Pedersen-Poteshman 2009 carefully (the GPP paper)
2. Read Bollerslev-Todorov 2011 carefully
3. Reproduce part of one of them on a small sample
4. Empirical core: VRP_insurance vs VRP_forecast decomposition on our 91 tickers
5. Find a finance professor co-author (UMD has an active derivatives group)

---

## 4. Half-Residual Auto-Corrector (AR(1) bias correction with damping)

### The idea

For each prediction at date t, additively shift by a fraction of the most-recent
observable residual:

```
y_pred_adj(t) = y_pred(t) + α · ewma(residuals_observable_through_t-1)
```

Special case of an AR(1) error-correction model with damping `α < 1`. The
damping is the safety mechanism — can't oscillate or amplify in regime
transitions because the correction always pulls back toward zero.

### Why it would help

Residuals have **positive autocorrelation** during regime drift (ORCL's bias
was negative for 30+ consecutive BD in Dec 2025 → Feb 2026). Yesterday's miss
is genuinely predictive of tomorrow's miss in those windows.

### Why it might hurt

Regime *transitions* — the day vol normalizes after a shock, residual flips
sign, and we apply yesterday's correction in the wrong direction. The α < 1
damping limits damage but doesn't eliminate it.

### Refinements before locking parameters

1. **EWMA over last 5-10 residuals, not single most-recent.** Smooths noise
   without losing recency. λ ≈ 0.7 reasonable default.
2. **Tune α empirically per horizon.** H=21 has high residual autocorrelation
   (recent regime ≈ next regime). H=126 averages over multiple regimes inside
   the 126-BD target window, so the signal is weaker. Predicted optima:
   α ≈ 0.5 for H=21, α ≈ 0.3 for H=63, α ≈ 0.15 for H=126.
3. **CRITICAL ordinal reframing**: don't apply correction in absolute residual
   units. Compute residual's percentile within the ticker's own 252-BD
   residual distribution, and only correct when in the tails (P85+ or P15−).
   Correction strength scales with percentile extremity. Mirrors the
   `percentile_to_risk_weight()` pattern in `signal_strength.py`. Avoids
   over-correcting tickers with naturally noisy fits (ORCL's typical residual
   is large; KO's is small — same raw number, vastly different implications).

### Complementarity with `mz_overlay`

- `mz_overlay` handles **structural** per-ticker bias (slope/intercept fit on
  full training history). Static between retrains.
- This corrector handles **time-varying** bias (last few residuals). Updates daily.
- Both can apply in sequence:
  `y_final = (α_mz + β_mz · y_pred) + α · ewma(residuals)`

### Practical first step

1. Re-read `mz_overlay.py:160-200` to understand existing calibration application.
2. Add post-processing step (in `mz_overlay.py` or new `residual_corrector.py`)
   that walks dates and applies the EWMA correction.
3. Backtest on existing extension data (2025-10-30 → today): compute pooled R²
   with vs without the corrector for each horizon.
4. Tune α via grid search {0.0, 0.25, 0.5, 0.75} per horizon.

### Deferred because

We chose to validate the **ordinal/relative principle empirically** via the
trail-dynamics IC test FIRST. If ordinal framing doesn't add IC over absolute,
the percentile-based correction may not help either — wasted engineering.

---

## 5. Trail-Dynamics IC Test — RESOLVED (2026-05-26): dynamics DON'T add IC

### What we tested

`regime_signal_test.py` measures whether *current* (β_mkt, β_mz) quadrant
predicts forward (return | drawdown | vol). We added dynamics features per
snapshot and tested whether they add Spearman IC over the static quadrant_rank.

Features tested:
- `velocity` = √((Δβ_mkt)² + (Δβ_mz)²) from prior snapshot
- `drift_mz_6mo` / `drift_mkt_6mo` = OLS slope of β over last 6 snapshots
- `drift_mz_3mo` = faster slope (3 snapshots)
- `direction_angle` = arctan2(Δβ_mz, Δβ_mkt)

Script: `model/pipeline/analysis/trail_dynamics_ic.py`.
Results: `model/pipeline/results/validation/trail_dynamics_ic.csv`.

### Findings

| Feature | H=21 vol | H=63 vol | H=126 vol |
|---|---|---|---|
| **quadrant_rank** (baseline) | **+0.264** | **+0.276** | **+0.291** |
| velocity | +0.119 | +0.113 | +0.107 |
| drift_mz_6mo | -0.073 | -0.121 | -0.133 |
| drift_mkt_6mo | +0.066 | +0.002 | -0.016 |
| stack (quadrant + drift_mz_6mo, rank-sum) | +0.114 | +0.085 | +0.092 |

**Three things:**

1. **Static quadrant_rank IS informative for forward vol** — +0.26 to +0.29 IC
   across all three horizons. The visual 2×2 framework as a vol-regime
   classifier is empirically validated.
2. **Trail dynamics don't add predictive content** — velocity is the only
   feature with same-sign-as-quadrant IC, and at less than half the magnitude.
3. **drift_mz_6mo has the WRONG sign** — counter-intuitive on its face but
   makes sense after thinking about it: β_mz is a **trailing** measure of
   model miss over the prior 252 BD. When β_mz has been rising, past shocks
   have hit the trailing window and pulled calibration toward "under-predict."
   Those shocks are already realized — forward vol tends to NORMALIZE from
   there (mean reversion). So `rising β_mz` reads as *"we're at the back end
   of a vol episode"*, not "more vol coming." Stacking it with quadrant_rank
   cancels signal rather than adding.

### Implication

The slug trail is a great **diagnostic visualization** ("here's where this
ticker has been in regime space") but NOT a forecast feature. Don't engineer
drift-as-feature into the model — it would inject backward-looking signal as
if it were forward-looking.

The user-facing slug trail in the equity page should be framed as *"where
ORCL has been in the regime space recently"* — context for the current
position — not as a "ORCL is heading into Q2 risk" forward signal.

### What's still open

- Could refine velocity-as-feature with sign-adjusted version (Δ toward
  higher-rank quadrants vs lower-rank). Marginal upside; not pursuing.
- The wrong-sign drift could be re-tested with NON-OVERLAPPING β_mz windows
  (current β_mz uses rolling 252-BD which heavily overlaps consecutive
  snapshots). Quarterly disjoint windows might give cleaner signal — but
  small sample size on 24 quarterly snapshots × 92 tickers.

---

## 6. Ticker-Relative Quadrant Thresholds — RESOLVED (2026-05-26): absolute WINS

### What we tested

Quadrant classifier currently uses absolute β=1.0 cutoffs. Tested three
schemes via Spearman IC vs forward outcomes:

| Scheme | Cutoff source |
|---|---|
| `abs` | universal β = 1.0 (existing baseline) |
| `rel_full` | per-ticker median across FULL trail (clean test, mild lookahead) |
| `rel_exp` | per-ticker expanding median, ≥8 prior snapshots (deployable) |

Script: `model/pipeline/analysis/relative_quadrant_ic.py`.
Results: `model/pipeline/results/validation/relative_quadrant_ic.csv`.

### Findings (common subset, apples-to-apples)

| horizon | metric | abs | rel_exp | rel_full |
|---|---|---|---|---|
| 21 | vol | **+0.228** | +0.017 | +0.015 |
| 63 | vol | **+0.231** | -0.079 | -0.083 |
| 126 | vol | **+0.235** | -0.095 | -0.091 |

**Absolute thresholds dominate.** Relative either kills the IC (H=21:
0.23 → 0.02) or flips its sign (H=63/126). `rel_full` and `rel_exp` give
nearly identical numbers, so it isn't the forward leak doing the work —
the principle just doesn't apply here.

### Why — the bounded ordinal/relative principle (key takeaway)

The VRP-percentile / "where it's been" principle works for SOME signal
types and fails for others. The discriminating question is:

**Is this signal already unit-comparable across tickers?**

| Signal type | Apply ordinal/relative? | Examples |
|---|---|---|
| Already cross-ticker comparable (unitless ratios) | **NO** — keep absolute | β_mkt, β_mz, IC, percentile, Sharpe |
| Magnitude depends on ticker baseline | **YES** — ticker-relative percentile | VRP_wedge, raw residual, ensemble output, IV level |

β_mz = actual / predicted is dimensionless. β_mz = 1.5 means "model
under-predicts by 50%" regardless of ticker. Normalizing it against the
ticker's own distribution destroys the cross-ticker comparability — that's
why the relative version's IC collapsed.

### Implication

- **Keep absolute thresholds in `regime_signal_test.py`.** Don't refactor.
- The VRP percentile principle still holds for VRP. Specifically check
  signal-by-signal: if it's a unitless ratio, leave it absolute; if its
  magnitude depends on ticker baseline, ticker-relative percentile makes sense.
- For the half-residual corrector (Section 4): residual is in vol units,
  ticker-dependent magnitude, so ticker-relative framing SHOULD help there.
  The test result here doesn't invalidate that.

---

## 7. Economic Policy Uncertainty / EMV as Features

### The idea

Add Baker/Bloom/Davis indices as macro features:
- **EMV (Equity Market Volatility infrastructure)** — equity-market-specific
  news-mention intensity. FRED code `EMVOVERALLEMV`. Most directly relevant.
- **EPU (Economic Policy Uncertainty)** — broader, fiscal/regulatory mentions.
  FRED code `USEPUINDXD`. Useful but more orthogonal to vol.

Both free, daily, academically validated as adding explanatory power for vol
beyond standard macro features.

### Where it fits

`data_loader.fetch_fred_yfinance()` already pulls 6 FRED series — add these
two. Feature builder converts to:
- Raw level (z-scored vs 252-BD rolling mean/std)
- 21-BD change (regime shift detector)

### Why plausibly useful

Our 2025-2026 regime collapse on ORCL/MU/COST hit precisely during AI/valuation
narrative shifts that pure technical features can't see. News-mention intensity
is a low-resolution proxy for what news sentiment per-ticker would give us at
much higher cost.

### Deferred because

Trail-dynamics + relative-quadrant IC tests took priority. Now unblocked.

### When to revisit

Anytime — next priority research item. EMV has VOL-MAGNITUDE-LIKE units (it's
an intensity index), so per Section 6's takeaway it's a "ticker-relative
makes sense" signal — should be entered as z-score vs 252-BD rolling
mean/std, AND interacted with sector (defensive vs cyclical sensitivity
differs). Don't add as a raw global feature.

---

## 8. Per-Ticker News Sentiment

### The idea

Per-ticker daily news sentiment as a feature. Directly captures the
narrative-driven vol shocks our model can't see (Oracle AI valuation,
Costco margin questions, etc.).

### Cost / quality landscape

- **RavenPack** — paid, expensive, gold standard
- **Reuters / Bloomberg sentiment** — paid, broker-quality
- **Reddit / Twitter** APIs — free, very noisy
- **GPT-based scoring of free headlines** — moderate cost, decent quality

### Status

Deferred to v12+ unless budget justifies paid source. The ordinal/relative
reframing of existing residuals (Section 4) may capture much of what
sentiment would capture, at zero marginal data cost.

---

## 9. Autoregressive Ensemble (regime self-fixing) — v12+ ambition

### The vision

Build a model that doesn't just predict from features, but **continuously corrects itself
against its own recent residual signal** — integrated, not bolted on. The 63 / 126-day
horizons suffer most from regime drift (accumulated miss over a long forward window),
and a self-correcting architecture would let the model "notice" it's been wrong and
adjust *without waiting for the next WFA retrain*.

### Two-layer interim architecture (current plan, NOT this ambition — see §4)

For v1-v11, the answer is the **frontend-only overlay**:

```
ensemble(features) ─┬─→ MODEL TRUTH (untouched)  ─→ residuals → 2×2 regime classifier
                    └─→ DISPLAY (corrected)       = pfv_cal + α · ewma(residuals)
```

Two pipes share the same y_pred but serve different consumers. Residuals stay real for
analytics (the 2×2 needs untouched residuals to mean anything); the display gets the
self-healing correction. This is implementable in the React layer in a single render-time
utility function and requires zero model retraining. See [§4](#4-half-residual-auto-corrector-ar1-bias-correction-with-damping)
for the corrector itself.

### The long-term ambition

Once the overlay is shipped and its lift quantified, build an autoregressive
**ensemble member** that is part of the model proper. Three architectural candidates:

**Option A — Teacher-Student stacking**
```
teacher = current ensemble(features)              # predicts vol from observable inputs
student = small_model(features + teacher_residual_lags)  # predicts CORRECTION to teacher
final   = teacher + λ · student
```
- Student learns *when* the AR signal is useful (conditional on regime features)
- Backtest-clean if student is trained on residuals from a PREVIOUS WFA fold's teacher
- Most flexible; cleanest separation

**Option B — Recurrent layer on top of ensemble outputs**
```
hidden_state(t) = f(ensemble_pred(t), hidden_state(t-1), recent_residual(t-h))
final(t) = g(hidden_state(t))
```
- GRU / LSTM / state-space layer wrapping the ensemble
- Captures longer-range residual dependencies than EWMA
- Adds nontrivial training complexity; not obvious it beats teacher-student

**Option C — Mixture of experts conditional on regime**
```
weight(t) = softmax(regime_features(t))
final(t) = w_model · ensemble(features) + w_ar · ar_correction(residuals)
```
- Routes between pure-ensemble and AR-corrected based on regime signal
- Naturally answers "when does AR help?" by learning the gate
- Most interpretable; requires explicit regime classifier as input

### Why this is v12+, not v11

- Overlay (§4) provides 80% of the win for 5% of the effort and ZERO retraining risk
- Integrated AR has a real **WFA leakage trap**: residuals at training time depend on
  the model's prior version, and getting fold construction wrong inflates backtest R²
  spuriously by 5-10 points. Need clean overlay-experiment results FIRST to have a
  benchmark to validate the integrated version against
- The 63/126-day horizons where this would help most also have the longest feedback
  latency (you wait h BD to observe residuals). The data accumulation cycle alone
  takes 6+ months to validate
- Frontend overlay can ship in weeks; integrated AR is a 2-3 month research project

### Practical first step (when v12+ comes up)

1. Confirm overlay results (§4) show meaningful R² lift on extension period
2. Choose architecture: lean Option A (teacher-student) — simplest WFA-clean implementation
3. Design fold structure: each WFA fold's student trains on residuals from previous fold's
   teacher only — no within-fold residual leakage
4. Backtest against three benchmarks: (a) pure ensemble (current), (b) ensemble + overlay
   (§4), (c) full integrated AR ensemble. Lift over (b) is the metric that matters

### Connection to other parked work

- §4 (half-residual corrector) is the **prerequisite proof of concept**. If overlay
  alone doesn't help, integrated AR almost certainly won't either
- §3 (VRP decomposition paper) — the AR-corrected forecast would be a cleaner `pfv_cal`
  for the VRP_insurance vs VRP_forecast decomposition. Lower forecast error means
  cleaner separation of the two components

---

## 10. Dual-Head Model: Risk Head + Baseline Head

### The reframe

Mission has bifurcated. Two different things we want from the model:
1. **Risk forecasting** — "alert me to vol spikes." Asymmetric loss (QLIKE) is correct:
   under-prediction of a real shock is much more costly than over-prediction of a calm.
2. **VRP baseline** — "what's the rational center against which to measure market
   fear?" Symmetric loss (MSE/MAE) is correct: unbiased forecast lets wedge `IV − σ̂`
   be interpreted as "fear above the rational baseline" rather than "fear above our
   biased-high reference."

Right now we use one model (QLIKE) for both purposes. The β_mz=0.55 universe-wide
average is partly an artifact: QLIKE BY DESIGN biases toward over-prediction, so
"actual < predicted" is the expected outcome, not a flaw. But for VRP wedge
interpretation, that bias contaminates the signal.

### Architecture

Same ensemble pipeline (XGB+RF+EN+GARCH+Quantile), just trained with two different
target/loss configurations:

```
features → ensemble_risk     (QLIKE loss)     → σ̂_risk     → user-facing risk gauge, SHAP
features → ensemble_baseline (MSE/MAE loss)   → σ̂_baseline → VRP wedge computation, paper analytics
```

The two heads share feature engineering, training data, and WFA infrastructure. Just
a `loss=` parameter swap per training fold. Storage roughly doubles per ticker
(two joblibs); compute roughly doubles per retrain (two ensembles). Manageable.

### Where each head is used

| Consumer | Use head | Why |
|---|---|---|
| Equity-page forecast curves | risk | conservative under uncertainty is right for the user-facing number |
| SHAP explainer | risk | explanations match what the user sees |
| VRP wedge (frontend display) | baseline | wedge is interpretable only if reference is unbiased |
| VRP IC tests, academic analytics | baseline | clean econometric quantity |
| 2×2 regime classifier (β_mz) | baseline | β_mz=1 means well-calibrated; symmetric loss makes that meaningful |
| Quantile floor (P15) | risk | tail safety is the whole point |

### Practical first step

1. Add `--loss {qlike,mse,mae}` flag to model training (currently only QLIKE)
2. Run a backtest with MSE loss on 5-10 tickers, compare aggregate β_mz
3. If MSE β_mz comes in near 1.0, validates the bias-is-artifact hypothesis
4. If MSE β_mz is still ≪ 1.0, there's a deeper calibration issue beyond loss choice
5. Wire downstream consumers per the table above

### Deferred because

Same reason as half-residual corrector (§4): the dual-head architecture is most
valuable AFTER we've established the VRP wedge as the core actionable signal in
the product. Once VRP is the headline number, the bias-cleanliness of σ̂_baseline
becomes important.

### Connection to §3 and §11

- §3 (Forward-Looking VRP Decomposition paper) needs σ̂_baseline to construct a
  clean `VRP_insurance` quantity. Without it the decomposition mixes insurance
  signal and forecast bias.
- §11 (IV-prediction reframe, below) is the natural extension — if we go all the
  way to predicting IV directly with the baseline head, the wedge becomes a
  pure "options market disagrees with our IV model" quantity.

---

## 11. IV-Prediction Reframe: Predict IV, Compare to Market IV

### The idea

Current: predict realized vol (σ̂_RV) from features → compare to market IV → wedge.
But σ̂_RV and IV are different fundamental objects (statistical quantity vs market-priced
quantity with insurance premium baked in). The wedge mixes the two natures.

Reframe: **predict IV itself from non-IV features**, then compare to actual IV.

```
Target:     iv_atm_30d at date D                                 (was: rv_forward_21d)
Predictors: rv_21d, vol_regime_zscore, macro, factor ETF returns,
            sector beta, technicals — EVERYTHING EXCEPT current IV features
            (no iv_atm_60d/91d/182d, no vrp_wedge, no put_call_skew)
Wedge:      actual_iv_atm_30d − predicted_iv_atm_30d
```

The wedge becomes: "given purely realized/macro/technical conditions, what SHOULD the
options market be pricing? How much MORE is it actually pricing?"

Single conceptual axis (both target and predictor are IV-units quantities). True
econometric apples-to-apples.

### Why this is better than σ̂_RV-based wedge

- **Removes the realized-vs-implied units mismatch.** IV is annualized, IV. RV is also
  annualized vol, but realized over a window. They're close but not identical (e.g.,
  IV reflects 30-day forward expectation; RV is 21-day backward measurement).
- **The model isn't trying to forecast the unforecastable.** Long-horizon RV is full of
  news shocks that features can't see. But IV at date D is a market-priced number THAT
  EXISTS, determined by current conditions + sentiment. Predicting it from current
  conditions and measuring the residual (sentiment) is a cleaner econometric problem.
- **The wedge directly measures market disagreement.** When wedge > 0, options market is
  pricing more fear than features would suggest. That IS the actionable signal.

### What about features that ARE options-derived

`put_call_skew_30d`, `term_structure_slope`, `iv_atm_60d/91d/182d`, `vrp_wedge` — all
options-derived. The "right" exclusion list depends on philosophy:

- **Strict**: exclude ALL options-derived features. Wedge measures "options market vs.
  realized/macro/technical world." Maximally clean econometric statement.
- **Loose**: include longer-tenor IV (60/91/182d) and skew. Wedge measures "near-term
  options pricing vs longer-tenor + skew structure." More forecasting power but less
  clean to interpret.

For the academic paper version (§3), strict is right. For practical product, loose
may yield better IC.

### Test plan (POC scope)

1. Pick 3-5 tickers (AAPL, JPM, XOM, NVDA, KO — sector mix)
2. Build feature matrix per ticker, target = iv_atm_30d at date D (concurrent)
3. Train single XGB per ticker (no ensemble for POC, just feasibility check)
4. WFA-style walk forward to generate OOS predictions of iv_atm_30d
5. Compute wedge = actual_iv − predicted_iv
6. Compute EWMA(21) wedge and test IC vs forward outcomes
7. Compare IC of new wedge vs current `vrp_wedge` (the classical IV − rv_21d)

### Expected outcomes

- If new wedge IC ≥ classical wedge IC → strict reframe is better, productionize
- If new wedge IC < classical → classical was right, but the new framing might still
  be cleaner for the paper / for interpretability
- If results are roughly equal → choose based on UI/explanation simplicity

### Deferred because

POC needs to be run first. Once POC validates the framework, full rollout means
re-training the entire baseline-head pipeline (per §10) with IV as target. That's
a 1-2 day effort plus a corpus retrain.

### Connection to product UX

The frontend mockup's "VRP Signal" panel becomes even more interpretable:
- Old framing: "VRP = IV − model's vol forecast" (technical, requires explanation)
- New framing: "Market is pricing X% more vol than current conditions warrant" (immediate)

---

## 12. What We're Actually Measuring — RESOLVED 2026-05-27 (foundational)

### The question we asked

The entire project was built on the assumption that our wedge `IV − σ̂(RV)` isolates
the volatility risk premium. We had +0.40 IC against forward realized vol corpus-wide,
but never tested whether the signal IS what we claim it is. Any of these would
produce the same +0.40 IC:

1. True VRP (insurance markup) — our claim
2. Information asymmetry (options market sees scheduled events we don't)
3. Vol persistence (clustering autocorrelation, captured by the wedge construction)
4. Demand-side option flow (dealer hedging, microstructure)
5. Macro fear leaking through (a noisy VIX in disguise)
6. Vol-of-vol risk premium
7. Tail-skew premium

### The four tests (results)

**Test A — Systematic vs idiosyncratic decomposition** (`analysis/vrp_what_are_we_measuring.py`)
- Variance share: **systematic 1.4%, idiosyncratic 98.6%** — not noisy-VIX
- BUT pooled IC: systematic +0.19, idiosyncratic +0.16; **per-ticker idio median IC: -0.05**
- ⇒ Predictive content is in **cross-sectional structure** (which tickers persistently
  have high wedge), not in per-ticker time-series wiggle. Within-ticker variation
  has near-zero average predictive power.

**Test B — Macro/VIX correlation of aggregate wedge**
| Signal | Spearman with agg wedge |
|---|---|
| dollar_index | +0.59 |
| breakeven_5y | +0.56 |
| yield_slope | -0.49 |
| treasury_3mo | +0.41 |
| inflation_forward_5y5y | +0.38 |
| hy_spread | -0.20 (negative!) |
| spy_vol_21d | +0.17 |

⇒ Aggregate wedge tracks **macro liquidity/rate cycle**, NOT equity-market fear. SPY-vol
correlation is +0.17 (negligible). HY spread is NEGATIVELY correlated — opposite of
what a fear premium should look like.

**Test C — Regime-conditional IC**
| Regime | IC vs fwd vol h=21 |
|---|---|
| calm | +0.42 |
| normal | +0.44 |
| stress | +0.36 |

⇒ IC is **weakest in stress regimes**, peaks in normal markets. True VRP should
*strengthen* in stress (fear premium most actionable when markets afraid). Ours doesn't.

**Test D — Event-orthogonal residual wedge**
| | IC vs fwd vol h=21 |
|---|---|
| raw wedge | +0.402 |
| wedge − within-ticker-calendar-week-mean | +0.138 |
| variance share explained by calendar week | 29.7% |

⇒ **~65% of the wedge's predictive power lives in calendar-week-mean patterns** (mostly
earnings season clustering). Strip that out and IC drops from +0.40 to +0.14.

### The honest reframe

What our wedge signal **actually** is:

> A combination of (a) **cross-sectional structural ranking** of which tickers have
> persistently rich options pricing relative to realized vol, (b) **earnings season
> calendar effects** (~65% of predictive power), and (c) **macro liquidity-cycle
> correlations** (dollar/rates/breakevens). NOT a per-stock real-time fear premium.

### What the project should and shouldn't claim

❌ "We isolate the per-stock volatility risk premium" — not supported
❌ "Strongest signal during market stress" — opposite is true (Test C)
❌ "Per-stock VRP captured in time-series variation" — not supported (Test A)
❌ "Real-time fear gauge" — wrong framing (Test C + D)

✅ "Identifies persistently rich-option names" (cross-sectional ranking, Test A)
✅ "Captures earnings-season options-pricing premium" (Test D)
✅ "Correlates with macro liquidity regime" (Test B)
✅ "Forward-vol prediction with +0.40 IC corpus-wide" (the empirical result)
✅ **"β_mz aggregate signal IS a genuine market-wide fear early warning"** (separately
   validated: caught 7/8 major shocks 2015-2026, +1.13× lift on down→up events)

### Strategic implications for product

1. **Equity-page VRP panel reframe**: not "real-time fear" — instead "structural
   ranking + seasonality indicator." Tooltip: "Where is this name in its long-run
   IV-vs-realized-vol pattern + earnings-season position?"
2. **β_mz Macro signal becomes the primary macro-fear story** (not the per-stock
   wedge). It's the corpus-wide indicator that actually behaves like a fear premium.
3. **HAR-RV is closer to the true benchmark for VRP analytics than we acknowledged.**
   Our ensemble's marginal R² lift over HAR-RV is real but small; the wedge derived
   from either gives similar predictive content because vol clustering does most of
   the work in both. The product's edge isn't "better forecast → cleaner wedge" —
   it's "richer feature set surfaces structural patterns more transparently."

### Connection to other sections

- §3 (VRP decomposition paper) — needs reframing. Instead of "novel forward-looking
  VRP decomposition," the paper becomes "decomposing what 'VRP signals' actually
  measure: cross-sectional vs time-series vs seasonal vs macro components." That
  may be a *better* contribution because it questions a widespread literature assumption.
- §10 (dual-head loss) — the bias-from-QLIKE story still matters for the wedge
  interpretation, but the underlying issue (wedge isn't pure fear) survives the
  loss-function fix.
- §11 (IV-prediction reframe) — even cleaner econometric framing under the dual-head
  + non-IV feature set, but doesn't change the structural conclusion that the
  resulting signal is mostly seasonality + macro cycle.

### Test E (residual wedge) and Test F (path-length target) — RESOLVED

**Test E** (`analysis/vrp_residual_and_path.py`): doubly-residualized wedge
(strip per-ticker calendar-week mean AND per-date cross-section mean).

| Predictor | Pooled IC vs fwd_vol_h21 | Per-ticker median IC |
|---|---|---|
| vrp_wedge_ewma (raw) | +0.402 | +0.189 |
| wedge_minus_week | +0.138 | +0.165 |
| **wedge_minus_both** | **-0.101** | **-0.092** |

⇒ After stripping seasonality + cross-sectional mean, the residual has SLIGHTLY
NEGATIVE IC — i.e., the leftover 70% of wedge variance carries weak mean
reversion, not hidden fear premium. **There is no per-stock fear-premium signal
to recover.** The +0.40 lives entirely in the 30%-of-variance seasonality + macro
component. Question closed.

**Test F** (same script): use forward absolute path length `Σ|log_return|` over
h BD as alternative target.

| Horizon | IC vs fwd_vol | IC vs fwd_path | delta |
|---|---|---|---|
| 21 | +0.402 | +0.405 | +0.003 |
| 63 | +0.428 | +0.430 | +0.002 |

⇒ Path-length and std-based vol are functionally interchangeable targets for the
wedge — IC delta is +0.003. The wedge doesn't distinguish "directional movement"
from "variance dispersion" at this resolution. **Goalpost change doesn't reveal
a different signal.**

### Final conclusion

The wedge `IV − rv_21d_back` carries +0.40 IC against forward realized vol
across 11 years / 267k observations. That signal decomposes empirically as:

- **30% of variance**: per-ticker calendar-week-mean (mostly earnings seasonality)
  + per-date cross-sectional mean (macro/systematic) → CARRIES THE +0.40 IC
- **70% of variance**: per-ticker idiosyncratic time-series wiggle → CARRIES -0.10 IC
  (slight mean reversion, NOT fear premium)

The predictive content is structural and seasonal, not real-time fear. Path-length
and vol-std targets give identical IC, so target choice isn't a hidden lever either.

### Honest project-positioning takeaways

- ❌ "Per-stock fear premium isolator" — empirically not supported
- ❌ "Real-time risk gauge per ticker" — wedge time-series wiggle is noise/mean-reverting
- ❌ "Hidden VRP signal beneath the noise" — tested, isn't there
- ✅ "Vol forecaster slightly better than HAR-RV with richer feature set" — true
- ✅ "Cross-sectional structural ranking of persistently rich-option names" — true
- ✅ "Earnings-cycle premium tracker" — true
- ✅ "Macro liquidity-cycle correlated signal" — true
- ✅ "β_mz aggregate Universe Calibration Drift = market-wide fear early warning" — separately validated, 7/8 major shocks caught

### The intellectual contribution worth claiming

Most quant work assumes "VRP signal" without decomposing what it actually measures
empirically. The four-test decomposition (§12 above + Test E here) gives receipts
on a widespread literature assumption. As a paper concept: "What 'VRP signals'
actually measure: a corpus-wide empirical decomposition of vol-prediction
information sources." That's a stronger contribution than the original §3 framing
because it questions an assumption that academic VRP papers generally accept.

### Why the YZ migration is now the highest-leverage next step

Per the gravity-feature observation: event gravity features are designed to flag
scheduled-event proximity. Earnings vol is mostly an OVERNIGHT gap. GK target
measures intraday only and undermeasures earnings vol by 60-80%. So the loss
function fights against the very feature design that's trying to capture earnings
effects. A YZ target would:

1. Make event gravity features structurally meaningful in loss (they should
   strengthen significantly in SHAP)
2. Make the model's σ̂ correctly inflate during earnings windows
3. Shrink the wedge during earnings (because IV's earnings-anticipation no longer
   exceeds σ̂'s now-corrected earnings-anticipation)
4. **POSSIBLY reveal a real per-stock fear residual** that's currently masked
   under the 30% calendar-week-mean component (which would shrink once σ̂
   correctly absorbs earnings effects)

This is the architectural change most likely to materially change the answer to
"what's in the wedge."

### YZ migration plan

**Phase 1 (1-2 hours dev)**: rewrite `features.py:_add_rv_features` to use
Yang-Zhang formula instead of Garman-Klass. New `_add_yz_rv_features`. Keep both
available behind a config flag for backtest-clean comparison.

**Phase 2 (1 hour compute + analysis)**: POC retrain on 5 tickers (AAPL, JPM,
XOM, NVDA, KO). Compare to existing GK-trained model on same tickers. Metrics to
check:
- SHAP weight on event_earn_gravity (should increase materially)
- β_mz on test sample (should move closer to 1.0)
- VRP wedge IC on test sample (should hold or improve)
- Forward R² on YZ target (should beat GK-trained model's R² on GK target)

**Phase 3 (decision)**: if Phase 2 results are encouraging, commit to full corpus
retrain. ~3-4 hours wall time using the existing weekly_extend pipeline. If
results are not encouraging, document the negative finding and stick with GK.

**Phase 4 (rollout, if positive)**: re-run `rebuild_aggregates` → `mz_overlay` →
`export_for_webapp --all --push-to-supabase`. New `model_run_id=5` becomes
canonical.

**Phase 5 (re-test what's in the wedge)**: re-run vrp_what_are_we_measuring.py
on the YZ-trained predictions. If the calendar-week-mean variance share drops
(model now absorbs earnings effects), check if the residual wedge has ANY
positive IC. That would be the genuine "is there fear premium under the
distortion" answer.

### YZ migration — RESOLVED 2026-05-27: rigorous POC says don't migrate

After the quick XGB-only POC gave mixed results, ran a rigorous WFA POC
(`analysis/yz_vs_gk_wfa.py`): 15 tickers × full ensemble (XGB + RF + ElasticNet)
× 5 disjoint WFA folds (2021-2026 sliding 6-month test windows) × 2 estimators.
150 ensemble trainings total.

**Aggregate results (15 tickers, 5-fold mean):**

| Metric | Result | Tickers improving |
|---|---|---|
| ΔR² (YZ − GK) | mean **−0.64**, median −0.24 | 5/15 |
| Δ\|β_mz − 1\| (positive = closer to 1) | mean **−0.09** | 6/15 |
| Δevent_gravity_importance | mean **+0.024** | 10/15 ✓ |
| Δearn_gravity_rank (positive = ranked higher) | mean **−2.45** | 5/15 |

**Verdict**: YZ migration does NOT improve forecast accuracy. Event-gravity
importance rises on 10/15 tickers (theoretical case partially validated), but
this doesn't translate to R² because **earnings overnight gaps are largely
surprises** — the model can know the date (gravity feature) but not the
magnitude. YZ adds unpredictable variance to the target.

**Economic intuition (in hindsight, obvious)**:
- GK target = predictable intraday vol → tractable forecasting problem
- YZ target = predictable intraday + somewhat-predictable seasonal earnings + **mostly-unpredictable overnight surprises** → harder problem
- GK was actually a defensible target choice all along by implicitly defining a more learnable forecasting problem

**Decision**: do NOT do full corpus YZ retrain. The wedge framing IS what it
is regardless of target choice; YZ doesn't rescue per-stock fear-premium
isolation, and degrades the model's R². Reframe from §12 is now empirically
**locked in** — the project measures structural + seasonal + macro patterns,
NOT per-stock real-time fear, and no architectural change we tested can
change that conclusion.

**What the negative result IS worth**:
- Saves ~4 hours of compute that would have produced a worse model
- Provides empirical receipts on architectural decisions
- Confirms the reframe; reduces "did we look at this carefully enough" doubts
- The methodology (15-ticker × WFA × full ensemble × 2 estimators) is a
  template for any future architectural-change validation

---

## 13. β_mz Universe Calibration Drift Signal — DEEP DIVE QUEUE

The β_mz aggregate signal is empirically the strongest validated risk indicator
in the project (caught 7 of 8 major US vol shocks 2015-2026, +1.13× lift on
down→up events). Per RESEARCH_TODO §12 conclusion, this is the genuine
market-fear early warning that the per-stock wedge is not. Productionization
priority: HIGH.

### What we know already

- Per-ticker β_mz = log-log MZ regression slope on rolling 252-BD predictions
- Aggregate = universe-mean β_mz per snapshot
- 12-week rolling slope of aggregate β_mz
- Sign-change events at weekly cadence
- 37 events over 11 years (2014-2026): 18 down→up, 19 up→down
- Forward 21-BD SPY vol lift: 1.13× on down→up, 0.88× on up→down
- Hit rate: 7 of 8 major US vol shocks caught with same-direction signal

### What's still open — deep dive candidates

**(a) Robustness across smoothing windows** — does signal hold at 4-week, 8-week,
24-week slopes? Sweet spot vs noise?

**(b) Lead time analysis** — for confirmed shocks, how many BD before vol spike
does signal fire? Is it actionable (30+ days) or coincident (<5 days)?

**(c) False positive characterization** — among 18 down→up events, what fraction
preceded a defined "real shock" (e.g., SPY vol > some threshold within N days)?

**(d) Level vs slope** — is absolute β_mz level informative, or only slope direction?

**(e) Confidence indicators** — do bigger slope changes have higher hit rate? Is
slope MAGNITUDE a useful "confidence" signal alongside sign?

**(f) Sector decomposition** — do sector-aggregate β_mz signals add information
beyond corpus aggregate? Tech vs financials vs staples β_mz timeseries.

**(g) Combination with other early-warning signals** — does β_mz add IC over
just monitoring HY spreads or VIX directly?

**(h) Current state diagnostic** — what's β_mz reading now and what does it say?

**(i) Simple long/flat strategy backtest** — fade equities on down→up, get long
on up→down. What's Sharpe? Skew? Max DD vs buy-and-hold?

### Productionization path

Once deep-dive validates the signal in 2-3 different ways, productionize as
the Macro page headline. Visual: 11-year sparkline of universe-mean β_mz with
slope-colored segments + vertical event-marker bars + "current regime: COOLING /
HEATING" pill + brief LLM-generated explanation of recent state.

Not on the equity page — that's the per-stock context engine. β_mz is
inherently a corpus-level signal and belongs on Macro.

---

## 14. β_mz Universe Calibration Drift — VALIDATED DEFENSIVE OVERLAY (2026-05-27)

### Full empirical receipts (cumulative across all tests run)

| Test | Result |
|---|---|
| Robustness across smoothing windows (4/8/12/24 weeks) | Signal strengthens monotonically; 24w lift = 1.52× (vs 12w 1.13×) |
| Lead time | Median 5 BD, max 13 BD (yen carry); coincident-to-leading |
| Hit rate (down→up events) | 9 of 18 caught SPY vol > P90 within 42 BD = 50% precision |
| Level vs slope IC | IC(level, fwd_vol_42d) = +0.13; IC(slope, fwd_dd_21d) = -0.15 |
| IC(slope, fwd_dd_21d) | **-0.146 — strongest single-signal IC against forward drawdowns** |
| Multi-signal: HY spread alone | 2.70× lift (BETTER than β_mz alone — humbling but important) |
| Multi-signal: β_mz + HY combinations | Naive AND/OR don't help; need smarter combiner |
| Cost-modeled backtest (5 bps/flip) | $300,680 ending value vs $230,992 BH on $100k starting |
| Multi-index test | 7/8 ETFs see Sharpe improvement, **8/8 see max DD reduction** |
| Subperiod (calm/COVID/infl) | Strategy works in all 3 regimes; COVID most dramatic (-36% → -11%) |
| Monte Carlo hypothesis test (N=1000 nulls) | **p < 0.001 on Sharpe; p = 0.012 on DD; p = 0.021 on return** |
| Best single index lift | XLF (financials): Sharpe 0.30 → 1.03, DD -43% → -16% |

### Why this signal exists (best explanation as of 2026-05-27)

Three plausible reasons combine; the signal lives in the intersection:

**1. It's a SECOND-ORDER signal** — about how forecasting models systematically
fail before regime transitions, not about first-order market state. Vol models
trained on historical patterns lag genuine regime shifts. Single-stock
miscalibration is noisy; CROSS-STOCK aggregate miscalibration cancels
idiosyncrasy and surfaces the regime transition itself, observed indirectly.

**2. Money-saving vs money-making research bias** — academic VRP literature is
overwhelmingly about return-premium isolation, not drawdown prediction. The
slope of β_mz has IC -0.15 against forward DD but only -0.11 against forward
return. Defensive signals don't get published because they don't pitch as
edge-generating alpha. The literature systematically underexplores "what
predicts losses" relative to "what predicts gains."

**3. Infrastructure prerequisite is unusual** — requires (a) per-stock vol
forecasting at scale (93 stocks), (b) walk-forward retraining for OOS
calibration measurements, (c) per-ticker β_mz tracking, (d) cross-stock
aggregation, (e) defensive overlay reframe. Each piece exists somewhere;
the combination is rare. Academic finance has #b and #d; practitioner alpha
research has #a and #c; risk-management groups have #c but not cross-stock
aggregation. **The signal lives in the gap between research domains.**

**Stumbled on because**: built the infrastructure for first-order reasons,
reframed midway from "isolate VRP for alpha" to "what does my model's failure
pattern tell me," accepted a negative result on the per-stock wedge, and the
β_mz aggregate emerged from honest re-examination of what survived the test.

### Honest framing for external claims

> "We tested the standard VRP isolation hypothesis rigorously and found it
> wasn't the right framing for our data. In doing that decomposition, we
> found something else — a corpus-level model-calibration-drift signal that
> empirically predicts forward equity drawdowns with statistical significance
> (Monte Carlo p < 0.001 vs random-signal null, N=1000). It's a defensive
> overlay signal, not an alpha signal. We don't claim it's never been
> discovered — we claim that the combination of infrastructure (per-stock
> vol ensemble + WFA calibration tracking + cross-stock aggregation) and
> framing (defensive overlay vs alpha hunting) is unusual enough that this
> specific signal didn't surface in the published literature we've reviewed."

### Productionization status

- Frontend spec: `model/DASHBOARD_SPEC_MACRO_REGIME.md` (SWE-ready)
- Analytics scripts: `analysis/aggregate_beta_weekly.py`, `beta_mz_deep_dive.py`,
  `beta_mz_drawdown_value.py`, `beta_mz_defensive_overlay.py`,
  `beta_mz_multi_index_test.py`
- Validation outputs: `results/validation/beta_mz_*.csv`
- Next step: SWE builds Macro page panel from spec; add nightly compute job
  for the panel JSON to `scripts/daily_refresh.bat`

### Remaining open research questions (lower priority)

1. **Multi-signal scoring** — naive AND/OR don't help; train a logistic
   regression composite of β_mz + HY + yield curve + breakeven. Likely path
   to a meaningfully better signal than HY alone.
2. **True out-of-sample validation** — split signal development on 2015-2020,
   test on 2021-2026 (or vice versa). Removes lookahead bias concern.
3. **Sector-aggregate variants** — Tech vs Financials vs Staples β_mz time
   series. Might add information beyond corpus aggregate.
4. **Real-time alert system** — email/SMS notifications on regime changes,
   with documented hit rate / lead time / historical context.

---

## 15. Notes from Conversation

---

## 13. Notes from Conversation

- Cross-sectional variance in VRP_ewma → return predictability is genuinely
  ticker-specific. Probably reflects retail/dealer flow mix per name.

- The "fear premium = mean reversion = positive forward return" finding is
  consistent with literature on contrarian indicators, but at this resolution
  it survives statistical scrutiny only at longer horizons (21d+).

- Treating supply as constant is a valid simplification for the product UI
  but NOT for an academic paper claiming "S/D decomposition." Be careful
  with framing.

- The AAPL anomaly (negative correlation with forward returns) is worth
  understanding. AAPL has unusual options flow (retail-heavy, gamma squeeze
  history, structural buyback demand). Could be a case study in why ticker-
  specific calibration matters.