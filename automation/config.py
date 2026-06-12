"""
config.py — configuration + environment wiring for the automation tooling.

`load_config()` reads the repo-root `.env` (then the process env) and returns typed config. Nothing
here makes network calls. Secrets are read from the environment — **never** hard-code them. See the
root `.env.example` and `automation/CLAUDE.md` §3 for the full var list.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Repo root = parent of the `automation/` package. Used to locate the shared `.env`.
REPO_ROOT: Path = Path(__file__).resolve().parent.parent


@dataclass
class SupabaseConfig:
    """Write-side Supabase connection — the secret API key bypasses RLS. See CLAUDE.md §3."""

    url: str = ""          # SUPABASE_URL (may reuse VITE_SUPABASE_URL's value)
    # New Supabase "secret" API key (sb_secret_...), which bypasses RLS. Falls back to the legacy
    # service_role JWT if only that is set. SECRET — never commit or expose to the frontend.
    secret_key: str = ""

    def validate(self) -> None:
        """Raise a clear error if required write credentials are missing."""
        missing = []
        if not self.url:
            missing.append("SUPABASE_URL")
        if not self.secret_key:
            missing.append("SUPABASE_SECRET_KEY (or legacy SUPABASE_SERVICE_ROLE_KEY)")
        if missing:
            raise RuntimeError(
                "Missing write-side Supabase env var(s): " + ", ".join(missing)
                + ". Set them in the repo-root .env (see .env.example). The secret key is created in "
                "the Supabase dashboard → Project Settings → API keys (it bypasses RLS)."
            )


@dataclass
class OptionsImportConfig:
    """
    Options-chain import config (CLAUDE.md §5). Provider-agnostic naming so swapping
    yfinance → Polygon/Tradier later is a config change, not a rewrite.
    """

    provider: str = "yfinance"                 # registry key for the options data source

    # Expiry selection (preset A + front monthlies) — see expiry_selection.py.
    term_dte_targets: tuple[int, ...] = (30, 60, 90, 180)
    front_monthlies: int = 2

    # Strike scoping (cost control).
    strike_band_pct: float = 0.30
    max_strikes_per_side: Optional[int] = None

    # Black-Scholes input for the computed delta (yfinance gives no greeks).
    risk_free_rate: float = 0.045

    # yfinance can rate-limit / return empties.
    max_retries: int = 3
    backoff_base_seconds: float = 1.0


@dataclass
class AutomationConfig:
    """Top-level configuration."""

    env: str = "dev"               # AUTOMATION_ENV: dev|stg|prod (mirrors backend APP_ENV)
    dry_run: bool = False          # if True, no external calls and no DB writes
    force: bool = False            # ignore freshness/skip checks and re-fetch

    supabase: SupabaseConfig = field(default_factory=SupabaseConfig)
    options: OptionsImportConfig = field(default_factory=OptionsImportConfig)


def load_config(*, dry_run: bool = False, force: bool = False) -> AutomationConfig:
    """
    Build an `AutomationConfig` from environment variables.

    Reads the repo-root `.env` (via python-dotenv) then the process environment. Does **not**
    validate secret presence here — callers validate the client they actually use, so `--dry-run`
    works with no secrets at all.
    """
    try:
        from dotenv import load_dotenv
        load_dotenv(dotenv_path=REPO_ROOT / ".env")
    except ImportError:
        pass  # dotenv optional; process env still honored

    supabase = SupabaseConfig(
        # URL may reuse VITE_SUPABASE_URL; the secret KEY must be its own secret (never the
        # publishable/anon key — that's read-only under RLS). Prefer the new secret API key
        # (SUPABASE_SECRET_KEY), fall back to the legacy service_role JWT.
        url=os.getenv("SUPABASE_URL") or os.getenv("VITE_SUPABASE_URL", ""),
        secret_key=os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY", ""),
    )

    return AutomationConfig(
        env=os.getenv("AUTOMATION_ENV", "dev"),
        dry_run=dry_run,
        force=force,
        supabase=supabase,
        options=OptionsImportConfig(),
    )
