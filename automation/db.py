"""
db.py — the write-capable Supabase client for the pipeline.

This is the ONLY DB client in the project that writes. It is constructed from `SUPABASE_URL` +
`SUPABASE_SERVICE_ROLE_KEY`, so it **bypasses RLS** (PLAN §6). It is deliberately separate from
`backend/database.py` (the app's read-only publishable/anon client) and must never be imported by
the backend, nor vice-versa.

Every write is an **upsert keyed on the table's real constraint** (PLAN §4.1) so re-running a day is
idempotent — no duplicates, no corruption. The two tables lacking a natural unique key
(`model_runs`, `ai_overview`) are handled per PLAN §4.2 (recommended migration + in-app fallback).

The supabase SDK is imported lazily inside `connect()` so `import automation` works without it
installed (e.g. for `--dry-run` and typechecking).
"""
from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any, Optional, Sequence

if TYPE_CHECKING:
    from supabase import AsyncClient

    from .config import SupabaseConfig
    from .logging_utils import StageReport


# ── Conflict keys per table (the real unique constraints in supabase/database_SQL_defs.sql) ──────
# Centralized so every upsert site references the same source of truth (PLAN §4.1).
CONFLICT_KEYS: dict[str, str] = {
    "securities": "security_id",
    "prices_history": "security_id,date",
    "options_chain": "security_id,snapshot_date,expiry,option_type,strike",
    "volatility_history": "security_id,date",
    "shap_snapshot": "security_id,retrain_date,horizon",
    # ⚠ model_runs & ai_overview have NO natural unique key today — see PLAN §4.2.
    # "model_runs": "run_date,model_version",                    # requires a migration
    # "ai_overview": "security_id,model_ver,prompt_ver,content_hash",  # requires a migration
}


class WriteClient:
    """Thin, typed wrapper over the service-role Supabase client (write side only)."""

    def __init__(self, config: "SupabaseConfig", *, dry_run: bool = False) -> None:
        self._config = config
        self._dry_run = dry_run
        self._client: Optional["AsyncClient"] = None

    # Max rows per PostgREST request — batch larger sets to stay well under limits.
    _BATCH = 500

    # ── lifecycle ────────────────────────────────────────────────────────────────────────────
    async def connect(self) -> None:
        """
        Create the underlying service-role AsyncClient (no-op in dry-run, so no creds are needed).
        """
        if self._dry_run:
            self._client = None
            return
        self._config.validate()
        from supabase import acreate_client  # lazy: keeps `import automation` dependency-free
        self._client = await acreate_client(self._config.url, self._config.secret_key)

    async def close(self) -> None:
        """Release the client/session. The supabase AsyncClient has no explicit close today."""
        self._client = None

    # ── generic upsert ───────────────────────────────────────────────────────────────────────
    async def _upsert(self, table: str, rows: Sequence[dict[str, Any]],
                      *, on_conflict: Optional[str] = None) -> int:
        """
        Upsert `rows` into `table`, deduped on `on_conflict` (defaults to CONFLICT_KEYS[table]).
        Returns the number of rows written (0 in dry-run). Batches to stay under request limits.
        """
        if not rows:
            return 0
        conflict = on_conflict or CONFLICT_KEYS[table]
        if self._dry_run or self._client is None:
            return 0
        written = 0
        for i in range(0, len(rows), self._BATCH):
            batch = list(rows[i:i + self._BATCH])
            try:
                await self._client.table(table).upsert(batch, on_conflict=conflict).execute()
            except Exception as e:  # noqa: BLE001
                # Keep table context for our logs; callers decide isolation. (Don't surface raw
                # PostgREST text to any external client — backend convention, PLAN §6.)
                raise RuntimeError(f"upsert into {table} failed: {e}") from e
            written += len(batch)
        return written

    # ── per-table typed helpers (keyed per PLAN §4.1) ─────────────────────────────────────────
    async def upsert_securities(self, rows: Sequence[dict[str, Any]]) -> int:
        """Upsert universe metadata. Keyed on security_id (PK). Rare — on universe change (PLAN §10)."""
        return await self._upsert("securities", rows)

    async def all_securities(self) -> list[dict[str, Any]]:
        """All securities rows (id, ticker, active) — for membership/universe planning."""
        if self._client is None:
            return []
        resp = await self._client.table("securities").select("security_id,ticker,active").execute()
        return resp.data or []

    async def securities_detail(self) -> list[dict[str, Any]]:
        """All securities rows with the GICS/name columns — for diffing a metadata sync."""
        if self._client is None:
            return []
        resp = await self._client.table("securities").select(
            "security_id,ticker,gics_sector,gics_subindustry,company_name,sector_etf,active"
        ).execute()
        return resp.data or []

    async def upsert_prices(self, rows: Sequence[dict[str, Any]]) -> int:
        """Append/upsert OHLCV bars. PK (security_id, date). Append-only in practice (PLAN §3.1)."""
        raise NotImplementedError

    async def upsert_options_chain(self, rows: Sequence[dict[str, Any]]) -> int:
        """Upsert a day's options snapshot. Unique (security_id, snapshot_date, expiry, option_type, strike)."""
        return await self._upsert("options_chain", rows)

    async def insert_model_run(self, row: dict[str, Any]) -> int:
        """
        Insert/locate the single `model_runs` row for this run and return its `id` (for the FK on
        volatility_history). ⚠ model_runs has no natural unique key (PLAN §4.2):

        TODO:
          - if the recommended unique (run_date, model_version) migration is applied → upsert + return id
          - else (fallback): SELECT existing (run_date, model_version); if present return its id; else insert
        """
        raise NotImplementedError("TODO(PLAN §4.2): idempotent model_runs insert returning id")

    async def upsert_volatility_history(self, rows: Sequence[dict[str, Any]]) -> int:
        """Upsert model output rows. PK (security_id, date). Each carries model_run_id (PLAN §7.4)."""
        raise NotImplementedError

    async def upsert_shap_snapshot(self, rows: Sequence[dict[str, Any]]) -> int:
        """Upsert SHAP snapshots. PK (security_id, retrain_date, horizon) (PLAN §7.4)."""
        raise NotImplementedError

    async def insert_ai_overview(self, row: dict[str, Any]) -> int:
        """
        Insert an AI overview, deduped in-app by (security_id, model_ver, prompt_ver) + content_hash
        (PLAN §8.2). ⚠ ai_overview has no natural unique key today (PLAN §4.2).

        TODO:
          - skip if an equivalent row already exists (see overview_exists)
          - else insert; if the recommended content_hash unique is added, switch to upsert
        """
        raise NotImplementedError("TODO(PLAN §8.2): dedup-aware ai_overview insert")

    async def upsert_pipeline_run(self, run_date: date, report: "StageReport") -> int:
        """Upsert the optional observability ledger row, unique (run_date, stage) (PLAN §3.3)."""
        raise NotImplementedError

    # ── freshness reads (DB-derived incrementality signals — PLAN §3.1) ───────────────────────
    # These read the DB to decide what's stale. Kept here so all SQL lives behind the write client.
    async def latest_price_date(self, security_ids: Sequence[int]) -> dict[int, Optional[date]]:
        """MAX(date) in prices_history per security — the append cursor for fetch_prices."""
        raise NotImplementedError

    async def options_snapshot_exists(self, security_ids: Sequence[int],
                                      snapshot_date: date) -> dict[int, bool]:
        """Whether today's options_chain snapshot already exists per security (skip-if-done)."""
        ids = list(security_ids)
        if not ids or self._client is None:
            return {sid: False for sid in ids}
        resp = await (
            self._client.table("options_chain")
            .select("security_id")
            .in_("security_id", ids)
            .eq("snapshot_date", snapshot_date.isoformat())
            .execute()
        )
        present = {row["security_id"] for row in (resp.data or [])}
        return {sid: sid in present for sid in ids}

    async def resolve_security_ids(self, tickers: Sequence[str]) -> dict[str, int]:
        """
        Map ticker → security_id from the securities table (the options_chain FK target).
        Tickers absent from securities are simply omitted from the result (caller warns/skips).
        """
        syms = [t.upper() for t in tickers]
        if not syms or self._client is None:
            return {}
        resp = await (
            self._client.table("securities")
            .select("security_id,ticker")
            .in_("ticker", syms)
            .execute()
        )
        return {row["ticker"].upper(): row["security_id"] for row in (resp.data or [])}

    async def model_run_exists(self, run_date: date, model_version: str) -> bool:
        """Whether the model already ran today for this version (skip-if-done — PLAN §3.1)."""
        raise NotImplementedError

    async def volatility_rows_for_date(self, run_date: date) -> set[int]:
        """security_ids that already have a volatility_history row for run_date (upload skip / overview trigger)."""
        raise NotImplementedError

    async def overview_exists(self, security_id: int, model_ver: str, prompt_ver: str,
                              content_hash: str) -> bool:
        """Whether an equivalent ai_overview already exists (content-hash cache — PLAN §8.2)."""
        raise NotImplementedError

    async def active_universe(self) -> list[dict[str, Any]]:
        """securities rows where active=true — the run's universe (PLAN §10)."""
        if self._client is None:
            return []
        resp = await (
            self._client.table("securities")
            .select("security_id,ticker,gics_sector,sector_etf,min_history_date")
            .eq("active", True)
            .order("ticker")
            .execute()
        )
        return resp.data or []
