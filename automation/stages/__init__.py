"""
automation.stages — the pipeline's stage modules (PLAN §2).

Each stage is a small unit with: a name, declared dependencies, a freshness check (is there anything
stale to do?), and a `run(ctx)` that does the work and returns a StageReport. Stages are wired into
the DAG by `automation.orchestrator.build_dag`.

  ensure_universe  → Stage 0   (securities)
  fetch_prices     → Stage 1a  (prices_history, incremental)         ┐ parallel
  fetch_options    → Stage 1b  (options_chain, daily snapshot)        ┘
  events           → Stage 1c  (DEFERRED — stub, not in the DAG)
  run_model        → Stage 2   (external model, subprocess)
  upload_outputs   → Stage 3   (volatility_history + model_runs + shap_snapshot)
  ai_overviews     → Stage 4   (ai_overview, provider-agnostic)
"""
