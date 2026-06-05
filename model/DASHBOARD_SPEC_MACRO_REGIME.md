# Macro Page: Universe Calibration Regime Panel — Frontend Spec

**Status**: ready for frontend handoff
**Last updated**: 2026-05-27
**Validation**: see `analysis/beta_mz_*.py` results; Monte Carlo p < 0.001 (N=1000)

---

## What this is

A defensive overlay signal derived from cross-stock model-calibration drift in
the 93-ticker corpus. Validated to:

- Cut historical max drawdown by **51%** on equal-weight universe (-36.1% → -17.7%)
- Win on Sharpe in **7 of 8 tested ETFs** (SPY, QQQ, IWM, XLF, XLE, XLK, XLV, XLI)
- Reduce max DD on **8 of 8 ETFs** (universal across equity markets)
- **Pass Monte Carlo significance test at p < 0.001** vs random-signal null

This is the strongest empirically-validated signal in the entire project. It
belongs on the Macro page as the headline risk indicator.

---

## Data sources

All from existing pipeline outputs, computed nightly:

| Source | Path | Refresh |
|---|---|---|
| Per-ticker β_mz weekly | `results/validation/aggregate_beta_weekly.csv` | weekly_extend |
| Universe-mean aggregate | computed from above | nightly via daily_refresh |
| 12-week rolling slope | derived feature | nightly |
| Sign-change events | derived from slope | nightly |
| Strategy backtest metrics | `results/validation/beta_mz_multi_index.csv` | weekly |
| Current regime state | derived from latest aggregate | nightly |

Frontend should read from the daily refresh's webapp_export bundle. Add the
β_mz time series + current-state JSON to that bundle.

---

## Panel layout (4 sub-components)

```
┌─ UNIVERSE CALIBRATION REGIME ─────────────────────────────────────────┐
│                                                                        │
│  [1. CURRENT STATE GAUGE]              [2. STRATEGY COMPARISON CARD]  │
│   Regime: COOLING   ↓                   $100k starting (Jan 2015):    │
│   β_mz: 0.594  (P22 of 1Y)              Buy-and-hold:    $230,992     │
│   12w slope: -0.015                     β_mz overlay:    $300,680     │
│   Last change: 2025-10-17 (155 BD ago)  ↳ +30% / DD -51% / Sharpe 2.1×│
│                                                                        │
│  [3. 11-YEAR TIME SERIES with regime shading + event markers]         │
│   X: time (2014 - now)  Y: aggregate β_mz                             │
│   Background: amber when slope > 0 (heating), gray when ≤ 0 (cooling) │
│   Vertical bars at sign-change events, labeled with what happened      │
│                                                                        │
│  [4. RECENT REGIME LOG (text)]                                         │
│   2025-10-17 → COOLING (currently 155 BD in)                          │
│   2025-07-25 → HEATING (lasted 64 BD)                                 │
│   2025-05-23 → COOLING (lasted 45 BD)                                 │
│   ...                                                                  │
└────────────────────────────────────────────────────────────────────────┘
```

### Component 1: Current State Gauge

**Display**:
- Regime label (large, color-coded): "COOLING" (green) or "HEATING" (amber)
  - Heating = slope_w12 > 0 (model under-predicting → vol regime escalating)
  - Cooling = slope_w12 ≤ 0
- Current β_mz value (3 decimals): "0.594"
- Percentile in 1-year history: "P22 of 1Y" (where in own distribution)
- 12-week slope value: "-0.015"
- Last regime change with BD elapsed: "2025-10-17 (155 BD ago)"

**Data shape (JSON)**:
```json
{
  "current_regime": "COOLING",
  "current_beta_mz": 0.594,
  "beta_mz_percentile_1y": 22,
  "slope_w12": -0.015,
  "last_regime_change_date": "2025-10-17",
  "days_in_current_regime": 155,
  "regime_color": "#4a8c4a"   // green for cooling, amber for heating
}
```

### Component 2: Strategy Comparison Card

**Display** (3 lines):
1. Setup: "$100k starting (Jan 2015):"
2. BH: "Buy-and-hold: $230,992"
3. Overlay: "β_mz overlay: $300,680 (+30% / DD -51% / Sharpe 2.1×)"

**Data shape**:
```json
{
  "starting_capital": 100000,
  "start_date": "2015-01-02",
  "end_date": "2026-05-26",
  "buy_and_hold": {
    "ending_value": 230992,
    "total_return": 1.31,
    "max_drawdown": -0.361,
    "sharpe": 0.43
  },
  "beta_mz_overlay": {
    "ending_value": 300680,
    "total_return": 2.01,
    "max_drawdown": -0.177,
    "sharpe": 0.92,
    "time_in_market_pct": 60
  },
  "lift_vs_bh": {
    "ending_value_pct": 30.2,
    "dd_reduction_pct": 51.0,
    "sharpe_ratio": 2.14
  }
}
```

### Component 3: 11-year Time Series Chart

**Display**:
- X axis: dates from 2014-12 to today
- Y axis: aggregate β_mz value (typical range: 0.2 to 1.0)
- Line: thin colored line of universe-mean β_mz, weekly granularity
- Background shading: amber when slope_w12 > 0 (heating regimes), green-tinted when ≤ 0 (cooling)
- Vertical bars at every sign-change event, color-coded:
  - Red for down→up (heating onset)
  - Blue for up→down (cooling onset)
- Annotation labels at each major bar (hover or always-visible):
  - "2020-02-21 → Feb COVID heating signal" (preceded -36% market DD)
  - "2018-01-26 → Volmageddon precursor"
  - etc.

**Data shape**:
```json
{
  "timeseries": [
    {"date": "2014-12-26", "beta_mz": 0.612, "slope_w12": null, "regime": null},
    ...
    {"date": "2026-05-22", "beta_mz": 0.594, "slope_w12": -0.015, "regime": "COOLING"}
  ],
  "events": [
    {"date": "2020-02-21", "direction": "down_to_up", "label": "COVID precursor", "forward_dd_42bd": -0.361},
    ...
  ]
}
```

### Component 4: Recent Regime Log

**Display** (last 6-10 sign changes, most recent first):
- Date + direction + duration if past
- Markdown-friendly format for easy LLM augmentation later

---

## Interactivity

Two toggles:

1. **Index selector**: "Show overlay performance vs: [SPY | QQQ | IWM | XLF | XLE | XLK | Equal-weight universe]" — swaps the Strategy Comparison Card numbers
2. **Time range selector**: "[1Y | 5Y | All]" for the time-series chart

---

## Headline copy / hover tooltips

**Panel title** (large):
> Universe Calibration Regime

**Subtitle** (one line):
> Cross-stock model-calibration drift signal · validated as defensive overlay

**Tooltip on the current regime label**:
> "HEATING: our 93 stock vol models are systematically *under*-predicting realized vol across the corpus. Historically, regime transitions of this type preceded above-average forward equity vol in 7 of 8 major US market shocks (2015-2026)."
> 
> "COOLING: our models are systematically over-predicting vol. Markets running calmer than features suggest."

**Tooltip on the strategy card**:
> "Hypothetical defensive overlay: hold the index when our regime signal indicates COOLING; rotate to cash when HEATING. Backtested 2015-2026. Past performance is not a guarantee — this is a model-derived indicator, not an investment recommendation."

---

## What NOT to claim

- ❌ "Predicts the next market crash"
- ❌ "Real-time fear gauge per stock" (that's the wedge — different signal, different page)
- ❌ "Outperforms buy-and-hold in all conditions" (only on Sharpe and DD; total return is sometimes lower)
- ❌ "Edge-generating alpha signal"

## What you CAN claim

- ✅ "Statistically significant at p < 0.001 vs random-signal null (Monte Carlo N=1000)"
- ✅ "Reduces historical max drawdown by 51% on equal-weight universe"
- ✅ "Wins on Sharpe vs buy-and-hold in 7 of 8 tested ETFs (SPY, QQQ, IWM, XLF, XLE, XLV, XLI)"
- ✅ "Reduces max drawdown in 8 of 8 tested ETFs (universal across equity sectors)"
- ✅ "Caught 7 of 8 major US vol shocks 2015-2026 with same-direction signal"
- ✅ "Cost-modeled at 5 bps/flip (10 bps round trip); strategy still beats buy-and-hold"

## Execution-timing caveat (IMPORTANT for honest claims)

The backtest assumes **Friday-close execution** (the signal is computable post-Friday-close).
Institutional players can act via Sunday futures; retail can only act at **Monday open**.

- **Monday-open execution costs ~0.34% per signal = ~14% of average signal PnL** (Test 22).
- Honest adjusted claims for retail:
  - Sharpe improvement ~**0.27** (institutional Friday-close ~0.34)
  - Max DD reduction ~**10pp** (institutional ~13pp)
- The headline backtest numbers (Sharpe 0.94, -21% DD on 25% tilt) are Friday-close.
  Display a footnote: "Backtest uses Friday-close execution; realized retail returns
  with Monday-open execution are ~14% lower per signal."

## Signal cadence facts (for the panel's methodology tooltip)

- Signal computed at **weekly (Friday) snapshots** — β_mz AND 12-week slope both weekly
- 12-week slope is the canonical smoothing (24-week is stronger per-event but fewer signals;
  12-week is best for portfolio outcomes)
- Asymmetry: UP→DOWN (calm) is 79% reliable; DOWN→UP (stress) is 56% reliable but bigger
  magnitude when right. Size positions accordingly — lean long on cooling, modest defense on heating.
- Daily-cadence β_mz never tested (Open Test G) — would catch signals 2-3 days earlier,
  possibly recovering some of the Monday-lag cost.

---

## Implementation notes for SWE

- **Data refresh**: panel data should be regenerated nightly by the daily_refresh
  pipeline. Add a step to `scripts/daily_refresh.bat` that runs
  `python -m model.pipeline.scripts.compute_beta_mz_panel_data` (to be written)
  and writes `results/webapp_export/macro_regime_panel.json`.
- **Frontend fetches** that JSON via Supabase storage or as part of the
  webapp_export bundle push.
- **No backend compute** required on user request — all metrics are precomputed
  nightly.
- **Acceptance criteria**: panel renders for a user with current state + 11-year
  chart in <500ms; hover tooltips include the educational copy above; index
  selector switches strategy card in <100ms.

---

## Future enhancements (post-MVP)

- LLM-generated narrative summary of current regime ("Markets have been in a
  cooling regime for 155 trading days. The last heating signal preceded the
  March 2025 vol spike by 6 BD. Universe β_mz is at P22 of its 1-year
  history — historically, low readings precede above-average forward vol in
  62% of past instances.")
- Per-sector β_mz breakdown (Tech / Financials / Energy aggregates as separate
  sub-panels — see RESEARCH_TODO §13 deep-dive item)
- Combined HY-spread + β_mz signal (research item — naive AND/OR don't help
  but a logistic-regression composite might)
- User-customizable starting capital and time range for the strategy
  comparison card
- Email/SMS alerts on regime changes
