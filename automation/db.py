"""
db.py — the write-capable Supabase client.

The ONLY DB client in the project that writes. Constructed from `SUPABASE_URL` + the secret API key,
so it **bypasses RLS** (CLAUDE.md §3). Deliberately separate from `backend/database.py` (the app's
read-only publishable/anon client) and must never be imported by the backend, nor vice-versa.

Every write is an **upsert keyed on the table's real constraint** so re-running is idempotent — no
duplicates, no corruption. The supabase SDK is imported lazily inside `connect()` so `import
automation` works without it installed (e.g. for dry-run / typechecking).
"""
from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any, Optional, Sequence

if TYPE_CHECKING:
    from supabase import AsyncClient

    from .config import SupabaseConfig


# Conflict keys = the real unique constraints in supabase/database_SQL_defs.sql, centralized so every
# upsert site shares one source of truth.
CONFLICT_KEYS: dict[str, str] = {
    "securities": "security_id",
    "options_chain": "security_id,snapshot_date,expiry,option_type,strike",
}


class WriteClient:
    """Thin, typed wrapper over the service-role Supabase client (write side only)."""

    _BATCH = 500   # max rows per PostgREST request; larger sets are batched

    def __init__(self, config: "SupabaseConfig", *, dry_run: bool = False) -> None:
        self._config = config
        self._dry_run = dry_run
        self._client: Optional["AsyncClient"] = None

    # ── lifecycle ────────────────────────────────────────────────────────────────────────────
    async def connect(self) -> None:
        """Create the underlying secret-key AsyncClient (no-op in dry-run, so no creds are needed)."""
        if self._dry_run:
            self._client = None
            return
        self._config.validate()
        from supabase import acreate_client  # lazy: keeps `import automation` dependency-free
        self._client = await acreate_client(self._config.url, self._config.secret_key)

    async def close(self) -> None:
        """Release the client. The supabase AsyncClient has no explicit close today."""
        self._client = None

    # ── writes ───────────────────────────────────────────────────────────────────────────────
    async def _upsert(self, table: str, rows: Sequence[dict[str, Any]]) -> int:
        """
        Upsert `rows` into `table`, deduped on its CONFLICT_KEYS constraint. Returns rows written
        (0 in dry-run). Batches to stay under PostgREST request limits.
        """
        if not rows:
            return 0
        if self._dry_run or self._client is None:
            return 0
        conflict = CONFLICT_KEYS[table]
        written = 0
        for i in range(0, len(rows), self._BATCH):
            batch = list(rows[i:i + self._BATCH])
            try:
                await self._client.table(table).upsert(batch, on_conflict=conflict).execute()
            except Exception as e:  # noqa: BLE001 — add table context; don't leak raw PostgREST text
                raise RuntimeError(f"upsert into {table} failed: {e}") from e
            written += len(batch)
        return written

    async def upsert_options_chain(self, rows: Sequence[dict[str, Any]]) -> int:
        """Upsert a day's options snapshot. Unique (security_id, snapshot_date, expiry, option_type, strike)."""
        return await self._upsert("options_chain", rows)

    async def upsert_securities(self, rows: Sequence[dict[str, Any]]) -> int:
        """Upsert universe metadata. Keyed on security_id (PK)."""
        return await self._upsert("securities", rows)

    # ── reads (freshness signals + planning) ──────────────────────────────────────────────────
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
        Tickers absent from securities are omitted from the result (caller warns/skips).
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

    async def securities_detail(self) -> list[dict[str, Any]]:
        """All securities rows with the GICS/name columns — for diffing a metadata sync."""
        if self._client is None:
            return []
        resp = await self._client.table("securities").select(
            "security_id,ticker,gics_sector,gics_subindustry,company_name,sector_etf,active"
        ).execute()
        return resp.data or []
