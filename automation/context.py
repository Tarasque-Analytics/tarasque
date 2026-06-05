"""
context.py — RunContext: the immutable per-run state threaded through every stage.

Crucially, `run_date` is resolved **once** at orchestrator startup (PLAN §3.2) and reused by every
stage so all tables agree on the day. Stages must read `ctx.run_date` rather than calling
`datetime.now()` themselves (that would let prices_history, options_chain, model_runs, and
volatility_history disagree on the date around midnight / across retries).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    # Import only for type checking to keep `import automation` free of heavy/optional deps.
    from .config import AutomationConfig
    from .db import WriteClient
    from .logging_utils import RunLogger


@dataclass(frozen=True)
class RunContext:
    """Everything a stage needs, constructed by the orchestrator and passed to `Stage.run`."""

    run_date: date                 # the resolved US business date (PLAN §3.2)
    config: "AutomationConfig"
    db: "WriteClient"              # write-capable, service-role client (PLAN §6)
    logger: "RunLogger"

    @property
    def dry_run(self) -> bool:
        return self.config.dry_run

    @property
    def force(self) -> bool:
        return self.config.force


def resolve_business_date(now_eastern: Optional["date"] = None) -> date:
    """
    Resolve the run's business date — the US trading day to attribute this run to (PLAN §3.2).

    The pipeline fires after US close (~6pm ET), so the business date is normally "today" in
    US/Eastern. On weekends/holidays this should resolve to the most recent trading day (or signal a
    market-data no-op).

    TODO:
      - compute in US/Eastern (zoneinfo "America/New_York")
      - roll back to the prior trading day on weekends/holidays (reuse the model's FOMC/holiday
        calendar in model/pipeline/utils.py rather than duplicating one)
    """
    raise NotImplementedError("TODO(PLAN §3.2): resolve US business/trading date")
