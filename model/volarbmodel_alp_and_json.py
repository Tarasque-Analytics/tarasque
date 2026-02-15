import os
import time
import json
import numpy as np
import pandas as pd
import xgboost as xgb
from datetime import datetime, date, timedelta
from pathlib import Path
from dotenv import load_dotenv
from arch import arch_model

# --- SKLEARN IMPORTS ---
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import mean_squared_error
from sklearn.linear_model import Lasso
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import StandardScaler

# --- SCIPY IMPORTS ---
from scipy.stats import norm
from scipy.optimize import brentq

# --- ALPACA IMPORTS (CRITICAL) ---
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.historical.option import OptionHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, OptionSnapshotRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.data.enums import Adjustment
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetOptionContractsRequest

import yfinance as yf # Ensure this is imported

# --- HELPER 1: GARCH FORECASTER (Isolated) ---
def get_garch_vol(returns, horizon=21):
    """Safe wrapper for GARCH. If it fails, returns None so we can fallback."""
    try:
        from arch import arch_model
        # Scale to avoid optimizer errors
        scaled = returns * 100.0 
        model = arch_model(scaled, vol='Garch', p=1, q=1, dist='skewt', rescale=False)
        res = model.fit(disp='off', show_warning=False)
        var = res.forecast(horizon=horizon).variance.iloc[-1].values
        # Rescale back
        return (np.sqrt(np.mean(var)) / 100.0) * np.sqrt(252)
    except Exception as e:
        print(f"[WARN] GARCH failed: {e}")
        return None

# --- HELPER 2: RATE FETCH (Isolated) ---
def get_risk_free_rate():
    """Fetches ^IRX without touching DataIngestion class."""
    try:
        ticker = yf.Ticker("^IRX")
        # specific check to ensure we don't crash on empty data
        hist = ticker.history(period="5d")
        if not hist.empty:
            return hist["Close"].iloc[-1] / 1000.0
    except:
        pass
    return 0.045 # Default fallback

# --- CLASS: EVENT CALENDAR ---
class EventCalendar:
    def __init__(self):
        # 2025-2026 FOMC Meeting Dates (Projected/Actual)
        # These are the Wednesdays when the rate decision is announced
        self.fomc_dates = [
            "2025-12-17", 
            "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
            "2026-07-29", "2026-09-16", "2026-11-04", "2026-12-16"
        ]
        self.fomc_dates = sorted([datetime.strptime(d, "%Y-%m-%d").date() for d in self.fomc_dates])

    def get_days_to_fomc(self, target_date):
        """Returns days to next Fed meeting (0 if today)."""
        if isinstance(target_date, datetime): target_date = target_date.date()
        
        future = [d for d in self.fomc_dates if d >= target_date]
        if not future: return 100 # Default "far away" if schedule runs out
        
        return (future[0] - target_date).days

    def get_hist_earnings(self, ticker):
        """Returns a list of all known earnings dates (past and future)."""
        try:
            df = yf.Ticker(ticker).get_earnings_dates()
            if df is None or df.empty: return []
            # Index is usually timestamps
            return [t.date() for t in df.index]
        except: return []

    def get_next_earnings(self, ticker):
        """
        Fetches next earnings date from yfinance. 
        Returns (Date, Days_Until).
        """
        try:
            t = yf.Ticker(ticker)
            cal = t.calendar
            
            # CRASH FIX: Check type before asking if it's empty
            if cal is None: return None, 100
            if isinstance(cal, pd.DataFrame) and cal.empty: return None, 100
            if isinstance(cal, dict) and not cal: return None, 100
            
            # Extract dates safely
            dates = []
            if isinstance(cal, dict):
                # Handle Dict (New yfinance)
                dates = cal.get('Earnings Date', [])
                if not dates: dates = cal.get('Earnings High', []) # Fallback
            else:
                # Handle DataFrame (Old yfinance)
                dates = cal.iloc[0].tolist()
            
            # Filter for future
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

# --- CLASS 1: DATA INGESTION ---
class DataIngestion:
    def __init__(self):
        # Stock Data
        self.stock_client = StockHistoricalDataClient(ALPACA_API_KEY, ALPACA_SECRET_KEY)
        # Trading (Finding Contracts)
        self.trade_client = TradingClient(ALPACA_API_KEY, ALPACA_SECRET_KEY, paper=True)
        # Option Data (Prices/Greeks)
        self.option_client = OptionHistoricalDataClient(ALPACA_API_KEY, ALPACA_SECRET_KEY)
        
        self.factor_data = [
            "SPY", "XLK", "VIXY", "HYG", "IEI", 
            "IEF", "QQQ", "TLT", "GLD", "USO", 
            "UUP", "XLP", "XLF", "XLE", "XLV", 
            "IWM", "XLC", "IYR", "EEM", "XLI", "MCHI"
        ]

    # Inside DataIngestion class
def fetch_risk_free_rate(self):
    """
    Fetches the 3-Month Treasury Bill Rate (^IRX) to use as the risk-free rate.
    Returns float (e.g., 0.052 for 5.2%)
    """
    try:
        # ^IRX is the CBOE Interest Rate 13-Week T-Bill Index
        # The price is the yield * 10 (e.g., 52.0 = 5.2%)
        ticker = yf.Ticker("^IRX")
        hist = ticker.history(period="5d")
        if not hist.empty:
            rate = hist["Close"].iloc[-1] / 1000.0 # Convert 52 -> 0.052
            print(f"[RATES] Risk-Free Rate set to: {rate:.2%}")
            return rate
    except Exception as e:
        print(f"[WARN] Rate fetch failed ({e}). Defaulting to 4.5%")
    return 0.045
                                             
def fetch_data(self, ticker, lookback_days=1200):
    print(f"\n[DATA] Pulling Data for {ticker} (High/Low/Close)...")
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
        
        # --- EVENT FEATURES (Historical Training) ---
        calendar = EventCalendar()
        
        # 1. FOMC (Fed)
        df["date_obj"] = df.index.date
        df["days_to_fomc"] = df["date_obj"].apply(calendar.get_days_to_fomc)
        df["event_fed_gravity"] = 1.0 / (df["days_to_fomc"] + 1)
        
        # 2. Earnings (Real History)
        earn_dates = calendar.get_hist_earnings(ticker)
        if earn_dates:
            # Create a dataframe of earnings dates
            earn_df = pd.DataFrame({"earn_date": pd.to_datetime(earn_dates)}).sort_values("earn_date")
            
            # --- TIMEZONE FIX START ---
            # 1. Ensure earnings are datetime64 (sometimes list comes back as date objects)
            earn_df["earn_date"] = pd.to_datetime(earn_df["earn_date"])
            
            # 2. Strip timezone from Earnings if it exists
            if earn_df["earn_date"].dt.tz is not None:
                earn_df["earn_date"] = earn_df["earn_date"].dt.tz_localize(None)
            
            # 3. Create temp column from index
            df["temp_ts"] = pd.to_datetime(df.index)
            
            # 4. Strip timezone from Main DF if it exists (Alpaca usually sends UTC)
            if df["temp_ts"].dt.tz is not None:
                df["temp_ts"] = df["temp_ts"].dt.tz_localize(None)
            # --- TIMEZONE FIX END ---

            # MERGE ASOF: Now safe because both are naive
            merged = pd.merge_asof(
                df, earn_df, 
                left_on="temp_ts", right_on="earn_date", 
                direction="forward"
            )
            
            # Calculate Days Until
            merged["days_to_earn"] = (merged["earn_date"] - merged["temp_ts"]).dt.days
            
            # Fill NaNs with 100
            merged["days_to_earn"] = merged["days_to_earn"].fillna(100)
            
            # Gravity
            df["event_earn_gravity"] = 1.0 / (merged["days_to_earn"].clip(0, 30) + 1).values
        else:
            df["event_earn_gravity"] = 0.0
            
        # ---------------------------

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
        return dfreq = StockBarsRequest(
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
        
        # --- EVENT FEATURES (Historical Training) ---
        calendar = EventCalendar()
        
        # 1. FOMC (Fed)
        df["date_obj"] = df.index.date
        df["days_to_fomc"] = df["date_obj"].apply(calendar.get_days_to_fomc)
        df["event_fed_gravity"] = 1.0 / (df["days_to_fomc"] + 1)
        
        # 2. Earnings (Real History)
        earn_dates = calendar.get_hist_earnings(ticker)
        if earn_dates:
            # Create a dataframe of earnings dates
            earn_df = pd.DataFrame({"earn_date": pd.to_datetime(earn_dates)}).sort_values("earn_date")
            
            # --- TIMEZONE FIX START ---
            # 1. Ensure earnings are datetime64 (sometimes list comes back as date objects)
            earn_df["earn_date"] = pd.to_datetime(earn_df["earn_date"])
            
            # 2. Strip timezone from Earnings if it exists
            if earn_df["earn_date"].dt.tz is not None:
                earn_df["earn_date"] = earn_df["earn_date"].dt.tz_localize(None)
            
            # 3. Create temp column from index
            df["temp_ts"] = pd.to_datetime(df.index)
            
            # 4. Strip timezone from Main DF if it exists (Alpaca usually sends UTC)
            if df["temp_ts"].dt.tz is not None:
                df["temp_ts"] = df["temp_ts"].dt.tz_localize(None)
            # --- TIMEZONE FIX END ---

            # MERGE ASOF: Now safe because both are naive
            merged = pd.merge_asof(
                df, earn_df, 
                left_on="temp_ts", right_on="earn_date", 
                direction="forward"
            )
            
            # Calculate Days Until
            merged["days_to_earn"] = (merged["earn_date"] - merged["temp_ts"]).dt.days
            
            # Fill NaNs with 100
            merged["days_to_earn"] = merged["days_to_earn"].fillna(100)
            
            # Gravity
            df["event_earn_gravity"] = 1.0 / (merged["days_to_earn"].clip(0, 30) + 1).values
        else:
            df["event_earn_gravity"] = 0.0
            
        # ---------------------------

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

    # --- THIS WAS MISSING ---
    def fetch_option_chain(self, ticker, spot_price, min_dte=25, max_dte=50):
        """
        Fetches REAL option chain. 
        Note: 'spot_price' is accepted to satisfy the call signature.
        """
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
            print("[CHAIN] No contracts found (Check your API subscription or DTE range).")
            return pd.DataFrame()

        print(f"[CHAIN] Found {len(contracts)} contracts. Snapshotting...")

        all_snaps = []
        chunk_size = 75
        symbols = [c.symbol for c in contracts]
        
        for i in range(0, len(symbols), chunk_size):
            chunk = symbols[i:i+chunk_size]
            try:
                snap_req = OptionSnapshotRequest(symbol_or_symbols=chunk)
                # FIX 1: Singular 'snapshot' (which you likely already fixed)
                snaps = self.option_client.get_option_snapshot(snap_req)
                
                for sym, snap in snaps.items():
                    c_det = next((x for x in contracts if x.symbol == sym), None)
                    if not c_det: continue
                    
                    # Live Quotes
                    bid = snap.latest_quote.bid_price if snap.latest_quote else 0.0
                    ask = snap.latest_quote.ask_price if snap.latest_quote else 0.0
                    last = snap.latest_trade.price if snap.latest_trade else 0.0
                    
                    # SAFE GREEK EXTRACTION
                    # Tries 'implied_volatility', then 'iv', then defaults to 0.0
                    # SAFE GREEK EXTRACTION (Debug Version)
                    iv = 0.0
                    if hasattr(snap, 'greeks') and snap.greeks:
                        # Try every known alias for IV in Alpaca's library
                        iv = getattr(snap.greeks, 'implied_volatility', 
                            getattr(snap.greeks, 'iv', 0.0))
                        
                    # Fallback: Sometimes IV is at the top level in snapshots (rare but happens)
                    if iv == 0.0:
                        iv = getattr(snap, 'implied_volatility', 0.0)
                    # Robust Price Logic:
                    # 1. Prefer Mid-Price (Bid+Ask)/2
                    # 2. Fallback to Last Trade if quotes are wide/missing
                    quality = "STALE"
                    mid = 0.0
                    
                    if bid > 0 and ask > 0:
                        mid = (bid + ask) / 2
                        quality = "REALTIME"
                    elif last > 0:
                        mid = last
                        quality = "LAST_TRADE"
                    
                    if mid > 0:
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
                            "quality": quality
                        })
            except Exception as e:
                print(f"[WARN] Chunk {i} failed: {e}")
                continue
            
        return pd.DataFrame(all_snaps)
# --- CLASS 2: MODEL ---
class VolArbModel:
    def __init__(self):
        # We train on 3 'Anchor' horizons: 1 Month, 3 Months, 6 Months
        self.horizons = [21, 63, 126] 
        self.models = {} 
        self.weights = {}
        self.rmse_scores = {}
        self.feature_importance = {}
        self.predictors = []
        self.final_scaler = None
        
        # Init containers
        for h in self.horizons:
            self.models[h] = {
                "XGB": xgb.XGBRegressor(n_jobs=-1, n_estimators=100, max_depth=4, learning_rate=0.05),
                "RF": RandomForestRegressor(n_jobs=-1, n_estimators=100, min_samples_leaf=5),
                "Lasso": Lasso(alpha=0.001, max_iter=10000)
            }
            self.weights[h] = {"XGB": 0.33, "RF": 0.33, "Lasso": 0.33}
            self.rmse_scores[h] = 0.0

    from arch import arch_model

class GarchForecaster:
    @staticmethod
    def fit_predict(returns, horizon=21):
        """
        Fits a GARCH(1,1) on returns (scaled to 100 for stability)
        and forecasts variance 'horizon' days out.
        """
        # 1. Scale returns (GARCH optimizers hate small numbers like 0.001)
        # We work in "percent" space (0.1% -> 0.1)
        scaled_ret = returns * 100.0
        
        # 2. Fit GARCH(1,1) with Skewed Student's T distribution (captures fat tails)
        # 'vol="Garch"' is standard. 'dist="skewt"' handles the non-normal crash risk.
        model = arch_model(scaled_ret, vol='Garch', p=1, q=1, dist='skewt', rescale=False)
        res = model.fit(disp='off', show_warning=False)
        
        # 3. Forecast
        # Analytic forecast of variance over the next 'horizon' days
        forecast = res.forecast(horizon=horizon)
        
        # Extract the variance forecast (cumulative over horizon)
        # The forecast object returns a DataFrame, we want the last row
        var_forecast = forecast.variance.iloc[-1].values
        
        # 4. Convert back to Annualized Volatility
        # Mean variance per day over the horizon
        avg_daily_var = np.mean(var_forecast) 
        
        # Rescale back from "percent space" (divide by 100^2) and annualize
        daily_vol = np.sqrt(avg_daily_var) / 100.0
        annualized_vol = daily_vol * np.sqrt(252)
        
        return annualized_vol, res.conditional_volatility.iloc[-1] / 100.0 * np.sqrt(252)

    def prepare_features(self, df):
        d = df.copy()
        
        # Create 3 distinct Targets (Realized Vol over 21, 63, and 126 days)
        for h in self.horizons:
            # We calculate the forward volatility for EACH horizon
            # This mimics what your old model did in 'build_features'
            d[f"y_{h}"] = d["rv_TARGET"].rolling(h).mean().shift(-h)
        
        # Shared Features
        d["vol_trend"] = d["rv_TARGET"] / (d["rv_TARGET"].rolling(63).mean() + 1e-9)
        d["vol_vel"] = d["rv_TARGET"].diff(5).abs()
        d["vol_of_vol"] = d["rv_TARGET"].rolling(21).std()
        
        d = d.dropna()
        self.predictors = [c for c in d.columns if "ret_" in c or "rv_" in c or "vol_" in c or "tech_" in c]
        self.predictors = [p for p in self.predictors if not p.startswith("y_")]
        
        # Return dict of targets
        y_dict = {h: d[f"y_{h}"] for h in self.horizons}
        return d[self.predictors], y_dict, d["vol_vel"].iloc[-1]

    def train_wfa(self, X, y_dict, splits=5):
        print(f"[MODEL] Training Term Structure Anchors {self.horizons}...")
        tscv = TimeSeriesSplit(n_splits=splits)
        
        self.final_scaler = StandardScaler()
        X_final_s = pd.DataFrame(self.final_scaler.fit_transform(X), columns=X.columns, index=X.index)

        for h in self.horizons:
            y = y_dict[h]
            errors = {"XGB": [], "RF": [], "Lasso": []}
            
            # WFA for this horizon
            for tr_idx, te_idx in tscv.split(X):
                X_tr, X_te = X.iloc[tr_idx], X.iloc[te_idx]
                y_tr, y_te = y.iloc[tr_idx], y.iloc[te_idx]
                
                scaler = StandardScaler()
                X_tr_s = scaler.fit_transform(X_tr)
                X_te_s = scaler.transform(X_te)
                
                self.models[h]["XGB"].fit(X_tr_s, y_tr)
                self.models[h]["RF"].fit(X_tr_s, y_tr)
                self.models[h]["Lasso"].fit(X_tr_s, y_tr)
                
                errors["XGB"].append(np.sqrt(mean_squared_error(y_te, self.models[h]["XGB"].predict(X_te_s))))
                errors["RF"].append(np.sqrt(mean_squared_error(y_te, self.models[h]["RF"].predict(X_te_s))))
                errors["Lasso"].append(np.sqrt(mean_squared_error(y_te, self.models[h]["Lasso"].predict(X_te_s))))

            # Weighting
            rmse_x, rmse_r, rmse_l = np.mean(errors["XGB"]), np.mean(errors["RF"]), np.mean(errors["Lasso"])
            inv = (1/rmse_x) + (1/rmse_r) + (1/rmse_l)
            self.weights[h] = {"XGB": (1/rmse_x)/inv, "RF": (1/rmse_r)/inv, "Lasso": (1/rmse_l)/inv}
            self.rmse_scores[h] = rmse_x*self.weights[h]["XGB"] + rmse_r*self.weights[h]["RF"] + rmse_l*self.weights[h]["Lasso"]
            
            # Final Retrain
            self.models[h]["XGB"].fit(X_final_s, y)
            self.models[h]["RF"].fit(X_final_s, y)
            self.models[h]["Lasso"].fit(X_final_s, y)

        # Grab feature importance from the shortest horizon model
        xgb_imps = self.models[21]["XGB"].feature_importances_
        self.feature_importance = {self.predictors[i]: float(xgb_imps[i]) for i in np.argsort(xgb_imps)[::-1][:10]}

    def predict_curve(self, current_features):
        # Predicts 3 points: {21: vol, 63: vol, 126: vol}
        feat_s = self.final_scaler.transform(current_features)
        feat_df = pd.DataFrame(feat_s, columns=current_features.columns)
        
        curve = {}
        for h in self.horizons:
            pred = (self.models[h]["XGB"].predict(feat_df)[0] * self.weights[h]["XGB"] +
                    self.models[h]["RF"].predict(feat_df)[0] * self.weights[h]["RF"] +
                    self.models[h]["Lasso"].predict(feat_df)[0] * self.weights[h]["Lasso"])
            curve[h] = pred
        return curve
    # --- CLASS 3: MATH ---
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
        r = 0.045
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
            "p95": p95.tolist(),
            "p05": p05.tolist(),
            "mean": mean_path.tolist(),
            "steps": list(range(steps + 1))
        }, p05[-1]
    
# --- CLASS 4: HEDGE ENGINE ---
class HedgeLab:
    @staticmethod
    def cook_recipe(df, target_ticker, factors):
        """
        Uses Lasso to find the optimal 'Hedge Basket' for the target equity.
        Returns a dictionary suitable for a Pie Chart.
        """
        # 1. Prepare Data
        # Filter for just the return columns
        factor_cols = [f"ret_{f}" for f in factors if f"ret_{f}" in df.columns]
        target_col = "ret_TARGET" # This is MS returns
        
        if not factor_cols or target_col not in df.columns:
            return {}

        # 2. Fit Lasso (Finds the 'Beta' to each factor)
        hedge_model = Lasso(alpha=0.0005, fit_intercept=False, positive=False)
        
        X = df[factor_cols]
        y = df[target_col]
        
        hedge_model.fit(X, y)
        
        # 3. Extract Recipe
        recipe = {}
        for factor, coef in zip(factors, hedge_model.coef_):
            if abs(coef) > 0.01: 
                recipe[factor] = round(-coef, 4)
                
        # Sort by impact
        return dict(sorted(recipe.items(), key=lambda item: abs(item[1]), reverse=True))# --- EXECUTION PIPELINE (v2.4: Robust & Z-Score Aware) ---
# --- EXECUTION (v2.5: Term Structure Interpolation) ---
import os
import time
import json
import numpy as np
import pandas as pd
from datetime import datetime, date, timedelta
from arch import arch_model  # Ensure this is installed: pip install arch
from scipy.stats import norm

# --- CLASS: GARCH FORECASTER (New Engine) ---
class GarchForecaster:
    @staticmethod
    def fit_predict(returns, horizon=21):
        """
        Fits a GARCH(1,1) with Skewed T-distribution to capture tail risk.
        Returns: (Annualized Vol Forecast, Current Conditional Vol)
        """
        # Scale returns to percentage (e.g., 0.01 -> 1.0) for optimizer stability
        scaled_ret = returns * 100.0
        
        # Fit GARCH(1,1) with Skewed Student's T
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
            # Fallback: simple std dev
            naive_vol = returns.std() * np.sqrt(252)
            return naive_vol, naive_vol

# --- EXECUTION PIPELINE (Refactored) ---
def run_analysis(ticker, lookback=1200):
    print("\n" + "="*50)
    print(f"   TARASQUE ENGINE v2.6 (STABILIZED Z-SCORE) | TARGET: {ticker}")
    print("="*50)
    
    # 1. SETUP & DATA
    start_t = time.time()
    try: from volarbmodel_alp_and_json import DataIngestion, VolArbModel, QuantLib, HedgeLab, EventCalendar
    except: 
        # Fallback for local testing if classes are in same file
        pass 
        
    engine = DataIngestion()
    df = engine.fetch_data(ticker, lookback_days=lookback)
    if df.empty: return

    # 2. RATES
    r_free = engine.fetch_risk_free_rate()

    # 3. ML MODEL TRAINING
    model = VolArbModel()
    # Note: prepare_features returns current_vol_vel (the last known velocity)
    X, y_dict, current_vol_vel = model.prepare_features(df)
    current_price = df[f"close_{ticker}"].iloc[-1]

    print(f"[INFO] Training Data: {len(X)} samples | {len(model.predictors)} features")
    model.train_wfa(X, y_dict, splits=5)

    # 4. GARCH BASELINE (The "True" Center)
    print("[MODEL] Fitting GARCH(1,1) Skew-T...")
    returns = df[f"ret_{ticker}"].dropna()
    garch_vol_21d, _ = GarchForecaster.fit_predict(returns, horizon=21)

    # 5. FORECAST GENERATION
    # Prepare current features for ML prediction
    current_features = X.iloc[[-1]].copy()
    
    # --- Event Gravity Injection ---
    ev_cal = EventCalendar()
    next_earn_date, earn_days = ev_cal.get_next_earnings(ticker)
    if earn_days < 14:
        print("[ADJUST] Earnings imminent. Boosting volatility gravity.")
        current_features["event_fed_gravity"] = max(
            current_features["event_fed_gravity"].iloc[0], 
            1.0 / (earn_days + 1)
        )
    
    # Get ML Curve
    rv_curve = model.predict_curve(current_features)
    
    print(f"[FORECAST] GARCH (21d): {garch_vol_21d:.2%} | ML (21d): {rv_curve[21]:.2%}")

    # 6. CALCULATE FAIR ATM VOL
    # We blend GARCH (Statistical) and ML (Feature-based)
    # Weighting GARCH higher (60%) as it is structurally sounder
    fair_atm_vol = 0.6 * garch_vol_21d + 0.4 * rv_curve[21]

    # 7. MARKET ANALYSIS & WEDGE CALCULATION
    chain = engine.fetch_option_chain(ticker, spot_price=current_price, min_dte=1, max_dte=300)
    
    opportunities = []
    avg_mkt_iv = 0.0
    
    if not chain.empty:
        # A. Find Market ATM Volatility
        atm_contracts = chain[
            (chain['strike'] >= current_price * 0.98) & 
            (chain['strike'] <= current_price * 1.02)
        ]
        
        if not atm_contracts.empty:
            mkt_atm_vol = atm_contracts['mkt_iv'].median()
        else:
            closest = chain.iloc[(chain['strike'] - current_price).abs().argsort()[:5]]
            mkt_atm_vol = closest['mkt_iv'].median()
            
        avg_mkt_iv = mkt_atm_vol

        # B. The VRP Wedge (Signal)
        # If Market > Fair, Wedge is Positive (Sell).
        vrp_wedge = mkt_atm_vol - fair_atm_vol
        print(f"[PRICING] Market ATM: {mkt_atm_vol:.2%} | Fair ATM: {fair_atm_vol:.2%} | Wedge: {vrp_wedge:.2%}")

        # C. The Velocity Stabilizer (Risk Control)
        # Normalize velocity to 0.0 - 1.0 range to prevent infinite denominators
        norm_velocity = min(abs(float(current_vol_vel)), 1.0)
        
        # Calculate Stabilized Z-Score Denominator
        base_uncertainty = model.rmse_scores[21]
        regime_penalty = 1.0 + (2.0 * norm_velocity) # Lambda = 2.0
        adjusted_uncertainty = base_uncertainty * regime_penalty
        
        # Calculate The Global Z-Score (Does the wedge survive the regime check?)
        # If velocity is high, adjusted_uncertainty is high -> Z-score drops -> We don't trade.
        global_z_score = vrp_wedge / adjusted_uncertainty
        
        print(f"[RISK] Vel: {norm_velocity:.2f} | Penalty: {regime_penalty:.2f}x | Z-Score: {global_z_score:.2f}")

        # 8. PRICING LOOP
        print("[PRICING] Running Parallel-Shift Pricing...")
        
        for _, row in chain.iterrows():
            # Expiry setup
            try: expiry_dt = datetime.strptime(row['expiry'], "%Y-%m-%d").date()
            except: continue
            dte = (expiry_dt - date.today()).days
            if dte < 1: continue
            T = dte / 365.0

            # --- ROBUST PRICING LOGIC ---
            
            # A. Parallel Shift
            # We accept market skew, but apply our Fair Value level
            mkt_iv = row['mkt_iv']
            if mkt_iv == 0: continue
            
            fair_vol_strike = mkt_iv - vrp_wedge
            fair_vol_strike = max(0.01, fair_vol_strike) # Safety floor

            # B. Black-Scholes Price
            theo_price = QuantLib.bs_price(
                S=current_price, K=row['strike'], T=T, r=r_free, 
                sigma=fair_vol_strike, type_=row['type']
            )

            # C. Trade Logic
            mkt = row['mid']
            edge = 0.0
            action = "WATCH"
            
            if mkt > 0:
                if theo_price > mkt:
                    edge = (theo_price - mkt) / mkt
                    # Only buy if edge is high AND Z-score confirms we are in a "Cheap" regime
                    if edge > 0.05 and global_z_score < -1.0: 
                        action = "BUY_UNDERSOLD"
                elif theo_price < mkt:
                    edge = (mkt - theo_price) / mkt
                    # Only sell if edge is high AND Z-score confirms "Expensive" regime
                    if edge > 0.05 and global_z_score > 1.0: 
                        action = "SELL_OVERPRICED"

            opportunities.append({
                "symbol": row['symbol'], "type": row['type'], "strike": row['strike'],
                "expiry": row['expiry'], "mkt_px": round(mkt, 2), "model_px": round(theo_price, 2),
                "edge_pct": round(edge*100, 1), "action": action, 
                "iv": round(mkt_iv, 4), 
                "fair_vol": round(fair_vol_strike, 4),
                "z_score": round(global_z_score, 2)
            })

        opportunities = sorted(opportunities, key=lambda x: abs(x['edge_pct']), reverse=True)
        print(f"[SCAN] Processed {len(opportunities)} contracts.")

    # 9. PAYLOAD GENERATION
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
            "garch_21d": round(garch_vol_21d, 4),
            "market_iv_atm": round(avg_mkt_iv, 4),
            "vrp_wedge": round(vrp_wedge, 4),
            "z_score_stabilized": round(global_z_score, 2), # The new key metric
            "tail_risk_95": round(tail_risk, 2)
        },
        "hedging": {
            "recipe": hedge_recipe,
            "interpretation": "Hold these positions to neutralize factor exposure."
        },
        "explainability": {
            "drivers": {k: round(v, 4) for k, v in model.feature_importance.items()}
        },
        "charts": {"monte_carlo": chart_data},
        "opportunities": opportunities 
    }

    os.makedirs("Results", exist_ok=True)
    fname = f"Results/{ticker}_Payload.json"
    with open(fname, "w") as f: json.dump(payload, f, indent=4)
        
    print(f"\n[SUCCESS] Dashboard generated at {fname}")

if __name__ == "__main__":
    run_analysis("MS")