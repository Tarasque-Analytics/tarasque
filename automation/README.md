# automation — data tooling for the volarbmodel DB

The only component that **writes** to the Supabase DB, via a secret-key client kept separate from the
app's read-only client. This package currently ships two working tools; the broader nightly pipeline
is **designed but not yet implemented** — see **[PLAN.md](PLAN.md)** and
**[OPTIONS_IMPORT_PLAN.md](OPTIONS_IMPORT_PLAN.md)** for the full design and rationale.

## What's implemented

| Tool | What it does | Writes |
|---|---|---|
| `tools/fetch_options.py` | Pull a scoped daily options chain from yfinance (expiries nearest 30/60/90/180 DTE + front monthlies, strikes ±band of spot), compute `delta` in-house (Black-Scholes), upsert. | `options_chain` |
| `tools/sync_sp500.py` | Maintain the S&P 500 reference (`data/sp500.csv`) and upsert constituents — add-missing or `--update-existing` to refresh GICS/company name. | `securities` |
| `sql/remap_security_ids_cik.sql` | One-off migration remapping `securities.security_id` → SEC CIK (cascades to child tables). Run in the Supabase SQL editor. | `securities` (+cascade) |

Re-runs are idempotent (keyed upserts), and freshness is derived from the DB (skip-if-already-present).

## Setup

```bash
pip install -r automation/requirements.txt          # from repo root
cp .env.example .env                                 # fill in values (.env is gitignored)
```

Required env vars:

| Var | Purpose |
|---|---|
| `SUPABASE_URL` | hosted project URL (may reuse `VITE_SUPABASE_URL`) |
| `SUPABASE_SECRET_KEY` | Supabase **secret** API key for writes (bypasses RLS) — SECRET (legacy `SUPABASE_SERVICE_ROLE_KEY` accepted) |
| `AUTOMATION_ENV` | `dev`/`stg`/`prod` (default `dev`) |

## Usage

Run as modules from the **repo root**.

```bash
# Options chain (yfinance). --dry-run fetches + prints with NO DB writes (no creds needed).
python -m automation.tools.fetch_options --tickers AAPL MSFT --dry-run
python -m automation.tools.fetch_options --tickers AAPL MSFT          # write
python -m automation.tools.fetch_options --tickers AAPL --force       # re-fetch today's snapshot

# Securities / S&P 500. --refresh rebuilds the CSV from Wikipedia; default previews; --apply writes.
python -m automation.tools.sync_sp500 --refresh                       # rebuild data/sp500.csv
python -m automation.tools.sync_sp500                                 # preview missing constituents
python -m automation.tools.sync_sp500 --apply                        # add missing
python -m automation.tools.sync_sp500 --update-existing --apply       # refresh GICS/name on existing
```

Tests (pure functions, no network/DB): `python -m pytest automation/tests`.

## Layout

```
automation/
  PLAN.md              ← full pipeline design (read for the broader plan)
  OPTIONS_IMPORT_PLAN.md ← options import design
  config.py            ← env/config (load_config)
  db.py                ← secret-key write client (idempotent upserts)
  black_scholes.py     ← in-house delta (yfinance has no greeks)
  expiry_selection.py  ← which expiries to fetch
  options_import.py    ← reusable per-security options import core
  providers/options_provider.py ← yfinance options provider
  tools/fetch_options.py, tools/sync_sp500.py  ← the CLIs
  sql/remap_security_ids_cik.sql ← CIK remap migration
  data/sp500.csv, company_tickers.json         ← reference metadata
  tests/               ← pure-function tests
```

## Boundaries

- The only component that **writes** the DB (`backend/` reads with the publishable/anon key, read-only
  under RLS). The write client (`db.py`) uses the secret key and must never be imported by `backend/`.
- Not the model. The forecasting model (`model/`) is a separate component with its own data path.
