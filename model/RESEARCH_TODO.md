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

## 4. Notes from Conversation

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