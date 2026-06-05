"""
upload_outputs.py — Stage 3: model artifacts → DB (PLAN §2, §4, §7.4).

Maps the model's on-disk artifacts onto three tables, all keyed to a single `model_runs` row:
  1. model_runs        — one row per (run_date, model_version); its id FKs the others (PLAN §4.2)
  2. volatility_history— per-security model output + market IV; PK (security_id, date)
  3. shap_snapshot     — per-security per-horizon SHAP; PK (security_id, retrain_date, horizon)

This stage is a **thin mapper** governed by `model_interface` (the §7.4 mapping). It must NOT
fabricate values for GAP columns (pfv_cal_*, pfv_q15_*, fwd_premium_*, SHAP, spec_hash) — those are
written NULL/empty and logged until the model dev resolves them (PLAN §7.5).

The IV columns (iv_atm_*) are today derived from the model's vsurfd; post-WRDS they must come from
the `options_chain` this run fetched. That seam is unresolved (PLAN §7.5.4) — flagged in the mapping.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .base import Stage

if TYPE_CHECKING:
    from ..context import RunContext
    from ..logging_utils import StageReport


class UploadOutputsStage(Stage):
    name = "upload_outputs"
    depends_on = ("run_model",)
    critical = True

    async def is_stale(self, ctx: "RunContext") -> bool:
        """
        Stale if any active security lacks a volatility_history row for run_date.

        TODO(PLAN §3.1): done = await ctx.db.volatility_rows_for_date(ctx.run_date);
        return len(done) < len(universe) (or True if ctx.force).
        """
        raise NotImplementedError

    async def run(self, ctx: "RunContext") -> "StageReport":
        """
        TODO(PLAN §4.2, §7.4):
          - artifacts = ModelArtifacts(ctx.config.model_results_dir, ctx.run_date)
          - model_run_id = await ctx.db.insert_model_run(MODEL_RUNS_MAP-derived row)   # idempotent (§4.2)
          - for each security:
                vol_row  = model_interface.read_volatility_row(artifacts, ticker, security_id, model_run_id)
                shap_rows = model_interface.read_shap_rows(artifacts, ticker, security_id)  # [] today
          - in dry_run: log row counts + the GAP columns that will be NULL; no writes
          - await ctx.db.upsert_volatility_history(vol_rows)   # on_conflict security_id,date
          - await ctx.db.upsert_shap_snapshot(shap_rows)       # on_conflict security_id,retrain_date,horizon
          - isolate per-ticker failures; once on the run, log model_interface.gaps(...) → StageReport
        """
        raise NotImplementedError("TODO(PLAN §7.4): map artifacts → 3 tables (idempotent)")
