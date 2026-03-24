import os
import time
import json
import shap
from matplotlib import ticker
import numpy as np
import pandas as pd
import xgboost as xgb
from datetime import datetime, date, timedelta
from pathlib import Path
from dotenv import load_dotenv
from arch import arch_model 
from scipy.stats import norm
from scipy.optimize import brentq

# --- SKLEARN IMPORTS ---
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import mean_squared_error
from sklearn.linear_model import LassoCV
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import StandardScaler

# --- ALPACA IMPORTS ---
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.historical.option import OptionHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, OptionSnapshotRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.data.enums import Adjustment
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetOptionContractsRequest

import yfinance as yf 
from scipy.interpolate import PchipInterpolator

def clean_num(val, decimals=2):
    """
    Sanitizes float inputs for JSON serialization.
    Converts NaN/Inf -> None (which becomes 'null' in JSON).
    Rounds valid numbers to 'decimals'.
    """
    if val is None or pd.isna(val) or np.isinf(val):
        return None
    return round(float(val), decimals)

# --- CONFIGURATION ---
env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path)

def require_env(name: str) -> str:
    value = os.getenv(name)
    if value is None:
        raise EnvironmentError(f"Environment variable '{name}' is required but not set.")
    return value

ALPACA_API_KEY = require_env('ALPACA_API_KEY')
ALPACA_SECRET_KEY = require_env('ALPACA_SECRET_KEY')

# --- CLASS 1: GARCH FORECASTER ---
class GarchForecaster:
    @staticmethod
    def fit_predict(returns, horizon=21):
        """
        Fits a GARCH(1,1) with Skewed T-distribution.
        Returns: (Annualized Vol Forecast, Current Conditional Vol)
        """
        # Scale returns to percentage (e.g., 0.01 -> 1.0) for optimizer stability
        scaled_ret = returns * 100.0
        
        try:
            model = arch_model(scaled_ret, vol='Garch', p=1, q=1, dist='skewt', rescale=False)
            res = model.fit(disp='off', show_warning=False)
            
            # Forecast variance over horizon
            forecast = res.forecast(horizon=horizon)
            var_forecast = forecast.variance.iloc[-1].values
            
            # Average daily variance -> Annualized Vol
            avg_daily_var = np.mean(var_forecast)
            daily_vol = np.sqrt(avg_daily_var) / 100.0
            annualized_vol = daily_vol * np.sqrt(252)
            
            current_cond_vol = res.conditional_volatility.iloc[-1] / 100.0 * np.sqrt(252)
            return annualized_vol, current_cond_vol
            
        except Exception as e:
            print(f"[WARN] GARCH fit failed: {e}. Defaulting to naive volatility.")
            naive_vol = returns.std() * np.sqrt(252)
            return naive_vol, naive_vol

# --- CLASS 2: EVENT CALENDAR ---
class EventCalendar:
    def __init__(self):
        self.fomc_dates = [
            "2025-12-17", "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
            "2026-07-29", "2026-09-16", "2026-11-04", "2026-12-16"
        ]
        self.fomc_dates = sorted([datetime.strptime(d, "%Y-%m-%d").date() for d in self.fomc_dates])

    def get_days_to_fomc(self, target_date):
        if isinstance(target_date, datetime): target_date = target_date.date()
        future = [d for d in self.fomc_dates if d >= target_date]
        if not future: return 100 
        return (future[0] - target_date).days

    def get_hist_earnings(self, ticker):
        try:
            df = yf.Ticker(ticker).get_earnings_dates()
            if df is None or df.empty: return []
            return [t.date() for t in df.index]
        except: return []

    def get_next_earnings(self, ticker):
        try:
            t = yf.Ticker(ticker)
            cal = t.calendar
            if cal is None: return None, 100
            
            # Extract dates safely (Handling new/old yfinance versions)
            dates = []
            if isinstance(cal, dict):
                dates = cal.get('Earnings Date', [])
                if not dates: dates = cal.get('Earnings High', []) 
            elif isinstance(cal, pd.DataFrame) and not cal.empty:
                dates = cal.iloc[0].tolist()
            
            future_dates = []
            for d in dates:
                if hasattr(d, "date"): d = d.date()
                if d >= date.today(): future_dates.append(d)
                
            if future_dates:
                return sorted(future_dates)[0], (sorted(future_dates)[0] - date.today()).days
            return None, 100
        except Exception as e:
            print(f"[WARN] Earnings fetch failed: {e}")
            return None, 100

# --- CLASS 3: DATA INGESTION ---
class DataIngestion:
    def __init__(self):
        self.stock_client = StockHistoricalDataClient(ALPACA_API_KEY, ALPACA_SECRET_KEY)
        self.trade_client = TradingClient(ALPACA_API_KEY, ALPACA_SECRET_KEY, paper=True)
        self.option_client = OptionHistoricalDataClient(ALPACA_API_KEY, ALPACA_SECRET_KEY)
        
        self.factor_data = [
             "VIXY", "HYG", "USO"
             "TLT", "UUP", "SPY"
        ]

    def fetch_risk_free_rate(self):
        """Fetches the 3-Month Treasury Bill Rate (^IRX)."""
        try:
            ticker = yf.Ticker("^IRX")
            hist = ticker.history(period="5d")
            if not hist.empty:
                rate = hist["Close"].iloc[-1] / 100.0 
                print(f"[RATES] Risk-Free Rate set to: {rate:.2%}")
                return rate
        except Exception as e:
            print(f"[WARN] Rate fetch failed ({e}). Defaulting to 4.5%")
        return 0.045
                            
    def fetch_data(self, ticker, lookback_days=3000):
        print(f"\n[DATA] Pulling Data for {ticker}...")
        symbols = [ticker] + self.factor_data
        start_dt = datetime.now() - timedelta(days=lookback_days)

        req = StockBarsRequest(
            symbol_or_symbols=symbols, timeframe=TimeFrame.Day,
            start=start_dt, limit=None, adjustment=Adjustment.ALL, feed="sip"
        )
        try: 
            bars = self.stock_client.get_stock_bars(req).df
        except Exception as e:
            print(f"[ERROR] Alpaca API: {e}")
            return pd.DataFrame()
            
        if bars.empty: return pd.DataFrame()
        
        bars = bars.reset_index()
        closes = bars.pivot(index="timestamp", columns="symbol", values="close").ffill()
        highs = bars.pivot(index="timestamp", columns="symbol", values="high").ffill()
        lows = bars.pivot(index="timestamp", columns="symbol", values="low").ffill()
        opens = bars.pivot(index="timestamp", columns="symbol", values="open").ffill()
        
        if ticker not in closes.columns: return pd.DataFrame()

        df = pd.DataFrame(index=closes.index)
        df[f"close_{ticker}"] = closes[ticker]
        
        # --- EVENT FEATURES ---
        calendar = EventCalendar()
        df["date_obj"] = df.index.date
        df["days_to_fomc"] = df["date_obj"].apply(calendar.get_days_to_fomc)
        df["event_fed_gravity"] = 1.0 / (df["days_to_fomc"] + 1)
        
        # Earnings Gravity
        earn_dates = calendar.get_hist_earnings(ticker)
        if earn_dates:
            earn_df = pd.DataFrame({"earn_date": pd.to_datetime(earn_dates)}).sort_values("earn_date")
            earn_df["earn_date"] = pd.to_datetime(earn_df["earn_date"])
            if earn_df["earn_date"].dt.tz is not None:
                earn_df["earn_date"] = earn_df["earn_date"].dt.tz_localize(None)
            
            df["temp_ts"] = pd.to_datetime(df.index)
            if df["temp_ts"].dt.tz is not None:
                df["temp_ts"] = df["temp_ts"].dt.tz_localize(None)

            merged = pd.merge_asof(
                df, earn_df, left_on="temp_ts", right_on="earn_date", direction="forward"
            )
            merged["days_to_earn"] = (merged["earn_date"] - merged["temp_ts"]).dt.days
            merged["days_to_earn"] = merged["days_to_earn"].fillna(100)
            df["event_earn_gravity"] = 1.0 / (merged["days_to_earn"].clip(0, 30) + 1).values
        else:
            df["event_earn_gravity"] = 0.0
            
        # Garman-Klass Volatility
        log_hl = np.log(highs[ticker] / lows[ticker])
        log_co = np.log(closes[ticker] / opens[ticker])
        gk_var = 0.5 * (log_hl**2) - (2 * np.log(2) - 1) * (log_co**2)
        
        df["rv_TARGET"] = np.sqrt(gk_var.rolling(window=21).mean()) * np.sqrt(252)
        df["ret_TARGET"] = np.log(closes[ticker] / closes[ticker].shift(1))

        # Technicals
        delta = closes[ticker].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / (loss + 1e-9)
        df["tech_RSI"] = 100 - (100 / (1 + rs))
        
        tr1 = highs[ticker] - lows[ticker]
        tr2 = abs(highs[ticker] - closes[ticker].shift(1))
        tr3 = abs(lows[ticker] - closes[ticker].shift(1))
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        df["tech_ATR"] = tr.rolling(14).mean() / closes[ticker]

        for sym in self.factor_data:
            if sym in closes.columns:
                df[f"ret_{sym}"] = np.log(closes[sym] / closes[sym].shift(1))
        
        df = df.dropna()
        df = df.drop(columns=["date_obj", "temp_ts"], errors="ignore")
        df.index = df.index.date
        print(f"[DATA] Success. {len(df)} rows ready.")
        return df

    def fetch_option_chain(self, ticker, spot_price, min_dte=25, max_dte=50):
        print(f"[CHAIN] Hunting for LIVE {ticker} options ({min_dte}-{max_dte} DTE)...")
    
        try:
            req = GetOptionContractsRequest(
                underlying_symbols=[ticker],
                status='active',
                expiration_date_gte=date.today() + timedelta(days=min_dte),
                expiration_date_lte=date.today() + timedelta(days=max_dte),
                limit=1000
            )
            res = self.trade_client.get_option_contracts(req)
            contracts = res.option_contracts
        except Exception as e:
            print(f"[ERROR] Contract Search: {e}")
            return pd.DataFrame()

        if not contracts:
            print("[CHAIN] No contracts found.")
            return pd.DataFrame()

        print(f"[CHAIN] Found {len(contracts)} active contracts. Snapshotting in chunks...")

        all_snaps = []
        chunk_size = 75
        symbols = [c.symbol for c in contracts]

        for i in range(0, len(symbols), chunk_size):
            chunk = symbols[i:i + chunk_size]
            try:
                snap_req = OptionSnapshotRequest(symbol_or_symbols=chunk)
                snaps = self.option_client.get_option_snapshot(snap_req)

                for sym, snap in snaps.items():          # snaps is always dict[str, OptionsSnapshot]
                    if snap is None:
                        continue

                    c_det = next((x for x in contracts if x.symbol == sym), None)
                    if not c_det:
                        continue

                
                    bid = snap.latest_quote.bid_price if snap.latest_quote else 0.0
                    ask = snap.latest_quote.ask_price if snap.latest_quote else 0.0
                    last = snap.latest_trade.price if snap.latest_trade else 0.0

                
                    iv = getattr(snap, 'implied_volatility', 0.0)
                    if iv == 0.0 and hasattr(snap, 'greeks') and snap.greeks:
                        iv = getattr(snap.greeks, 'implied_volatility', getattr(snap.greeks, 'iv', 0.0))

                    # === MID PRICE ===
                    mid = 0.0
                    if bid > 0 and ask > 0:
                        mid = (bid + ask) / 2
                    elif last > 0:
                        mid = last

                    # === MARKET GREEKS ===
                    greeks_dict = {}
                    if hasattr(snap, 'greeks') and snap.greeks is not None:
                        g = snap.greeks
                        greeks_dict = {
                            "delta": clean_num(getattr(g, 'delta', None), 4),
                            "gamma": clean_num(getattr(g, 'gamma', None), 6),
                            "vega":  clean_num(getattr(g, 'vega', None), 4),
                            "theta": clean_num(getattr(g, 'theta', None), 4),
                            "rho":   clean_num(getattr(g, 'rho', None), 4),
                        }

                    # === OPEN INTEREST ===
                    oi = None
                    if hasattr(c_det, 'open_interest') and c_det.open_interest is not None:
                        try:
                            oi = int(c_det.open_interest)
                        except (ValueError, TypeError):
                            oi = None

                    # === APPEND EVERY VALID SNAPSHOT (this fixes the empty list) ===
                    # We include even zero-mid contracts so your JSON always has data.
                    # The pricing loop already skips mkt_iv == 0 or mkt == 0.
                    all_snaps.append({
                        "symbol": sym,
                        "type": c_det.type,
                        "strike": float(c_det.strike_price),
                        "expiry": str(c_det.expiration_date),
                        "bid": bid,
                        "ask": ask,
                        "mid": mid,
                        "last": last,
                        "mkt_iv": iv,
                        "greeks": greeks_dict,
                        "open_interest": oi,
                    })

            except Exception as e:
                print(f"[WARN] Snapshot chunk failed ({len(chunk)} symbols): {e}")
                continue

        print(f"[CHAIN] ✅ Snapshot complete → {len(all_snaps)} contracts loaded (including illiquid/after-hours).")
        return pd.DataFrame(all_snaps)

# --- CLASS 4: MODEL ---
class VolArbModel:
    def __init__(self):
        self.horizons = [21, 63, 126] 
        self.models = {} 
        self.weights = {}
        self.rmse_scores = {}
        self.feature_importance = {}
        self.predictors = []
        self.final_scaler = None
        
        for h in self.horizons:
            self.models[h] = {
                "XGB": xgb.XGBRegressor(n_jobs=-1, n_estimators=100, max_depth=4, learning_rate=0.05, reg_alpha=0.01, gamma=0.1, colsample_bytree=0.8, reg_lambda=1.0),
                "RF": RandomForestRegressor(n_jobs=-1, n_estimators=100, min_samples_leaf=5), # change leafs to 50 when we have full database in place
                "LassoCV": LassoCV(cv=TimeSeriesSplit(n_splits=3), max_iter=10000) # when we expand DB, splits must be scaled to fit growth, can make dynamic later
            }
            self.weights[h] = {"XGB": 0.33, "RF": 0.33, "LassoCV": 0.33}
            self.rmse_scores[h] = 0.0

    def prepare_features(self, df):
        d = df.copy()
        for h in self.horizons:
            raw_target = d["rv_TARGET"].rolling(h).mean().shift(-h)
            d[f"y_{h}"] = np.log(raw_target + 1e-9)
        
        d["vol_trend"] = d["rv_TARGET"] / (d["rv_TARGET"].rolling(63).mean() + 1e-9)
        d["vol_vel"] = d["rv_TARGET"].diff(5).abs()
        d["vol_of_vol"] = d["rv_TARGET"].rolling(21).std()
        
        d = d.dropna()
        self.predictors = [c for c in d.columns if "ret_" in c or "rv_" in c or "vol_" in c or "tech_" in c]
        self.predictors = [p for p in self.predictors if not p.startswith("y_")]
        
        y_dict = {h: d[f"y_{h}"] for h in self.horizons}
        return d[self.predictors], y_dict, d["vol_vel"].iloc[-1]

    def train_wfa(self, X, y_dict, splits=5):
        print(f"[MODEL] Training Term Structure Anchors {self.horizons}...")
        tscv = TimeSeriesSplit(n_splits=splits)
        
        # 1. THE FINAL SCALER
        # Fit on all available data up to today. Used ONLY for the final model fit.
        self.final_scaler = StandardScaler()
        X_final_s = pd.DataFrame(self.final_scaler.fit_transform(X), columns=X.columns, index=X.index)

        for h in self.horizons:
            y = y_dict[h]
            errors = {"XGB": [], "RF": [], "Lasso": []}
            
            # 2. THE VALIDATION LOOP
            for tr_idx, te_idx in tscv.split(X):
                X_tr, X_te = X.iloc[tr_idx], X.iloc[te_idx]
                y_tr, y_te = y.iloc[tr_idx], y.iloc[te_idx]
                
                # STRICT OUT-OF-SAMPLE SCALING: Fit only on the training fold
                fold_scaler = StandardScaler()
                X_tr_s = fold_scaler.fit_transform(X_tr)
                X_te_s = fold_scaler.transform(X_te)
                
                # Fit fold models on LOG targets
                self.models[h]["XGB"].fit(X_tr_s, y_tr)
                self.models[h]["RF"].fit(X_tr_s, y_tr)
                self.models[h]["LassoCV"].fit(X_tr_s, y_tr) # Assuming you made this change
                
                # Predict in LOG space, but exponentiate back to LINEAR space
                preds_lin_xgb = np.exp(self.models[h]["XGB"].predict(X_te_s))
                preds_lin_rf = np.exp(self.models[h]["RF"].predict(X_te_s))
                preds_lin_lasso = np.exp(self.models[h]["LassoCV"].predict(X_te_s))
                
                # Exponentiate the OOS test targets back to LINEAR space
                y_te_lin = np.exp(y_te)
                
                # Calculate True Economic RMSE
                errors["XGB"].append(np.sqrt(mean_squared_error(y_te_lin, preds_lin_xgb)))
                errors["RF"].append(np.sqrt(mean_squared_error(y_te_lin, preds_lin_rf)))
                errors["Lasso"].append(np.sqrt(mean_squared_error(y_te_lin, preds_lin_lasso)))

            # 3. CALCULATE WEIGHTS
            rmse_x, rmse_r, rmse_l = np.mean(errors["XGB"]), np.mean(errors["RF"]), np.mean(errors["Lasso"])
            inv = (1/rmse_x) + (1/rmse_r) + (1/rmse_l)
            
            self.weights[h] = {"XGB": (1/rmse_x)/inv, "RF": (1/rmse_r)/inv, "Lasso": (1/rmse_l)/inv}
            self.rmse_scores[h] = rmse_x*self.weights[h]["XGB"] + rmse_r*self.weights[h]["RF"] + rmse_l*self.weights[h]["Lasso"]
            
            # 4. FINAL FIT
            # Train the models on the fully scaled dataset for live prediction
            self.models[h]["XGB"].fit(X_final_s, y)
            self.models[h]["RF"].fit(X_final_s, y)
            self.models[h]["LassoCV"].fit(X_final_s, y)

        # 5. FEATURE IMPORTANCE
        xgb_imps = self.models[21]["XGB"].feature_importances_
        self.feature_importance = {self.predictors[i]: float(xgb_imps[i]) for i in np.argsort(xgb_imps)[::-1][:10]}

    def predict_curve(self, current_features):
        feat_s = self.final_scaler.transform(current_features)
        feat_df = pd.DataFrame(feat_s, columns=current_features.columns)
        curve = {}
        
        for h in self.horizons:
            # Predict in log space
            pred_log_xgb = self.models[h]["XGB"].predict(feat_df)[0]
            pred_log_rf = self.models[h]["RF"].predict(feat_df)[0]
            pred_log_lasso = self.models[h]["LassoCV"].predict(feat_df)[0]
            
            # Blend the LOG forecasts using your inverse-linear-RMSE weights
            blended_log_pred = (pred_log_xgb * self.weights[h]["XGB"] +
                                pred_log_rf * self.weights[h]["RF"] +
                                pred_log_lasso * self.weights[h]["Lasso"])
            
            # Convert final blended forecast back to LINEAR space
            curve[h] = np.exp(blended_log_pred)
            
        return curve

    

    def explain_prediction(self, current_features, horizon=21):
        """
        Calculates SHAP values for the current day's features.
        Returns the data dictionary required for the web app's Force Plot.
        """
        # 1. Scale today's features using the WFA-fitted scaler
        feat_s = self.final_scaler.transform(current_features)
        feat_df = pd.DataFrame(feat_s, columns=current_features.columns)

        # 2. Extract the dominant tree model from the ensemble
        # SHAP TreeExplainer requires a tree architecture (XGBoost/RandomForest)
        tree_model = None
        model_name = ""
        for name, model in self.models[horizon].items():
            if hasattr(model, "feature_importances_"): 
                tree_model = model
                model_name = name
                break

        if tree_model is None:
            return {"error": "No tree-based model found in the ensemble for SHAP extraction."}

        # 3. Calculate SHAP Values
        explainer = shap.TreeExplainer(tree_model)
        shap_values = explainer.shap_values(feat_df)

        # 4. Extract the Base Value safely
        base_value = explainer.expected_value
        if isinstance(base_value, np.ndarray):
            base_value = base_value[0]
            
        # 5. Map values to feature names and sort by absolute impact
        feature_names = self.predictors
        # shap_values for a single prediction is a 2D array, we want the first row
        impacts = {feature_names[i]: float(shap_values[0][i]) for i in range(len(feature_names))}
        
        # Sort by the absolute magnitude to find the top 10 market drivers today
        top_impacts = dict(sorted(impacts.items(), key=lambda item: abs(item[1]), reverse=True)[:10])

        # 6. JSON Payload for the Web Developer
        return {
            "horizon": horizon,
            "anchor_model": model_name,
            "base_value_log": float(base_value),
            "shap_values": top_impacts
        }

# --- CLASS 5: MATH ---
class QuantLib:
    @staticmethod
    def bs_price(S, K, T, r, sigma, type_="call"):
        if T <= 1e-5: return max(0, S - K) if type_ == "call" else max(0, K - S)
        d1 = (np.log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*np.sqrt(T))
        d2 = d1 - sigma*np.sqrt(T)
        if type_ == "call":
            return S * norm.cdf(d1) - K * np.exp(-r*T) * norm.cdf(d2)
        else:
            return K * np.exp(-r*T) * norm.cdf(-d2) - S * norm.cdf(-d1)

    @staticmethod
    def monte_carlo_cone(S0, sigma, T, rmse_vol, n_sims=500):
        r = 0.0359
        steps = int(T * 252)
        if steps < 5: steps = 5
        dt = T / steps
        paths = np.zeros((n_sims, steps + 1))
        paths[:, 0] = S0
        for t in range(1, steps + 1):
            shock_vol = np.maximum(0.01, sigma + np.random.normal(0, rmse_vol, n_sims))
            z = np.random.standard_normal(n_sims)
            paths[:, t] = paths[:, t-1] * np.exp((r - 0.5 * shock_vol**2) * dt + shock_vol * np.sqrt(dt) * z)
        
        p95 = np.percentile(paths, 95, axis=0)
        p05 = np.percentile(paths, 5, axis=0)
        mean_path = np.mean(paths, axis=0)
        return {
            "p95": p95.tolist(), "p05": p05.tolist(), "mean": mean_path.tolist(), "steps": list(range(steps + 1))
        }, p05[-1]
    
# --- CLASS 6: HEDGE ENGINE ---
class HedgeLab:
    @staticmethod
    def cook_recipe(df, target_ticker, factors):
        factor_cols = [f"ret_{f}" for f in factors if f"ret_{f}" in df.columns]
        target_col = "ret_TARGET"
        if not factor_cols or target_col not in df.columns: return {}

        hedge_model = LassoCV(alphas=[0.0005], fit_intercept=False, positive=False)
        X = df[factor_cols]
        y = df[target_col]
        hedge_model.fit(X, y)
        
        recipe = {}
        for factor, coef in zip(factors, hedge_model.coef_):
            if abs(coef) > 0.01: recipe[factor] = round(-coef, 4)
        return dict(sorted(recipe.items(), key=lambda item: abs(item[1]), reverse=True))

# --- EXECUTION PIPELINE ---
def run_analysis(ticker, lookback=1200):
    print("\n" + "="*50)
    print(f"   TARASQUE ENGINE v2.6 (STABILIZED) | TARGET: {ticker}")
    print("="*50)
    
    engine = DataIngestion()
    df = engine.fetch_data(ticker, lookback_days=lookback)
    if df.empty: return

    # 1. RATES
    r_free = engine.fetch_risk_free_rate()

    # 2. ML MODEL
    model = VolArbModel()
    X, y_dict, current_vol_vel = model.prepare_features(df)
    current_price = df[f"close_{ticker}"].iloc[-1]

    print(f"[INFO] Training Data: {len(X)} samples | {len(model.predictors)} features")
    model.train_wfa(X, y_dict, splits=5)

    # 3. GARCH
    print("[MODEL] Fitting GARCH(1,1) Skew-T...")
    returns = df[f"ret_TARGET"].dropna()
    garch_vol_21d, _ = GarchForecaster.fit_predict(returns, horizon=21)

    # 4. FORECAST
    current_features = X.iloc[[-1]].copy()
    ev_cal = EventCalendar()
    next_earn_date, earn_days = ev_cal.get_next_earnings(ticker)
    if earn_days < 14:
        print("[ADJUST] Earnings imminent. Boosting volatility gravity.")
        current_features["event_fed_gravity"] = max(
            current_features["event_fed_gravity"].iloc[0], 1.0 / (earn_days + 1)
        )
    
    rv_curve = model.predict_curve(current_features)
    print(f"[FORECAST] GARCH (21d): {garch_vol_21d:.2%} | ML (21d): {rv_curve[21]:.2%}")

    shap_payload = model.explain_prediction(current_features, horizon=21)
    if "error" in shap_payload:
        print(f"[SHAP] Explanation Error: {shap_payload['error']}")
    else:
        print(f"\n[SHAP DIAGNOSTICS] Top volatility drivers today for {ticker} (21d):")
        print(f"Anchor Model: {shap_payload['anchor_model']}")
        print(f"Base Log-Vol: {shap_payload['base_value_log']:.4f}")
        print("-" * 45)

        # Iterate through the dictionary to create a clean visual leaderboard
        for feature, impact in shap_payload['shap_values'].items():
            # Force a '+' sign for positive numbers to make directional impact obvious
            sign = "+" if impact > 0 else ""
        print(f"{feature:<25} | Impact: {sign}{impact:.4f}")
        
        print("-" * 45 + "\n")
    # 5. FAIR VOL & WEDGE
    fair_atm_vol = 0.25 * garch_vol_21d + 0.75 * rv_curve[21]
    
    x_anchors = [21, 63, 126]
    y_anchors = [rv_curve[21], rv_curve[63], rv_curve[126]]
    vol_term_structure = PchipInterpolator(x_anchors, y_anchors)
    chain = engine.fetch_option_chain(ticker, spot_price=current_price, min_dte=1, max_dte=300)
    opportunities = []
    avg_mkt_iv = 0.0
    vrp_wedge = 0.0
    global_z_score = 0.0

    target_dte = 21 

    import pandas as pd
    import re

    # If the OCC symbol is the index, move it to a column temporarily
    if 'symbol' not in chain.columns:
        chain = chain.reset_index(names='symbol')

    # The OCC format contains a 6-digit date (YYMMDD) right before the 'C' or 'P'
    # Extract that string, convert to datetime, and calculate DTE
    chain['expiration_date'] = pd.to_datetime(chain['symbol'].str.extract(r'(\d{6})[CP]', expand=False), format='%y%m%d')
    chain['days_to_expiration'] = (chain['expiration_date'] - pd.Timestamp.today().normalize()).dt.days
    chain['dte_distance'] = (chain['days_to_expiration'] - target_dte).abs()
    
    # Assuming your fair_atm_vol is your 21-day prediction

    # 1. Ensure Alpaca's expiration_date is a pandas datetime object
    chain['expiration_date'] = pd.to_datetime(chain['expiration_date'])

    # 2. Calculate the raw DTE integer against today's date
    chain['days_to_expiration'] = (chain['expiration_date'] - pd.Timestamp.today().normalize()).dt.days

    # 3. Now your original wedge math will execute
    chain['dte_distance'] = (chain['days_to_expiration'] - target_dte).abs()

    

    if not chain.empty:
        # 1. Lock the Term Structure: Find the expiration date closest to your model's target
        chain['dte_distance'] = (chain['days_to_expiration'] - target_dte).abs()
        best_dte = chain.sort_values('dte_distance').iloc[0]['days_to_expiration']
        
        # Isolate the chain to ONLY contracts on that specific expiration date
        time_filtered_chain = chain[chain['days_to_expiration'] == best_dte]

        # 2. Lock the Moneyness: Find the ATM contracts for that specific date
        atm_contracts = time_filtered_chain[
            (time_filtered_chain['strike'] >= current_price * 0.98) & 
            (time_filtered_chain['strike'] <= current_price * 1.02)
        ]
    
        # 3. Calculate the Market IV
        if not atm_contracts.empty: 
            mkt_atm_vol = atm_contracts['mkt_iv'].median()
        else:
            # Fallback: Grab the 4 closest strikes on that specific expiration date
            closest = time_filtered_chain.iloc[(time_filtered_chain['strike'] - current_price).abs().argsort()[:4]]
            mkt_atm_vol = closest['mkt_iv'].median()
            
        # 4. Calculate the localized Wedge
        avg_mkt_iv = mkt_atm_vol
        vrp_wedge = mkt_atm_vol - fair_atm_vol
        
        # Print the diagnostics so you can verify the DTE match
        print(f"[PRICING] Target DTE: {target_dte} | Matched DTE: {best_dte}")
        print(f"[PRICING] Market ATM: {mkt_atm_vol:.2%} | Fair ATM: {fair_atm_vol:.2%} | Wedge: {vrp_wedge:.2%}")

        # Stabilized Z-Score
        norm_velocity = min(abs(float(current_vol_vel)), 1.0)
        base_uncertainty = model.rmse_scores[21]
        regime_penalty = 1.0 + (2.0 * norm_velocity)
        adjusted_uncertainty = base_uncertainty * regime_penalty
        global_z_score = vrp_wedge / adjusted_uncertainty
        
        print(f"[RISK] Vel: {norm_velocity:.2f} | Penalty: {regime_penalty:.2f}x | Z-Score: {global_z_score:.2f}")

        # Pricing Loop
        print("[PRICING] Running Parallel-Shift Pricing...")
        for _, row in chain.iterrows():
    
            # 1. Expiry & Time to Maturity (T)
            try: 
                expiry_dt = datetime.strptime(row['expiry'], "%Y-%m-%d").date()
            except Exception: 
                continue
        
            dte = (expiry_dt - date.today()).days
            if dte < 1: 
                continue
            T = dte / 365.0

            mkt_iv = row['mkt_iv']
            if mkt_iv == 0: 
                continue

            # 2. INTERPOLATION (Monotonic Cubic Spline)
            if dte <= 21:
                model_vol_interp = rv_curve[21]
            elif dte >= 126:
                model_vol_interp = rv_curve[126]
            else:
                model_vol_interp = float(vol_term_structure(dte))

            # 3. PER-CONTRACT Z-SCORE
            term_z_score = (mkt_iv - model_vol_interp) / adjusted_uncertainty

            # 4. PRICING
            fair_vol_strike = mkt_iv - vrp_wedge
            fair_vol_strike = max(0.01, fair_vol_strike)

            theo_price = QuantLib.bs_price(
                S=current_price, K=row['strike'], T=T, r=r_free, 
                sigma=fair_vol_strike, type_=row['type']
            )

            # 5. LIQUIDITY MEASURE
            bid = row.get('bid', 0.0)
            ask = row.get('ask', 0.0)
            spread_pct = 0.0
            liquidity_status = "ILLIQUID"
    
            if ask > 0:
                spread_pct = (ask - bid) / ask
                if spread_pct <= 0.02: liquidity_status = "HIGH"
                elif spread_pct <= 0.05: liquidity_status = "MEDIUM"
                else: liquidity_status = "LOW"

            # 6. MONEYNESS CHECK
            moneyness = row['strike'] / current_price
            is_deep = (moneyness < 0.85 or moneyness > 1.15)
    
            # 7. TRADE LOGIC
            mkt = row.get('mid', 0.0)
            edge = 0.0
            action = "WATCH" 
    
            if mkt > 0:
                if theo_price > mkt:
                    edge = (theo_price - mkt) / mkt
                    if liquidity_status == "LOW": action = "PASS_Liquidity"
                    elif is_deep: action = "PASS_DeepITM"
                    elif edge > 0.10 and term_z_score < -1.5: action = "BUY_VOL_CHEAP"
                    elif edge > 0.05: action = "LEAN_LONG"
            
                elif theo_price < mkt:
                    edge = (mkt - theo_price) / mkt
                    if liquidity_status == "LOW": action = "PASS_Liquidity"
                    elif is_deep: action = "PASS_StockSub" 
                    elif edge > 0.10 and term_z_score > 1.5: action = "SELL_VOL_RICH"
                    elif edge > 0.05: action = "LEAN_SHORT"

            # 8. JSON STRUCTURE UPDATE
            # Safely using .get() with defaults to prevent KeyErrors on missing data
            opportunities.append({
                "symbol": row['symbol'], 
                "type": row['type'], 
                "strike": float(row['strike']), 
                "expiry": row['expiry'], 
        
                "mkt_px": clean_num(mkt, 2), 
                "model_px": clean_num(theo_price, 2),
                "edge_pct": clean_num(edge*100, 1), 
                "spread_pct": clean_num(spread_pct*100, 1), 
        
                "liquidity": liquidity_status,          
                "action": action, 
        
                "iv": clean_num(mkt_iv, 4), 
                "fair_vol": clean_num(fair_vol_strike, 4),
                "z_score": clean_num(term_z_score, 2),

                "open_interest": clean_num(row.get("open_interest", 0), 0),
                "bid_size": clean_num(row.get("bid_size", 0), 0),
                "ask_size": clean_num(row.get("ask_size", 0), 0),
            })
        opportunities = sorted(opportunities, key=lambda x: abs(x['edge_pct']), reverse=True)
        print(f"[SCAN] Processed {len(opportunities)} contracts.")

    # 6. PAYLOAD
    print("[HEDGE] Cooking optimal hedge basket...")
    hedge_recipe = HedgeLab.cook_recipe(df, ticker, engine.factor_data)
    
    chart_data, tail_risk = QuantLib.monte_carlo_cone(
        current_price, rv_curve[21], 30/365, model.rmse_scores[21]
    )

    payload = {
        "meta": {
            "ticker": ticker,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "spot_price": round(current_price, 2),
            "forecast_rv": {k: round(v, 4) for k, v in rv_curve.items()},
            "garch_21d": clean_num(garch_vol_21d, 4),
            "market_iv_atm": round(avg_mkt_iv, 4),
            "vrp_wedge": clean_num(vrp_wedge, 4),
            "z_score_stabilized": clean_num(global_z_score, 2),
            "tail_risk_95": round(tail_risk, 2)
        },
        "hedging": {"recipe": hedge_recipe, "interpretation": "Factor Hedge Positions"},
        "explainability": {"drivers": {k: round(v, 4) for k, v in model.feature_importance.items()}},
        "charts": {"monte_carlo": chart_data},
        "opportunities": opportunities 
    }

    os.makedirs("Results", exist_ok=True)
    fname = f"Results/{ticker}_Payload.json"
    with open(fname, "w") as f: json.dump(payload, f, indent=4)
    print(f"\n[SUCCESS] Dashboard generated at {fname}")

if __name__ == "__main__":
    run_analysis("NNE")

  
