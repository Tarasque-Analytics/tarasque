"""
market_data.py — STOCK-BARS provider abstraction (PLAN §5; prices → prices_history).

A narrow `MarketDataProvider` protocol with an `AlpacaProvider` implementation for **stock bars**.
Rate-limit / backoff / bounded-concurrency live HERE so the prices stage inherits consistent
throttling.

⚠ **Options moved off Alpaca.** The options chain is now sourced from **yfinance** — see
`automation/providers/options_provider.py` and `OPTIONS_IMPORT_PLAN.md` (Alpaca has no open interest
or per-contract volume). The `OptionsScope` / `fetch_options_snapshot` members below are **superseded
stubs** kept only so the prices scaffold still type-checks; do not implement them here.

Rows are returned already shaped for the DB tables (the stages just upsert them), so the app's column
names are the contract — not the vendor's.

The `alpaca` SDK is imported lazily inside methods so `import automation` works without it installed.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Any, Optional, Protocol, Sequence

if TYPE_CHECKING:
    from ..config import AlpacaConfig


@dataclass(frozen=True)
class OptionsScope:
    """Cost-scoping for the (heaviest) options fetch (PLAN §4.3)."""

    max_dte: int                  # ignore expiries beyond this many days out
    strike_band_pct: float        # keep strikes within ±this fraction of spot
    # TODO(PLAN §7.5.4): align the expiry set with the model's IV term points (30/60/91/182d).


class MarketDataProvider(Protocol):
    """The interface stages depend on (so a second/alternate provider can drop in)."""

    async def fetch_bars(
        self, symbols: Sequence[str], *, start: date, end: date,
    ) -> dict[str, list[dict[str, Any]]]:
        """
        Daily OHLCV bars per symbol, shaped for prices_history
        ({date, open, high, low, close, adj_close, volume}). PLAN §3.1 (append window = start..end).
        """
        ...

    async def fetch_options_snapshot(
        self, symbol: str, *, snapshot_date: date, scope: "OptionsScope",
    ) -> list[dict[str, Any]]:
        """
        One day's options chain for `symbol`, shaped for options_chain
        ({expiry, strike, option_type, bid, ask, mid, last, volume, open_interest, iv, delta}). PLAN §4.3.
        """
        ...


class AlpacaProvider:
    """Alpaca implementation of MarketDataProvider (PLAN §1, §4.3, §5)."""

    def __init__(self, config: "AlpacaConfig") -> None:
        self._config = config
        self._stock_client: Optional[Any] = None
        self._option_client: Optional[Any] = None

    # ── lazy clients (mirror model/pipeline/data_loader.py's deferred-import pattern) ───────────
    @property
    def stock_client(self) -> Any:
        """TODO(PLAN §1): from alpaca.data.historical import StockHistoricalDataClient(api_key, secret)."""
        raise NotImplementedError

    @property
    def option_client(self) -> Any:
        """
        TODO(PLAN §4.3): from alpaca.data.historical.option import OptionHistoricalDataClient.
        Requires an Alpaca plan with options (OPRA) market data — confirm coverage (PLAN §13).
        """
        raise NotImplementedError

    # ── fetches ────────────────────────────────────────────────────────────────────────────────
    async def fetch_bars(
        self, symbols: Sequence[str], *, start: date, end: date,
    ) -> dict[str, list[dict[str, Any]]]:
        """
        TODO(PLAN §3.1, §5):
          - batch multi-symbol StockBarsRequest (TimeFrame.Day, adjustment=ALL, feed=config.feed)
          - reshape to prices_history rows; compute adj_close as appropriate
          - retry/backoff on 429 (config.max_retries, backoff_base_seconds)
        """
        raise NotImplementedError

    async def fetch_options_snapshot(
        self, symbol: str, *, snapshot_date: date, scope: "OptionsScope",
    ) -> list[dict[str, Any]]:
        """
        TODO(PLAN §4.3, §5):
          - request the option chain for `symbol`, filtered to DTE ≤ scope.max_dte and strikes within
            ±scope.strike_band_pct of spot (minimize the heaviest call)
          - reshape to options_chain rows (option_type as 'C'/'P'; mid from bid/ask if absent;
            iv/delta as available from the greeks/snapshot)
          - retry/backoff on throttling
        """
        raise NotImplementedError
