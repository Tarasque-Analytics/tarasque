"""
db.py — Supabase client wrapper for the model-side ETL.

One class — SupabaseClient — that wraps supabase-py with:
  - Connection from .env (URL + SERVICE_ROLE_KEY)
  - Chunked batch upserts to stay within request size limits
  - Idempotency via on_conflict matching our unique constraints
  - Schema verification helper (verify_schema) for pre-flight checks
  - Retry/backoff on transient failures

Usage:

    from model.pipeline.db import SupabaseClient

    db = SupabaseClient()
    db.verify_schema()
    run_id = db.upsert_model_run(manifest_dict)
    db.upsert_securities(securities_df)
    db.upsert_volatility_history(vol_df, run_id=run_id)
    db.upsert_prices_history(prices_df)

All upsert methods are idempotent: rerunning never produces duplicates
provided the schema migration (001_supabase_schema_fixes.sql) has landed.
"""
from __future__ import annotations
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from dotenv import load_dotenv


# Load env from model/.env (same pattern as the rest of the pipeline)
_ENV_PATH = Path(__file__).resolve().parent.parent / '.env'
load_dotenv(dotenv_path=_ENV_PATH)


# Default chunk size for batch upserts. Supabase free tier limits requests
# to ~10 MB, and our widest row (volatility_history) is ~500 bytes, so 500
# rows/chunk = ~250 KB — well within limits, fast enough for daily appends.
DEFAULT_CHUNK_SIZE = 500

# Columns we use to identify each table's natural key — the basis for
# idempotent upserts (PostgREST's on_conflict parameter).
TABLE_CONFLICT_COLUMNS = {
    'securities':         'security_id',
    'model_runs':         'id',  # surrogate, handled separately
    'volatility_history': 'security_id,date',
    'prices_history':     'security_id,date',
    'options_chain':      'security_id,snapshot_date,expiry,strike,option_type',
    'ai_overview':        'security_id,date,model_ver,prompt_ver',
    'shap_snapshot':      'security_id,retrain_date,horizon,snapshot_date',
    'event_history':      'security_id,event_date,event_type',  # natural-key UNIQUE per migration 004
    'macro_calendar':     'date,event_type',
}

# Columns the model writes for each table. Used by verify_schema() to
# confirm the DB-side schema matches. If you add a column on the model
# side, add it here too — that surfaces missing-column errors immediately.
EXPECTED_COLUMNS = {
    'securities': [
        'security_id', 'ticker', 'gics_sector', 'gics_industry', 'sector_etf',
        'active', 'excluded_reason', 'min_history_date', 'last_model_run',
    ],
    'model_runs': [
        'id', 'run_date', 'model_version', 'spec_hash', 'n_tickers',
        'horizons', 'notes', 'created_at',
    ],
    'volatility_history': [
        'security_id', 'date', 'rv', 'ewma_vol',
        'iv_atm_30d', 'iv_atm_60d', 'iv_atm_91d', 'iv_atm_182d',
        'vrp_wedge', 'vrp_wedge_ewma_21d',
        'pfv_21', 'pfv_63', 'pfv_126',
        'pfv_q15_21', 'pfv_q15_63', 'pfv_q15_126',
        'pfv_cal_21', 'pfv_cal_63', 'pfv_cal_126',
        'fwd_premium_21d', 'fwd_premium_63d', 'fwd_premium_126d',
        'fwd_premium_21_to_63d', 'fwd_premium_63_to_126d',
        'fwd_premium_ewma_21d', 'fwd_premium_ewma_63d', 'fwd_premium_ewma_126d',
        # Regime betas — Macro page 2x2 Regime Modeler (added 2026-06).
        'beta_mkt_252d',
        'beta_mz_h21', 'beta_mz_h63', 'beta_mz_h126',
        'mz_alpha_h21', 'mz_alpha_h63', 'mz_alpha_h126',
        'next_earnings_date', 'days_to_earnings',
        'next_dividend_date', 'days_to_dividend',
        'model_run_id',
    ],
    'prices_history': [
        'security_id', 'date', 'open', 'high', 'low', 'close',
        'adj_close', 'volume',
    ],
    'ai_overview': [
        # Matches the lead-dev redesign (no `date`, no risk_tier/input_hash/
        # token-count/flagged_reason cols; PK is (id, generated_at)).
        # Model side does not write here — this list is just for verify_schema.
        # If/when the LLM pipeline lands, add its columns here.
        'id', 'security_id', 'model_ver', 'prompt_ver',
        'headline', 'content', 'generated_at', 'flagged',
    ],
    'shap_snapshot': [
        'security_id', 'retrain_date', 'horizon', 'snapshot_date',
        'base_value', 'predicted_value', 'feature_data',
    ],
    'event_history': [
        'security_id', 'event_date', 'title', 'description',
        'event_type', 'scope', 'source',
        # event_id is BIGINT GENERATED ALWAYS AS IDENTITY — DB assigns, not us
    ],
    'macro_calendar': [
        'date', 'event_type', 'event_date', 'days_to_event',
    ],
    'options_chain': [
        'id', 'security_id', 'snapshot_date', 'expiry', 'strike',
        'option_type', 'bid', 'ask', 'mid', 'last',
        'volume', 'open_interest', 'iv', 'delta',
    ],
}


class SupabaseConfigError(RuntimeError):
    """Raised when credentials are missing or invalid."""


class SchemaMismatchError(RuntimeError):
    """Raised when verify_schema() finds missing tables or columns."""


class SupabaseClient:
    """Thin wrapper around supabase-py for the model-side ETL.

    Connects via SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY from model/.env.
    Service role key bypasses RLS — required for writes.

    Parameters
    ----------
    dry_run : bool, default False
        When True, logs all operations without sending them to Supabase.
        Useful for CI and pre-flight validation.
    chunk_size : int, default 500
        Rows per batch upsert. Lower if hitting payload limits.
    """

    def __init__(self, dry_run: bool = False, chunk_size: int = DEFAULT_CHUNK_SIZE):
        self.dry_run = dry_run
        self.chunk_size = chunk_size
        self._client = None

        if not dry_run:
            self._init_client()

    # ─────────────────────────────────────────────────────────────────────
    # Connection
    # ─────────────────────────────────────────────────────────────────────

    def _init_client(self):
        url = os.getenv('SUPABASE_URL', '').strip()
        key = os.getenv('SUPABASE_SERVICE_ROLE_KEY', '').strip()

        if not url or url.startswith('https://YOUR_'):
            raise SupabaseConfigError(
                'SUPABASE_URL not configured in model/.env. '
                'Add SUPABASE_URL=https://<project>.supabase.co'
            )
        if not key or key.startswith('YOUR_'):
            raise SupabaseConfigError(
                'SUPABASE_SERVICE_ROLE_KEY not configured in model/.env. '
                'Use the service_role key (not anon) for write access.'
            )

        try:
            from supabase import create_client
        except ImportError:
            raise SupabaseConfigError(
                'supabase-py not installed. Run: pip install supabase python-dotenv'
            )

        self._client = create_client(url, key)
        print(f'[db] Connected to {url}')

    @property
    def client(self):
        if self._client is None and not self.dry_run:
            self._init_client()
        return self._client

    # ─────────────────────────────────────────────────────────────────────
    # Pre-flight checks
    # ─────────────────────────────────────────────────────────────────────

    def verify_schema(self) -> Dict[str, List[str]]:
        """Verify all expected tables and columns exist.

        Returns dict mapping table_name -> list of missing columns.
        Empty dict means everything matches. Raises SchemaMismatchError if
        any table is missing entirely.

        In dry_run mode, prints what would be verified without contacting DB.
        """
        if self.dry_run:
            print('[db] dry-run: skipping live schema verification')
            print(f'[db] would verify {len(EXPECTED_COLUMNS)} tables, '
                  f'{sum(len(c) for c in EXPECTED_COLUMNS.values())} columns total')
            return {}

        missing = {}
        for table, expected_cols in EXPECTED_COLUMNS.items():
            try:
                # SELECT 0 rows but with the columns we expect — if any column
                # is missing, PostgREST returns a 400 with the column name.
                # SELECT * is enough — supabase-py returns the row schema.
                self.client.table(table).select('*').limit(0).execute()
                # If the SELECT * succeeded, the table exists. We can't easily
                # introspect columns from supabase-py without raw SQL, so we
                # do a best-effort check by trying to select each column.
                table_missing = []
                for col in expected_cols:
                    try:
                        self.client.table(table).select(col).limit(0).execute()
                    except Exception as e:
                        if 'column' in str(e).lower() or 'does not exist' in str(e).lower():
                            table_missing.append(col)
                if table_missing:
                    missing[table] = table_missing
            except Exception as e:
                raise SchemaMismatchError(
                    f'Table {table!r} not found or inaccessible: {e}\n'
                    f'Apply migration 001_supabase_schema_fixes.sql first.'
                )

        if missing:
            print('[db] schema gaps detected:')
            for table, cols in missing.items():
                print(f'  {table}: missing columns {cols}')
        else:
            print('[db] schema verified — all expected tables and columns present')

        return missing

    # ─────────────────────────────────────────────────────────────────────
    # Upsert primitives
    # ─────────────────────────────────────────────────────────────────────

    def _df_to_records(self, df: pd.DataFrame) -> List[Dict[str, Any]]:
        """Convert DataFrame to JSON-serializable records.

        Handles: pandas Timestamps -> ISO strings, NaN -> None,
        numpy types -> Python primitives. Required because supabase-py
        sends JSON over HTTP.
        """
        # Replace NaN with None (JSON null) via where; works on all dtypes
        clean = df.where(pd.notna(df), None)
        records = clean.to_dict(orient='records')

        # Coerce any remaining numpy types and datetimes to JSON-safe
        for r in records:
            for k, v in list(r.items()):
                # pd.NaT is its own type (NaTType) — catch it BEFORE the
                # Timestamp/datetime64 check since it's not an instance of those
                if v is pd.NaT or (
                    type(v).__name__ == 'NaTType'
                ):
                    r[k] = None
                elif isinstance(v, (pd.Timestamp, np.datetime64)):
                    if pd.isna(v):
                        r[k] = None
                    else:
                        r[k] = pd.Timestamp(v).strftime('%Y-%m-%d')
                elif isinstance(v, np.integer):
                    r[k] = int(v)
                elif isinstance(v, np.floating):
                    r[k] = None if np.isnan(v) else float(v)
                elif isinstance(v, np.bool_):
                    r[k] = bool(v)
                elif isinstance(v, float) and np.isnan(v):
                    r[k] = None
                # Defensive catch-all for any other pd-NA flavor
                elif v is not None and v is not False and v is not True:
                    try:
                        if pd.isna(v):
                            r[k] = None
                    except (TypeError, ValueError):
                        pass  # not a scalar — leave alone
        return records

    def _upsert_chunked(
        self,
        table: str,
        df: pd.DataFrame,
        on_conflict: Optional[str] = None,
        retries: int = 3,
    ) -> int:
        """Chunked upsert to keep request size manageable.

        Returns total rows upserted.
        """
        if df.empty:
            print(f'[db] {table}: 0 rows, skipping')
            return 0

        on_conflict = on_conflict or TABLE_CONFLICT_COLUMNS.get(table)
        records = self._df_to_records(df)
        total = 0

        for i in range(0, len(records), self.chunk_size):
            chunk = records[i:i + self.chunk_size]

            if self.dry_run:
                print(f'[db] dry-run: would upsert {len(chunk)} rows '
                      f'to {table} (on_conflict={on_conflict})')
                total += len(chunk)
                continue

            for attempt in range(retries):
                try:
                    if on_conflict:
                        self.client.table(table).upsert(
                            chunk, on_conflict=on_conflict
                        ).execute()
                    else:
                        self.client.table(table).insert(chunk).execute()
                    total += len(chunk)
                    break
                except Exception as e:
                    if attempt < retries - 1:
                        backoff = 2 ** attempt
                        print(f'[db] {table} chunk {i}: {e}; retry in {backoff}s')
                        time.sleep(backoff)
                    else:
                        raise

        print(f'[db] {table}: upserted {total:,} rows')
        return total

    # ─────────────────────────────────────────────────────────────────────
    # Public upsert API — one method per table
    # ─────────────────────────────────────────────────────────────────────

    def upsert_securities(self, df: pd.DataFrame) -> int:
        return self._upsert_chunked('securities', df)

    def upsert_model_run(self, manifest: Dict[str, Any]) -> Optional[int]:
        """Insert a single model_runs row, return its surrogate id.

        Manifest fields (run_date, model_version, spec_hash, n_tickers,
        horizons, notes) come from the model_run_manifest.json.

        Returns the inserted id, or None in dry_run mode.
        """
        if self.dry_run:
            print(f'[db] dry-run: would insert model_runs row: {manifest}')
            return None

        row = {
            'run_date':      manifest.get('run_date'),
            'model_version': manifest.get('model_version'),
            'spec_hash':     manifest.get('spec_hash'),
            'n_tickers':     manifest.get('n_tickers'),
            'horizons':      manifest.get('horizons'),
            'notes':         manifest.get('notes'),
        }
        result = self.client.table('model_runs').insert(row).execute()
        run_id = result.data[0]['id'] if result.data else None
        print(f'[db] model_runs: inserted run_id={run_id}')
        return run_id

    def upsert_volatility_history(self, df: pd.DataFrame, run_id: Optional[int] = None) -> int:
        """Upsert volatility_history rows. Sets model_run_id if provided."""
        if run_id is not None and 'model_run_id' not in df.columns:
            df = df.copy()
            df['model_run_id'] = run_id
        elif run_id is not None:
            df = df.copy()
            df['model_run_id'] = df['model_run_id'].fillna(run_id)
        return self._upsert_chunked('volatility_history', df)

    def upsert_prices_history(self, df: pd.DataFrame) -> int:
        return self._upsert_chunked('prices_history', df)

    def upsert_options_chain(self, df: pd.DataFrame) -> int:
        return self._upsert_chunked('options_chain', df)

    def upsert_ai_overview(self, df: pd.DataFrame) -> int:
        return self._upsert_chunked('ai_overview', df)

    def upsert_shap_snapshots(self, df: pd.DataFrame) -> int:
        return self._upsert_chunked('shap_snapshot', df)

    def upsert_event_history(self, df: pd.DataFrame) -> int:
        """Upsert per-security event rows. Idempotent via natural-key UNIQUE
        constraint (security_id, event_date, event_type) added in migration 004.

        Rows without a resolved security_id are dropped with a warning — these
        usually mean a ticker that's not in the securities table yet.

        Also dedupes within-batch on the natural key — Compustat earnings can
        have multiple datadate entries producing the same rdq per ticker,
        which Postgres rejects with "ON CONFLICT DO UPDATE command cannot
        affect row a second time".
        """
        if df.empty:
            return 0
        unmapped = df['security_id'].isna().sum() if 'security_id' in df.columns else 0
        if unmapped > 0:
            print(f'[db] event_history: dropping {unmapped} rows with NULL security_id '
                  f'(ticker not seeded in securities table)')
            df = df.dropna(subset=['security_id'])
        # Within-batch dedupe on the natural-key UNIQUE constraint
        before = len(df)
        df = df.drop_duplicates(
            subset=['security_id', 'event_date', 'event_type'], keep='last'
        )
        if before > len(df):
            print(f'[db] event_history: deduped {before - len(df)} '
                  f'within-batch duplicate rows')
        if df.empty:
            return 0
        return self._upsert_chunked('event_history', df)

    # Backward-compat alias
    def upsert_events_history(self, df: pd.DataFrame) -> int:
        return self.upsert_event_history(df)

    def upsert_macro_calendar(self, df: pd.DataFrame) -> int:
        return self._upsert_chunked('macro_calendar', df)

    # ─────────────────────────────────────────────────────────────────────
    # Read helpers (for append-only mode)
    # ─────────────────────────────────────────────────────────────────────

    def get_last_volatility_date(self, security_id: int) -> Optional[pd.Timestamp]:
        """Return the most recent date in volatility_history for a security,
        or None if no rows exist. Used to detect what's new for append-only."""
        if self.dry_run:
            return None
        result = (
            self.client.table('volatility_history')
            .select('date')
            .eq('security_id', security_id)
            .order('date', desc=True)
            .limit(1)
            .execute()
        )
        if not result.data:
            return None
        return pd.Timestamp(result.data[0]['date'])

    def get_security_id(self, ticker: str) -> Optional[int]:
        """Look up a security_id by ticker. Returns None if not found."""
        if self.dry_run:
            return None
        result = (
            self.client.table('securities')
            .select('security_id')
            .eq('ticker', ticker)
            .limit(1)
            .execute()
        )
        if not result.data:
            return None
        return result.data[0]['security_id']


# ─────────────────────────────────────────────────────────────────────────
# Quick smoke test when run directly
# ─────────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    import sys
    dry = '--dry-run' in sys.argv
    db = SupabaseClient(dry_run=dry)
    if not dry:
        missing = db.verify_schema()
        if missing:
            print('\nSchema migration not fully applied. See model/sql/migrations/.')
            sys.exit(1)
    print('OK')