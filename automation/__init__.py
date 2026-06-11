"""
automation — data tooling for the volarbmodel database.

The only component that **writes** to the DB (via a secret-key client, separate from the app's
read-only client). What's implemented today:

  - Options-chain import (yfinance → options_chain): `tools/fetch_options.py`
  - Securities / universe sync (SEC CIK + S&P 500 + GICS): `tools/sync_sp500.py`,
    `sql/remap_security_ids_cik.sql`

The broader daily pipeline (prices, model run, output upload, AI overviews) is **designed but not
yet implemented** — see `PLAN.md` and `OPTIONS_IMPORT_PLAN.md` for the full plan.
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
