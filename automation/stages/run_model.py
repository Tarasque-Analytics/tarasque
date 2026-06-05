"""
run_model.py — Stage 2: run the external forecasting model (PLAN §2, §7).

The model is an external component (owned by another dev). This stage invokes it as a **subprocess**
(`python -m model.pipeline.run ...`, built by `model_interface.build_invocation`) over the active
universe and waits for its artifacts to land in the results dir. It does NOT import the model.

**Skip-if-done (PLAN §3.1):** if `model_runs` already has a row for (run_date, model_version), skip
the (expensive, compute-heavy) run unless `--force`.

⚠ The model's current `--mode live` only PRINTS — it has no DB-ready output mode yet. Finalizing the
invocation + a `--mode emit-db` is the central model-dev coordination item (PLAN §7.5.5).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .base import Stage

if TYPE_CHECKING:
    from ..context import RunContext
    from ..logging_utils import StageReport


class RunModelStage(Stage):
    name = "run_model"
    depends_on = ("fetch_prices", "fetch_options")   # needs current prices (+ IV for IV features)
    critical = True

    async def is_stale(self, ctx: "RunContext") -> bool:
        """
        TODO(PLAN §3.1): model_version = resolve from model config; return
        await should_run_model(ctx, model_version).
        """
        raise NotImplementedError

    async def run(self, ctx: "RunContext") -> "StageReport":
        """
        TODO(PLAN §7, §9.2):
          - tickers = active universe symbols
          - argv = model_interface.build_invocation(ctx.config, tickers)   # blocked on §7.5.5
          - in dry_run: log the argv that WOULD run; do not spawn the model
          - else: run the subprocess with a timeout; capture stdout/stderr; check exit code
          - verify expected artifacts exist (ModelArtifacts paths); fail clearly if missing
          - report runtime + which tickers produced artifacts → StageReport.meta['model_version'], etc.
        NOTE: this stage does NOT write the DB — Stage 3 (upload_outputs) reads the artifacts.
        """
        raise NotImplementedError("TODO(PLAN §7.5): invoke model subprocess + verify artifacts")
