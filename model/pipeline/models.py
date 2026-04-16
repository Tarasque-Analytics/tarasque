"""
models.py — Ensemble volatility model with walk-forward validation.

Ported from volarbmodel_backtest.py:
    GarchForecaster  (:58-88)
    VolArbModel      (:352-466)
    SHAP explanation  (:469-514)
"""
import time
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple

from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import mean_squared_error
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LassoCV
from sklearn.ensemble import RandomForestRegressor as SklearnRF
import xgboost as xgb

# Try GPU-accelerated RF from cuML (RAPIDS); falls back to sklearn.
try:
    from cuml.ensemble import RandomForestRegressor as CumlRF
    _CUML_AVAILABLE = True
except ImportError:
    _CUML_AVAILABLE = False

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
    XGBoost + RandomForest + LassoCV ensemble with inverse-RMSE weighting.

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
        # Per-model RMSE from CV (for weight diagnostics)
        self.cv_rmse: Dict[int, Dict[str, float]] = {}

        for h in self.horizons:
            self.models[h] = self._init_models()
            self.weights[h] = {"XGB": 0.33, "RF": 0.33, "LassoCV": 0.33}
            self.rmse_scores[h] = 0.0

    _gpu_checked: bool = False
    _gpu_available: bool = False
    _cuml_rf: bool = False  # True if using cuML GPU-accelerated RF

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

            # cuML RF GPU check (one-time, paired with XGB GPU check)
            if _CUML_AVAILABLE:
                try:
                    _test_rf = CumlRF(n_estimators=2)
                    _test_rf.fit(np.array([[0.0, 1.0]], dtype=np.float32),
                                 np.array([0.0], dtype=np.float32))
                    self.__class__._cuml_rf = True
                    print("[MODEL] cuML GPU Random Forest enabled")
                except Exception as e:
                    self.__class__._cuml_rf = False
                    print(f"[MODEL] cuML RF not available ({e}) -- using sklearn RF")

        if xgb_params.get("device") == "cuda" and not self.__class__._gpu_available:
            xgb_params["device"] = "cpu"

        # RF: use cuML GPU version if available, else sklearn CPU
        if self.__class__._cuml_rf:
            rf_params = {k: v for k, v in self.config.rf_params.items() if k != "n_jobs"}
            rf = CumlRF(**rf_params)
        else:
            rf = SklearnRF(**self.config.rf_params)

        return {
            "XGB": xgb.XGBRegressor(**xgb_params),
            "RF": rf,
            "LassoCV": LassoCV(
                cv=TimeSeriesSplit(n_splits=3), max_iter=10000,
                n_jobs=getattr(self.config, "lasso_n_jobs", -1),
                alphas=20,  # 20-point grid (default 100); sklearn 1.7+ uses alphas= not n_alphas=
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
            Subset of ["XGB", "RF", "LassoCV"] for ablation studies.
        """
        splits = splits or self.config.wfa_splits
        if model_names is None:
            model_names = ["XGB", "RF", "LassoCV"]

        self.predictors = list(X.columns)

        print(f"[MODEL] Training Term Structure Anchors {self.horizons}...")
        tscv = TimeSeriesSplit(n_splits=splits)

        lam = self.config.exp_weight_lambda

        # 1. FINAL SCALER — fit on all data (backtest :394-396)
        self.final_scaler = StandardScaler()
        X_final_s = pd.DataFrame(
            self.final_scaler.fit_transform(X),
            columns=X.columns, index=X.index,
        )

        # Final-fit sample weights (same lambda, applied once outside horizon loop)
        if lam > 0:
            n_final = len(X_final_s)
            raw_w_final = np.exp(lam * np.arange(n_final))
            final_sample_weights = raw_w_final / raw_w_final.mean()
        else:
            final_sample_weights = None

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

                # Exponential sample weights: recent rows get higher weight.
                # w_i = exp(lambda * i), i=0 oldest, i=N-1 newest.
                # Normalised so mean weight = 1.0 (preserves effective sample size signal).
                if lam > 0:
                    n_tr = len(X_tr_s)
                    raw_w = np.exp(lam * np.arange(n_tr))
                    fold_sample_weights = raw_w / raw_w.mean()
                else:
                    fold_sample_weights = None

                for name in model_names:
                    _t = time.perf_counter()
                    # cuML RF doesn't support sample_weight; XGB always does
                    sw_ok = name == "XGB" or (name == "RF" and not self.__class__._cuml_rf)
                    if fold_sample_weights is not None and sw_ok:
                        self.models[h][name].fit(X_tr_s, y_tr, sample_weight=fold_sample_weights)
                    else:
                        self.models[h][name].fit(X_tr_s, y_tr)
                    self.__class__._profile[name] = self.__class__._profile.get(name, 0) + (time.perf_counter() - _t)
                    if name == "LassoCV":
                        _lasso = self.models[h]["LassoCV"]
                        self.lasso_log.append({
                            "horizon": h, "stage": "fold", "fold": _fold,
                            "alpha": float(_lasso.alpha_),
                            "coefs": _lasso.coef_.tolist(),
                        })
                    log_preds = np.clip(self.models[h][name].predict(X_te_s), -5, 5)
                    preds_lin = np.exp(log_preds)
                    y_te_lin = np.exp(np.clip(y_te.values, -5, 5))
                    rmse = np.sqrt(mean_squared_error(y_te_lin, preds_lin))
                    errors[name].append(rmse)

            # 3. INVERSE-RMSE WEIGHTING (backtest :430-434)
            avg_rmse = {n: np.mean(e) for n, e in errors.items()}
            self.cv_rmse[h] = dict(avg_rmse)
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
            for name in model_names:
                sw_ok = name == "XGB" or (name == "RF" and not self.__class__._cuml_rf)
                if final_sample_weights is not None and sw_ok:
                    self.models[h][name].fit(X_final_s, y, sample_weight=final_sample_weights)
                else:
                    self.models[h][name].fit(X_final_s, y)
                if name == "LassoCV":
                    _lasso = self.models[h]["LassoCV"]
                    self.lasso_log.append({
                        "horizon": h, "stage": "final", "fold": -1,
                        "alpha": float(_lasso.alpha_),
                        "coefs": _lasso.coef_.tolist(),
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

    def predict_curve_batch_detailed(
        self, features: pd.DataFrame,
    ) -> Tuple[Dict[int, np.ndarray], Dict[int, Dict[str, np.ndarray]]]:
        """
        Batch prediction returning both blended and per-model predictions.

        Returns
        -------
        blended : {horizon: array of blended vol forecasts}
        per_model : {horizon: {model_name: array of vol forecasts}}
        """
        feat_s = self.final_scaler.transform(features)
        feat_df = pd.DataFrame(feat_s, columns=features.columns)

        blended: Dict[int, np.ndarray] = {}
        per_model: Dict[int, Dict[str, np.ndarray]] = {}

        for h in self.horizons:
            model_preds = {}
            for name in self.weights[h]:
                log_preds = np.clip(self.models[h][name].predict(feat_df), -5, 5)
                model_preds[name] = np.exp(log_preds)

            blended_log = sum(
                np.log(np.clip(model_preds[name], 1e-8, None)) * self.weights[h][name]
                for name in self.weights[h]
            )
            blended[h] = np.exp(np.clip(blended_log, -5, 5))
            per_model[h] = model_preds

        return blended, per_model

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
