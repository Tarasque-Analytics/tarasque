"""
ensure_universe.py — Stage 0: ensure/refresh the universe (PLAN §2, §10).

Resolves the active universe from `securities` (the source of truth) and makes it available to
downstream stages. Universe **metadata** (sector, min_history_date, ...) is static-ish, so it is
upserted only on change — never re-pulled daily (PLAN §3.1).

In the common case this stage does no writes: it just confirms the active set is non-empty and hands
it to the run. Metadata upserts happen only when the universe config changes.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .base import Stage

if TYPE_CHECKING:
    from ..context import RunContext
    from ..logging_utils import StageReport


class EnsureUniverseStage(Stage):
    name = "ensure_universe"
    depends_on = ()
    critical = True   # an empty/broken universe means the whole run is meaningless

    async def is_stale(self, ctx: "RunContext") -> bool:
        """Always runs (cheap) — it's how every other stage learns the universe (PLAN §10)."""
        return True

    async def run(self, ctx: "RunContext") -> "StageReport":
        """
        TODO(PLAN §10):
          - universe = await resolve_active_universe(ctx)   # securities where active = true
          - if empty: warn loudly and mark FAILED (critical)
          - (optional) upsert changed securities metadata only
          - stash the resolved universe for downstream stages (e.g. return via report.meta or a
            shared run-scoped cache the orchestrator passes along)
        """
        raise NotImplementedError("TODO(PLAN §10): resolve + (rarely) upsert universe")
