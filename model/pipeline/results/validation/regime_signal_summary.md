# Regime Classifier — Economic Content Test

_Generated 2026-05-04, n=624 (ticker × monthly snapshot) observations._

## Hypothesized risk ordering (low → high):
Q3 (genuinely calm) → Q4 (mega-cap buffer) → Q1 (stealth event-risk) → Q2 (idiosync + systematic)

## Forward-outcome means by quadrant
### H=21d
| Quadrant | n | Ret mean | Ret %neg | DD mean | DD p10 | Vol mean |
|---|---|---|---|---|---|---|
| Q1-stealth-event-risk | 20 | -2.123% | 60% | -7.383% | -14.406% | 0.291 |
| Q2-idiosync-plus-systematic | 23 | -11.860% | 65% | -16.244% | -14.342% | 0.598 |
| Q3-genuinely-calm | 352 | 0.392% | 45% | -4.508% | -10.908% | 0.233 |
| Q4-mega-cap-buffer | 229 | 3.338% | 35% | -5.216% | -15.089% | 0.334 |

### H=63d
| Quadrant | n | Ret mean | Ret %neg | DD mean | DD p10 | Vol mean |
|---|---|---|---|---|---|---|
| Q1-stealth-event-risk | 20 | -0.826% | 50% | -10.646% | -23.385% | 0.268 |
| Q2-idiosync-plus-systematic | 23 | -6.045% | 48% | -19.418% | -18.198% | 0.446 |
| Q3-genuinely-calm | 352 | 0.609% | 42% | -8.976% | -19.734% | 0.258 |
| Q4-mega-cap-buffer | 229 | 6.095% | 29% | -11.288% | -25.355% | 0.384 |

### H=126d
| Quadrant | n | Ret mean | Ret %neg | DD mean | DD p10 | Vol mean |
|---|---|---|---|---|---|---|
| Q1-stealth-event-risk | 20 | 2.622% | 35% | -12.082% | -23.385% | 0.256 |
| Q2-idiosync-plus-systematic | 23 | 3.229% | 17% | -21.003% | -21.827% | 0.381 |
| Q3-genuinely-calm | 352 | 2.649% | 39% | -12.775% | -27.154% | 0.263 |
| Q4-mega-cap-buffer | 229 | 10.140% | 25% | -17.223% | -33.390% | 0.416 |

## IC of regime label vs forward outcomes
- **ic_quadrant_rank**: Spearman rank correlation of quadrant ordering (0-3 by risk) vs realized
- **ic_beta_mz_continuous**: rank correlation of raw β_mz vs realized
- Expected sign: ret NEGATIVE (high regime risk → lower fwd ret), dd NEGATIVE (worse DD), vol POSITIVE (more vol)

| Horizon | Metric | n | IC quadrant | IC β_mz | IC β_mkt |
|---|---|---|---|---|---|
| H=21 | ret | 624 | +0.0666 | -0.0219 | +0.1203 |
| H=21 | dd | 624 | -0.0883 | -0.0045 | -0.0836 |
| H=21 | vol | 624 | +0.3536 | -0.0555 | +0.4709 |
| H=63 | ret | 624 | +0.1620 | -0.0212 | +0.1820 |
| H=63 | dd | 624 | -0.0452 | +0.0172 | -0.0785 |
| H=63 | vol | 624 | +0.3391 | -0.1083 | +0.5057 |
| H=126 | ret | 624 | +0.2105 | -0.0413 | +0.2457 |
| H=126 | dd | 624 | -0.0195 | +0.0082 | -0.0694 |
| H=126 | vol | 624 | +0.3360 | -0.1177 | +0.5382 |

## Interpretation
If the regime classifier carries economic content, you'd expect:
- IC quadrant vs forward DD: **negative** (Q2 → worse DD than Q3)
- IC quadrant vs forward vol: **positive** (Q2 → higher vol than Q3)
- IC magnitude: 0.05–0.15 = real signal, 0.15+ = strong, comparable to factor models

## Caveats
- Trails are computed on full prediction history; not strictly OOS.
- Quadrant boundaries (β=1.0) are arbitrary; many obs near boundary swap quadrants on small noise.
- Sample size per quadrant uneven (Q3 typically dominates).
- This tests REGIME LABEL signal, NOT vol-forecast signal. Different, complementary tests.