# automation — agent/dev context

The `automation/` package is the **only component that writes to the Supabase DB** (via a secret-key
client, separate from the app's read-only client). It currently ships two working tools; the broader
nightly pipeline is **designed here but not yet implemented**.

> Read this first. It consolidates the former `PLAN.md` + `OPTIONS_IMPORT_PLAN.md`. §§1–4 are what's
> built and the must-know conventions; §§5–8 are the design detail (incl. the planned pipeline).

---

## 1. Status — built vs planned

**Built and in use (verified against the hosted DB):**
- **Options-chain import** (yfinance → `options_chain`): `tools/fetch_options.py` over a reusable core
  (`options_import.py`, `providers/options_provider.py`, `black_scholes.py`, `expiry_selection.py`).
- **Securities / universe sync** (SEC CIK + S&P 500 + GICS → `securities`): `tools/sync_sp500.py`,
  `sql/remap_security_ids_cik.sql`.
- **Write client + config**: `db.py` (keyed upserts, freshness reads), `config.py`.

**Designed but NOT implemented (§6):** the orchestrated nightly DAG — fetch prices, run the model,
upload model outputs, generate AI overviews — plus the orchestrator/scheduler. Don't assume these
exist; they're the forward plan.

## 2. How to run

From the **repo root** (modules, like `backend`/`model`):

```bash
pip install -r automation/requirements.txt          # supabase, yfinance, requests, pandas, python-dotenv
cp .env.example .env                                 # fill in values (.env is gitignored)

# Options chain (yfinance). --dry-run fetches + prints, NO DB writes (no creds needed).
python -m automation.tools.fetch_options --tickers AAPL MSFT --dry-run
python -m automation.tools.fetch_options --tickers AAPL MSFT          # write
python -m automation.tools.fetch_options --tickers AAPL --force       # re-fetch today's snapshot

# Securities / S&P 500. --refresh is standalone (rebuilds data/sp500.csv from Wikipedia, no DB).
python -m automation.tools.sync_sp500 --refresh                       # rebuild the CSV (network only)
python -m automation.tools.sync_sp500                                 # preview missing constituents
python -m automation.tools.sync_sp500 --apply                        # add missing
python -m automation.tools.sync_sp500 --update-existing --apply       # refresh GICS/name on existing

python -m pytest automation/tests                                     # pure-function tests
```

## 3. Boundaries & secrets

- **Writes only.** `backend/database.py` reads with the publishable/anon key (read-only under RLS).
  This package's `db.WriteClient` uses the **secret key** and must never be imported by `backend/`,
  nor the read client here.
- **Required env** (root `.env`, gitignored — see `.env.example`):
  - `SUPABASE_URL` (may reuse `VITE_SUPABASE_URL`)
  - `SUPABASE_SECRET_KEY` — Supabase **secret** API key (`sb_secret_…`); bypasses RLS; SECRET. Legacy
    `SUPABASE_SERVICE_ROLE_KEY` still accepted as a fallback.
  - `AUTOMATION_ENV` — `dev|stg|prod` (default `dev`).
  - Options import uses **yfinance** (no API key).
- **Not the model.** The forecasting model (`model/`) is a separate component with its own data path
  (WRDS/Parquet). This package does not import it.
- **RLS gotcha (inherited from backend):** a table read through the Data API needs a permissive `anon`
  `SELECT` policy, or PostgREST returns 0 rows silently. The secret-key write client bypasses RLS, so
  writes are unaffected — but a new table the app starts *reading* needs the policy.

## 4. Key decisions & conventions (must-knows)

- **`security_id` is the SEC CIK** (set by `sql/remap_security_ids_cik.sql`, applied to the hosted DB;
  all child-table FKs are `ON UPDATE CASCADE`). It is the PK/FK joined on by every table, so it must
  be unique per security. **GICS codes can't be the id** (a classification shared by many firms) — GICS
  lives in the `gics_*` columns.
- **Dual-class share classes collapse to one row.** CIK is a *filer* id, so GOOG/GOOGL, FOX/FOXA,
  NWS/NWSA share a CIK; `sync_sp500` keeps one (first-listed) and drops the other (still in
  `data/sp500.csv`). A per-class representation (`alt_tickers` column / `security_tickers` alias table /
  a per-security key like FIGI) is **deferred — low priority** (only 3 S&P 500 names). Consequence:
  only the primary class's prices/options are stored.
- **`snapshot_date` is the trading SESSION the data belongs to, not the wall-clock date.** This job may
  run at midnight, so `fetch_options` resolves it **data-derived** from a liquid proxy's (SPY) last
  daily bar (`provider.latest_session_date()`) — self-correcting for time-of-day, weekends, and
  holidays (a 3 AM run stamps yesterday's close as *yesterday*). Clock-based fallback
  (`_computed_session_date`, before-open / weekend rollback, not holiday-aware) only if that lookup
  fails. Override with `--snapshot-date`.
- **Idempotency — keyed upserts** (`db.CONFLICT_KEYS`): `options_chain` on
  `(security_id, snapshot_date, expiry, option_type, strike)`; `securities` on `security_id` (PK).
  Re-running a day overwrites in place — no duplicates.
- **Freshness / skip-if-done:** `fetch_options` skips a security whose snapshot for `snapshot_date`
  already exists (`db.options_snapshot_exists`); `--force` overrides. `sync_sp500 --update-existing`
  writes only rows whose metadata actually changed.
- **Options scoping (cost control):** expiries nearest **30/60/90/180 DTE + the next 1–2 monthlies**
  (3rd-Friday detection), strikes within **±30% of spot**. yfinance gives **no greeks**, so `delta` is
  computed in-house (`black_scholes.bs_delta`, `math.erf`, dividend `q≈0`, flat `r=0.045` — fine for a
  display greek; not for pricing).
- **`--dry-run`** still calls yfinance (free) but does no DB writes/reads, so it needs no creds.
- **yfinance is unofficial → robustness:** `provider._retry` backs off on both exceptions **and** empty
  responses (yfinance intermittently returns `()`/empty frames). A failed spot lookup raises
  `SpotUnavailableError` (a `RuntimeError`, caught per-ticker) and logs to `<repo-root>/log/` (gitignored
  via `*.log`) rather than importing an unbounded, delta-less chain.
- **Serial / blocking (scale caveat):** the yfinance calls are synchronous but run inside the `async`
  import, so tickers are processed **strictly serially**. Fine for a handful; wrap with
  `asyncio.to_thread` before running the full ~500-name universe.
- **Provider-agnostic by design:** swapping yfinance → Polygon/Tradier is a config change
  (`OptionsImportConfig.provider` + a new `OptionsProvider` in the registry).

---

## 5. Options import — design detail (the built path)

**Decisions:** yfinance (free, current-day, has bid/ask/last/volume/OI/IV; we only need current-day
data for the **frontend** — the model keeps its own historical path, so this is **decoupled from the
model's IV needs**). Daily-forward only (no historical backfill). Greeks computed in-house.

**Flow** (`options_import.import_options_for_security`, reused by the CLI today and the future pipeline
stage): skip-if-snapshot-exists → `list_expiries` → `select_expiries` (§4 scoping) → `fetch_spot` →
`fetch_chain` (normalize to `options_chain` rows, filter strike band, fill `delta`) → `upsert_options_chain`.
Per-ticker failures are caught and returned as `ImportResult(error=…)` so one bad ticker can't sink a
multi-ticker run.

**`options_chain` column mapping (yfinance → app columns):** `expiry/strike/option_type('C'/'P')` from
the chain; `bid/ask` from the quote, `mid=(bid+ask)/2` (both >0 else NULL); `last=lastPrice`;
`volume`/`open_interest` from yfinance (NaN→NULL; OI is prior-session); `iv=impliedVolatility`;
`delta` computed. Defensive parsing coerces NaN/blank → NULL.

**Not in scope here:** the "opportunities"/edge view (`app/components/ticker/options.tsx` `mkt_px`/
`model_px`/`edge_pct`) is model pricing layered on the raw chain — a separate downstream step.

---

## 6. The planned daily pipeline (forward design — NOT built)

A single nightly run (after US close) leaving the DB fresh, **incremental + idempotent**: re-fetch/
re-run only what's stale, minimizing expensive market-data and LLM calls.

### 6.1 Stage DAG
```
ensure_universe (securities.active)
  → fetch_prices  → prices_history    ┐ parallel
  → fetch_options → options_chain     ┘   (events/macro deferred)
  → run_model     → model artifacts (subprocess to model/; skip if model_runs has today)
  → upload_outputs→ volatility_history + model_runs + shap_snapshot
  → ai_overviews  → ai_overview        (only securities with a new model output; content-hash dedupe)
```

### 6.2 Freshness / incrementality (derive from DB signals, not a separate store)
| Data | Signal | Rule |
|---|---|---|
| `securities` | universe config change | refresh rarely; upsert on change |
| `prices_history` | `MAX(date)`/security | append-only; fetch bars *after* latest stored date |
| `options_chain` | `MAX(snapshot_date)`/security | one snapshot/day; skip if today's present *(BUILT)* |
| model run | `model_runs.run_date == today` | once/day; skip if present |
| `ai_overview` | latest `(security_id, model_ver, prompt_ver)` + content hash | only on new model output |

### 6.3 Idempotency / write semantics (keyed on real constraints)
- `prices_history` PK `(security_id,date)`; `options_chain` unique 5-tuple *(BUILT)*;
  `volatility_history` PK `(security_id,date)`; `shap_snapshot` PK `(security_id,retrain_date,horizon)`;
  `securities` PK `security_id` *(BUILT)*.
- ⚠ **`model_runs`** (PK `id`) and **`ai_overview`** (PK `(id, generated_at)`) have **no natural unique
  key** → naive re-runs duplicate. Fix when building upload/overviews: add `unique(run_date,model_version)`
  to `model_runs`; add `content_hash` + `unique(security_id,model_ver,prompt_ver,content_hash)` to
  `ai_overview` (or dedupe in-app). Not yet applied.

### 6.4 Model interface contract (external component — coordinate with the model dev)
The model is invoked as a **subprocess** (`python -m model.pipeline.run …`), not imported. Its current
outputs (`results/predictions_*.csv`, `payloads/*.json`) don't cover every `volatility_history` column.
GAPs to resolve before building `upload_outputs`:
- **SHAP**: model emits none → `shap_snapshot` + `volatility_history.shap_h*_top10` are unfillable.
- **`pfv_cal_*`, `pfv_q15_*`, `fwd_premium_*`**: calibrated/quantile forecasts + IV term premia not
  emitted today.
- **`model_version` / `spec_hash`**: need a canonical version string + feature/config fingerprint.
- **The IV seam**: model derives `iv_atm_*` from WRDS `vsurfd` (WRDS access lapses ~mid-2026). Post-WRDS,
  IV must come from the Alpaca/`options_chain` data — decide whether the model consumes `options_chain`
  or `upload_outputs` computes IV from it.
- Cleanest long-term: a model-side `--mode emit-db` producing a typed per-day record. `pfv_21/63/126`
  map from the model's `y_pred` per horizon; `rv`/`ewma_vol`/`vrp_wedge`/event dates are derivable.

### 6.5 Cost minimization
Expensive calls, in order: **options fetch** (scope by universe/expiries/strikes; skip-if-done),
**model run** (compute; skip-if-today), **LLM overviews** (only new model output; content-hash cache;
later a per-run token budget). Append-only prices + skip-if-fresh everywhere.

### 6.6 Scheduling, failure, universe
- **Scheduling (planned):** a portable Python orchestrator runnable by cron/CI, GitHub Actions to start
  (after US close), movable to a managed host cron post-deploy. Supabase pg_cron rejected (can't host
  model compute).
- **Failure handling:** per-stage retries/backoff; **partial-failure isolation** (one ticker can't sink
  a run — already the pattern in `options_import`); non-critical stage failures (overviews) don't roll
  back upstream writes; a `--dry-run` mode. Optional `pipeline_runs` ledger for observability (DB-derived
  freshness stays the source of truth).
- **Universe:** source of truth is **`securities.active`**; add/remove = a DB edit. The model's own
  `config.py` ticker list is the model dev's separate concern — reconcile as a coordination item.

---

## 7. Module map

**Implemented**
```
automation/
  CLAUDE.md            ← this file        README.md ← quickstart (points here)
  requirements.txt     ← supabase, yfinance, requests, pandas, python-dotenv
  config.py            ← env/config (SupabaseConfig, OptionsImportConfig, load_config)
  db.py                ← WriteClient (secret-key): keyed upserts + freshness reads
  black_scholes.py     ← in-house delta (math.erf; q≈0, r=0.045)
  expiry_selection.py  ← which expiries to fetch (30/60/90/180 DTE + front monthlies)
  options_import.py    ← reusable per-security options import core
  providers/options_provider.py ← yfinance OptionsProvider (+ OptionsScope, SpotUnavailableError)
  tools/fetch_options.py        ← options-chain import CLI → options_chain
  tools/sync_sp500.py           ← S&P 500 / securities sync → securities
  sql/remap_security_ids_cik.sql ← CIK remap migration (applied; kept for history)
  data/sp500.csv, company_tickers.json ← reference metadata
  tests/               ← pure-function tests (black_scholes, expiry_selection)
```

**Planned (designed in §6, not in the tree):** `orchestrator` + `RunContext`; stage modules
`fetch_prices`, `run_model`, `upload_outputs`, `ai_overviews`; a `model_interface` contract (§6.4); a
provider-agnostic LLM layer; freshness/logging helpers; the optional `pipeline_runs` ledger; the
scheduled runner.

## 8. Open items / coordination

- Model dev: SHAP output; `pfv_cal_*`/`pfv_q15_*`/`fwd_premium_*`; canonical `model_version` + `spec_hash`;
  the post-WRDS IV seam; ideally a `--mode emit-db` (§6.4).
- Migrations before building upload/overviews: `model_runs` unique key; `ai_overview` content_hash (§6.3).
- Dual-class: revisit only if a per-class chain is needed (§4).
- Scale: wrap the yfinance import in `asyncio.to_thread` before running the full universe (§4).
- `sync_sp500`: unmatched-CIK tickers are silently skipped in the sync (only surfaced during `--refresh`).
