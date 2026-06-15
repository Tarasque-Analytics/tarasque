"""
models.py — Ensemble volatility model with walk-forward validation.

Ported from volarbmodel_backtest.py:
    GarchForecaster  (:58-88)
    VolArbModel      (:352-466)
    SHAP explanation  (:469-514)
"""
import time
from pathlib import Path

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple

from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import mean_squared_error
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import ElasticNetCV
from sklearn.ensemble import RandomForestRegressor
import xgboost as xgb

from .config import ModelConfig


# ═══════════════════════════════════════════════════════════════════════════
# GARCH FORECASTER
# ═══════════════════════════════════════════════════════════════════════════

class GarchForecaster:
    """GARCH(1,1) with configurable distribution (default: Skewed-T)."""

    @staticmethod
    def fit_predict(
        returns: pd.Series,
        horizon: int = 21,
        dist: str = "skewt",
    ) -> Tuple[float, float]:
        """
        Fit GARCH(1,1) and forecast annualised vol.

        Returns (annualised_vol_forecast, current_conditional_vol).
        """
        from arch import arch_model

        scaled_ret = returns * 100.0

        try:
            model = arch_model(
                scaled_ret, vol="Garch", p=1, q=1,
                dist=dist, rescale=False,
            )
            res = model.fit(disp="off", show_warning=False)

            forecast = res.forecast(horizon=horizon)
            var_forecast = forecast.variance.iloc[-1].values
            avg_daily_var = np.mean(var_forecast)
            daily_vol = np.sqrt(avg_daily_var) / 100.0
            annualised_vol = daily_vol * np.sqrt(252)

            current_cond_vol = (
                res.conditional_volatility.iloc[-1] / 100.0 * np.sqrt(252)
            )
            return annualised_vol, current_cond_vol

        except Exception as e:
            print(f"[WARN] GARCH fit failed: {e}. Defaulting to naive volatility.")
            naive_vol = returns.std() * np.sqrt(252)
            return naive_vol, naive_vol

    @staticmethod
    def cond_vol_series(
        returns: pd.Series,
        dist: str = "skewt",
    ) -> pd.Series:
        """
        Fit GARCH(1,1) on the full returns series and return the in-sample
        conditional volatility as an annualised pd.Series (same index as returns).

        h_t depends only on returns up to t, so this is point-in-time safe
        at the observation level.  GARCH parameters (omega/alpha/beta) are
        estimated on the full series — mild parameter lookahead, standard
        practice for a feature input.

        Falls back to a 21-day EWMA vol on fit failure.
        """
        from arch import arch_model

        scaled = returns.dropna() * 100.0
        try:
            res = arch_model(
                scaled, vol="Garch", p=1, q=1, dist=dist, rescale=False,
            ).fit(disp="off", show_warning=False)
            cond_vol = res.conditional_volatility / 100.0 * np.sqrt(252)
            return cond_vol.reindex(returns.index)
        except Exception:
            fallback = np.sqrt(returns.pow(2).ewm(span=21).mean() * 252)
            return fallback


# ═══════════════════════════════════════════════════════════════════════════
# ENSEMBLE VOL MODEL
# ═══════════════════════════════════════════════════════════════════════════

class EnsembleVolModel:
    """
    XGBoost + RandomForest + ElasticNetCV ensemble with inverse-RMSE weighting.

    Ported from VolArbModel in volarbmodel_backtest.py:352-466.
    Additions: minimum weight floor, model_names ablation parameter.
    """

    _profile: Dict[str, float] = {}   # class-level timing accumulator

    def __init__(self, config: ModelConfig):
        self.config = config
        self.horizons = config.horizons
        self.models: Dict[int, Dict[str, object]] = {}
        self.weights: Dict[int, Dict[str, float]] = {}
        self.rmse_scores: Dict[int, float] = {}
        self.feature_importance: Dict[str, float] = {}
        self.predictors: List[str] = []
        self.final_scaler: Optional[StandardScaler] = None
        # Lasso tracking: list of {horizon, stage, fold, alpha, coefs}
        # Populated during train_wfa(); consumed by backtest.py for CSV export.
        self.lasso_log: List[dict] = []

        for h in self.horizons:
            self.models[h] = self._init_models()
            self.weights[h] = {"XGB": 0.33, "RF": 0.33, "ElasticNet": 0.33}
            self.rmse_scores[h] = 0.0

    _gpu_checked: bool = False
    _gpu_available: bool = False

    def _init_models(self) -> Dict[str, object]:
        xgb_params = dict(self.config.xgb_params)

        # One-time GPU availability check with fallback to CPU
        if xgb_params.get("device") == "cuda" and not self.__class__._gpu_checked:
            self.__class__._gpu_checked = True
            try:
                test = xgb.XGBRegressor(device="cuda", tree_method="hist",
                                        n_estimators=1, verbosity=0)
                test.fit([[0]], [0])
                self.__class__._gpu_available = True
                print("[MODEL] XGBoost CUDA GPU acceleration enabled")
            except Exception:
                self.__class__._gpu_available = False
                print("[MODEL] CUDA not available -- XGBoost using CPU")

        if xgb_params.get("device") == "cuda" and not self.__class__._gpu_available:
            xgb_params["device"] = "cpu"

        return {
            "XGB": xgb.XGBRegressor(**xgb_params),
            "RF": RandomForestRegressor(**self.config.rf_params),
            "ElasticNet": ElasticNetCV(
                cv=TimeSeriesSplit(n_splits=3), max_iter=10000,
                n_jobs=getattr(self.config, "lasso_n_jobs", -1),
                l1_ratio=[0.5, 0.7, 0.9],  # cross-validates sparsity vs group-shrinkage
                alphas=20,                  # 20-point alpha grid (sklearn 1.7+ accepts int)
            ),
        }

    # ── Training ──────────────────────────────────────────────────────

    def train_wfa(
        self,
        X: pd.DataFrame,
        y_dict: Dict[int, pd.Series],
        splits: Optional[int] = None,
        model_names: Optional[List[str]] = None,
    ):
        """
        Walk-forward training for all horizons.

        Parameters
        ----------
        model_names : list[str], optional
            Subset of ["XGB", "RF", "ElasticNet"] for ablation studies.
        """
        splits = splits or self.config.wfa_splits
        if model_names is None:
            model_names = ["XGB", "RF", "ElasticNet"]

        self.predictors = list(X.columns)

        print(f"[MODEL] Training Term Structure Anchors {self.horizons}...")
        tscv = TimeSeriesSplit(n_splits=splits)

        lam = self.config.exp_weight_lambda
        # Vol-weighted MSE knob: w = 1 + alpha * y_rank_pct.
        # alpha=0 -> uniform (default); alpha>0 -> upweight high-vol training obs.
        # Targets the AAPL-style under-forecast (β>1) cluster. NOT for the
        # corpus-wide over-forecast (β<0.7) cluster — use exp_weight_lambda there.
        vol_alpha = float(getattr(self.config, "vol_weight_alpha", 0.0))

        # 1. FINAL SCALER — fit on all data (backtest :394-396)
        self.final_scaler = StandardScaler()
        X_final_s = pd.DataFrame(
            self.final_scaler.fit_transform(X),
            columns=X.columns, index=X.index,
        )

        # Final-fit sample weights (recency + vol, applied once outside horizon loop)
        final_sample_weights = None
        if lam > 0 or vol_alpha > 0:
            n_final = len(X_final_s)
            w_f = np.ones(n_final)
            if lam > 0:
                w_f = w_f * np.exp(lam * np.arange(n_final))
            # Note: final-fit vol weighting applied per-horizon below since y is
            # different per horizon.
            final_sample_weights = w_f / w_f.mean()

        for h in self.horizons:
            y = y_dict[h]
            errors: Dict[str, list] = {n: [] for n in model_names}

            # 2. VALIDATION LOOP (backtest :402-428)
            for _fold, (tr_idx, te_idx) in enumerate(tscv.split(X)):
                X_tr, X_te = X.iloc[tr_idx], X.iloc[te_idx]
                y_tr, y_te = y.iloc[tr_idx], y.iloc[te_idx]

                # Drop NaN targets (safety net for horizon tail rows)
                tr_valid = y_tr.notna()
                te_valid = y_te.notna()
                X_tr, y_tr = X_tr[tr_valid], y_tr[tr_valid]
                X_te, y_te = X_te[te_valid], y_te[te_valid]

                if len(y_tr) == 0 or len(y_te) == 0:
                    continue

                # Strict OOS scaling (backtest :407-409)
                fold_scaler = StandardScaler()
                X_tr_s = fold_scaler.fit_transform(X_tr)
                X_te_s = fold_scaler.transform(X_te)

                # Sample weights: combine recency (lambda) and vol-rank (alpha).
                # Both default off; either can be enabled independently via config.
                # Final weight = recency_w * vol_w, normalised so mean = 1.0.
                fold_sample_weights = None
                if lam > 0 or vol_alpha > 0:
                    n_tr = len(X_tr_s)
                    w = np.ones(n_tr)
                    if lam > 0:
                        w = w * np.exp(lam * np.arange(n_tr))
                    if vol_alpha > 0:
                        # Rank in [0, 1]; higher realized vol -> higher weight.
                        rank_pct = pd.Series(y_tr).rank(pct=True).values
                        w = w * (1.0 + vol_alpha * rank_pct)
                    fold_sample_weights = w / w.mean()

                for name in model_names:
                    _t = time.perf_counter()
                    if fold_sample_weights is not None:
                        # All three estimators accept sample_weight in fit()
                        self.models[h][name].fit(X_tr_s, y_tr, sample_weight=fold_sample_weights)
                    else:
                        self.models[h][name].fit(X_tr_s, y_tr)
                    self.__class__._profile[name] = self.__class__._profile.get(name, 0) + (time.perf_counter() - _t)
                    if name == "ElasticNet":
                        _en = self.models[h]["ElasticNet"]
                        self.lasso_log.append({
                            "horizon": h, "stage": "fold", "fold": _fold,
                            "alpha":    float(_en.alpha_),
                            "l1_ratio": float(_en.l1_ratio_),
                            "coefs":    _en.coef_.tolist(),
                        })
                    log_preds = np.clip(self.models[h][name].predict(X_te_s), -5, 5)
                    preds_lin = np.exp(log_preds)
                    y_te_lin = np.exp(np.clip(y_te.values, -5, 5))
                    rmse = np.sqrt(mean_squared_error(y_te_lin, preds_lin))
                    errors[name].append(rmse)

            # 3. INVERSE-RMSE WEIGHTING (backtest :430-434)
            avg_rmse = {n: np.mean(e) for n, e in errors.items()}
            inv_sum = sum(1.0 / v for v in avg_rmse.values() if v > 0)

            raw_weights = {}
            for n in model_names:
                raw_weights[n] = (1.0 / avg_rmse[n]) / inv_sum if avg_rmse[n] > 0 else 0.0

            # Apply minimum weight floor (new)
            floor = self.config.min_ensemble_weight
            for n in model_names:
                raw_weights[n] = max(floor, raw_weights[n])
            w_sum = sum(raw_weights.values())
            self.weights[h] = {n: w / w_sum for n, w in raw_weights.items()}

            # Blended RMSE
            self.rmse_scores[h] = sum(
                avg_rmse[n] * self.weights[h][n] for n in model_names
            )

            print(f"  [H={h:3d}] RMSE: {self.rmse_scores[h]:.4f} | "
                  f"Weights: {', '.join(f'{n}={self.weights[h][n]:.2f}' for n in model_names)}")

            # 4. FINAL FIT on fully scaled data (backtest :437-440)
            # Compose per-horizon final sample weights: recency * vol-rank
            if final_sample_weights is not None or vol_alpha > 0:
                base = (final_sample_weights if final_sample_weights is not None
                        else np.ones(len(X_final_s)))
                if vol_alpha > 0:
                    rank_pct_h = y.rank(pct=True).values
                    final_w_h = base * (1.0 + vol_alpha * rank_pct_h)
                    final_w_h = final_w_h / final_w_h.mean()
                else:
                    final_w_h = base
            else:
                final_w_h = None

            for name in model_names:
                if final_w_h is not None:
                    self.models[h][name].fit(X_final_s, y, sample_weight=final_w_h)
                else:
                    self.models[h][name].fit(X_final_s, y)
                if name == "ElasticNet":
                    _en = self.models[h]["ElasticNet"]
                    self.lasso_log.append({
                        "horizon": h, "stage": "final", "fold": -1,
                        "alpha":    float(_en.alpha_),
                        "l1_ratio": float(_en.l1_ratio_),
                        "coefs":    _en.coef_.tolist(),
                    })

        # 5. FEATURE IMPORTANCE from XGB at shortest horizon (backtest :443-444)
        if "XGB" in model_names:
            xgb_imps = self.models[self.horizons[0]]["XGB"].feature_importances_
            top_idx = np.argsort(xgb_imps)[::-1][:10]
            self.feature_importance = {
                self.predictors[i]: float(xgb_imps[i]) for i in top_idx
            }

    # ── Prediction ────────────────────────────────────────────────────

    def predict_curve(
        self, current_features: pd.DataFrame,
    ) -> Dict[int, float]:
        """
        Blended prediction across all horizons.

        Parameters
        ----------
        current_features : DataFrame
            Single-row or multi-row DataFrame with predictor columns.

        Returns
        -------
        dict  {horizon: annualised_vol_forecast}
        """
        feat_s = self.final_scaler.transform(current_features)
        feat_df = pd.DataFrame(feat_s, columns=current_features.columns)

        curve = {}
        for h in self.horizons:
            blended_log = sum(
                self.models[h][name].predict(feat_df)[0] * self.weights[h][name]
                for name in self.weights[h]
            )
            curve[h] = float(np.exp(np.clip(blended_log, -5, 5)))

        return curve

    def predict_curve_batch(
        self, features: pd.DataFrame,
    ) -> Dict[int, np.ndarray]:
        """
        Batch prediction for multiple rows at once.

        Returns {horizon: array of annualised vol forecasts} with one value per row.
        """
        feat_s = self.final_scaler.transform(features)
        feat_df = pd.DataFrame(feat_s, columns=features.columns)

        curves: Dict[int, np.ndarray] = {}
        for h in self.horizons:
            blended_log = sum(
                self.models[h][name].predict(feat_df) * self.weights[h][name]
                for name in self.weights[h]
            )
            curves[h] = np.exp(np.clip(blended_log, -5, 5))
        return curves

    # ── Persistence ───────────────────────────────────────────────────

    def save(self, path) -> None:
        """
        Serialize the trained ensemble to *path* via joblib.

        Used by `--mode forecast` to avoid retraining between cycle boundaries.
        Daily refresh loads the model and runs `predict_curve` only.
        """
        import joblib
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({
            "models": self.models,
            "weights": self.weights,
            "rmse_scores": self.rmse_scores,
            "feature_importance": self.feature_importance,
            "predictors": self.predictors,
            "final_scaler": self.final_scaler,
            "config": self.config,
        }, path)

    @classmethod
    def load(cls, path) -> "EnsembleVolModel":
        """Restore a previously-saved ensemble."""
        import joblib
        state = joblib.load(path)
        obj = cls(state["config"])
        obj.models = state["models"]
        obj.weights = state["weights"]
        obj.rmse_scores = state.get("rmse_scores", obj.rmse_scores)
        obj.feature_importance = state.get("feature_importance", {})
        obj.predictors = state["predictors"]
        obj.final_scaler = state["final_scaler"]
        return obj

    # ── SHAP Explainability (backtest :469-514) ───────────────────────

    def explain_prediction(
        self,
        current_features: pd.DataFrame,
        horizon: int = 21,
    ) -> dict:
        """
        SHAP values for the current day's features.

        Returns dict with base_value_log, shap_values (top 10), anchor_model.
        """
        try:
            import shap
        except ImportError:
            return {"error": "shap package not installed"}

        feat_s = self.final_scaler.transform(current_features)
        feat_df = pd.DataFrame(feat_s, columns=current_features.columns)

        # Find the dominant tree model
        tree_model = None
        model_name = ""
        for name in ["XGB", "RF"]:
            m = self.models[horizon].get(name)
            if m is not None and hasattr(m, "feature_importances_"):
                tree_model = m
                model_name = name
                break

        if tree_model is None:
            return {"error": "No tree-based model found for SHAP."}

        explainer = shap.TreeExplainer(tree_model)
        shap_values = explainer.shap_values(feat_df)

        base_value = explainer.expected_value
        if isinstance(base_value, np.ndarray):
            base_value = base_value[0]

        impacts = {
            self.predictors[i]: float(shap_values[0][i])
            for i in range(len(self.predictors))
        }
        top_impacts = dict(
            sorted(impacts.items(), key=lambda x: abs(x[1]), reverse=True)[:10]
        )

        return {
            "horizon": horizon,
            "anchor_model": model_name,
            "base_value_log": float(base_value),
            "shap_values": top_impacts,
        }


# ═══════════════════════════════════════════════════════════════════════════
# QUANTILE VOL MODEL
# ═══════════════════════════════════════════════════════════════════════════

class QuantileVolModel:
    """
    Walk-forward XGBoost quantile regressor.

    Trains one XGBRegressor(objective="reg:quantileerror") per horizon using
    the same expanding training window as the ensemble.  No WFA fold loop is
    needed — quantile models have no weights to compute, so a direct fit on
    the full training window is sufficient.

    Predicts log(RV) at quantile ``tau``, then exp()-s to annualised vol.
    Because log() is monotone, P_tau(log RV) = log(P_tau(RV)).

    Calibration check (run in audit / analysis):
        coverage = mean(y_true > y_pred_q{int(tau*100)})
        Perfect calibration: coverage ≈ 1 - tau   (e.g. 0.15 for tau=0.85)

    Requirements: XGBoost >= 2.0 (reg:quantileerror + quantile_alpha).
    """

    def __init__(self, config: ModelConfig, tau: float = 0.85):
        self.config   = config
        self.tau      = tau
        self.horizons = config.horizons
        self._models:  Dict[int, xgb.XGBRegressor] = {}
        self._scaler:  Optional[StandardScaler]     = None

    def _make_xgb(self) -> xgb.XGBRegressor:
        params = dict(self.config.xgb_params)
        params["objective"]      = "reg:quantileerror"
        params["quantile_alpha"] = self.tau
        # Reuse the GPU flag already resolved by EnsembleVolModel._init_models()
        if params.get("device") == "cuda" and not EnsembleVolModel._gpu_available:
            params["device"] = "cpu"
        return xgb.XGBRegressor(**params)

    def fit(self, X: pd.DataFrame, y_dict: Dict[int, pd.Series]) -> None:
        """
        Fit one quantile XGB per horizon on the full training window.

        A single StandardScaler is fitted on X (all rows) and shared across
        horizons, matching the ensemble's final_scaler convention.
        """
        self._scaler = StandardScaler()
        X_s = self._scaler.fit_transform(X)

        for h in self.horizons:
            y = y_dict.get(h)
            if y is None:
                continue
            valid = y.notna()
            if valid.sum() < 10:
                continue
            m = self._make_xgb()
            m.fit(X_s[valid.values], y[valid].values)
            self._models[h] = m

    def predict_batch(self, X: pd.DataFrame) -> Dict[int, np.ndarray]:
        """
        Predict quantile vol for a batch of test rows.

        Returns {horizon: array_of_annualised_vol} (one value per row).
        Missing horizons (fit failed) are omitted from the dict.
        """
        if self._scaler is None or not self._models:
            return {}
        X_s = self._scaler.transform(X)
        out: Dict[int, np.ndarray] = {}
        for h, m in self._models.items():
            log_q    = np.clip(m.predict(X_s), -5, 5)
            out[h]   = np.exp(log_q)
        return out

    def save(self, path) -> None:
        """Serialize the fitted quantile model to *path*."""
        import joblib
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({
            "models": self._models,
            "scaler": self._scaler,
            "config": self.config,
            "tau":    self.tau,
        }, path)

    @classmethod
    def load(cls, path) -> "QuantileVolModel":
        """Restore a previously-saved quantile model."""
        import joblib
        state = joblib.load(path)
        obj = cls(state["config"], tau=state["tau"])
        obj._models = state["models"]
        obj._scaler = state["scaler"]
        return obj
