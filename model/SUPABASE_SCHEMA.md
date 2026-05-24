# Tarasque — Supabase Schema & Web App Handoff

_Schema design for the Tarasque equity intelligence platform. Covers the database tables, the per-ticker handoff files produced by the model backtest, ETL flow, and the query patterns that compose into the `/equity/:symbol` page._

_Audience: Leo (model side) and the web developer building the frontend + backend ETL. Reading this doc gives you the full mental model before any SQL migrations are written._

---

## 1. Architecture Overview

```
┌──────────────────────┐     ┌────────────────────────┐     ┌────────────────────┐
│  Tarasque Backtest   │     │       ETL Layer        │     │  Supabase Postgres │
│  (Python pipeline)   │ ──> │  Reads handoff bundle  │ ──> │     9 tables       │
│  Runs on the 5950X   │     │  Splits + upserts rows │     │     1 RPC          │
└──────────────────────┘     └────────────────────────┘     └────────┬───────────┘
                                                                      │
                              ┌───────────────────────────────────────┘
                              ▼
                    ┌──────────────────────┐
                    │   React Router App   │
                    │  /equity/:symbol     │
                    │  /sector/:sector     │
                    │  /macro              │
                    │  /dashboard          │
                    └──────────────────────┘
```

The model runs the backtest. The backtest produces a **handoff bundle** of CSVs (one per ticker + a few shared files). The ETL layer reads those CSVs and upserts them into the appropriate Supabase tables. The frontend queries Supabase via React Router loaders.

**Key design principle**: the handoff bundle is the contract between the model side and the web dev side. As long as those CSVs match the schema documented below, the model can iterate freely without breaking the frontend.

---

## 2. The Per-Ticker Predictions File (the heart of the system)

The model writes one fat append-only file per ticker. Every column the equity page needs is in this file, indexed by date.

### File: `predictions_<TICKER>.csv`

One row per (ticker, date). One file per ticker. Append-only — daily inference adds one new row per file.

**Column groups (28 columns total):**

#### Identity (1)
| Column | Type | Description |
|---|---|---|
| `date` | DATE | Trading day. Unique within file. |

#### Price block (6)
| Column | Type | Description |
|---|---|---|
| `open` | NUMERIC(12,4) | Day open |
| `high` | NUMERIC(12,4) | Day high |
| `low` | NUMERIC(12,4) | Day low |
| `close` | NUMERIC(12,4) | Day close (raw) |
| `adj_close` | NUMERIC(12,4) | Split + dividend adjusted close |
| `volume` | BIGINT | Daily share volume |

Source: CRSP daily via your existing data pipeline. Adjusted close uses your CRSP `ret`-based reconstruction (the v6 split-fix methodology).

#### Realized vol (2)
| Column | Type | Description |
|---|---|---|
| `rv` | DOUBLE PRECISION | Garman-Klass realized vol, annualized decimal (e.g., 0.245 = 24.5%) |
| `ewma_vol` | DOUBLE PRECISION | Exponentially-weighted moving vol from log returns, span=21 |

#### IV term structure (4)
| Column | Type | Description |
|---|---|---|
| `iv_atm_30d` | DOUBLE PRECISION | ATM implied vol, 30 DTE, delta=50 |
| `iv_atm_60d` | DOUBLE PRECISION | ATM implied vol, 60 DTE |
| `iv_atm_91d` | DOUBLE PRECISION | ATM implied vol, 91 DTE |
| `iv_atm_182d` | DOUBLE PRECISION | ATM implied vol, 182 DTE |

Source: OptionMetrics `vsurfd` table. The model already pulls all four DTEs into the parquet cache; the new export step writes them out as columns.

#### VRP (2)
| Column | Type | Description |
|---|---|---|
| `vrp_wedge` | DOUBLE PRECISION | `iv_atm_30d − rv` (the H=21 wedge — canonical) |
| `vrp_wedge_ewma_21d` | DOUBLE PRECISION | EWMA of `vrp_wedge` with span=21 |

#### Forecasts (9)
Three flavors × three horizons. Frontend defaults to `pfv_cal_*` (production); raw and floor are for diagnostics.

| Column | Type | Description |
|---|---|---|
| `pfv_21` | DOUBLE PRECISION | Raw model forecast, H=21d |
| `pfv_63` | DOUBLE PRECISION | Raw model forecast, H=63d |
| `pfv_126` | DOUBLE PRECISION | Raw model forecast, H=126d |
| `pfv_q15_21` | DOUBLE PRECISION | P15 quantile floor, H=21d |
| `pfv_q15_63` | DOUBLE PRECISION | P15 quantile floor, H=63d |
| `pfv_q15_126` | DOUBLE PRECISION | P15 quantile floor, H=126d |
| `pfv_cal_21` | DOUBLE PRECISION | MZ-overlay calibrated, H=21d |
| `pfv_cal_63` | DOUBLE PRECISION | MZ-overlay calibrated, H=63d |
| `pfv_cal_126` | DOUBLE PRECISION | MZ-overlay calibrated, H=126d |

#### SHAP (3 JSON columns)
| Column | Type | Description |
|---|---|---|
| `shap_h21_top10` | TEXT (JSON) | Top 10 features for H=21 forecast |
| `shap_h63_top10` | TEXT (JSON) | Top 10 features for H=63 forecast |
| `shap_h126_top10` | TEXT (JSON) | Top 10 features for H=126 forecast |

Each JSON has shape:
```json
{
  "base_value": -1.42,
  "predicted_value": -1.31,
  "features": [
    {"name": "iv_atm_z_score", "display": "IV Z-Score", "value": 1.42, "shap": 0.024, "abs_shap": 0.024},
    {"name": "vrp_wedge", "display": "VRP Wedge", "value": 0.058, "shap": -0.012, "abs_shap": 0.012}
  ]
}
```

Re-computed daily on the existing model. Re-trained model ⇒ new TreeExplainer ⇒ new SHAP for all subsequent rows.

#### Forward events (4)
| Column | Type | Description |
|---|---|---|
| `next_earnings_date` | DATE | Next scheduled earnings announcement |
| `days_to_earnings` | INT | Trading days until next_earnings_date |
| `next_dividend_date` | DATE | Next ex-dividend date |
| `days_to_dividend` | INT | Trading days until next_dividend_date |

#### Reference (1)
| Column | Type | Description |
|---|---|---|
| `model_run_id` | INT | FK to `model_runs.id`. Lets you trace which retrain produced this row. |

---

## 3. The Supporting Handoff Files

Three sparse files that don't fit the per-ticker time-series shape.

### `securities_metadata.csv` (one row per ticker)

```
symbol, gics_sector, gics_industry, sector_etf, active, excluded_reason, min_history_date
```

Static-ish. Updated only when ticker universe changes. ETL upserts into `securities` table.

### `events_history.csv` (sparse rows; all earnings, dividends, FOMC for initial scope)

```
event_date, event_type, severity, scope, scope_value, title, description, source
```

`event_type` ∈ `{'earnings', 'dividend', 'fomc'}` for the initial launch. Manual curation of macro crisis events deferred. Schema supports the broader scope when added later.

### `macro_calendar.csv` (forward macro dates)

```
date, event_type, event_date, days_to_event
```

`event_type` ∈ `{'fomc', 'cpi', 'nfp'}`. One row per (date, event_type) — universe-wide, reused by every ticker.

### `model_run_manifest.json` (registry)

```json
{
  "run_id": 12,
  "run_date": "2026-05-04",
  "model_version": "v10",
  "spec_hash": "0356b9d",
  "n_tickers": 91,
  "horizons": [21, 63, 126],
  "notes": "v10+ full corpus, post-VIF cleanup",
  "generated_at": "2026-05-07T03:14:09Z"
}
```

ETL inserts one row into `model_runs`. The `run_id` becomes the `model_run_id` referenced by every prediction row in the per-ticker CSVs.

---

## 4. Database Schema (Supabase / Postgres)

Nine tables and one RPC. Listed in dependency order — create them top to bottom.

### 4.1 `securities` (existing, extend it)

```sql
ALTER TABLE securities
  ADD COLUMN gics_sector       TEXT,
  ADD COLUMN gics_industry     TEXT,
  ADD COLUMN sector_etf        TEXT,
  ADD COLUMN active            BOOLEAN DEFAULT TRUE,
  ADD COLUMN excluded_reason   TEXT,
  ADD COLUMN min_history_date  DATE,
  ADD COLUMN last_model_run    TIMESTAMPTZ;
```

The frontend universe list filters `WHERE active = TRUE`. Excluded tickers (LIN, OXY, VZ, META) keep their row for audit but don't appear in the picker.

### 4.2 `model_runs`

```sql
CREATE TABLE model_runs (
    id              BIGSERIAL PRIMARY KEY,
    run_date        DATE NOT NULL,
    model_version   TEXT NOT NULL,
    spec_hash       TEXT,
    n_tickers       INT,
    horizons        INT[],
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
```

Created first since other tables FK into it.

### 4.3 `volatility_history`

```sql
CREATE TABLE volatility_history (
    security_id          INT NOT NULL REFERENCES securities,
    date                 DATE NOT NULL,
    rv                   DOUBLE PRECISION,
    ewma_vol             DOUBLE PRECISION,
    iv_atm_30d           DOUBLE PRECISION,
    iv_atm_60d           DOUBLE PRECISION,
    iv_atm_91d           DOUBLE PRECISION,
    iv_atm_182d          DOUBLE PRECISION,
    vrp_wedge            DOUBLE PRECISION,
    vrp_wedge_ewma_21d   DOUBLE PRECISION,
    pfv_21               DOUBLE PRECISION,
    pfv_63               DOUBLE PRECISION,
    pfv_126              DOUBLE PRECISION,
    pfv_q15_21           DOUBLE PRECISION,
    pfv_q15_63           DOUBLE PRECISION,
    pfv_q15_126          DOUBLE PRECISION,
    pfv_cal_21           DOUBLE PRECISION,
    pfv_cal_63           DOUBLE PRECISION,
    pfv_cal_126          DOUBLE PRECISION,
    next_earnings_date   DATE,
    days_to_earnings     INT,
    next_dividend_date   DATE,
    days_to_dividend     INT,
    model_run_id         BIGINT REFERENCES model_runs,
    PRIMARY KEY (security_id, date)
);

CREATE INDEX idx_vol_security_date ON volatility_history (security_id, date DESC);
```

**Why wide format**: every chart on `/equity/:symbol` queries all of these columns together for a date range. Wide = one SELECT, no joins. Long format would force 8+ round trips or one ugly pivoted query.

**Why DOUBLE PRECISION not NUMERIC**: vol forecasts are inherently approximate. Storage is smaller, math is faster. NUMERIC is reserved for prices and money where precision is contractual.

**Why `(security_id, date)` PK**: natural identity for a daily snapshot. No surrogate key needed because we never reference a single row from elsewhere — always queried in date ranges.

### 4.4 `prices_history`

```sql
CREATE TABLE prices_history (
    security_id   INT NOT NULL REFERENCES securities,
    date          DATE NOT NULL,
    open          NUMERIC(12,4),
    high          NUMERIC(12,4),
    low           NUMERIC(12,4),
    close         NUMERIC(12,4),
    adj_close     NUMERIC(12,4),
    volume        BIGINT,
    PRIMARY KEY (security_id, date)
);

CREATE INDEX idx_prices_security_date ON prices_history (security_id, date DESC);
```

**Why backend cache, not live API**:
1. API keys never exposed to browser
2. Single ETL = predictable rate-limit usage
3. Same source as model training data = consistent UX (CRSP-aligned, split-adjusted)
4. Page load latency: ~50ms Postgres vs. ~500ms+ external API

### 4.5 `options_chain`

```sql
CREATE TABLE options_chain (
    id              BIGSERIAL PRIMARY KEY,
    security_id     INT NOT NULL REFERENCES securities,
    snapshot_date   DATE NOT NULL,
    expiry          DATE NOT NULL,
    strike          NUMERIC(10,2) NOT NULL,
    option_type     CHAR(1) NOT NULL CHECK (option_type IN ('C','P')),
    bid             NUMERIC(8,2),
    ask             NUMERIC(8,2),
    mid             NUMERIC(8,2),
    last            NUMERIC(8,2),
    volume          INT,
    open_interest   INT,
    iv              DOUBLE PRECISION,
    delta           DOUBLE PRECISION,
    UNIQUE (security_id, snapshot_date, expiry, strike, option_type)
);

CREATE INDEX idx_opt_security_snapshot ON options_chain (security_id, snapshot_date);
CREATE INDEX idx_opt_security_expiry   ON options_chain (security_id, snapshot_date, expiry);
```

**Source**: live daily ETL (yfinance/Polygon/Tradier — web dev's choice). NOT from the backtest. ~300 contracts × 91 tickers × daily ≈ 27k rows/day.

**Why surrogate PK**: composite (security_id, snapshot_date, expiry, strike, option_type) is too many columns to use as a foreign key elsewhere. Keep ID, enforce uniqueness via constraint.

### 4.6 `ai_overview_equity`

```sql
CREATE TABLE ai_overview_equity (
    id              BIGSERIAL PRIMARY KEY,
    security_id     INT NOT NULL REFERENCES securities,
    date            DATE NOT NULL,
    model_version   TEXT NOT NULL,
    prompt_version  TEXT NOT NULL,
    headline        TEXT NOT NULL,
    risk_tier       TEXT,
    content         JSONB NOT NULL,
    input_hash      TEXT,
    input_tokens    INT,
    output_tokens   INT,
    generated_at    TIMESTAMPTZ DEFAULT NOW(),
    flagged         BOOLEAN DEFAULT FALSE,
    flagged_reason  TEXT,
    UNIQUE (security_id, date, model_version, prompt_version)
);

CREATE INDEX idx_ai_eq_recent
  ON ai_overview_equity (security_id, date DESC)
  WHERE flagged = FALSE;
```

**Source**: separate daily LLM pipeline. NOT from the backtest. Generated by Claude/GPT using current model output as context.

**Hybrid storage pattern**: top-level columns for anything the database needs to filter or sort by (`headline`, `risk_tier`). JSONB for content the frontend renders as-is (`body`, `key_drivers`, `confidence`, `sentiment`).

**Why versioning columns are part of the unique constraint**: prompt iteration and model swapping are inevitable. Storing all permutations means you can compare quality before promoting.

**Soft delete via `flagged`**: LLMs hallucinate. When something bad slips through, set `flagged=TRUE` and the partial index excludes it from the default query path instantly.

### 4.7 `shap_snapshot`

```sql
CREATE TABLE shap_snapshot (
    security_id        INT NOT NULL REFERENCES securities,
    retrain_date       DATE NOT NULL,
    horizon            INT NOT NULL,
    snapshot_date      DATE NOT NULL,
    base_value         DOUBLE PRECISION,
    predicted_value    DOUBLE PRECISION,
    feature_data       JSONB NOT NULL,
    PRIMARY KEY (security_id, retrain_date, horizon, snapshot_date)
);

CREATE INDEX idx_shap_recent
  ON shap_snapshot (security_id, snapshot_date DESC, horizon);
```

**Why JSONB**: each row stores ~10 features × 5 fields ≈ 50 small values. Normalized would be 50 rows × 91 tickers × 3 horizons × daily = millions of rows just for one chart. JSONB stores the whole force-plot payload as one queryable blob. Postgres handles JSONB efficiently.

**Frontend pattern**: single fetch returns a complete data structure, React renders the force plot directly without joins.

**Source**: this is mostly redundant with the per-ticker file's `shap_h*_top10` columns — the per-ticker file is the source of truth. ETL splits the JSON columns out into this separate table for cleaner indexed queries on SHAP across tickers (e.g., "which tickers had `vrp_wedge` as their top driver today"). If you don't need cross-ticker SHAP queries, this table can be skipped — read SHAP straight from `volatility_history` JSON columns.

### 4.8 `events_history`

```sql
CREATE TABLE events_history (
    id            BIGSERIAL PRIMARY KEY,
    event_date    DATE NOT NULL,
    event_type    TEXT NOT NULL,        -- 'earnings' | 'dividend' | 'fomc'
    severity      TEXT,                 -- 'crisis' | 'major' | 'notable'
    scope         TEXT NOT NULL,        -- 'market' | 'sector' | 'ticker'
    scope_value   TEXT,                 -- NULL for market; sector name; ticker symbol
    title         TEXT NOT NULL,
    description   TEXT,
    source        TEXT
);

CREATE INDEX idx_events_date  ON events_history (event_date);
CREATE INDEX idx_events_scope ON events_history (scope, scope_value);
```

**Initial scope** (auto-loaded from existing data sources):
- All earnings dates from Compustat (per ticker, scope='ticker', severity='notable')
- All dividend ex-dates from Compustat (per ticker, scope='ticker', severity='notable')
- All FOMC meeting dates from `utils.py` calendar (scope='market', severity='major')

**Future**: manual curation of ~30-50 high-severity macro events (COVID, SVB, etc.) with `severity='crisis'`. Schema is built to accept these later as additive inserts — no migration needed.

**Frontend usage**: hover over a date on the price chart, get the event title in a tooltip. Click for the description.

### 4.9 `macro_calendar`

```sql
CREATE TABLE macro_calendar (
    date          DATE NOT NULL,
    event_type    TEXT NOT NULL,        -- 'fomc' | 'cpi' | 'nfp'
    event_date    DATE NOT NULL,
    days_to_event INT,
    PRIMARY KEY (date, event_type)
);
```

Forward-looking. One row per (date, event_type). The frontend's "next FOMC: 14 days" widget queries this.

### 4.10 `get_distribution()` RPC

```sql
CREATE FUNCTION get_distribution(
    p_security_id    INT,
    p_metric         TEXT,    -- 'rv' | 'iv_atm_30d' | 'vrp_wedge' | 'pfv_cal_21'
    p_lookback_days  INT DEFAULT 1260
) RETURNS TABLE (
    scope               TEXT,    -- 'stock' | 'sector' | 'market'
    bin_low             DOUBLE PRECISION,
    bin_high            DOUBLE PRECISION,
    count               INT,
    current_value       DOUBLE PRECISION,
    current_percentile  DOUBLE PRECISION
);
```

**Why a function, not a materialized view**: distributions need the *current value* dotted line per call, and that moves daily. A view per (security × metric × scope) would be way too many objects to maintain.

**Why all three scopes in one call**: frontend toggle between Stock / Sector / Market doesn't trigger network requests — toggle is instant client-side state swap.

**Compute pattern**: `width_bucket()` over `volatility_history` filtered by security/sector/all + lookback window. Returns ~30 bins × 3 scopes = ~90 rows per call. Fast enough at the data volume (~250k rows in `volatility_history`).

### 4.11 Indexes summary

```sql
-- volatility_history: time-range queries by ticker
CREATE INDEX idx_vol_security_date     ON volatility_history (security_id, date DESC);

-- prices_history: same access pattern
CREATE INDEX idx_prices_security_date  ON prices_history (security_id, date DESC);

-- options_chain: snapshot lookups
CREATE INDEX idx_opt_security_snapshot ON options_chain (security_id, snapshot_date);
CREATE INDEX idx_opt_security_expiry   ON options_chain (security_id, snapshot_date, expiry);

-- ai_overview_equity: latest non-flagged
CREATE INDEX idx_ai_eq_recent
  ON ai_overview_equity (security_id, date DESC) WHERE flagged = FALSE;
CREATE INDEX idx_ai_eq_date_tier
  ON ai_overview_equity (date DESC, risk_tier) WHERE flagged = FALSE;

-- shap_snapshot: latest per ticker
CREATE INDEX idx_shap_recent
  ON shap_snapshot (security_id, snapshot_date DESC, horizon);

-- events_history
CREATE INDEX idx_events_date  ON events_history (event_date);
CREATE INDEX idx_events_scope ON events_history (scope, scope_value);
```

### 4.12 Materialized views (for `/sector/:sector` and `/macro` later)

```sql
CREATE MATERIALIZED VIEW sector_aggregates AS
SELECT
    s.gics_sector,
    v.date,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY v.rv) AS median_rv,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY v.iv_atm_30d) AS median_iv,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY v.vrp_wedge) AS median_vrp,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY v.pfv_cal_21) AS median_pfv_21,
    COUNT(*) AS n_tickers
FROM securities s
JOIN volatility_history v USING (security_id)
WHERE s.active = TRUE
GROUP BY s.gics_sector, v.date;

CREATE MATERIALIZED VIEW market_aggregates AS
SELECT
    v.date,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY v.rv) AS median_rv,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY v.vrp_wedge) AS median_vrp,
    STDDEV(v.pfv_cal_21) AS dispersion_pfv_21
FROM volatility_history v
JOIN securities s USING (security_id)
WHERE s.active = TRUE
GROUP BY v.date;
```

Refresh nightly after the model run finishes:
```sql
REFRESH MATERIALIZED VIEW sector_aggregates;
REFRESH MATERIALIZED VIEW market_aggregates;
```

---

## 5. ETL: How the Handoff Bundle Becomes Database Rows

The ETL runs after the backtest. Reads files from `webapp_export/`, writes to Supabase via service-role key.

```python
# Pseudocode — actual implementation in backend/etl/load_run.py

def load_run(export_dir: Path):
    # 1. Insert run manifest first (other tables FK into this)
    manifest = json.loads((export_dir / 'model_run_manifest.json').read_text())
    run_id = upsert_model_run(manifest)

    # 2. Update securities metadata (extends existing rows)
    sec_meta = pd.read_csv(export_dir / 'securities_metadata.csv')
    upsert_securities(sec_meta)

    # 3. Per-ticker time-series — column-group split into 2 tables
    for csv_path in (export_dir / 'tickers').glob('predictions_*.csv'):
        ticker = csv_path.stem.replace('predictions_', '')
        sec_id = lookup_security_id(ticker)

        df = pd.read_csv(csv_path, parse_dates=['date'])

        # Prices block → prices_history
        upsert_prices(
            df[['date','open','high','low','close','adj_close','volume']],
            security_id=sec_id
        )

        # Vol + IV + forecasts + events block → volatility_history
        vol_cols = ['date','rv','ewma_vol',
                    'iv_atm_30d','iv_atm_60d','iv_atm_91d','iv_atm_182d',
                    'vrp_wedge','vrp_wedge_ewma_21d',
                    'pfv_21','pfv_63','pfv_126',
                    'pfv_q15_21','pfv_q15_63','pfv_q15_126',
                    'pfv_cal_21','pfv_cal_63','pfv_cal_126',
                    'next_earnings_date','days_to_earnings',
                    'next_dividend_date','days_to_dividend',
                    'model_run_id']
        upsert_volatility_history(df[vol_cols], security_id=sec_id)

        # Optional: SHAP JSON columns → shap_snapshot table
        # (Skip if reading SHAP straight from volatility_history JSONB columns)
        upsert_shap_snapshots(df, security_id=sec_id)

    # 4. Sparse files
    upsert_events_history(pd.read_csv(export_dir / 'events_history.csv'))
    upsert_macro_calendar(pd.read_csv(export_dir / 'macro_calendar.csv'))

    # 5. Refresh aggregates
    refresh_materialized_views()
```

All upserts use `INSERT ... ON CONFLICT (...) DO UPDATE` — re-running the ETL is idempotent.

---

## 6. Frontend Query Pattern: `/equity/:symbol`

When the user navigates to `/equity/AAPL`, React Router's loader fires one composite query (or a backend API endpoint that bundles them):

```sql
-- 1. Static metadata
SELECT * FROM securities WHERE symbol = 'AAPL';

-- 2. Time-series for charts (5 years)
SELECT * FROM volatility_history
WHERE security_id = $1 AND date >= NOW() - INTERVAL '5 years'
ORDER BY date;

-- 3. Price chart (1 year is plenty for the equity page)
SELECT * FROM prices_history
WHERE security_id = $1 AND date >= NOW() - INTERVAL '1 year'
ORDER BY date;

-- 4. Options chain (latest snapshot, all expiries)
SELECT * FROM options_chain
WHERE security_id = $1
  AND snapshot_date = (SELECT MAX(snapshot_date) FROM options_chain WHERE security_id = $1)
ORDER BY expiry, strike;

-- 5. Latest AI overview
SELECT * FROM ai_overview_equity
WHERE security_id = $1
  AND model_version  = $current_model
  AND prompt_version = $current_prompt
  AND flagged = FALSE
ORDER BY date DESC LIMIT 1;

-- 6. Latest SHAP per horizon (or skip — read JSON column from volatility_history)
SELECT * FROM shap_snapshot
WHERE security_id = $1
  AND retrain_date = (SELECT MAX(retrain_date) FROM shap_snapshot WHERE security_id = $1);

-- 7. Distribution data (single RPC call, all 3 scopes)
SELECT * FROM get_distribution($1, 'rv');

-- 8. Event annotations for the price chart
SELECT * FROM events_history
WHERE event_date >= NOW() - INTERVAL '1 year'
  AND (
    scope = 'market'
    OR (scope = 'sector' AND scope_value = (SELECT gics_sector FROM securities WHERE security_id = $1))
    OR (scope = 'ticker' AND scope_value = (SELECT symbol FROM securities WHERE security_id = $1))
  )
ORDER BY severity, event_date;
```

Backend API endpoint `GET /api/equity/:symbol` runs these in parallel, assembles into one composite JSON payload. Frontend gets everything in a single React-Query hook on page mount.

---

## 7. Update Lifecycle

### Daily (after market close + model inference)
1. Backtest pipeline appends one row to each `predictions_<TICKER>.csv` file
2. ETL detects new rows and upserts into `volatility_history`, `prices_history`, `shap_snapshot`
3. Live options ETL pulls today's chain into `options_chain`
4. AI overview pipeline generates daily commentary, inserts into `ai_overview_equity`
5. Materialized views refresh: `sector_aggregates`, `market_aggregates`

### Weekly / on retrain (every 20 trading days)
6. New model retrained → SHAP TreeExplainer rebuilt
7. All subsequent daily SHAP rows reference the new model

### Per backtest run (full corpus regeneration)
8. Full handoff bundle regenerated
9. ETL re-loads all tables (idempotent via UPSERT)
10. New row inserted into `model_runs`
11. Materialized views fully rebuilt

---

## 7b. Daily Append Lifecycle — Implementation

This is the operational counterpart of §7. Lists the actual commands run on
the rig, the cron cadence, and the failure-handling expectations.

### Files in play

| File | Purpose |
|---|---|
| `model/pipeline/export_for_webapp.py` | Per-ticker CSV writer + Supabase upserter |
| `model/pipeline/db.py` | Supabase client wrapper (chunked upserts, idempotency, schema verification) |
| `model/pipeline/test_daily_append.py` | End-to-end integration test |
| `model/sql/migrations/001_supabase_schema_fixes.sql` | Schema migration the web side runs once |

### Pre-flight (one-time)

```bash
# Web side: apply migration
psql -h db.<project>.supabase.co -U postgres -d postgres -f \
    model/sql/migrations/001_supabase_schema_fixes.sql

# Model side: install supabase-py
pip install supabase python-dotenv

# Model side: add credentials to model/.env
#   SUPABASE_URL=https://<project>.supabase.co
#   SUPABASE_SERVICE_ROLE_KEY=eyJ...   (service_role, not anon)

# Sanity check the connection + schema
python -m model.pipeline.db
```

### One-time full upload (after the v10+ corpus run completes)

```bash
# Dry-run first to validate everything
python -m model.pipeline.export_for_webapp \
    --all --push-to-supabase --dry-run

# Real upload
python -m model.pipeline.export_for_webapp \
    --all --push-to-supabase
```

Expected runtime: ~5 min for 91 tickers (260k rows total, chunked at 500/batch).

### Daily append (production cron job)

Runs nightly after the daily inference step completes:

```bash
# Append-only mode: queries DB for last loaded date per ticker,
# only pushes rows newer than that. Idempotent on rerun.
python -m model.pipeline.export_for_webapp \
    --all --push-to-supabase --append-only
```

Expected runtime: <10s (one new row per ticker per day).

### Failure modes and recovery

| Failure | Detection | Recovery |
|---|---|---|
| Supabase down | HTTP error in `db.py` retry loop | Retry 3× with backoff. If still failing, cron exits non-zero; next day's run will catch up via `--append-only` |
| Schema migration not applied | `verify_schema()` raises `SchemaMismatchError` at startup | Exit code 2 with clear message. Web side runs migration, model side reruns. |
| Partial upload | Chunked upserts; idempotent on rerun via natural-key constraints | Rerun the same command. `ON CONFLICT DO UPDATE` reconciles. |
| `model/.env` credentials missing or stale | `SupabaseConfigError` at client init | Re-fetch service role key from Supabase dashboard, update `.env` |
| New ticker added to universe | First `--append-only` run for the new ticker shows "no security_id" warning | Insert row into `securities` table first, then rerun the export |

### Integration test cadence

Run `test_daily_append.py` against the test Supabase project:
- Before any production deploy
- Weekly as a smoke test
- Anytime the schema or `db.py` changes

```bash
# Default: dry-run mode
python -m model.pipeline.test_daily_append --ticker AAPL

# Live: actually writes + cleanup
python -m model.pipeline.test_daily_append --ticker AAPL --live --cleanup
```

### Why CSV stays as the source of truth

Even with Supabase writes turned on, the per-ticker CSVs are always written
first. This is intentional:

1. **Auditability** — if Supabase data ever diverges from CSV, the CSV wins
2. **Repository state** — backtest reproducibility lives in the file system, not the database
3. **Recovery** — if the DB is wiped, a full re-upload from CSV is one command
4. **Decoupling** — model iteration doesn't depend on DB availability

The Supabase tables are the **frontend's consumption layer**, not the model's
output layer. Keep this separation clean.

---

## 8. Conventions and Gotchas

**Decimal formatting**: vol values are stored as **annualized decimals** throughout the database (0.245 means 24.5%). The frontend formats to "24.5%". Do NOT mix percent and decimal across columns — that's a class of bug you don't want.

**Time zones**: store everything as `DATE` (not `TIMESTAMP`) for daily data. Eliminates time-zone bugs. Use `TIMESTAMPTZ` only for `generated_at` columns where wall-clock matters.

**Idempotent ETL**: every upsert uses `ON CONFLICT ... DO UPDATE`. Rerunning a day's load never produces duplicates.

**RLS (Row Level Security)**: enable on all tables. Anonymous role gets `SELECT` on the public-readable tables. Service role (backend ETL) gets `INSERT`/`UPDATE`/`DELETE`. Standard Supabase pattern.

**Retention policies**:
- `ai_overview_equity`: keep last 90 days, delete older nightly
- `options_chain`: keep last 2 years (active options only — historical analysis lives elsewhere)
- `shap_snapshot`: keep last 1 year (the 21d trail UI uses this)
- All others: keep all history (cheap relative to value)

**Active vs excluded tickers**: frontend universe queries always filter `WHERE active = TRUE`. The 4 excluded tickers (LIN, OXY, VZ, META) keep their historical rows for audit/research but never appear in the picker or aggregates.

---

## 9. Migration Order (for the web dev to execute)

```sql
-- 1. Extend existing securities table
ALTER TABLE securities ADD COLUMN gics_sector TEXT;
ALTER TABLE securities ADD COLUMN gics_industry TEXT;
ALTER TABLE securities ADD COLUMN sector_etf TEXT;
ALTER TABLE securities ADD COLUMN active BOOLEAN DEFAULT TRUE;
ALTER TABLE securities ADD COLUMN excluded_reason TEXT;
ALTER TABLE securities ADD COLUMN min_history_date DATE;
ALTER TABLE securities ADD COLUMN last_model_run TIMESTAMPTZ;

-- 2. Create model_runs (FK target)
CREATE TABLE model_runs (...);

-- 3. Create time-series tables
CREATE TABLE volatility_history (...);
CREATE TABLE prices_history (...);
CREATE TABLE options_chain (...);

-- 4. Create content tables
CREATE TABLE ai_overview_equity (...);
CREATE TABLE shap_snapshot (...);

-- 5. Create event tables
CREATE TABLE events_history (...);
CREATE TABLE macro_calendar (...);

-- 6. Create indexes
-- (all CREATE INDEX statements from §4.11)

-- 7. Create RPC
CREATE FUNCTION get_distribution(...) AS ...;

-- 8. Create materialized views (after some data is loaded)
CREATE MATERIALIZED VIEW sector_aggregates AS ...;
CREATE MATERIALIZED VIEW market_aggregates AS ...;

-- 9. Enable RLS + policies on every table
ALTER TABLE volatility_history ENABLE ROW LEVEL SECURITY;
CREATE POLICY "public read" ON volatility_history FOR SELECT TO anon USING (true);
-- (repeat for each table)
```

---

## 10. What's NOT in This Schema (Deferred)

- `/sector/:sector` page-specific tables (use `sector_aggregates` view + filter on securities)
- `/macro` page-specific tables (use `market_aggregates` view + macro_calendar)
- `/dashboard` user-state tables (`user_watchlists`, `user_layouts`) — auth-gated, separate concern
- Manual macro crisis events curation (~30 high-severity events) — schema supports them, content deferred
- `risk_free_rate` table — was in an earlier draft but eliminated when we decided not to do Black-Scholes fair-pricing in the options chart (we use ±1σ bands instead)
- Historical sector rotation tables — out of MVP scope

---

## 11. Reference: The Equity Page UI Components and Their Data Sources

| UI Component | Source Table(s) |
|---|---|
| Header (symbol, sector, risk pill) | `securities` + `ai_overview_equity` (latest) |
| Price chart (1y candlestick + line) | `prices_history` |
| Event annotations on price chart | `events_history` |
| VRP wedge + EWMA panel | `volatility_history.vrp_wedge` + `vrp_wedge_ewma_21d` |
| Vol term structure (Forecast vs IV, splined) | `volatility_history.pfv_cal_*` + `iv_atm_*d` |
| Options chart (price vs strike + bands) | `options_chain` + `volatility_history` (latest) |
| Distribution panel (toggle: stock/sector/market) | `get_distribution()` RPC |
| SHAP force plot | `shap_snapshot` OR `volatility_history.shap_h*_top10` JSON |
| AI overview text card | `ai_overview_equity` (latest) |
| Forward calendar (next earnings, FOMC) | `volatility_history.next_*` + `macro_calendar` |
| Footer (model version, run date) | `model_runs` joined via `volatility_history.model_run_id` |

---

_Schema designed by Leo + Claude collaboration sessions. Last updated 2026-05-07._