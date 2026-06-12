"""
options_provider.py — options-chain data provider (CLAUDE.md §5).

A narrow `OptionsProvider` interface with a `YFinanceOptionsProvider` implementation. yfinance is the
chosen source (free, current-day, has bid/ask/last/volume/OI/IV); it gives **no greeks**, so `delta`
is computed in-house via `automation.black_scholes`.

Returns rows already shaped for the `options_chain` table (the app's columns are the contract, not
yfinance's). The `yfinance` import is lazy so `import automation` works without it installed.

Provider-agnostic by design: a future Polygon/Tradier provider implements the same protocol and the
rest of the import is unchanged.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Optional, Protocol

from ..black_scholes import bs_delta

if TYPE_CHECKING:
    from ..config import OptionsImportConfig


# ── logging ──────────────────────────────────────────────────────────────────────────────────────
# No package-wide logging exists yet; this provider configures one file logger lazily (on first use)
# so a failed import leaves a durable trace in the repo-root `log/` folder instead of vanishing.
_LOGGER_NAME = "automation.options_provider"


def _logger() -> logging.Logger:
    """Module logger writing to `<repo-root>/log/options_import.log` (configured once, lazily)."""
    log = logging.getLogger(_LOGGER_NAME)
    if not log.handlers:
        from ..config import REPO_ROOT  # lazy: avoids an import-time dependency / side effects
        log_dir = REPO_ROOT / "log"
        log_dir.mkdir(exist_ok=True)
        handler = logging.FileHandler(log_dir / "options_import.log", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        log.addHandler(handler)
        log.setLevel(logging.INFO)
        log.propagate = False  # don't double-log if the host app also configures the root logger
    return log


class SpotUnavailableError(RuntimeError):
    """Underlying spot couldn't be fetched, so a scoped chain import can't proceed.

    Subclasses RuntimeError so the per-security import loop (which catches Exception) records it as a
    handled per-ticker error rather than letting it sink a multi-ticker run.
    """


@dataclass(frozen=True)
class OptionsScope:
    """Strike-band scoping for the fetch (keeps row counts bounded)."""

    strike_band_pct: float = 0.30          # keep strikes within ±this fraction of spot
    max_strikes_per_side: Optional[int] = None  # optional hard cap of strikes each side of spot


class OptionsProvider(Protocol):
    """Interface the import core depends on."""

    def list_expiries(self, ticker: str) -> list[date]:
        """All available expiries for the underlying (future + past as the source reports them)."""
        ...

    def fetch_spot(self, ticker: str) -> Optional[float]:
        """Latest underlying price (for strike-band scoping + BS delta)."""
        ...

    def latest_session_date(self) -> Optional[date]:
        """The most recent trading-session date the source's data belongs to (stamps snapshot_date)."""
        ...

    def fetch_chain(
        self, ticker: str, expiries: list[date], *,
        snapshot_date: date, security_id: int, scope: "OptionsScope",
        spot: Optional[float] = None, risk_free_rate: float = 0.045,
    ) -> list[dict[str, Any]]:
        """Fetch + normalize the chain for the given expiries → options_chain rows."""
        ...


def _to_float(val: Any) -> Optional[float]:
    """Coerce a cell to float; NaN/None/blank → None (so missing data becomes a NULL column)."""
    if val is None:
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    # NaN != NaN
    if f != f:
        return None
    return f


def _to_int(val: Any) -> Optional[int]:
    f = _to_float(val)
    return int(f) if f is not None else None


def _chain_is_empty(chain: Any) -> bool:
    """True when a yfinance option_chain carries neither calls nor puts.

    yfinance intermittently returns empty frames on a transient hiccup, so `_retry` treats this as a
    retryable 'empty' (mirrors the per-frame emptiness check in `fetch_chain`).
    """
    if chain is None:
        return True

    def _empty(df: Any) -> bool:
        return df is None or getattr(df, "empty", True)

    return _empty(getattr(chain, "calls", None)) and _empty(getattr(chain, "puts", None))


class YFinanceOptionsProvider:
    """yfinance implementation of OptionsProvider (CLAUDE.md §5)."""

    def __init__(self, config: "OptionsImportConfig") -> None:
        self._config = config

    # ── lazy client ──────────────────────────────────────────────────────────────────────────
    def _ticker(self, ticker: str) -> Any:
        import yfinance as yf  # lazy: keeps `import automation` dependency-free
        return yf.Ticker(ticker)

    def _retry(self, fn, what: str, *, is_empty=None):
        """Run `fn` with exponential backoff, retrying transient failures.

        yfinance both raises (rate-limit / network errors) **and** intermittently returns empty
        results, so we retry on either: an exception, or — when an `is_empty` predicate is given — a
        result the caller considers empty.

        On exhaustion: re-raise if the last attempt raised; otherwise return the last (possibly empty)
        result and let the caller decide what an empty means (a ticker with no options, no quote, …).
        """
        last_exc: Optional[BaseException] = None
        result: Any = None
        for attempt in range(self._config.max_retries):
            try:
                result = fn()
            except Exception as e:  # noqa: BLE001 — yfinance raises a variety of network errors
                last_exc = e
            else:
                last_exc = None
                if is_empty is None or not is_empty(result):
                    return result  # got a usable result
                # empty result — treat like a transient failure and back off / retry
            if attempt < self._config.max_retries - 1:
                time.sleep(self._config.backoff_base_seconds * (2 ** attempt))
        if last_exc is not None:
            raise RuntimeError(f"yfinance {what} failed after {self._config.max_retries} attempts: {last_exc}")
        return result

    # ── reads ────────────────────────────────────────────────────────────────────────────────
    def list_expiries(self, ticker: str) -> list[date]:
        """Parse Ticker.options ('YYYY-MM-DD' strings) → date list."""
        raw = self._retry(
            lambda: self._ticker(ticker).options,
            f"{ticker}.options",
            is_empty=lambda r: not r,  # None / empty tuple → retry (yfinance occasionally returns ())
        )
        out: list[date] = []
        for s in (raw or ()):
            try:
                out.append(datetime.strptime(s, "%Y-%m-%d").date())
            except (TypeError, ValueError):
                continue
        return out

    def fetch_spot(self, ticker: str) -> Optional[float]:
        """Latest price via fast_info, with a history() fallback."""
        t = self._ticker(ticker)

        def _spot() -> Optional[float]:
            fi = getattr(t, "fast_info", None)
            if fi is not None:
                for key in ("last_price", "lastPrice", "last_close", "previous_close"):
                    try:
                        v = fi[key] if isinstance(fi, dict) else getattr(fi, key, None)
                    except (KeyError, TypeError):
                        v = None
                    f = _to_float(v)
                    if f is not None and f > 0:  # 0.0 spot price is useless, but we can guard this explicitly
                        return f
            hist = t.history(period="1d")
            if hist is not None and not hist.empty and "Close" in hist:
                return _to_float(hist["Close"].iloc[-1])
            return None

        return self._retry(_spot, f"{ticker} spot", is_empty=lambda r: r is None)

    def latest_session_date(self, proxy: str = "SPY") -> Optional[date]:
        """
        The most recent trading session, from a liquid proxy's last daily bar.

        Self-correcting for time-of-day / weekends / holidays: yfinance only has a daily bar for a
        session that has *begun*, so the last bar's date is the session the current snapshot belongs
        to — intraday/after-close → today; overnight/weekend/holiday → the last real session. This is
        what stamps `snapshot_date`, so a midnight run doesn't mislabel yesterday's close as today.
        """
        def _fetch() -> Optional[date]:
            hist = self._ticker(proxy).history(period="5d")  # 5d spans long weekends/holidays
            if hist is None or hist.empty:
                return None
            ts = hist.index[-1]
            return ts.date() if hasattr(ts, "date") else None

        return self._retry(_fetch, f"{proxy} latest session", is_empty=lambda r: r is None)

    # ── chain fetch + normalize ────────────────────────────────────────────────────────────────
    def fetch_chain(
        self, ticker: str, expiries: list[date], *,
        snapshot_date: date, security_id: int, scope: "OptionsScope",
        spot: Optional[float] = None, risk_free_rate: float = 0.045,
    ) -> list[dict[str, Any]]:
        """
        Fetch each expiry's calls/puts, filter strikes to the band, normalize to options_chain rows,
        and fill `delta` via Black-Scholes from the underlying spot.
        """
        if spot is None:
            # Spot drives BOTH strike-band scoping and the max-strikes cap; without it the fetch would
            # silently import every strike of every expiry (each with a None delta). Fail the chain
            # import loudly instead — the per-security loop records it as a handled per-ticker error.
            _logger().warning(
                "%s: spot unavailable for %s — failing chain import for %d expiry(ies) "
                "(would otherwise import an unbounded, delta-less chain)",
                ticker, snapshot_date.isoformat(), len(expiries),
            )
            raise SpotUnavailableError(
                f"{ticker}: spot unavailable for {snapshot_date.isoformat()}; "
                f"aborting options-chain import to avoid an unbounded, unscoped fetch"
            )

        # spot is guaranteed non-None past this point — scoping and delta both rely on it.
        lo = hi = None
        if scope.strike_band_pct:
            lo = spot * (1.0 - scope.strike_band_pct)
            hi = spot * (1.0 + scope.strike_band_pct)

        t = self._ticker(ticker)
        rows: list[dict[str, Any]] = []

        for expiry in expiries:
            chain = self._retry(
                lambda e=expiry: t.option_chain(e.isoformat()),
                f"{ticker}.option_chain({expiry})",
                is_empty=_chain_is_empty,
            )
            for df, opt_type in ((getattr(chain, "calls", None), "C"),
                                 (getattr(chain, "puts", None), "P")):
                if df is None or getattr(df, "empty", True):
                    continue
                dte_days = (expiry - snapshot_date).days
                for rec in df.to_dict("records"):
                    strike = _to_float(rec.get("strike"))
                    if strike is None:
                        continue
                    if lo is not None and not (lo <= strike <= hi):
                        continue

                    bid = _to_float(rec.get("bid"))
                    ask = _to_float(rec.get("ask"))
                    mid = (bid + ask) / 2.0 if (bid and ask and bid > 0 and ask > 0) else None
                    iv = _to_float(rec.get("impliedVolatility"))
                    iv = iv if (iv and iv > 0) else None

                    rows.append({
                        "security_id": security_id,
                        "snapshot_date": snapshot_date.isoformat(),
                        "expiry": expiry.isoformat(),
                        "strike": strike,
                        "option_type": opt_type,
                        "bid": bid,
                        "ask": ask,
                        "mid": mid,
                        "last": _to_float(rec.get("lastPrice")),
                        "volume": _to_int(rec.get("volume")),
                        "open_interest": _to_int(rec.get("openInterest")),
                        "iv": iv,
                        "delta": bs_delta(spot, strike, dte_days, iv, opt_type, r=risk_free_rate),
                    })

        # Optional hard cap: nearest N strikes each side of spot, per (expiry, option_type).
        if scope.max_strikes_per_side:
            rows = _cap_strikes_per_side(rows, spot, scope.max_strikes_per_side)

        return rows


def _cap_strikes_per_side(rows: list[dict[str, Any]], spot: float, n: int) -> list[dict[str, Any]]:
    """Keep only the n nearest strikes below and n at/above spot, per (expiry, option_type)."""
    from collections import defaultdict

    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        groups[(r["expiry"], r["option_type"])].append(r)

    kept: list[dict[str, Any]] = []
    for group in groups.values():
        below = sorted((r for r in group if r["strike"] < spot),
                       key=lambda r: spot - r["strike"])[:n]
        atabove = sorted((r for r in group if r["strike"] >= spot),
                         key=lambda r: r["strike"] - spot)[:n]
        kept.extend(below + atabove)
    return kept
