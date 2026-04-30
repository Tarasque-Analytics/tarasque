# Claude Handoff — Tarasque/Volarbear v9 Planning

_Created 2026-04-28 by claude-sonnet-4-6 (audit session) on the sneakernet SSD._
_Intended for the next Claude instance picking this up on Leo's main workstation (5950X + 1070 + 32GB) or on the campus workstation (Xeon W-2275 + A5000 + 64GB)._

---

## Read in this order

1. **[model/claude_context.md](model/claude_context.md)** — standing project context. The file's own instructions say read it first every session. Do that.
2. **[model/iteration_log.md](model/iteration_log.md)** — full v1→v8 history with metrics tables.
3. **[AUDIT_PLAN_2026-04-28.md](AUDIT_PLAN_2026-04-28.md)** (root) — pre-deployment audit findings, Tier 0/1/2/3 work plan.
4. **[model/v9_planning_2026-04-28.md](model/v9_planning_2026-04-28.md)** — cross-version comparison with actual v8 corpus aggregates, v9 spec steps including decomposition test (Step A).
5. THIS FILE — quick-reference, hardware notes, and what to do *first* on the next session.

---

## TL;DR state as of 2026-04-28

- **v8 corpus is complete and on disk.** 91 tickers (not 93 as documented — see "Universe gap" below). Production-ready forecasting outputs, MZ-calibrated, with quantile model (τ=0.15) producing the P15 floor signal.
- **v8 R² is materially lower than v6 across all horizons** — H21 0.374→0.262, H63 0.319→0.204, H126 0.458→0.286. Drop of 0.10–0.17.
- **v8 H126 β calibration improved materially** — 1.192→0.947, calibrated tickers 40%→59%. Other horizons roughly flat.
- **Coverage_q15 is functional, not catastrophic.** Mean 0.74-0.77 vs target 0.85; modestly under-target (floor too high), but the signal works. A per-ticker scalar offset closes the gap.
- **Leo's hypothesis (validated by data shape):** the R² loss came from step_days going 25→63. Short feature half-life means the model runs on stale-fit weights for ~50 days at the end of each refit window. The drop being biggest at H126 (where stale-weight effects compound) supports this.
- **The clean experiment to confirm has not been run.** That's what the next session does.
- **Universe gap:** 6 tickers missing from v8 corpus. 4 documented (LIN, META, OXY, VZ). 2 undocumented (**MSFT, MU**). Investigate.
- **Three data-artifact rows:** DOW H126, EQIX H21, GILD H21 — RMSE > 2, β ≈ 0. Total fit failure. Diagnose.
- **RTX is also broken** (R²=0.030, β=0.213, only 626 predictions). Corporate-action exclusion candidate — 2020 UTX-Raytheon merger. Likely add to LIN/META/OXY/VZ exclusion list.
- **WRDS access expires ~mid-June 2026.** OI differential pull is mandatory before then. ~40 days remaining.
- **Sector forensics done 2026-04-28.** Energy is best-forecast at H21 (R²=0.382), Staples worst (0.191). XOM H21 R² monotonically decayed v2→v8 (0.555→0.347) — likely ElasticNet weight-spreading + step_days=63 + sector_wedge being autocorrelation-in-disguise for sector leaders. PG and BA had biggest v6→v8 R² regressions (-0.185 / -0.183).
- **Two cheap dynamic-adaptation hooks already half-built in the codebase** — wider l1_ratio grid in [models.py:159](model/pipeline/models.py#L159) and inverse-RMSE ensemble weights advertised in docstrings but hardcoded at 0.33/0.33/0.33 in [backtest.py:605](model/pipeline/backtest.py#L605). Both are v9 inclusions — see Step "Dynamic adaptation" in v9_planning.
- **New engineered feature for v9:** Leo proposed `fear_intensity_25d = iv_skew_25d × log(oi_put/oi_call)` — multiplicative interaction of price asymmetry × quantity asymmetry. Theoretically captures market-maker gamma exposure. Specced in v9_planning + AUDIT_PLAN under Tier 1-E.

---

## Do this first: Step A — decomposition test

**This is the highest-leverage thing on the project right now.** ~6 hours overnight on the home rig. Resolves whether v9 = "v8 with step_days=25" or something more complicated.

Three runs on a 6-ticker canary set (AAPL, JPM, XOM, BA, AMZN, NVDA):

1. **v8 model class + Optuna params + step_days=25** → does R² recover toward v6 levels?
2. **v8 model class + default XGB params + step_days=25** → isolates Optuna's contribution
3. (already on disk in `model/pipeline/results/` from v8 production) Optuna + step_days=63

Decision tree:
- Run #1 R² ≈ v6 (within 0.02): **step_days was the dominant cause.** v9 = v8 with step_days=25, keep Optuna. Best of both worlds (v6 R² + v8 calibration + v8 quantile).
- Run #1 still depressed, run #2 ≈ v6: **Optuna also costs R².** Real fork — keep Optuna for H126 β win or revert for R². Most likely answer is keep, because biased H126 forecasts are a deployment problem R² can't fix.
- Neither recovers: **third explanation** (likely ElasticNet redistributing weight differently than LassoCV did). Deeper investigation.

Compute on home rig: ~6 hours overnight. On campus rig with parallel_tickers=8: probably ~3.5-4 hours. Not worth the trip just for this.

---

## Don't-do list

These are temptations to resist until Step A returns. They were temptations the previous session resisted — keep doing that.

- **Don't propose v9 yet.** v9 spec is conditional on Step A's outcome. Anything proposed now is hypothesis.
- **Don't add new features** beyond OI (which is the only one with strong theoretical motivation right now and a hard data-availability deadline).
- **Don't run another Optuna sweep.** The first one was already overfit-risky (validation = optimization on JPM/AAPL). A second sweep compounds the meta-overfitting.
- **Don't do partial corpus runs to "spot check"** without the full controlled experiment. Eight versions in 25 days, all observed against the same backtest, is the meta-overfitting pattern.
- **Don't ship v6 to the SWE team** even though R² is higher. v6 doesn't have the quantile floor signal, and its H126 forecasts are 19% biased high. The SWE-deployable surface is the analytics layer (signal_strength, vrp_return_conditional, MZ overlay, payload schemas) which is version-agnostic. v8 is the right basis to build that against.
- **Don't update Optuna hyperparameters** until Step A confirms whether they're adding or subtracting value.

---

## Hardware: home rig vs campus workstation

| Component | Home (Leo) | Campus | Comparison |
|-----------|-----------|--------|------------|
| CPU | Ryzen 9 5950X (16C/32T, Zen 3, ~28k CB R23 MT) | Xeon W-2275 (14C/28T, Cascade Lake, ~17k CB R23 MT) | **5950X ~1.6× faster on MT** |
| RAM | 32GB DDR4 | 64GB DDR4 ECC | **Campus 2× capacity, ECC reliability** |
| GPU | RTX 1070 (8GB GDDR5, Pascal, 6.5 TFLOPS, no tensor cores) | RTX A5000 (24GB GDDR6, Ampere, 27.8 TFLOPS, 256 tensor cores) | **A5000 ~3-4× FP32, but ~1.5-2× on small-dataset XGBoost** |

### Per-ticker wall-time math (fixed parallel_tickers=4)

Original timing breakdown from [claude_context.md#L607](model/claude_context.md#L607): XGB 56% / RF 37% / Lasso 7%.

- XGB phase on A5000: ~28 units (vs 56 on 1070; ~2× speedup, conservative for small data)
- RF/Lasso phase on W-2275: ~70 units (vs 44 on 5950X; ~1.6× slower)
- **Total: ~98 vs 100 → essentially flat**

The CPU regression on campus eats most of the GPU gain. **Per-ticker compute is roughly equal between the two rigs at fixed parallel_tickers.**

### The real unlock: RAM enables parallel_tickers=8

Home has historically OOM'd at parallel_tickers=4 with n_jobs=-1 (claude_context.md#L329 documents an OOM kill). Campus's 64GB lets you safely run parallel_tickers=8 (verify with a 1-step canary, peak RAM should stay under ~50GB).

- **Home: parallel_tickers=4** (capped by 32GB)
- **Campus: parallel_tickers=8** (64GB headroom)
- Net throughput: **~1.8-2× faster wall time on campus**

### Practical recommendations

| Workload | Where to run | Why |
|----------|--------------|-----|
| Step A decomposition (6 tickers, ~6 hrs home) | Home | Fits in one overnight; campus trip not justified |
| Full v9 retrain at step_days=25 (~31 hrs home) | **Campus** | Cuts to ~14-16 hrs with parallel_tickers=8. ECC reliability is a bonus on a 30hr job. |
| OI WRDS pull (data download, no compute) | Either | Bandwidth-bound, not compute-bound |
| Ablation studies (canary sets) | Home | Overnight is plenty |
| Corpus aggregate / signal_strength scripts | Either | Sub-minute |

### Caveat

The original 56/37/7 breakdown was from Caleb's machine, which may not match your home rig's actual ratios. Before committing 30+ hours of campus time, do a `time` comparison on the canary set first — if your home rig's actual ratio is more CPU-heavy (e.g., RF 50% with all 32 threads going), the campus rig's CPU regression matters more and the A5000 helps less.

---

## Memory locations

Project memory at `C:\Users\ldipiet1\.claude\projects\d--volarbmodel\memory\` exists on the **non-portable Windows host** (not on this SSD). When the SSD plugs into the home rig at d:\, that machine has its own separate memory directory. Memories don't follow the SSD.

Three files there worth reading if accessible:
- `user_leo.md` — Leo's profile and constraints (econ/stats senior, WRDS deadline, sneakernet workflow)
- `project_framing_reset.md` — risk analytics platform, not VRP overlay thesis
- `feedback_iteration_discipline.md` — don't propose v9 until Tier 0 audits close
- `feedback_directness.md` — Leo wants direct critique, never appeasement

If on a different machine where these don't exist, the same content is roughly captured in this handoff doc + the v9 planning doc + claude_context.md L24 ("wants to know when he is wrong or out of touch").

---

## Files on the SSD (added 2026-04-28)

| File | Purpose |
|------|---------|
| [AUDIT_PLAN_2026-04-28.md](AUDIT_PLAN_2026-04-28.md) (root) | Pre-deployment audit findings, Tier 0/1/2/3 work plan |
| [model/v9_planning_2026-04-28.md](model/v9_planning_2026-04-28.md) | Cross-version comparison + v9 spec steps |
| [CLAUDE_HANDOFF_2026-04-28.md](CLAUDE_HANDOFF_2026-04-28.md) (root) | THIS file |
| `_v8_analysis_temp.py` (root) | Throwaway stdlib script that computed the v8 corpus aggregates. Move to `model/pipeline/analysis/corpus_aggregates.py` and parameterize, or delete. Leo's call. |

---

## Open questions / loose ends for the next session

These are things the audit session didn't resolve and that future Claude should engage with:

1. **MSFT and MU undocumented absence from v8 corpus.** Check the v8 run log (`logs/full_corpus_93t_tau15.log`) and `D:/Tarasque_DB/ohlcv/` for these tickers. Either fix and rerun, or document the exclusion.
2. **Three data-artifact rows.** DOW H126, EQIX H21, GILD H21 — RMSE > 2, β ≈ 0. Probably target imputation or log-clip issue at a regime discontinuity. Sub-hour to diagnose each.
3. **XOM H21 R² monotonic decay across versions** (0.555 → 0.347). Read `lasso_tracking_XOM.csv`, compare to what a v2-shaped LassoCV would have selected. Research lead, not blocking.
4. **TS-inversion second-pass fix in mz_overlay.py.** Already specced in claude_context.md L554-568. Implement and re-run on v8 outputs.
5. **GOOGL diagnosis reconciliation** — v6 said class-split contamination, v7 said ElasticNet+sector coupling fixed it. Pick one.
6. **LIN/VZ/OXY post-mortem paragraphs.** One paragraph each in iteration_log.md replacing the one-line dismissals.
7. **Coverage_q15 per-ticker scalar offset fit.** Sub-minute script that brings each ticker's coverage to 0.85 exactly via a per-ticker `δ` shift on q15. Output a small CSV consumed by signal_strength.py and the dashboard layer.

---

## What the next session should NOT do

- Edit `model/claude_context.md` without explicit instruction. The file's own protocol asks for end-of-session updates, but Leo's standing instruction is "we are only here to plan and analyze past work" until the SWE-handoff phase. Update only with explicit ask.
- Propose architectural changes (new model class, new horizon, etc.). Stay in the v9 lane.
- Run the OI pull *while* Step A is running on the same machine — WRDS connections + heavy compute can OOM the home rig. Sequence them.
- Skip reading claude_context.md just because this handoff exists. The protocol is the protocol.
