"""
model_interface.py — the contract for the external forecasting model (PLAN §7).

The model (`model/`) is owned by another developer and treated as an external component. This module
is the single place that knows:
  1. how to **invoke** it (subprocess CLI, not a Python import — keeps the boundary clean), and
  2. how to **read** its artifacts and map them onto DB columns, with explicit GAP markers where the
     current outputs don't cover a column (the locked "define vs current + flag gaps" decision).

The GAP/UNKNOWN items here are the coordination list for the model dev — see PLAN §7.5 and §13.
Nothing in this module runs the model or imports its internals.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from .config import AutomationConfig


# ── invocation ───────────────────────────────────────────────────────────────────────────────────
# How the model is run today (PLAN §7.1). We shell out to its CLI rather than importing it.
MODEL_MODULE = "model.pipeline.run"

# The model's horizons (model/pipeline/config.py ModelConfig.horizons) — map to pfv_*/shap_h* columns.
MODEL_HORIZONS = (21, 63, 126)


def build_invocation(config: "AutomationConfig", tickers: list[str]) -> list[str]:
    """
    Build the argv to invoke the model for today's forecast.

    NOTE (PLAN §7.1, §7.5.5): the model's existing `--mode live` only PRINTS — it does not persist a
    per-day DB-ready record. The clean long-term fix is a model-side `--mode emit-db` producing a
    typed daily record. Until then this stage must either (a) drive `backtest`/`live` and
    reverse-engineer artifacts, or (b) wait on the model dev. Returned argv is a placeholder.

    TODO(PLAN §7.5): finalize the exact mode/flags with the model dev.
    """
    raise NotImplementedError("TODO(PLAN §7.5): finalize model invocation contract")


# ── output → DB column mapping (PLAN §7.4) ────────────────────────────────────────────────────────
class FieldStatus(str, Enum):
    OK = "ok"          # directly available from current outputs
    DERIVE = "derive"  # computable from current outputs / feature_df
    GAP = "gap"        # NOT produced today — needs model-dev input (PLAN §7.5)


@dataclass(frozen=True)
class ColumnMapping:
    """One DB column's provenance from model artifacts."""

    column: str
    status: FieldStatus
    source: str        # where it comes from (CSV col, payload key, feature, or 'TODO')
    note: str = ""


# volatility_history — mixes model outputs with market IV (PLAN §7.4). The authoritative,
# machine-readable version of the §7.4 table; upload_outputs consults it and refuses to fabricate
# GAP columns (writes NULL + logs) until the model dev resolves them.
VOLATILITY_HISTORY_MAP: tuple[ColumnMapping, ...] = (
    ColumnMapping("rv", FieldStatus.DERIVE, "feature_df.rv_21d"),
    ColumnMapping("ewma_vol", FieldStatus.DERIVE, "feature_df.ewma_vol"),
    ColumnMapping("iv_atm", FieldStatus.DERIVE, "feature_df.iv_atm_30d",
                  "market IV; GAP post-WRDS unless sourced from options_chain (PLAN §7.5.4)"),
    ColumnMapping("iv_atm_30d", FieldStatus.DERIVE, "feature_df.iv_atm_30d", "PLAN §7.5.4"),
    ColumnMapping("iv_atm_60d", FieldStatus.DERIVE, "feature_df.iv_atm_60d", "PLAN §7.5.4"),
    ColumnMapping("iv_atm_91d", FieldStatus.DERIVE, "feature_df.iv_atm_91d", "PLAN §7.5.4"),
    ColumnMapping("iv_atm_182d", FieldStatus.DERIVE, "feature_df.iv_atm_182d", "PLAN §7.5.4"),
    ColumnMapping("vrp_wedge", FieldStatus.DERIVE, "feature_df.vrp_wedge"),
    ColumnMapping("vrp_wedge_ewma_21d", FieldStatus.DERIVE, "feature_df.vrp_wedge (ewma)"),
    ColumnMapping("pfv_21", FieldStatus.DERIVE, "predictions H21 y_pred / payload forecast_rv['21']"),
    ColumnMapping("pfv_63", FieldStatus.DERIVE, "predictions H63 y_pred"),
    ColumnMapping("pfv_126", FieldStatus.DERIVE, "predictions H126 y_pred"),
    ColumnMapping("pfv_cal_21", FieldStatus.GAP, "TODO", "calibrated forecast not emitted (PLAN §7.5.3)"),
    ColumnMapping("pfv_cal_63", FieldStatus.GAP, "TODO", "PLAN §7.5.3"),
    ColumnMapping("pfv_cal_126", FieldStatus.GAP, "TODO", "PLAN §7.5.3"),
    ColumnMapping("pfv_q15_21", FieldStatus.GAP, "TODO", "quantile band not emitted (PLAN §7.5.3)"),
    ColumnMapping("pfv_q15_63", FieldStatus.GAP, "TODO", "PLAN §7.5.3"),
    ColumnMapping("pfv_q15_126", FieldStatus.GAP, "TODO", "PLAN §7.5.3"),
    ColumnMapping("fwd_premium_21d", FieldStatus.GAP, "TODO", "IV term premium not emitted (PLAN §7.5.3)"),
    ColumnMapping("fwd_premium_63d", FieldStatus.GAP, "TODO", "PLAN §7.5.3"),
    ColumnMapping("fwd_premium_126d", FieldStatus.GAP, "TODO", "PLAN §7.5.3"),
    ColumnMapping("fwd_premium_21_to_63d", FieldStatus.GAP, "TODO", "PLAN §7.5.3"),
    ColumnMapping("fwd_premium_63_to_126d", FieldStatus.GAP, "TODO", "PLAN §7.5.3"),
    ColumnMapping("next_earnings_date", FieldStatus.DERIVE, "model event features"),
    ColumnMapping("days_to_earnings", FieldStatus.DERIVE, "model event features"),
    ColumnMapping("next_dividend_date", FieldStatus.DERIVE, "model event features"),
    ColumnMapping("days_to_dividend", FieldStatus.DERIVE, "model event features"),
    ColumnMapping("model_run_id", FieldStatus.OK, "model_runs row written this run"),
    ColumnMapping("shap_h21_top10", FieldStatus.GAP, "TODO", "no SHAP emitted (PLAN §7.5.2)"),
    ColumnMapping("shap_h63_top10", FieldStatus.GAP, "TODO", "PLAN §7.5.2"),
    ColumnMapping("shap_h126_top10", FieldStatus.GAP, "TODO", "PLAN §7.5.2"),
)

# shap_snapshot — entirely GAP today (model emits no SHAP) (PLAN §7.4, §7.5.2).
SHAP_SNAPSHOT_MAP: tuple[ColumnMapping, ...] = (
    ColumnMapping("retrain_date", FieldStatus.DERIVE, "run/retrain date"),
    ColumnMapping("snapshot_date", FieldStatus.DERIVE, "run date"),
    ColumnMapping("horizon", FieldStatus.OK, "21/63/126"),
    ColumnMapping("base_value", FieldStatus.GAP, "TODO", "SHAP explainer base (PLAN §7.5.2)"),
    ColumnMapping("predicted_value", FieldStatus.GAP, "TODO", "PLAN §7.5.2"),
    ColumnMapping("feature_data", FieldStatus.GAP, "TODO", "full SHAP attribution (PLAN §7.5.2)"),
)

# model_runs — run metadata (PLAN §7.4).
MODEL_RUNS_MAP: tuple[ColumnMapping, ...] = (
    ColumnMapping("run_date", FieldStatus.OK, "ctx.run_date"),
    ColumnMapping("model_version", FieldStatus.DERIVE, "TODO", "canonical version string (PLAN §7.5.1)"),
    ColumnMapping("spec_hash", FieldStatus.GAP, "TODO", "feature/config fingerprint (PLAN §7.5.1)"),
    ColumnMapping("n_tickers", FieldStatus.OK, "len(universe)"),
    ColumnMapping("horizons", FieldStatus.OK, "ModelConfig.horizons"),
    ColumnMapping("notes", FieldStatus.OK, "free text"),
)


def gaps(mapping: tuple[ColumnMapping, ...]) -> list[ColumnMapping]:
    """Return the GAP columns in a mapping — the model-dev coordination list (PLAN §7.5, §13)."""
    return [m for m in mapping if m.status is FieldStatus.GAP]


# ── reading artifacts (PLAN §7.3) ─────────────────────────────────────────────────────────────────
@dataclass
class ModelArtifacts:
    """Handle to the model's on-disk outputs for a run (PLAN §7.3)."""

    results_dir: Path
    run_date: date

    def predictions_csv(self, ticker: str, horizon: int) -> Path:
        """Path to predictions_{TICKER}_H{h}.csv."""
        return self.results_dir / f"predictions_{ticker}_H{horizon}.csv"

    def payload_json(self, ticker: str) -> Path:
        """Path to payloads/{TICKER}_Payload.json."""
        return self.results_dir / "payloads" / f"{ticker}_Payload.json"

    def market_overview_json(self) -> Path:
        return self.results_dir / "payloads" / "market_overview.json"


def read_volatility_row(artifacts: "ModelArtifacts", ticker: str,
                        security_id: int, model_run_id: int) -> dict[str, Any]:
    """
    Assemble one `volatility_history` row for `ticker` from model artifacts, per VOLATILITY_HISTORY_MAP.

    GAP columns are written as NULL (and logged once per run) until the model dev resolves them — the
    pipeline must never fabricate values for GAP fields.

    TODO(PLAN §7.4): parse predictions CSVs + payload JSON; fill OK/DERIVE columns; NULL the GAPs.
    """
    raise NotImplementedError("TODO(PLAN §7.4): map model artifacts → volatility_history row")


def read_shap_rows(artifacts: "ModelArtifacts", ticker: str, security_id: int) -> list[dict[str, Any]]:
    """
    Assemble `shap_snapshot` rows (one per horizon) for `ticker`.

    Returns [] today — the model emits no SHAP (PLAN §7.5.2). Implement once SHAP output exists.
    """
    raise NotImplementedError("TODO(PLAN §7.5.2): blocked on model SHAP output")
