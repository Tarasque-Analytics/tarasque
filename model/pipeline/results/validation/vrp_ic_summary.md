# VRP Information Coefficient Suite

Tests whether VRP-derived signals predict forward outcomes. The
central thesis of the project — does VRP carry forward-looking
information?

## Sign expectations
- `vol`: higher VRP-fear/elevation → higher forward vol → POSITIVE IC
- `absret`: same intuition → POSITIVE IC
- `ret`: contrarian/mean-revert literature → POSITIVE IC at long horizons
  (high VRP = fear priced = subsequent rally)
- `dd`: higher fear → worse forward drawdown → NEGATIVE IC

## Pooled IC (all tickers × dates concatenated)

### Forward VOL

**Best at H=21:** `vrp_ewma` (IC=+0.396)

| predictor | h21 | h63 | h126 |
|---|---|---|---|
| vrp_ewma | +0.396 | +0.426 | +0.427 |
| vrp_ewma_pct_own | +0.116 | +0.088 | +0.086 |
| vrp_ewma_slope5 | +0.149 | +0.053 | +0.057 |
| vrp_pct_own | +0.148 | +0.058 | +0.062 |
| vrp_raw | +0.332 | +0.273 | +0.275 |
| vrp_sign | +0.057 | +0.035 | +0.051 |
| vrp_slope5 | +0.067 | +0.048 | +0.043 |
| vrp_zscore_own | +0.146 | +0.050 | +0.053 |

### Forward ABSRET

**Best at H=21:** `vrp_ewma` (IC=+0.218)

| predictor | h21 | h63 | h126 |
|---|---|---|---|
| vrp_ewma | +0.218 | +0.217 | +0.232 |
| vrp_ewma_pct_own | +0.081 | +0.039 | +0.028 |
| vrp_ewma_slope5 | +0.078 | +0.031 | +0.021 |
| vrp_pct_own | +0.080 | +0.033 | +0.022 |
| vrp_raw | +0.177 | +0.143 | +0.145 |
| vrp_sign | +0.039 | +0.027 | +0.027 |
| vrp_slope5 | +0.024 | +0.021 | +0.021 |
| vrp_zscore_own | +0.080 | +0.027 | +0.014 |

### Forward RET

**Best at H=21:** `vrp_ewma` (IC=+0.046)

| predictor | h21 | h63 | h126 |
|---|---|---|---|
| vrp_ewma | +0.046 | +0.090 | +0.122 |
| vrp_ewma_pct_own | +0.007 | +0.027 | +0.046 |
| vrp_ewma_slope5 | +0.013 | -0.001 | +0.005 |
| vrp_pct_own | +0.001 | +0.004 | +0.011 |
| vrp_raw | +0.033 | +0.052 | +0.075 |
| vrp_sign | -0.009 | -0.012 | +0.003 |
| vrp_slope5 | -0.014 | -0.001 | -0.004 |
| vrp_zscore_own | +0.003 | +0.003 | +0.007 |

### Forward DD

**Best at H=21:** `vrp_ewma` (IC=-0.116)

| predictor | h21 | h63 | h126 |
|---|---|---|---|
| vrp_ewma | -0.116 | -0.114 | -0.098 |
| vrp_ewma_pct_own | -0.045 | -0.038 | -0.031 |
| vrp_ewma_slope5 | -0.051 | -0.030 | -0.029 |
| vrp_pct_own | -0.055 | -0.036 | -0.035 |
| vrp_raw | -0.099 | -0.081 | -0.071 |
| vrp_sign | -0.032 | -0.035 | -0.035 |
| vrp_slope5 | -0.025 | -0.022 | -0.019 |
| vrp_zscore_own | -0.052 | -0.031 | -0.031 |

## Per-ticker IC distribution (median across tickers)

Pooled IC can be inflated by between-ticker variance; per-ticker
median is the strict test. `frac_abs_above_010` = fraction of
tickers where |IC| > 0.10 (rule-of-thumb actionable threshold).

### Forward VOL

| predictor | h | n_tickers | ic_median | ic_mean | iqr_lo | iqr_hi | frac>0.10 |
|---|---|---|---|---|---|---|---|
| vrp_raw | 21 | 93 | +0.227 | +0.231 | +0.172 | +0.286 | 0.99 |
| vrp_raw | 63 | 93 | +0.128 | +0.132 | +0.059 | +0.191 | 0.57 |
| vrp_raw | 126 | 93 | +0.117 | +0.128 | +0.059 | +0.177 | 0.60 |
| vrp_ewma | 21 | 93 | +0.179 | +0.194 | +0.076 | +0.279 | 0.69 |
| vrp_ewma | 63 | 93 | +0.192 | +0.181 | +0.042 | +0.279 | 0.70 |
| vrp_ewma | 126 | 93 | +0.144 | +0.160 | +0.018 | +0.285 | 0.71 |
| vrp_pct_own | 21 | 93 | +0.167 | +0.177 | +0.125 | +0.222 | 0.87 |
| vrp_pct_own | 63 | 93 | +0.060 | +0.070 | +0.038 | +0.096 | 0.23 |
| vrp_pct_own | 126 | 93 | +0.071 | +0.078 | +0.044 | +0.103 | 0.31 |
| vrp_ewma_pct_own | 21 | 93 | +0.141 | +0.139 | +0.076 | +0.202 | 0.68 |
| vrp_ewma_pct_own | 63 | 93 | +0.095 | +0.107 | +0.044 | +0.158 | 0.52 |
| vrp_ewma_pct_own | 126 | 93 | +0.096 | +0.107 | +0.023 | +0.188 | 0.51 |
| vrp_zscore_own | 21 | 93 | +0.164 | +0.176 | +0.117 | +0.225 | 0.83 |
| vrp_zscore_own | 63 | 93 | +0.054 | +0.066 | +0.032 | +0.092 | 0.23 |
| vrp_zscore_own | 126 | 93 | +0.066 | +0.072 | +0.034 | +0.097 | 0.25 |
| vrp_slope5 | 21 | 93 | +0.061 | +0.063 | +0.038 | +0.081 | 0.13 |
| vrp_slope5 | 63 | 93 | +0.035 | +0.037 | +0.024 | +0.045 | 0.01 |
| vrp_slope5 | 126 | 93 | +0.026 | +0.030 | +0.017 | +0.039 | 0.01 |
| vrp_ewma_slope5 | 21 | 93 | +0.155 | +0.168 | +0.115 | +0.216 | 0.85 |
| vrp_ewma_slope5 | 63 | 93 | +0.058 | +0.058 | +0.037 | +0.079 | 0.11 |
| vrp_ewma_slope5 | 126 | 93 | +0.068 | +0.068 | +0.045 | +0.093 | 0.17 |
| vrp_sign | 21 | 93 | +0.011 | +0.017 | -0.031 | +0.053 | 0.14 |
| vrp_sign | 63 | 93 | -0.019 | -0.015 | -0.053 | +0.016 | 0.12 |
| vrp_sign | 126 | 93 | +0.003 | +0.003 | -0.045 | +0.040 | 0.13 |

### Forward ABSRET

| predictor | h | n_tickers | ic_median | ic_mean | iqr_lo | iqr_hi | frac>0.10 |
|---|---|---|---|---|---|---|---|
| vrp_raw | 21 | 93 | +0.109 | +0.117 | +0.074 | +0.160 | 0.55 |
| vrp_raw | 63 | 93 | +0.060 | +0.061 | +0.005 | +0.111 | 0.32 |
| vrp_raw | 126 | 93 | +0.064 | +0.059 | +0.003 | +0.110 | 0.34 |
| vrp_ewma | 21 | 93 | +0.097 | +0.112 | +0.053 | +0.176 | 0.51 |
| vrp_ewma | 63 | 93 | +0.062 | +0.075 | -0.002 | +0.162 | 0.48 |
| vrp_ewma | 126 | 93 | +0.075 | +0.078 | -0.001 | +0.154 | 0.48 |
| vrp_pct_own | 21 | 93 | +0.088 | +0.086 | +0.050 | +0.125 | 0.41 |
| vrp_pct_own | 63 | 93 | +0.033 | +0.033 | -0.007 | +0.093 | 0.24 |
| vrp_pct_own | 126 | 93 | +0.019 | +0.024 | -0.020 | +0.072 | 0.15 |
| vrp_ewma_pct_own | 21 | 93 | +0.087 | +0.084 | +0.046 | +0.126 | 0.44 |
| vrp_ewma_pct_own | 63 | 93 | +0.045 | +0.040 | -0.031 | +0.108 | 0.45 |
| vrp_ewma_pct_own | 126 | 93 | +0.023 | +0.031 | -0.043 | +0.114 | 0.43 |
| vrp_zscore_own | 21 | 93 | +0.085 | +0.086 | +0.043 | +0.127 | 0.40 |
| vrp_zscore_own | 63 | 93 | +0.030 | +0.030 | -0.015 | +0.085 | 0.20 |
| vrp_zscore_own | 126 | 93 | +0.019 | +0.019 | -0.031 | +0.057 | 0.16 |
| vrp_slope5 | 21 | 93 | +0.016 | +0.019 | -0.010 | +0.043 | 0.02 |
| vrp_slope5 | 63 | 93 | +0.013 | +0.011 | -0.009 | +0.030 | 0.01 |
| vrp_slope5 | 126 | 93 | +0.013 | +0.013 | -0.003 | +0.027 | 0.00 |
| vrp_ewma_slope5 | 21 | 93 | +0.075 | +0.077 | +0.032 | +0.119 | 0.38 |
| vrp_ewma_slope5 | 63 | 93 | +0.029 | +0.031 | -0.007 | +0.070 | 0.12 |
| vrp_ewma_slope5 | 126 | 93 | +0.027 | +0.023 | -0.012 | +0.064 | 0.13 |
| vrp_sign | 21 | 93 | +0.019 | +0.020 | -0.017 | +0.045 | 0.10 |
| vrp_sign | 63 | 93 | +0.003 | +0.002 | -0.047 | +0.045 | 0.11 |
| vrp_sign | 126 | 93 | +0.008 | +0.004 | -0.041 | +0.047 | 0.09 |

### Forward RET

| predictor | h | n_tickers | ic_median | ic_mean | iqr_lo | iqr_hi | frac>0.10 |
|---|---|---|---|---|---|---|---|
| vrp_raw | 21 | 93 | +0.023 | +0.026 | -0.025 | +0.072 | 0.19 |
| vrp_raw | 63 | 93 | +0.042 | +0.036 | -0.018 | +0.081 | 0.18 |
| vrp_raw | 126 | 93 | +0.039 | +0.052 | +0.006 | +0.108 | 0.30 |
| vrp_ewma | 21 | 93 | +0.045 | +0.035 | -0.016 | +0.084 | 0.25 |
| vrp_ewma | 63 | 93 | +0.068 | +0.069 | -0.004 | +0.163 | 0.44 |
| vrp_ewma | 126 | 93 | +0.090 | +0.096 | -0.002 | +0.181 | 0.54 |
| vrp_pct_own | 21 | 93 | +0.008 | +0.004 | -0.046 | +0.041 | 0.10 |
| vrp_pct_own | 63 | 93 | +0.004 | +0.005 | -0.036 | +0.035 | 0.05 |
| vrp_pct_own | 126 | 93 | +0.006 | +0.011 | -0.018 | +0.040 | 0.06 |
| vrp_ewma_pct_own | 21 | 93 | +0.012 | +0.011 | -0.033 | +0.067 | 0.24 |
| vrp_ewma_pct_own | 63 | 93 | +0.034 | +0.029 | -0.032 | +0.085 | 0.26 |
| vrp_ewma_pct_own | 126 | 93 | +0.051 | +0.047 | -0.022 | +0.105 | 0.37 |
| vrp_zscore_own | 21 | 93 | +0.010 | +0.006 | -0.048 | +0.047 | 0.13 |
| vrp_zscore_own | 63 | 93 | +0.006 | +0.005 | -0.032 | +0.039 | 0.05 |
| vrp_zscore_own | 126 | 93 | +0.002 | +0.008 | -0.029 | +0.047 | 0.05 |
| vrp_slope5 | 21 | 93 | -0.021 | -0.016 | -0.043 | +0.009 | 0.01 |
| vrp_slope5 | 63 | 93 | -0.004 | -0.005 | -0.018 | +0.009 | 0.00 |
| vrp_slope5 | 126 | 93 | -0.007 | -0.006 | -0.019 | +0.003 | 0.01 |
| vrp_ewma_slope5 | 21 | 93 | +0.015 | +0.014 | -0.021 | +0.047 | 0.13 |
| vrp_ewma_slope5 | 63 | 93 | +0.004 | +0.001 | -0.022 | +0.032 | 0.01 |
| vrp_ewma_slope5 | 126 | 93 | +0.006 | +0.005 | -0.023 | +0.033 | 0.03 |
| vrp_sign | 21 | 93 | -0.018 | -0.012 | -0.055 | +0.030 | 0.02 |
| vrp_sign | 63 | 93 | -0.016 | -0.017 | -0.057 | +0.019 | 0.10 |
| vrp_sign | 126 | 93 | +0.010 | -0.002 | -0.047 | +0.034 | 0.08 |

### Forward DD

| predictor | h | n_tickers | ic_median | ic_mean | iqr_lo | iqr_hi | frac>0.10 |
|---|---|---|---|---|---|---|---|
| vrp_raw | 21 | 93 | -0.057 | -0.061 | -0.098 | -0.027 | 0.24 |
| vrp_raw | 63 | 93 | -0.029 | -0.032 | -0.067 | +0.011 | 0.12 |
| vrp_raw | 126 | 93 | -0.007 | -0.016 | -0.056 | +0.025 | 0.15 |
| vrp_ewma | 21 | 93 | -0.042 | -0.045 | -0.085 | +0.001 | 0.22 |
| vrp_ewma | 63 | 93 | -0.023 | -0.027 | -0.075 | +0.021 | 0.27 |
| vrp_ewma | 126 | 93 | +0.003 | +0.003 | -0.053 | +0.075 | 0.37 |
| vrp_pct_own | 21 | 93 | -0.056 | -0.058 | -0.096 | -0.016 | 0.25 |
| vrp_pct_own | 63 | 93 | -0.035 | -0.037 | -0.084 | +0.004 | 0.16 |
| vrp_pct_own | 126 | 93 | -0.038 | -0.035 | -0.079 | +0.011 | 0.16 |
| vrp_ewma_pct_own | 21 | 93 | -0.052 | -0.047 | -0.091 | -0.003 | 0.26 |
| vrp_ewma_pct_own | 63 | 93 | -0.048 | -0.039 | -0.107 | +0.029 | 0.35 |
| vrp_ewma_pct_own | 126 | 93 | -0.023 | -0.032 | -0.115 | +0.043 | 0.40 |
| vrp_zscore_own | 21 | 93 | -0.056 | -0.056 | -0.093 | -0.013 | 0.23 |
| vrp_zscore_own | 63 | 93 | -0.031 | -0.034 | -0.081 | +0.002 | 0.13 |
| vrp_zscore_own | 126 | 93 | -0.037 | -0.033 | -0.074 | +0.017 | 0.17 |
| vrp_slope5 | 21 | 93 | -0.022 | -0.023 | -0.047 | +0.001 | 0.00 |
| vrp_slope5 | 63 | 93 | -0.018 | -0.019 | -0.036 | -0.002 | 0.01 |
| vrp_slope5 | 126 | 93 | -0.016 | -0.015 | -0.029 | -0.000 | 0.00 |
| vrp_ewma_slope5 | 21 | 93 | -0.056 | -0.052 | -0.085 | -0.024 | 0.19 |
| vrp_ewma_slope5 | 63 | 93 | -0.030 | -0.030 | -0.058 | +0.003 | 0.10 |
| vrp_ewma_slope5 | 126 | 93 | -0.029 | -0.028 | -0.062 | +0.008 | 0.08 |
| vrp_sign | 21 | 93 | -0.019 | -0.020 | -0.052 | +0.016 | 0.10 |
| vrp_sign | 63 | 93 | -0.014 | -0.019 | -0.066 | +0.026 | 0.10 |
| vrp_sign | 126 | 93 | -0.021 | -0.017 | -0.055 | +0.035 | 0.13 |

## Top-vs-bottom quintile spread on forward vol (H=21)

Q5 = highest predictor values, Q1 = lowest. Spread > 0 = top
quintile of predictor has higher forward vol than bottom.

| predictor | n | Q1 mean | Q5 mean | spread |
|---|---|---|---|---|
| vrp_raw | 266758 | 0.2383 | 0.3809 | +0.1426 |
| vrp_ewma | 266758 | 0.2088 | 0.3851 | +0.1763 |
| vrp_pct_own | 260992 | 0.2512 | 0.3160 | +0.0648 |
| vrp_ewma_pct_own | 260992 | 0.2480 | 0.3133 | +0.0653 |
| vrp_zscore_own | 260992 | 0.2503 | 0.3164 | +0.0662 |
| vrp_slope5 | 266293 | 0.2865 | 0.3178 | +0.0312 |
| vrp_ewma_slope5 | 266293 | 0.2734 | 0.3454 | +0.0720 |
| vrp_sign | 266758 | 0.2639 | nan | +nan |

## How to read

- A predictor has **actionable signal** if pooled IC is in the
  expected sign AND per-ticker median IC is the same sign AND
  `frac>0.10` ≥ 0.3 (at least 30% of tickers show |IC| > 0.10).
- If `vrp_pct_own` beats `vrp_raw`, the ordinal/relative framing
  works for VRP (validating the bounded principle from §6 holds
  here as expected — VRP is vol-magnitude-units).
- If `vrp_ewma_slope5` shows positive IC for forward vol, the
  prior 6-ticker finding that VRP_ewma slope is predictive
  generalizes to the 93-ticker corpus.