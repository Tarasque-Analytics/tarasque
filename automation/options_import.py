"""
options_import.py — reusable options-import core (CLAUDE.md §5).

The single place that wires provider → expiry selection → fetch → upsert for ONE security, so callers
share one implementation:
  - the standalone CLI  (`automation/tools/fetch_options.py`) — the shipped entry point
  - the pipeline stage   (planned — will reuse this core when the orchestrator is built)

Provider network calls are synchronous (yfinance); they're invoked directly here. Callers that need
concurrency can wrap `import_options_for_security` with `asyncio.to_thread`, but sequential is fine
for a handful of tickers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING, Optional

from .expiry_selection import select_expiries
from .providers.options_provider import OptionsScope, YFinanceOptionsProvider

if TYPE_CHECKING:
    from .config import OptionsImportConfig
    from .db import WriteClient
    from .providers.options_provider import OptionsProvider


# provider registry — provider-agnostic by design (add Polygon/Tradier here later).
_PROVIDERS = {
    "yfinance": YFinanceOptionsProvider,
}


def make_options_provider(config: "OptionsImportConfig") -> "OptionsProvider":
    """Resolve the configured options provider from the registry."""
    try:
        cls = _PROVIDERS[config.provider]
    except KeyError:
        raise ValueError(
            f"Unknown options provider {config.provider!r}; known: {sorted(_PROVIDERS)}"
        ) from None
    return cls(config)


@dataclass
class ImportResult:
    """Outcome of importing one security's options snapshot (for logging + reports)."""

    ticker: str
    security_id: int
    snapshot_date: date
    n_contracts: int = 0
    rows_written: int = 0
    skipped: bool = False  # today's snapshot already present (skip-if-done)
    error: Optional[str] = None
    expiries: list[date] = field(default_factory=list)
    spot: Optional[float] = None


async def import_options_for_security(
    db: "WriteClient",
    provider: "OptionsProvider",
    *,
    ticker: str,
    security_id: int,
    snapshot_date: date,
    config: "OptionsImportConfig",
    force: bool = False,
    dry_run: bool = False,
) -> ImportResult:
    """
    Import one security's options snapshot for `snapshot_date`.

    Steps: skip-if-done (unless force) → list+select expiries → fetch spot → fetch+normalize chain →
    upsert (unless dry_run). Returns an ImportResult; on a handled error returns it with `error` set
    rather than raising, so a single ticker can't sink a multi-ticker run.
    """
    try:
        if not force:
            exists = await db.options_snapshot_exists([security_id], snapshot_date)
            if exists.get(security_id):
                return ImportResult(ticker, security_id, snapshot_date, skipped=True)

        available = provider.list_expiries(ticker)
        expiries = select_expiries(
            available,
            snapshot_date,
            term_dte_targets=tuple(config.term_dte_targets),
            front_monthlies=config.front_monthlies,
        )
        if not expiries:
            return ImportResult(
                ticker, security_id, snapshot_date, error="no future expiries available"
            )

        spot = provider.fetch_spot(ticker)
        scope = OptionsScope(
            strike_band_pct=config.strike_band_pct,
            max_strikes_per_side=config.max_strikes_per_side,
        )
        rows = provider.fetch_chain(
            ticker,
            expiries,
            snapshot_date=snapshot_date,
            security_id=security_id,
            scope=scope,
            spot=spot,
            risk_free_rate=config.risk_free_rate,
        )

        written = 0 if dry_run else await db.upsert_options_chain(rows)
        return ImportResult(
            ticker,
            security_id,
            snapshot_date,
            n_contracts=len(rows),
            rows_written=written,
            expiries=expiries,
            spot=spot,
        )
    except Exception as e:  # noqa: BLE001 — isolate per-ticker failures
        return ImportResult(ticker, security_id, snapshot_date, error=str(e))
