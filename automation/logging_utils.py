"""
logging_utils.py — structured per-stage logging and the optional pipeline_runs ledger.

Each stage reports a `StageReport` (counts + status + timing). The `RunLogger` prints a structured
summary and, when `config.write_run_ledger` is on, upserts a row into `pipeline_runs` (PLAN §3.3).
The ledger is **observability only** — never the authority on freshness (PLAN §3.1).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from .db import WriteClient


class StageStatus(str, Enum):
    SUCCESS = "success"
    PARTIAL = "partial"     # some securities failed but under the failure threshold (PLAN §9.2)
    FAILED = "failed"
    SKIPPED = "skipped"     # nothing stale — no work to do (PLAN §3)


@dataclass
class StageReport:
    """The outcome of one stage, for logging + the optional ledger."""

    stage: str
    status: StageStatus
    rows_written: int = 0
    n_securities: int = 0
    n_skipped: int = 0
    n_failed: int = 0
    duration_seconds: float = 0.0
    error: Optional[str] = None
    meta: dict[str, Any] = field(default_factory=dict)   # provider, model_version, cost est., ...


class RunLogger:
    """Structured logging for a single pipeline run."""

    def __init__(self, run_date: date, *, dry_run: bool, db: Optional["WriteClient"] = None,
                 write_ledger: bool = False) -> None:
        self.run_date = run_date
        self.dry_run = dry_run
        self._db = db
        self._write_ledger = write_ledger

    def stage_start(self, stage: str) -> None:
        """Log the start of a stage."""
        raise NotImplementedError("TODO(PLAN §9.3): structured stage-start log line")

    def stage_finish(self, report: StageReport) -> None:
        """
        Log a stage's `StageReport` and, if enabled, upsert it into `pipeline_runs`.

        TODO:
          - emit a single structured line (stage, run_date, counts, duration, status)
          - if self._write_ledger and not dry_run: self._db.upsert_pipeline_run(self.run_date, report)
        """
        raise NotImplementedError("TODO(PLAN §3.3, §9.3): log + optional ledger upsert")

    def info(self, msg: str) -> None:
        raise NotImplementedError

    def warning(self, msg: str) -> None:
        raise NotImplementedError

    def error(self, msg: str, *, exc: Optional[BaseException] = None) -> None:
        raise NotImplementedError
