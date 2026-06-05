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

    url: str = ""                  # SUPABASE_URL (may reuse VITE_SUPABASE_URL's value)
    service_role_key: str = ""     # SUPABASE_SERVICE_ROLE_KEY — SECRET, never commit/expose to FE

    def validate(self) -> None:
        """Raise if required write credentials are missing (skipped in dry-run)."""
        # TODO(PLAN §6): raise a clear error naming the missing env var(s).
        raise NotImplementedError


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


def load_config(
    *,
    dry_run: bool = False,
    force: bool = False,
    only_stages: Optional[list[str]] = None,
) -> AutomationConfig:
    """
    Build an `AutomationConfig` from environment variables.

    Reads the repo-root `.env` (via python-dotenv) then the process environment. Does **not**
    validate secret presence here — stages validate the clients they actually use, so `--dry-run`
    works with no secrets at all (PLAN §9.3).

    TODO:
      - load_dotenv(REPO_ROOT / ".env")
      - populate SupabaseConfig from SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY
        (fall back to VITE_SUPABASE_URL for the URL only — never read a publishable key for writes)
      - populate AlpacaConfig from ALPACA_API_KEY / ALPACA_SECRET_KEY
      - populate LLMConfig from AUTOMATION_LLM_* / ANTHROPIC_API_KEY
      - read AUTOMATION_ENV
    """
    raise NotImplementedError("TODO(PLAN §11): wire env → AutomationConfig")
