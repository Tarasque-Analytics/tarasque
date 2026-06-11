# automation — daily data pipeline

Automated, **incremental + idempotent** daily run that leaves the Supabase DB fresh every morning:
pull prices + options → run the model → upload model outputs → generate AI overviews.

> **Status: SCAFFOLD.** Stubs, interfaces, and a design doc only — no stage logic yet. It makes
> **no** real Alpaca/LLM/model calls. Start with **[`PLAN.md`](PLAN.md)** — it's the source of truth;
> every `TODO(PLAN §N)` in the code points back to a section there.

## What it does (once implemented)

| Stage | Writes | Incremental rule |
|---|---|---|
| `ensure_universe` | `securities` (rare) | active set from `securities.active` |
| `fetch_prices` ∥ | `prices_history` | bars **after** the latest stored date per security |
| `fetch_options` | `options_chain` | one daily snapshot; skip if today's already present |
| `run_model` | (model artifacts) | skip if `model_runs` has today's row |
| `upload_outputs` | `volatility_history`, `model_runs`, `shap_snapshot` | keyed upserts, one `model_run_id` |
| `ai_overviews` | `ai_overview` | only securities with new model output; content-hash cache |

Re-running a day never duplicates or corrupts — every write is an upsert on the table's real
constraint, and freshness is derived from the DB itself (see PLAN §3–§4).

## How it'll be run

### Now — locally, dry-run (no calls, no writes)

> The commands below are the **intended CLI**. While scaffolded they raise `NotImplementedError`
> (the orchestrator is stubbed) — they document the interface the wiring will fill in. `--dry-run`
> is designed to be the first thing that actually runs once the orchestrator + freshness reads land.

```bash
pip install -r automation/requirements.txt        # from repo root
cp .env.example .env                               # fill in values (see below); .env is gitignored

# Resolve freshness and print exactly what WOULD be fetched / run / uploaded / spent. No side effects.
python -m automation --dry-run
```

Useful flags (PLAN §9.3):

```bash
python -m automation --force                  # ignore skip/freshness checks; re-run everything
python -m automation --only fetch_prices      # run a subset (dependency order preserved)
python -m automation --env stg                # target selection (dev|stg|prod), mirrors backend APP_ENV
```

Run it as a module from the **repo root** (like `backend`/`model`) so `from automation import ...`
resolves.

### Standalone options import (implemented now)

The options-chain import is the first **working** piece — it runs independently of the (still
stubbed) orchestrator. It pulls a scoped daily chain from **yfinance** and upserts `options_chain`.
Design: [`OPTIONS_IMPORT_PLAN.md`](OPTIONS_IMPORT_PLAN.md).

```bash
# Fetch + print normalized rows; NO DB writes, no Supabase creds needed (yfinance calls only):
python -m automation.tools.fetch_options --tickers AAPL MSFT --dry-run

# Write to Supabase (set SUPABASE_URL + SUPABASE_SECRET_KEY in .env — secret key bypasses RLS):
python -m automation.tools.fetch_options --tickers AAPL MSFT

# Re-fetch even if today's snapshot already exists:
python -m automation.tools.fetch_options --tickers AAPL --force
```

- Expiries: nearest to **30/60/90/180 DTE** + the next **1–2 monthlies**; strikes within ±30% of spot.
- `delta` is computed in-house (Black-Scholes); `volume`/`open_interest` come from yfinance.
- The pipeline stage `stages/fetch_options.py` reuses the **same** core (`automation/options_import.py`),
  so the scheduled run behaves identically.
- Pure-logic tests: `python -m pytest automation/tests`.

### Later — scheduled

- **Initial:** GitHub Actions cron, after US close (~6pm ET) — see
  [`.github/workflows/daily-pipeline.yml`](../.github/workflows/daily-pipeline.yml) (stubbed,
  disabled until secrets are set).
- **Post-deploy:** move the same `python -m automation` entry point to a managed cron on the backend
  host (Render/Fly/Railway). The orchestrator is host-agnostic, so this is a scheduler swap, not a
  rewrite. (PLAN §9.1.)

## Required env vars (PLAN §11)

Documented in the root [`.env.example`](../.env.example) — **never commit real values**.

| Var | Purpose |
|---|---|
| `SUPABASE_URL` | hosted project URL (may reuse `VITE_SUPABASE_URL`) |
| `SUPABASE_SECRET_KEY` | Supabase **secret** API key for writes (bypasses RLS) — SECRET (legacy `SUPABASE_SERVICE_ROLE_KEY` still accepted) |
| `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` | prices + options (needs an options-enabled plan) |
| `ANTHROPIC_API_KEY` | Claude provider for AI overviews |
| `AUTOMATION_ENV` | `dev`/`stg`/`prod` target (default `dev`) |

## Layout

```
automation/
  PLAN.md            ← design doc (read first)
  config.py context.py orchestrator.py __main__.py
  db.py              ← service-role write client (idempotent upserts)
  freshness.py       ← DB-derived incrementality
  universe.py        ← active universe from securities
  model_interface.py ← contract for the external model (+ GAP markers)
  logging_utils.py
  stages/            ← ensure_universe, fetch_prices, fetch_options, events(deferred),
                       run_model, upload_outputs, ai_overviews
  providers/         ← market_data (Alpaca), llm (Claude + registry)
  sql/               ← pipeline_runs.sql (proposed ledger, not applied)
```

## Boundaries

- **Not the model.** `model/` is an external component (another dev). This pipeline invokes it via
  subprocess and maps its outputs; it never imports model internals. Known interface gaps
  (SHAP, `pfv_cal_*`/`pfv_q15_*`/`fwd_premium_*`, the post-WRDS IV seam) are listed in PLAN §7.5/§13.
- **Not the backend.** `backend/` reads the DB with the publishable/anon key (read-only). This is the
  only component that **writes**, via a separate service-role client (PLAN §6).
