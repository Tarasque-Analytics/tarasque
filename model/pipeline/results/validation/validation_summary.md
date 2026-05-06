# v10+ Signal Validation — Economic Significance Brief

_Generated 2026-05-04._

## 1. 3-sigma event lead-time precision
- **Lead 5d**: n=26 tickers, base rate=3.594%, precision (top-15% forecast)=**4.669%**, recall=34.977%, lift=1.27x
- **Lead 10d**: n=26 tickers, base rate=3.598%, precision (top-15% forecast)=**3.288%**, recall=24.767%, lift=0.89x
- **Lead 21d**: n=26 tickers, base rate=3.613%, precision (top-15% forecast)=**1.732%**, recall=12.963%, lift=0.46x

## 2. Drawdown-conditional (forecast decile -> forward DD)
- **H=21d**: top-decile mean DD=-6.252%, bottom-decile DD=-2.487%, spread=-3.765%
- **H=63d**: top-decile mean DD=-11.969%, bottom-decile DD=-3.338%, spread=-8.631%
- **H=126d**: top-decile mean DD=-17.871%, bottom-decile DD=-4.200%, spread=-13.671%

## 3. Demeaned cross-sectional IC
- Daily IC mean: **0.5259**, std: 0.1968, n_dates: 2719
- IC > 0 fraction: 98.86%
- IC > 0.05 fraction: 97.76%
- t-stat (IC mean vs zero): 139.33

## 4. Quintile lift (cross-sectional)
Mean realized vol by forecast quintile (cross-sectional, all dates):
- Q0: 0.2214
- Q1: 0.2101
- Q2: 0.2135
- Q3: 0.2254
- Q4: 0.2538
- **Q5/Q1 lift: 1.15x**

## 5. Coverage q15 (floor signal validation)
- **H=21**: mean coverage=0.774 (target 0.85), in [0.80, 0.90]: 4/26
- **H=63**: mean coverage=0.758 (target 0.85), in [0.80, 0.90]: 3/26
- **H=126**: mean coverage=0.768 (target 0.85), in [0.80, 0.90]: 8/26

## Caveats
- All tests are in-sample (walk-forward but no held-out test set).
- Survivorship bias: tickers in our 91-name corpus all survived 2014-2025.
- Period sensitivity: 2020-2021 vol regime dominates the realized vol distribution.
- DM test vs HAR-RV: see prior `benchmark_comparison.csv` (v6 audit, 97/97 tickers beat persistence).