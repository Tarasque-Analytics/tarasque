"""
orchestrator.py — builds and runs the stage DAG (PLAN §2, §9).

Responsibilities:
  - resolve the run's business date ONCE and build the RunContext (PLAN §3.2)
  - construct + connect the write client (skipped in dry-run)
  - run stages in dependency order, with fetch_prices ∥ fetch_options concurrent (PLAN §2)
  - isolate partial failures (one ticker can't sink the run) and stage failures (PLAN §9.2)
  - emit a structured run summary

It is intentionally thin: each stage owns its own freshness check and work. The DAG order is fixed
(the dependency graph is small and well-understood) rather than computed.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .config import AutomationConfig
    from .logging_utils import StageReport
    from .stages.base import Stage


def build_dag() -> "list[list[Stage]]":
    """
    Build the ordered DAG as a list of *levels*; stages within a level run concurrently (PLAN §2).

    Level 0: [ensure_universe]
    Level 1: [fetch_prices, fetch_options]      # parallel; events stage is DEFERRED, not included
    Level 2: [run_model]
    Level 3: [upload_outputs]
    Level 4: [ai_overviews]

    TODO: instantiate the Stage objects from automation.stages and return the levels. Respect
    config.only_stages (subset selection) by filtering, preserving dependency order.
    """
    raise NotImplementedError("TODO(PLAN §2): assemble stage levels")


async def run_daily(config: "AutomationConfig") -> "list[StageReport]":
    """
    Execute one full daily run and return per-stage reports.

    Flow (PLAN §2, §9):
      1. run_date = resolve_business_date(); build RunLogger
      2. db = WriteClient(config.supabase, dry_run=config.dry_run); await db.connect()
      3. ctx = RunContext(run_date, config, db, logger)
      4. for level in build_dag():
             run the level's stages concurrently (asyncio.gather), isolating exceptions
             a critical-stage failure (universe/prices) aborts; a non-critical one (ai_overviews)
             logs + continues so upstream DB writes are preserved (PLAN §9.2)
      5. finally: await db.close(); print run summary

    TODO: implement the level loop with per-stage try/except + StageReport collection.
    """
    raise NotImplementedError("TODO(PLAN §2, §9): run the DAG")


def main(argv: Optional[list[str]] = None) -> int:
    """
    CLI entry (invoked by `python -m automation`). Parses flags, loads config, runs the DAG.

    Flags (PLAN §9.3):
      --dry-run          resolve freshness + print intended work; no external calls, no DB writes
      --force            ignore skip/freshness checks; re-run everything
      --only STAGE ...   run only the named stage(s), preserving dependency order
      --env dev|stg|prod target selection (default from AUTOMATION_ENV)

    TODO:
      - argparse the flags above
      - cfg = load_config(dry_run=..., force=..., only_stages=...)
      - asyncio.run(run_daily(cfg)); return non-zero on any 'failed' stage
    """
    raise NotImplementedError("TODO(PLAN §9): CLI wiring")
