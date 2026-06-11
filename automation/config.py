"""
config.py — Central configuration for the automation pipeline.

All tunable parameters and environment wiring live here, mirroring the model's `config.py` dataclass
style. Nothing here makes network calls; `load_config()` only reads env vars and returns typed config.

Secrets are read from environment (a repo-root `.env` in dev). See `automation/PLAN.md` §11 and the
root `.env.example` for the full var list. **Never** hard-code secrets here.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Repo root = parent of the `automation/` package. Used to locate the shared `.env` and the model's
# results directory.
REPO_ROOT: Path = Path(__file__).resolve().parent.parent


@dataclass
class SupabaseConfig:
    """Write-side Supabase connection (service-role — bypasses RLS). See PLAN §6."""

    url: str = ""          # SUPABASE_URL (may reuse VITE_SUPABASE_URL's value)
    # New Supabase "secret" API key (sb_secret_...), which bypasses RLS. Falls back to the legacy
    # service_role JWT if only that is set. SECRET — never commit or expose to the frontend.
    secret_key: str = ""

    def validate(self) -> None:
        """Raise a clear error if required write credentials are missing (skipped in dry-run)."""
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
class AlpacaConfig:
    """Alpaca market-data credentials + tuning (prices + options). See PLAN §4.3, §5."""

    api_key: str = ""              # ALPACA_API_KEY
    secret_key: str = ""           # ALPACA_SECRET_KEY
    feed: str = "sip"              # data feed for stock bars

    # Cost/scoping controls for the (heaviest) options fetch — see PLAN §4.3.
    # TODO(PLAN §7.5.4): map these to the model's term points once the IV seam is decided.
    option_max_dte: int = 200      # ignore expiries beyond this many days out
    option_strike_band_pct: float = 0.30  # keep strikes within ±30% of spot (near/ATM band)

    # Rate-limit / concurrency (PLAN §5).
    max_concurrency: int = 6       # bounded per-security fan-out
    max_retries: int = 4
    backoff_base_seconds: float = 1.0


@dataclass
class LLMConfig:
    """AI-overview provider config — provider/model-agnostic. See PLAN §8."""

    provider: str = "claude"       # registry key in providers/llm.py
    model: str = "claude-opus-4-8"  # provider-specific model id; part of ai_overview.model_ver
    prompt_ver: str = "v1"          # bumped when the prompt/spec changes; part of the dedupe key
    anthropic_api_key: str = ""    # ANTHROPIC_API_KEY (for the Claude provider)

    # Optional cost ceiling (PLAN §9.3) — enforcement is a TODO; field exists so config is stable.
    max_overview_tokens: Optional[int] = None


@dataclass
class OptionsImportConfig:
    """
    Options-chain import config (OPTIONS_IMPORT_PLAN.md). Provider-agnostic naming so swapping
    yfinance → Polygon/Tradier later is a config change, not a rewrite.
    """

    provider: str = "yfinance"                 # registry key for the options data source

    # Expiry selection (preset A + front monthlies) — see expiry_selection.py.
    term_dte_targets: tuple[int, ...] = (30, 60, 90, 180)
    front_monthlies: int = 2

    # Strike scoping (cost control).
    strike_band_pct: float = 0.30
    max_strikes_per_side: Optional[int] = None

    # Black-Scholes inputs for the computed delta (yfinance gives no greeks).
    risk_free_rate: float = 0.045

    # yfinance can rate-limit / return empties.
    max_retries: int = 3
    backoff_base_seconds: float = 1.0


@dataclass
class AutomationConfig:
    """Top-level pipeline configuration."""

    env: str = "dev"               # AUTOMATION_ENV: dev|stg|prod (mirrors backend APP_ENV)
    dry_run: bool = False          # if True, no external calls and no DB writes (PLAN §9.3)
    force: bool = False            # ignore freshness/skip checks and re-run everything (PLAN §3)

    # Stage selection — allow running a subset (e.g. just refresh prices). Empty = all wired stages.
    only_stages: list[str] = field(default_factory=list)

    # Where the model writes its artifacts (PLAN §7.3). Defaults to the model's results dir.
    model_results_dir: Path = field(
        default_factory=lambda: REPO_ROOT / "model" / "pipeline" / "results"
    )

    # Partial-failure tolerance: fraction of a stage's securities that may fail before the stage is
    # marked 'failed' rather than 'partial' (PLAN §9.2).
    stage_failure_threshold: float = 0.5

    # Whether to write the optional pipeline_runs observability ledger (PLAN §3.3).
    write_run_ledger: bool = False

    supabase: SupabaseConfig = field(default_factory=SupabaseConfig)
    alpaca: AlpacaConfig = field(default_factory=AlpacaConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    options: OptionsImportConfig = field(default_factory=OptionsImportConfig)


def load_config(
    *,
    dry_run: bool = False,
    force: bool = False,
    only_stages: Optional[list[str]] = None,
) -> AutomationConfig:
    """
    Build an `AutomationConfig` from environment variables.

    Reads the repo-root `.env` (via python-dotenv) then the process environment. Does **not**
    validate secret presence here — callers validate the clients they actually use, so `--dry-run`
    works with no secrets at all (PLAN §9.3).
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
    alpaca = AlpacaConfig(
        api_key=os.getenv("ALPACA_API_KEY", ""),
        secret_key=os.getenv("ALPACA_SECRET_KEY", ""),
    )
    llm = LLMConfig(anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""))

    return AutomationConfig(
        env=os.getenv("AUTOMATION_ENV", "dev"),
        dry_run=dry_run,
        force=force,
        only_stages=list(only_stages or []),
        supabase=supabase,
        alpaca=alpaca,
        llm=llm,
        options=OptionsImportConfig(),
    )
