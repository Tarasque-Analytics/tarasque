# Automated Daily Data Pipeline — Design Plan

> **Status:** SCAFFOLD / DESIGN ONLY. No stage logic is implemented yet. This document is the
> contract; the `automation/` module tree holds stubs, typed signatures, docstrings, and TODOs
> that point back here. Nothing in this package makes real Alpaca/LLM calls or runs the model yet.
>
> _Last updated: 2026-06-04 — initial scaffold (branch `automation-pipeline-scaffold`)._

---

## 1. Purpose & scope

One automated run, eventually nightly, that leaves the Supabase database with fresh data every
morning. End to end it does four things:

1. **Pull market data → DB** — stock bars into `prices_history`, the options chain into
   `options_chain`.
2. **Run the model** on the active universe of equities.
3. **Upload model outputs → DB** — `volatility_history`, `model_runs`, `shap_snapshot`.
4. **Generate AI overviews** on the model outputs → `ai_overview`.

The whole run must be **incremental and idempotent**: re-fetch / re-run only what is stale and skip
what is not, to **minimize expensive market-data and LLM API calls**. Re-running a day must never
duplicate or corrupt rows.

### What this package is NOT

- It is **not** the model. The model (`model/`, maintained by a different developer) is treated as
  an **external component** with an interface we define (§7). We do not rewrite it.
- It is **not** the backend API (`backend/`). The API reads the DB with the **publishable/anon**
  key (read-only under RLS). This pipeline **writes**, so it uses a separate **service-role** client
  (§6) and lives in its own package.
- It is **not** the model's own data acquisition. The model pulls *its own* market data from WRDS +
  Alpaca into a Parquet cache for feature-building/backtesting (`model/pipeline/data_loader.py`).
  This pipeline's market-data fetch targets the **app's DB tables** the frontend reads. These are
  two distinct data flows that happen to overlap in source (Alpaca) — see §7.5 for the seam.

### Decisions locked for this scaffold (from kickoff Q&A)

| Dimension | Decision |
|---|---|
| Market-data provider | **Alpaca** for stock bars. **Options chain → yfinance** (revised; see [`OPTIONS_IMPORT_PLAN.md`](OPTIONS_IMPORT_PLAN.md) — Alpaca has no OI/volume). |
| Scheduling | **Portable Python orchestrator**, run by **GitHub Actions cron** initially; movable to a managed host scheduler post-deploy. |
| Model interface | **Define the contract against the model's current outputs**, map what maps cleanly, and flag the gaps (§7) for the model dev. |
| AI overviews | **Provider/model-agnostic** abstraction; **Claude** is the first provider tested. Per-model "workflows" allowed, but all share a relatively similar **input** and produce a relatively similar **output** shape. |
| Universe | Driven by the **`securities.active`** flag — the DB is the source of truth. |
| Events / macro | **Deferred** — `event_history` / `macro_calendar` get a stubbed stage but are **not** in the daily DAG yet. |
| Cadence | **After US market close (~6pm ET)**. No hard per-run spend cap wired yet (add later). |

---

## 2. Stage DAG

```
                         ┌─────────────────────────────┐
                         │  Stage 0: ensure_universe    │
                         │  (securities, active=true)   │
                         └──────────────┬──────────────┘
                                        │ universe = [(security_id, ticker), ...]
              ┌─────────────────────────┼─────────────────────────┐
              │ (parallel)              │ (parallel)               │  (deferred)
   ┌──────────▼──────────┐  ┌───────────▼───────────┐  ┌───────────▼───────────┐
   │ Stage 1a: fetch_    │  │ Stage 1b: fetch_      │  │ Stage 1c: events/     │
   │ prices              │  │ options               │  │ macro   [NOT IN DAG]   │
   │ → prices_history    │  │ → options_chain       │  │ → event_history /      │
   │ (incremental)       │  │ (daily snapshot)      │  │   macro_calendar       │
   └──────────┬──────────┘  └───────────┬───────────┘  └────────────────────────┘
              └─────────────┬───────────┘
                            │ prices fresh (+ IV available)
                 ┌──────────▼──────────┐
                 │ Stage 2: run_model  │   skip if model_runs.run_date == today
                 │ (external component)│   for this model_version
                 └──────────┬──────────┘
                            │ model artifacts on disk
                 ┌──────────▼───────────────────────────────┐
                 │ Stage 3: upload_outputs                   │
                 │ → model_runs (1 row) ─┐                   │
                 │ → volatility_history  ├ keyed to run_id   │
                 │ → shap_snapshot      ─┘                   │
                 └──────────┬───────────────────────────────┘
                            │ new model output per security (today)
                 ┌──────────▼──────────┐
                 │ Stage 4: ai_        │   only for securities with a NEW model
                 │ overviews           │   output today; dedupe by natural key
                 │ → ai_overview       │   + content hash
                 └─────────────────────┘
```

### Stage table

| # | Stage | Inputs | Outputs (tables) | Depends on | Parallel with | Expensive? |
|---|---|---|---|---|---|---|
| 0 | `ensure_universe` | `securities` table | `securities` (rare upserts) | — | — | No |
| 1a | `fetch_prices` | Alpaca stock bars; `prices_history` MAX(date)/sec | `prices_history` | 0 | 1b | Moderate (bars API) |
| 1b | `fetch_options` | Alpaca options chain; `options_chain` MAX(snapshot_date)/sec | `options_chain` | 0 | 1a | **Yes — heaviest** |
| 1c | events/macro | (deferred) | `event_history`, `macro_calendar` | 0 | 1a/1b | No (deferred) |
| 2 | `run_model` | model's own data + (current prices/IV); model CLI | model artifacts (disk) | 1a (1b for IV) | — | **Yes — compute** |
| 3 | `upload_outputs` | model artifacts; `options_chain` (for market IV?) | `model_runs`, `volatility_history`, `shap_snapshot` | 2 | — | No |
| 4 | `ai_overviews` | uploaded model outputs | `ai_overview` | 3 | — | **Yes — LLM tokens** |

**Parallelism:** 1a ∥ 1b (independent writes to different tables). 1c would join them when enabled.
Everything from Stage 2 on is sequential (each needs the prior stage's DB writes). Within a stage,
work fans out **per security** (e.g. all tickers' price fetches concurrently, bounded by a
rate-limit-aware pool) — see §5.

**Why this order:** `run_model` needs current prices and (for IV-dependent features) the options
snapshot, so it follows 1a/1b. `upload_outputs` needs the model's artifacts. `ai_overviews` needs
the uploaded model outputs to summarize, so it is strictly last.

---

## 3. Freshness / incrementality (the core concern)

**Principle:** derive freshness from **existing DB signals**, not a separate fragile state store.
Each stage asks "what is the latest thing already in the DB?" and fetches/computes only the delta.
A lightweight run-ledger (`pipeline_runs`, §3.3) is proposed for **observability only**, not as the
authority on what is stale.

### 3.1 Per-data-type freshness rules

| Data type | Table | Freshness signal (from DB) | Re-fetch / reuse rule |
|---|---|---|---|
| Universe metadata | `securities` | universe config change; manual | **Refresh rarely.** Upsert only on universe change (new ticker, sector edit, `active` toggle). Never re-pull metadata daily. |
| Stock bars | `prices_history` | `MAX(date)` per `security_id` | **Append-only.** Fetch bars **strictly after** the latest stored date per security. Never re-pull old history. New listings backfill from `securities.min_history_date`. |
| Options snapshot | `options_chain` | `MAX(snapshot_date)` per `security_id` | **Point-in-time daily.** If today's `snapshot_date` already exists for a security, **skip** it. Otherwise fetch one fresh snapshot for the active universe / needed expiries only. **Heaviest call** — scope aggressively (§4). |
| Model run | `model_runs` | `run_date == today` for this `model_version` | **Once/day/universe.** If a `model_runs` row exists for `(today, model_version)`, **skip** the run (unless `--force`). |
| Model outputs | `volatility_history`, `shap_snapshot` | `volatility_history.date == today` per `security_id`; `securities.last_model_run` | Upload only securities whose model output for today is not yet present. |
| AI overview | `ai_overview` | latest `(security_id, model_ver, prompt_ver)` by `generated_at` + **content hash** | **Only for securities with a NEW model output today.** Dedupe by `(security_id, model_ver, prompt_ver, run_date)` and/or content hash — skip if an equivalent overview already exists (§8). |

### 3.2 How "today" is decided

- Run fires **after US close (~6pm ET)**. The pipeline's "business date" is the **US trading day**
  that just closed (a single `run_date`, US/Eastern), resolved once at orchestrator startup and
  threaded through every stage so all tables agree on the date. Weekends/holidays: if the resolved
  business date is not a trading day, the run is a **no-op** for market data (nothing new to fetch),
  but model/overview re-runs can still be forced.
- `options_chain.snapshot_date`, `model_runs.run_date`, and `volatility_history.date` all use this
  same resolved `run_date`. **Do not** use `datetime.now()` inside stages — pass `ctx.run_date`.

### 3.3 Optional run-ledger: `pipeline_runs` (observability, not authority)

Freshness is derived from the data tables above. A `pipeline_runs` ledger is **recommended but
optional**, purely for observability/alerting and audit (when did each stage last succeed, how many
rows, how long, what failed). It must **never** become the source of truth for incrementality — if
it disagrees with the data tables, the data tables win. Proposed shape (**not applied** — a proposal):

```sql
create table public.pipeline_runs (
  id           bigint generated always as identity primary key,
  run_date     date        not null,
  stage        text        not null,         -- 'fetch_prices', 'fetch_options', ...
  status       text        not null,         -- 'success' | 'partial' | 'failed' | 'skipped'
  started_at   timestamptz not null default now(),
  finished_at  timestamptz,
  rows_written integer,
  n_securities integer,
  n_skipped    integer,
  n_failed     integer,
  error        text,
  meta         jsonb,                         -- per-stage extras (provider, model_version, cost est.)
  unique (run_date, stage)                    -- one ledger row per stage per day; upsert on rerun
);
```

**Decision — state file vs table:** use the **`pipeline_runs` table**, not a state file. The DB is
already the shared substrate, the table is queryable for the future "last run" dashboard/navbar
status, and a file would not survive a stateless CI runner. Until the table exists, the orchestrator
logs structured stage summaries (§9) and freshness still works from the data tables alone.

---

## 4. Idempotency, writes & cost minimization

### 4.1 Upsert semantics per table (keyed on real constraints)

| Table | Conflict key (from `database_SQL_defs.sql`) | Write strategy |
|---|---|---|
| `prices_history` | PK `(security_id, date)` | `upsert(on_conflict="security_id,date")`. Append-only in practice; UPDATE-on-conflict tolerates vendor restatements. |
| `options_chain` | unique `(security_id, snapshot_date, expiry, option_type, strike)` | `upsert(on_conflict="security_id,snapshot_date,expiry,option_type,strike")`. Re-running the same day overwrites that snapshot's rows in place — no dupes. |
| `volatility_history` | PK `(security_id, date)` | `upsert(on_conflict="security_id,date")`. Carries `model_run_id` FK. |
| `shap_snapshot` | PK `(security_id, retrain_date, horizon)` | `upsert(on_conflict="security_id,retrain_date,horizon")`. |
| `model_runs` | PK `id` (identity) — **no natural unique** | ⚠ See §4.2. |
| `ai_overview` | PK `(id, generated_at)` — **no natural unique** | ⚠ See §8.2. Dedupe in-app + (proposed) `content_hash` unique. |
| `securities` | PK `security_id` | `upsert(on_conflict="security_id")`, rarely. |

### 4.2 ⚠ Schema idempotency gaps to resolve

Two write targets lack a natural unique key, so naive re-runs would **duplicate** rows. Flagged for
a decision (a small migration is the clean fix; an in-app guard is the no-migration fallback):

- **`model_runs`** — PK is `id` (identity). Re-running a day would insert a *second* row for the
  same `(run_date, model_version)`. **Recommended:** add `unique (run_date, model_version)` and
  `upsert(on_conflict="run_date,model_version")`. **Fallback (no migration):** `SELECT` for an
  existing `(run_date, model_version)` row before insert; reuse its `id`.
- **`ai_overview`** — PK is `(id, generated_at)`; `generated_at` defaults to `now()`, so every
  insert is unique and re-runs pile up. **Recommended:** add a `content_hash text` column and
  `unique (security_id, model_ver, prompt_ver, content_hash)` (or a date-bucketed unique). See §8.

These are documented, not applied — no migration ships in this scaffold.

### 4.3 Cost minimization (call out the expensive calls)

The three expensive resources, in rough cost order:

1. **Options chain fetch (`fetch_options`) — heaviest market-data call.** A full chain per security
   across many strikes/expiries. Minimize by:
   - **Skip-if-done-today:** if `snapshot_date == run_date` already present for a security, don't call.
   - **Universe scoping:** only `active=true` securities.
   - **Expiry/strike scoping:** only the expiries/strike-band the model + frontend need (e.g. near
     ATM, the DTEs that map to the model's `iv_atm_30d/60d/91d/182d` term points), not the entire
     surface. Exact scope is a **TODO with the model dev** (§7.5).
   - **Batching + bounded concurrency** with rate-limit backoff (§5).
2. **Model run (`run_model`) — compute, not API.** Minimize by skip-if-`model_runs`-has-today, and
   by running the model only over the active universe.
3. **LLM overviews (`ai_overviews`) — token spend.** Minimize by:
   - **Only securities with a NEW model output today** (no model change ⇒ no overview).
   - **Content-hash caching:** hash the prompt inputs; if an overview with that hash already exists
     for `(security_id, model_ver, prompt_ver)`, skip the call entirely.
   - **Dedupe by natural key** so re-runs never re-bill.
   - (Later) a per-run token/$ budget ceiling enforced in the orchestrator (§9) — not wired yet.

General: **incremental fetches** (deltas only), **append-only** prices, and **skip-if-fresh** at
every stage are the primary cost levers. A `--dry-run` mode (§9) prints what *would* be fetched/spent
without making any calls.

---

## 5. Concurrency, batching & rate limits

- **Per-stage fan-out per security**, bounded by a config'd concurrency cap (default small, e.g. 4–8)
  to respect Alpaca rate limits. The orchestrator runs **1a ∥ 1b** as two concurrent stages; inside
  each, securities are processed by a bounded worker pool.
- **Rate-limit / backoff:** exponential backoff with jitter on HTTP 429 / throttling; a token-bucket
  or simple sleep-between-batches to stay under Alpaca's per-minute caps. Centralized in the provider
  client (§ `providers/market_data.py`) so every stage inherits it.
- **Batching:** Alpaca's bars endpoint accepts multi-symbol requests — batch symbols per call where
  the API allows, rather than one call per ticker. Options chains are generally per-underlying.

---

## 6. Database access — the write client

- The app's `backend/database.py` uses the **publishable/anon** key and is **read-only under RLS**.
  This pipeline must **WRITE**, so it needs the **service-role key** (bypasses RLS) — or explicit
  write RLS policies. We use the **service-role key**.
- The service-role key is a **separate secret**, env-injected, **never committed** (documented in
  `.env.example` only; §11).
- The pipeline's DB client is **distinct** from the app's read client: it lives in
  [`automation/db.py`](db.py) (`WriteClient`), is constructed from `SUPABASE_URL` +
  `SUPABASE_SECRET_KEY` (new secret API key; legacy `SUPABASE_SERVICE_ROLE_KEY` accepted), and
  exposes typed `upsert_*` helpers keyed on the constraints in §4.1.
  It must **never** be imported by `backend/`, and the read client must never be imported here.
- **RLS gotcha (inherited):** tables read via the Data API need a permissive `SELECT` policy for
  `anon` or PostgREST returns 0 rows silently. That is a *read* concern for the app; the service-role
  write client **bypasses RLS**, so writes are unaffected — but when a new table starts being read by
  the API (e.g. `pipeline_runs` for a status widget), it will need the read policy too (see
  `backend/CLAUDE.md`).

---

## 7. Model interface (external component)

The model is owned by another developer. We define the **contract**: how we invoke it, what it
consumes, what it produces, and how its outputs map to DB columns. Where the current outputs don't
cover a DB column, it is flagged **GAP** for the model dev (per the locked decision). The
contract is specified by the output→column mapping in §7.4 (to be encoded as a `model_interface`
module when the upload stage is built).

### 7.1 How it's invoked today

```bash
python -m model.pipeline.run --mode backtest  [--tickers AAPL MSFT] [--base-dir <parquet root>]
python -m model.pipeline.run --mode refresh_data
python -m model.pipeline.run --mode live --tickers AAPL     # NOTE: only PRINTS, writes nothing
```

- `backtest` runs a walk-forward sweep and writes CSVs + JSON payloads to
  `model/pipeline/results/` (and `results/payloads/`).
- `refresh_data` pulls the model's own market data (WRDS + Alpaca) into its Parquet cache.
- `live` does single-day inference but currently only **prints to stdout** — it does not persist a
  per-day forecast record. **GAP:** there is no existing "produce today's DB-ready record" mode.

### 7.2 Inputs

- The model maintains its **own** data acquisition (WRDS CRSP/OptionMetrics/Compustat/FRED + Alpaca
  continuation → Parquet at `TARASQUE_BASE_DIR`). It does **not** read the app DB.
- For the daily pipeline, the model needs **current prices and IV** to produce today's forecast. The
  open question is whether it reads its own freshly-refreshed Parquet (its current design) or whether
  we feed it the prices/options this pipeline just wrote (§7.5).

### 7.3 Outputs today (what we can read)

In `model/pipeline/results/`:
- `predictions_{TICKER}_H{h}.csv` — columns `date, y_true, y_pred[, vrp_wedge, put_call_skew_30d]`.
- `all_predictions.csv` — the above concatenated with `ticker, horizon`.
- `backtest_results.csv` — per-`(ticker, horizon)` metrics (`rmse, mz_alpha, mz_beta, mz_r2, qlike, event_capture_rate, n_predictions`).
- `payloads/{TICKER}_Payload.json` — `meta` (forecast_rv per horizon, garch_21d, market_iv_atm,
  vrp_wedge, vrp_percentile_1y, vol_regime, risk_tier, z_score_stabilized, ensemble_weights),
  `vol_forecast_series`, `calibration`.
- `payloads/market_overview.json`, `payloads/metrics_summary.json`.

### 7.4 Output → DB column mapping

Legend: **OK** = directly available; **DERIVE** = computable from current outputs/features;
**GAP** = not produced today, needs model-dev input.

#### `model_runs` (one row per run)
| Column | Source | Status |
|---|---|---|
| `run_date` | orchestrator `ctx.run_date` | OK |
| `model_version` | model config / `claude_context` version tag | DERIVE (needs a canonical version string from the model) |
| `spec_hash` | hash of model config/feature spec | GAP (model should emit a spec hash) |
| `n_tickers` | len(universe) | OK |
| `horizons` | `ModelConfig.horizons` = `[21,63,126]` | OK |
| `notes` | free text | OK |

#### `volatility_history` (per security, per day) — **mixes model outputs + market IV**
| Column group | Source | Status |
|---|---|---|
| `rv`, `ewma_vol` | model feature_df last row (`rv_21d`, `ewma_vol`) | DERIVE |
| `iv_atm`, `iv_atm_30d/60d/91d/182d` | **market IV** — model computes these from its vsurfd surface today; post-WRDS they'd come from `options_chain` | DERIVE now / **GAP post-WRDS** (§7.5 — who produces IV) |
| `vrp_wedge`, `vrp_wedge_ewma_21d` | model feature_df | DERIVE |
| `pfv_21/63/126` (predicted fwd vol) | model `y_pred` per horizon (`forecast_rv` in payload) | DERIVE |
| `pfv_cal_21/63/126` (calibrated) | calibrated forecast | **GAP** (not in current outputs) |
| `pfv_q15_21/63/126` (quantile band) | quantile/interval forecast | **GAP** |
| `fwd_premium_21d/63d/126d`, `fwd_premium_21_to_63d/63_to_126d` | IV term-structure premium | **GAP** (not in current outputs) |
| `next_earnings_date`, `days_to_earnings`, `next_dividend_date`, `days_to_dividend` | model event features (earnings/dividend gravity sources) | DERIVE (model has the dates internally) |
| `model_run_id` | FK to the `model_runs` row written this run | OK (set by `upload_outputs`) |
| `shap_h21/63/126_top10` (jsonb) | per-horizon top-10 SHAP | **GAP** (model emits no SHAP today) |

#### `shap_snapshot` (per security, per retrain, per horizon)
| Column | Source | Status |
|---|---|---|
| `retrain_date`, `snapshot_date` | run/retrain date | DERIVE |
| `horizon` | 21/63/126 | OK |
| `base_value`, `predicted_value` | SHAP explainer base + prediction | **GAP** |
| `feature_data` (jsonb) | full SHAP attribution per feature | **GAP** |

### 7.5 ⚠ Open questions for the model dev (the "who produces what" seam)

1. **Canonical model version + spec hash.** We need a stable `model_version` string and a
   `spec_hash` (feature set + config fingerprint) emitted per run, for `model_runs`.
2. **SHAP.** `volatility_history.shap_h*_top10` and the whole `shap_snapshot` table need SHAP
   attributions per horizon. The model emits none today. Either the model adds SHAP to its output,
   or we compute it (needs the trained estimator + feature matrix — currently not persisted).
3. **`pfv_cal_*`, `pfv_q15_*`, `fwd_premium_*`.** These columns imply calibrated forecasts, quantile
   bands, and IV term-structure premia the current CSV/JSON outputs don't carry. Need the model dev
   to define and emit them (or confirm they're derivable).
4. **Who produces IV** (`iv_atm`, `iv_atm_30d/60d/91d/182d`)? Today the model derives them from its
   WRDS `vsurfd` surface. **WRDS access expires ~1.5 months out.** Post-WRDS, IV must come from the
   Alpaca `options_chain` this pipeline fetches — meaning either the model consumes our
   `options_chain`, or `upload_outputs` computes ATM/term IV from `options_chain` and merges it into
   the `volatility_history` row. **This is the central seam to resolve.**
5. **A DB-ready output mode.** Cleanest long-term fix: the model grows a `--mode emit-db` (or writes
   a typed per-security daily record — JSON/parquet) containing exactly the `volatility_history` +
   `shap_snapshot` fields for `run_date`, so `upload_outputs` is a thin mapper rather than a
   reverse-engineer of backtest CSVs. Proposed, pending model-dev buy-in.

`run_model` (the stage) invokes the model as a **subprocess** (`python -m model.pipeline.run ...`)
and reads artifacts from a known results dir — it does **not** import model internals, keeping the
boundary clean.

---

## 8. AI overviews — provider/model-agnostic

Per the locked decision: the overview layer must be **model- and prompt-agnostic** so we can swap
models freely. Per-model "workflows" are allowed, but all consume a **relatively similar input** and
produce a **relatively similar output**. Claude (Anthropic API) is the first provider tested.

### 8.1 Shared contract

- `OverviewInput` — a standardized, provider-independent bundle assembled from the uploaded model
  outputs for one security (e.g. ticker, sector, forecast_rv per horizon, vrp_wedge + percentile,
  vol_regime/risk_tier, top SHAP drivers, recent calibration). This is the "relatively similar data"
  every workflow receives.
- `OverviewOutput` — `headline: str` + `content: dict` (jsonb) + `model_ver` + `prompt_ver`. The
  "relatively the same form" every workflow returns, mapping straight onto the `ai_overview` columns.
- `LLMProvider` protocol (`providers/llm.py`): `generate(OverviewInput) -> OverviewOutput`. Each
  concrete provider (`ClaudeProvider` first; others later) owns its own message formatting / prompt
  template (its "workflow") but must honor the contract. A small **registry** maps a provider name to
  its class so the active model is config/env-selected.
- `model_ver` / `prompt_ver` on every row capture *which* provider + prompt produced it, so switching
  models writes **new** rows distinguished by key rather than colliding (and lets the app pin a
  version).

### 8.2 Dedupe & caching (cost control)

- Generate overviews **only** for securities whose model output is **new today** (Stage 3 reports
  which `security_id`s got a fresh `volatility_history` row).
- Before calling the LLM, compute a **content hash** of the `OverviewInput` (the prompt inputs). If
  an `ai_overview` already exists for `(security_id, model_ver, prompt_ver)` with that hash, **skip**
  the call (no re-bill). This is the §4.2 schema gap: recommend adding `content_hash` +
  `unique (security_id, model_ver, prompt_ver, content_hash)` for a DB-enforced guarantee; until
  then, the stage queries the latest row and compares in-app.

---

## 9. Scheduling, failure handling & observability

### 9.1 Scheduling / orchestration

- **Primary (planned):** a portable Python orchestrator (`python -m automation`) runnable locally, by
  cron, or by CI — no host assumptions. A **GitHub Actions** scheduled workflow (to be added under
  `.github/workflows/`) triggers it after US close, with secrets injected from repo/Org secrets.
- **Later (post-deploy):** move the same entry point to a **managed cron** on the backend host
  (Render/Fly/Railway). Because the orchestrator is host-agnostic, this is a scheduler swap, not a
  rewrite.
- **Rejected:** Supabase pg_cron / scheduled functions as the *primary* — they can't host the heavy
  model compute (they're DB-side); at most they could trigger an external job.

| Option | Pro | Con | Verdict |
|---|---|---|---|
| GH Actions cron + Python orchestrator | Free, in-repo, works pre-deploy, portable | 6-hr job cap, runner has no GPU (model runtime), secrets in GH | **Chosen (now)** |
| Managed host cron (Render/Fly/Railway) | Co-located with deployed backend, can size compute | Needs the deploy to exist first | **Target (later)** |
| Supabase pg_cron / functions | DB-native, simple for DB-only jobs | Can't run model compute | Rejected as primary |
| Prefect/Dagster | Rich retries/observability/UI | Heavyweight for one daily DAG pre-deploy | Defer until scale warrants |

### 9.2 Failure handling

- **Per-stage retries** with backoff for transient (network/429) errors; deterministic errors fail fast.
- **Partial-failure isolation:** one ticker failing inside a fan-out must **not** sink the run. Each
  security is processed independently; failures are collected, logged, counted, and reported; the
  stage continues. A stage's overall status is `success` / `partial` / `failed` based on the failure
  ratio (threshold config'd).
- **Stage isolation:** a non-critical stage failing (e.g. `ai_overviews`) should not roll back the
  upstream DB writes that already succeeded (prices/options/model outputs). Critical-path stages
  (universe, prices) failing abort the run.
- **Idempotent restart:** because every write is keyed (§4) and freshness is DB-derived (§3),
  re-running after a failure simply resumes — already-done work is skipped, the failed delta retried.

### 9.3 Observability

- Structured per-stage logging (stage, run_date, counts: written/skipped/failed, duration) →
  optionally the `pipeline_runs` ledger (§3.3).
- **Dry-run mode** (`--dry-run`): resolve freshness and print exactly what *would* be fetched, run,
  uploaded, and (roughly) spent — **no** API/LLM/model calls, **no** DB writes. The default posture
  for local verification of this scaffold.
- **Alerting** (later): on `failed`/`partial`, emit a notification (GH Actions job status, or a
  webhook). Hook left as a TODO.
- **Budget guard** (later): optional per-run token/$ ceiling that short-circuits `ai_overviews` (and
  warns on market-data spend). Wired as a config field now, enforcement TODO.

---

## 10. Universe configuration

- Source of truth: **`securities.active`**. Each run resolves its universe as the `security_id, ticker`
  rows where `active = true` (`automation/universe.py`).
- Adding/removing a name is a **DB edit** (toggle `active`, set `excluded_reason`), which keeps the
  pipeline, the model universe, and the app's served set consistent without code changes.
- `securities` metadata (sector, `min_history_date`, etc.) is upserted only on change by
  `ensure_universe` (Stage 0). The model's own `config.py` ticker list is a *separate* concern (the
  model dev's), but the two should be reconciled — flagged as a coordination item.

---

## 11. Secrets & environment

Documented in [`.env.example`](../.env.example) (root) — **never commit real values**; `.gitignore`
already excludes `.env` / `.env.*` while keeping `.env.example`.

| Var | Used by | Notes |
|---|---|---|
| `SUPABASE_URL` | write client | hosted project URL (can reuse `VITE_SUPABASE_URL`'s value). |
| `SUPABASE_SECRET_KEY` | write client | Supabase **secret** API key — bypasses RLS (legacy `SUPABASE_SERVICE_ROLE_KEY` accepted). **Never** ship to the frontend or commit. |
| `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` | market-data provider | already present; reused for prices + options. Needs an options-enabled plan. |
| `ANTHROPIC_API_KEY` | Claude LLM provider | for `ai_overviews` (first provider). |
| `AUTOMATION_ENV` | orchestrator | `dev`/`stg`/`prod` target selection, mirroring the backend's `APP_ENV` story. |

---

## 12. Module tree

This is a **design doc**: §§2–11 describe the full intended pipeline, most of which is **not yet
built**. To keep the package lean, only implemented code lives in the tree — the rest of the DAG
(prices, model run, output upload, AI overviews, the orchestrator/scheduler) is planned here and will
be added when built. Implemented today:

```
automation/
  PLAN.md, OPTIONS_IMPORT_PLAN.md, README.md
  requirements.txt         ← deps (supabase, yfinance, requests, pandas, python-dotenv)
  config.py                ← config + env loading (SupabaseConfig, OptionsImportConfig, load_config)
  db.py                    ← WriteClient (secret-key): keyed upserts + freshness reads
  black_scholes.py         ← in-house delta (yfinance has no greeks)
  expiry_selection.py      ← which expiries to fetch (§4-equivalent for options)
  options_import.py        ← reusable per-security options import core
  providers/options_provider.py ← yfinance options provider
  tools/fetch_options.py   ← options-chain import CLI → options_chain
  tools/sync_sp500.py      ← S&P 500 / securities sync → securities
  sql/remap_security_ids_cik.sql ← CIK remap migration (cascades to child tables)
  data/sp500.csv, company_tickers.json ← reference metadata
  tests/                   ← pure-function tests
```

**Planned (designed above, not yet in the tree):** an `orchestrator` + `RunContext` running the stage
DAG (§2); per-stage modules for `fetch_prices` → `prices_history`, `run_model` (subprocess to the
model), `upload_outputs` → `volatility_history`/`model_runs`/`shap_snapshot`, and `ai_overviews` →
`ai_overview`; the `model_interface` contract (§7) and provider-agnostic LLM layer (§8); freshness/
logging helpers; the optional `pipeline_runs` ledger (§3.3); and the scheduled runner (§9.1).

---

## 13. Open items checklist (carry-forward)

- [ ] Model dev: canonical `model_version` + `spec_hash` emission (§7.5.1).
- [ ] Model dev: SHAP outputs for `shap_snapshot` + `volatility_history.shap_*` (§7.5.2).
- [ ] Model dev: define/emit `pfv_cal_*`, `pfv_q15_*`, `fwd_premium_*` (§7.5.3).
- [ ] **Decide the IV seam** post-WRDS: model consumes our `options_chain`, or `upload_outputs`
      computes IV from it (§7.5.4).
- [ ] Model dev: agree a `--mode emit-db` / typed daily record (§7.5.5).
- [ ] Migration decision: `model_runs` unique `(run_date, model_version)` (§4.2).
- [ ] Migration decision: `ai_overview` `content_hash` + unique (§4.2 / §8.2).
- [ ] Confirm Alpaca plan covers options market data; map model term points → chain expiries (§4.3).
- [ ] Decide `pipeline_runs` table adoption (§3.3) and add its read RLS policy if the app surfaces it.
- [ ] Reconcile model `config.py` universe vs `securities.active` (§10).
- [ ] Later: per-run budget enforcement + alerting (§9.3).
```
