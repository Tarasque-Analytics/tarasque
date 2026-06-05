# VRP Decomposition IC Test

Three VRP variants tested. All EWMA(halflife=21)-smoothed.

- **VRP_classical** = IV − rv_21d_backward (current `vrp_wedge`; +0.40 baseline)
- **VRP_model_fwd** = IV − σ̂_model (uses our ensemble forecast)
- **VRP_oracle_fwd** = IV − σ̂_oracle (uses actual realized fwd vol — LOOKAHEAD, theoretical ceiling)

## Verdict logic

- If `vrp_oracle_fwd` IC ≈ `vrp_classical` IC → classical definition is fine,
  no upside from forward framing.
- If `vrp_oracle_fwd` IC > `vrp_classical` IC → forward-looking VRP has a
  higher ceiling; our model just isn't accurate enough to claim it.
- If `vrp_model_fwd` IC > `vrp_classical` IC → our forecast IS good enough
  to construct a better VRP signal than the classical definition.
- If `vrp_model_fwd` < `vrp_classical` < `vrp_oracle_fwd` → forward framing
  is theoretically better but our forecast isn't there yet (room to grow).

## Pooled IC (all tickers × dates)

### Forward VOL

| predictor | h=21 | h=63 | h=126 |
|---|---|---|---|
| vrp_classical_ewma | +0.396 | +0.426 | +0.427 |
| vrp_model_fwd_ewma | +0.522 | +0.533 | +0.517 |
| vrp_oracle_fwd_ewma | +0.135 | +0.238 | +0.294 |

### Forward ABSRET

| predictor | h=21 | h=63 | h=126 |
|---|---|---|---|
| vrp_classical_ewma | +0.218 | +0.217 | +0.232 |
| vrp_model_fwd_ewma | +0.247 | +0.241 | +0.253 |
| vrp_oracle_fwd_ewma | +0.091 | +0.165 | +0.188 |

### Forward RET

| predictor | h=21 | h=63 | h=126 |
|---|---|---|---|
| vrp_classical_ewma | +0.046 | +0.090 | +0.122 |
| vrp_model_fwd_ewma | +0.092 | +0.123 | +0.139 |
| vrp_oracle_fwd_ewma | +0.116 | +0.095 | +0.133 |

### Forward DD

| predictor | h=21 | h=63 | h=126 |
|---|---|---|---|
| vrp_classical_ewma | -0.116 | -0.114 | -0.098 |
| vrp_model_fwd_ewma | -0.118 | -0.098 | -0.086 |
| vrp_oracle_fwd_ewma | +0.066 | +0.018 | -0.002 |

## Per-ticker median IC

### Forward VOL

| predictor | h | n_tickers | ic_median | ic_mean | frac>0.10 |
|---|---|---|---|---|---|
| vrp_classical_ewma | 21 | 93 | +0.179 | +0.194 | 0.69 |
| vrp_classical_ewma | 63 | 93 | +0.192 | +0.181 | 0.70 |
| vrp_classical_ewma | 126 | 93 | +0.144 | +0.160 | 0.71 |
| vrp_model_fwd_ewma | 21 | 93 | +0.392 | +0.386 | 0.98 |
| vrp_model_fwd_ewma | 63 | 93 | +0.366 | +0.355 | 0.94 |
| vrp_model_fwd_ewma | 126 | 93 | +0.319 | +0.323 | 0.91 |
| vrp_oracle_fwd_ewma | 21 | 93 | -0.153 | -0.134 | 0.75 |
| vrp_oracle_fwd_ewma | 63 | 93 | -0.065 | -0.053 | 0.57 |
| vrp_oracle_fwd_ewma | 126 | 93 | -0.001 | +0.001 | 0.59 |

### Forward ABSRET

| predictor | h | n_tickers | ic_median | ic_mean | frac>0.10 |
|---|---|---|---|---|---|
| vrp_classical_ewma | 21 | 93 | +0.097 | +0.112 | 0.51 |
| vrp_classical_ewma | 63 | 93 | +0.062 | +0.075 | 0.48 |
| vrp_classical_ewma | 126 | 93 | +0.075 | +0.078 | 0.48 |
| vrp_model_fwd_ewma | 21 | 93 | +0.167 | +0.154 | 0.74 |
| vrp_model_fwd_ewma | 63 | 93 | +0.092 | +0.113 | 0.51 |
| vrp_model_fwd_ewma | 126 | 93 | +0.098 | +0.118 | 0.55 |
| vrp_oracle_fwd_ewma | 21 | 93 | -0.041 | -0.033 | 0.25 |
| vrp_oracle_fwd_ewma | 63 | 93 | +0.024 | +0.032 | 0.31 |
| vrp_oracle_fwd_ewma | 126 | 93 | +0.044 | +0.045 | 0.47 |

### Forward RET

| predictor | h | n_tickers | ic_median | ic_mean | frac>0.10 |
|---|---|---|---|---|---|
| vrp_classical_ewma | 21 | 93 | +0.045 | +0.035 | 0.25 |
| vrp_classical_ewma | 63 | 93 | +0.068 | +0.069 | 0.44 |
| vrp_classical_ewma | 126 | 93 | +0.090 | +0.096 | 0.54 |
| vrp_model_fwd_ewma | 21 | 93 | +0.090 | +0.086 | 0.44 |
| vrp_model_fwd_ewma | 63 | 93 | +0.124 | +0.113 | 0.58 |
| vrp_model_fwd_ewma | 126 | 93 | +0.134 | +0.123 | 0.68 |
| vrp_oracle_fwd_ewma | 21 | 93 | +0.113 | +0.108 | 0.58 |
| vrp_oracle_fwd_ewma | 63 | 93 | +0.088 | +0.075 | 0.52 |
| vrp_oracle_fwd_ewma | 126 | 93 | +0.093 | +0.107 | 0.58 |

### Forward DD

| predictor | h | n_tickers | ic_median | ic_mean | frac>0.10 |
|---|---|---|---|---|---|
| vrp_classical_ewma | 21 | 93 | -0.042 | -0.045 | 0.22 |
| vrp_classical_ewma | 63 | 93 | -0.023 | -0.027 | 0.27 |
| vrp_classical_ewma | 126 | 93 | +0.003 | +0.003 | 0.37 |
| vrp_model_fwd_ewma | 21 | 93 | -0.056 | -0.053 | 0.25 |
| vrp_model_fwd_ewma | 63 | 93 | -0.011 | -0.014 | 0.34 |
| vrp_model_fwd_ewma | 126 | 93 | +0.021 | +0.010 | 0.48 |
| vrp_oracle_fwd_ewma | 21 | 93 | +0.164 | +0.156 | 0.78 |
| vrp_oracle_fwd_ewma | 63 | 93 | +0.127 | +0.113 | 0.62 |
| vrp_oracle_fwd_ewma | 126 | 93 | +0.114 | +0.100 | 0.67 |
