"""
automation — the automated daily data pipeline for volarbmodel.

A single, idempotent, incremental run (eventually nightly, after US market close) that leaves the
Supabase database fresh every morning:

    1. fetch_prices   → prices_history      (incremental, append-only)
    2. fetch_options  → options_chain       (daily point-in-time snapshot)   ∥ with (1)
    3. run_model      → model artifacts      (external component; subprocess)
    4. upload_outputs → volatility_history + model_runs + shap_snapshot
    5. ai_overviews   → ai_overview          (provider/model-agnostic)

This package is **separate** from `model/` (the forecasting model, owned by another developer) and
`backend/` (the read-only API). It is the only component that **writes** to the DB, using a
service-role client distinct from the app's read client.

SCAFFOLD STATUS: stubs only. No stage logic is implemented. See `automation/PLAN.md` for the full
design; every TODO in this package points back to a section there.
"""

__all__ = ["__version__"]

__version__ = "0.0.0-scaffold"
