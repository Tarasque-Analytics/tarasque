# Trail Dynamics IC Test

Does *where the trail has been* add predictive content over the
static quadrant_rank? Reports Spearman IC vs forward outcomes.

Convention:
- `ret`: forward log return.  Lower is bad → expect NEGATIVE IC for risk-up features.
- `dd`: forward drawdown (negative log diff).  Lower is bad → expect NEGATIVE IC.
- `vol`: forward realized vol.  Higher = more risk → expect POSITIVE IC.

## IC table

| horizon | metric | n | ic_quadrant | ic_velocity | ic_drift_mz_6mo | ic_drift_mkt_6mo | ic_drift_mz_3mo | ic_direction_angle | ic_stack_quadrant_plus_drift_mz_6mo |
|---|---|---|---|---|---|---|---|---|---|
| 21 | ret | 2024 | +0.057 | -0.011 | -0.043 | +0.022 | -0.089 | +0.045 | +0.013 |
| 21 | dd | 2024 | -0.070 | -0.072 | -0.030 | +0.010 | -0.115 | +0.058 | -0.055 |
| 21 | vol | 2024 | +0.264 | +0.119 | -0.073 | +0.066 | -0.009 | +0.014 | +0.114 |
| 63 | ret | 2024 | +0.136 | +0.029 | +0.028 | +0.014 | -0.037 | +0.044 | +0.109 |
| 63 | dd | 2024 | -0.029 | -0.039 | +0.033 | +0.036 | -0.055 | +0.040 | +0.016 |
| 63 | vol | 2024 | +0.276 | +0.113 | -0.121 | +0.002 | -0.040 | +0.029 | +0.085 |
| 126 | ret | 2024 | +0.154 | +0.001 | -0.019 | +0.084 | -0.012 | +0.024 | +0.079 |
| 126 | dd | 2024 | -0.026 | -0.043 | +0.035 | +0.057 | -0.014 | +0.019 | +0.015 |
| 126 | vol | 2024 | +0.291 | +0.107 | -0.133 | -0.016 | -0.077 | +0.042 | +0.092 |

## Interpretation guide

**Trail dynamics are additive** if `ic_drift_mz_6mo` (or `_3mo`) has
a meaningful Spearman IC with the SAME SIGN as the matching `ic_quadrant`
row — e.g., for `vol`, both positive. That means drift is independently
tracking the same risk gradient the quadrant captures.

**Trail dynamics REPLACE the quadrant** if the stack IC is
meaningfully larger than `ic_quadrant` alone. That would suggest the
drift axis carries more signal than the static rank.

**Trail dynamics are noise** if `ic_drift_*` hovers near zero and the
stack IC is no better than `ic_quadrant` alone.