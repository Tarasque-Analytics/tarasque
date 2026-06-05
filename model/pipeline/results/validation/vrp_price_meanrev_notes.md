# VRP-Conditional Price Mean-Reversion — Findings

**Run date:** 2026-06-04
**Script:** `model/pipeline/analysis/vrp_price_meanrev.py`
**Daily-spread CSV:** `model/pipeline/results/validation/vrp_price_meanrev_daily_spread.csv`

## Hypothesis

A wide forward VRP can be the market pricing in "a big move is coming." If the move
has *already happened* (recent drop or rally), the wide VRP may be anticipating the
*aftermath* — i.e., a partial reversal. Does conditioning forward returns on
**recent-direction × own-VRP-percentile** reveal a directional mean-reversion edge
beyond the level-only signal?

## Test design

- Per (ticker, date) over the 93-ticker universe, 2015-01 → 2026-05.
- `recent_dir` = tercile of trailing 21-BD log-return (DOWN / FLAT / UP).
- `vrp_bkt` = tercile of own trailing-252-BD percentile of `fwd_premium_ewma_21d`
  (LOW / MID / HIGH).
- Forward outcome = 21-BD forward log-return on the stock (close-to-close).
- Significance via within-date long-short HAC test (Newey-West, lags=42).

## Result 1 — the 3×3 grid (forward 21-BD return)

| recent_dir \ VRP | LOW | MID | HIGH |
|---|---|---|---|
| DOWN | +0.54% | +0.45% | **+2.04%** |
| FLAT | +0.27% | +0.40% | +0.84% |
| UP | +0.27% | +0.01% | +0.34% |

Hit-rates align: **DOWN+HIGH = 62.2%** (highest of nine cells), UP+HIGH = 56.9%,
LOW-VRP cells all ~54%.

## Result 2 — VRP amplifies the DOWN−UP reversal spread ~6×

| VRP bucket | DOWN−UP reversal spread |
|---|---|
| LOW | +0.27 pp |
| MID | +0.45 pp |
| **HIGH** | **+1.70 pp** |

The reversal pattern is *not* a generic post-drop bounce — it's specifically
amplified in rich-options names.

## Result 3 — tradeable LS in HIGH-VRP names is significant

Within-date long-short (long DOWN+HIGH, short UP+HIGH, daily spread series, HAC):

| | Mean / 21BD | HAC t | p | Annualized | IR |
|---|---|---|---|---|---|
| **HIGH-VRP** | **+1.38%** | **+2.00** | **0.045** | **+16.6%/yr** | +0.44 |
| LOW-VRP (control) | +0.44% | +1.22 | 0.22 | — | — |

The reversal trade is significant in HIGH-VRP names and **not** in LOW-VRP. The
interaction is real.

## Result 4 — forward path shape: wider range at HIGH-VRP

| VRP | Max DD | Max rally | Range |
|---|---|---|---|
| LOW | −4.77% | +4.77% | 9.54% |
| MID | −5.25% | +5.21% | 10.46% |
| **HIGH** | −5.78% | **+6.50%** | **12.28%** |

HIGH-VRP forward paths are wider *and* positively-skewed at the extremes (max rally
larger than max DD only at HIGH). Consistent with the +2.6pp Q5−Q1 forward-vol
prediction we already had — vol manifests partly as wider price excursions, and the
asymmetric extremes are what give the reversal trade its edge.

## Result 5 — time stability (the caveat)

| Period | HIGH-VRP DOWN−UP spread | HAC t | p |
|---|---|---|---|
| 2015–2020 | **+1.59% / 21BD** | +2.05 | **0.040** ✓ |
| 2021–2026 | +1.11% / 21BD | +0.91 | 0.36 ✗ |

Concentrated in 2015–2020. Both halves directionally positive (second half still
+1.1%/21BD in point estimate, not zero), but statistical significance evaporates in
the post-COVID period. Same temporal-softening pattern observed on the
cross-sectional VRP rank return premium and the β_mz cooling-vs-HY incremental
alpha. **Honest framing: real in the first half, weaker but still positive in the
second; do not market as guaranteed.**

## Mechanism

The wide VRP is the market pricing "a big move." When the move has already
happened to the downside (DOWN tercile), the rich-options premium reflects
anticipated forward vol — which empirically resolves partly via mean reversion
(bounce) rather than continuation. The mirror (UP + wide VRP) shows little
extension, consistent with the same vol-anticipation effect resolving via
sideways/down rather than continuation.

This is the **directional cousin** of the VRP→IV mean-reversion finding from the
prior turn (`vrp_meanrev_test.py`): both reflect rich-options names tending toward
"the move resolves" rather than "the move extends."

## How this fits with the existing VRP findings

| Signal | Predicts forward equity return? |
|---|---|
| Own-percentile VRP, unconditional (`vrp_own_pct_test`) | ✗ within-date LS n.s. |
| Cross-sectional VRP rank (`vrp_rank_test`) | ✓ +8.8%/yr LS, p=0.035 (structural premium compensation) |
| **Own-percentile VRP × recent direction** (this test) | **✓ +16.6%/yr LS in HIGH-VRP names, p=0.045 (conditional mean-reversion)** |
| Own-percentile VRP → forward vol (`vrp_own_pct_test`) | ✓ +2.6pp Q5−Q1, p ~ 1e-8 (always) |

The conditioning on recent direction unlocks a predictive signal that the level
alone doesn't carry.

## Product implication

Equity-page contextual badge candidate:

> "This stock is at the **P82 of its own VRP history** AND has dropped **−4% over
> the last 21 BD** → historical base rate **+2% expected over the next 21 BD
> (hit rate ~62%)**."

Honest framing notes:
- Display the full-sample base rate (~+1.4% / ~56% hit) as the headline; note the
  2015-2020 base rate (+1.6% / higher hit) only if context warrants.
- Frame as *contextual indicator*, not *signal-to-trade*.
- Flag the temporal-softening caveat for any user-facing language.

## Files

- Script: `model/pipeline/analysis/vrp_price_meanrev.py`
- Daily-spread CSV: `model/pipeline/results/validation/vrp_price_meanrev_daily_spread.csv`
- This notes file: `model/pipeline/results/validation/vrp_price_meanrev_notes.md`
