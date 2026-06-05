"""
base.py — the Stage abstract base class (PLAN §2, §9).

A Stage encapsulates one node of the DAG. The orchestrator calls `is_stale()` (cheap, DB-derived)
to decide whether to skip, then `run(ctx)` to do the work. `run` must:
  - honor `ctx.dry_run` (no external calls, no DB writes — just report intended work; PLAN §9.3)
  - isolate per-security failures (one ticker failing must not raise out of the stage; PLAN §9.2)
  - return a StageReport with counts + status

`critical` marks stages whose failure aborts the run (universe, prices); non-critical failures are
logged and the run continues so already-committed upstream writes are preserved.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..context import RunContext
    from ..logging_utils import StageReport


class Stage(ABC):
    """Abstract DAG node."""

    #: stable stage name (matches CONFLICT-free ledger key / --only selector / PLAN stage ids)
    name: str = "stage"

    #: names of stages that must complete before this one (PLAN §2). Informational — the
    #: orchestrator enforces order via DAG levels; this documents intent and powers --only.
    depends_on: tuple[str, ...] = ()

    #: if True, a failure aborts the whole run; if False, it's logged and the run continues (PLAN §9.2)
    critical: bool = False

    @abstractmethod
    async def is_stale(self, ctx: "RunContext") -> bool:
        """Cheap, DB-derived check: is there anything for this stage to do? (PLAN §3)."""
        ...

    @abstractmethod
    async def run(self, ctx: "RunContext") -> "StageReport":
        """Execute the stage. Must be idempotent and dry-run aware. Returns a StageReport."""
        ...
