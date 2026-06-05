"""
events.py — Stage 1c: events / macro (DEFERRED — PLAN §2, §1c).

Scaffolded but **not wired into the DAG** (kickoff decision: defer event_history / macro_calendar).
Left here so the shape is agreed and turning it on later is a one-line orchestrator change.

Two distinct sources (do not conflate — see backend/CLAUDE.md "Event model"):
  - event_history  — PER-SECURITY events (earnings, dividends). Natural unique
                     (security_id, event_date, event_type).
  - macro_calendar — MARKET-WIDE events (CPI, FOMC, NFP). PK (date, event_type). Not tied to a
                     security.

The model already derives earnings/dividend/FOMC signals for its own features (model utils +
Compustat), so much of this data exists model-side — a coordination point when this is enabled.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .base import Stage

if TYPE_CHECKING:
    from ..context import RunContext
    from ..logging_utils import StageReport


class EventsStage(Stage):
    name = "events"
    depends_on = ("ensure_universe",)
    critical = False

    async def is_stale(self, ctx: "RunContext") -> bool:
        """Deferred — not in the DAG. Returns False so a stray inclusion is a no-op."""
        return False

    async def run(self, ctx: "RunContext") -> "StageReport":
        """
        DEFERRED (PLAN §1c, §13). When enabled:
          - event_history: upsert per-security earnings/dividends, on_conflict
            (security_id, event_date, event_type)
          - macro_calendar: upsert CPI/FOMC/NFP, on_conflict (date, event_type); recompute days_to_event
          - decide a source (model-derived vs a calendar API) and add the read RLS policy if the API
            starts serving these (backend/CLAUDE.md RLS gotcha)
        """
        raise NotImplementedError("DEFERRED(PLAN §1c): events/macro stage not in scope yet")
