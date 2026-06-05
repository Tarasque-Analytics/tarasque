# What Are We Actually Measuring? — Four Tests

Tests run on the corpus per-ticker `vrp_wedge_ewma` signal. All ICs are Spearman rank correlation against forward realized vol.

## Test A

| horizon | n | ic_total_pooled | ic_systematic_pooled | ic_idiosyncratic_pooled | ic_idiosyncratic_per_ticker_median | n_idio_tickers |
|---|---|---|---|---|---|---|
| +21.000 | +266758.000 | +0.402 | +0.187 | +0.163 | -0.055 | +93.000 |
| +63.000 | +266758.000 | +0.428 | +0.195 | +0.177 | -0.112 | +93.000 |

## Test B

| signal | n | pearson | spearman |
|---|---|---|---|
| dollar_index | 2936 | +0.514 | +0.591 |
| breakeven_5y | 2936 | +0.549 | +0.557 |
| yield_slope | 2942 | -0.553 | -0.486 |
| treasury_3mo | 2942 | +0.553 | +0.410 |
| inflation_forward_5y5y | 2936 | +0.364 | +0.378 |
| treasury_10y | 2942 | +0.408 | +0.263 |
| hy_spread | 2936 | -0.223 | -0.197 |
| spy_vol_21d | 2943 | +0.062 | +0.174 |

## Test C

| regime | horizon | n | ic_wedge_vs_fwd_vol |
|---|---|---|---|
| calm | 21 | 88096 | +0.424 |
| calm | 63 | 88096 | +0.399 |
| normal | 21 | 90465 | +0.435 |
| normal | 63 | 90465 | +0.473 |
| stress | 21 | 88197 | +0.361 |
| stress | 63 | 88197 | +0.415 |

## Test D

| horizon | n | ic_raw_wedge | ic_residual_wedge | var_share_explained_by_calendar_week |
|---|---|---|---|---|
| +21.000 | +266758.000 | +0.402 | +0.138 | +0.297 |
| +63.000 | +266758.000 | +0.428 | +0.139 | +0.297 |
