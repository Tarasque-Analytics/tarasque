import warnings
import logging
import os

from pathlib import Path
from dotenv import load_dotenv

# Load .env FIRST
env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path)

def require_env(name: str) -> str:
    val = os.getenv(name)
    if not val:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return val

# Define keys SECOND
ALPACA_API_KEY = require_env("ALPACA_API_KEY")
ALPACA_SECRET_KEY = require_env("ALPACA_SECRET_KEY")
ALPACA_BASE_URL = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

import time
import datetime
import csv
from datetime import datetime, date, timedelta
import numpy as np
import pandas as pd
import yfinance as yf
import xgboost as xgb
from scipy.stats import norm
from scipy.optimize import brentq, minimize
import matplotlib
matplotlib.use('Agg')  # Prevents the "Main thread" crash
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import seaborn as sns
from sklearn.model_selection import TimeSeriesSplit, GridSearchCV
from sklearn.metrics import mean_squared_error
from sklearn.linear_model import Lasso
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import LinearRegression
from alpaca.data.historical.option import OptionHistoricalDataClient
option_data_client = OptionHistoricalDataClient(ALPACA_API_KEY, ALPACA_SECRET_KEY)
env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path)

def require_env(name: str) -> str:
    val = os.getenv(name)
    if not val:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return val

ALPACA_API_KEY = require_env("ALPACA_API_KEY")
ALPACA_SECRET_KEY = require_env("ALPACA_SECRET_KEY")
ALPACA_BASE_URL = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

from alpaca.trading.client import TradingClient

trading_client = TradingClient(ALPACA_API_KEY, ALPACA_SECRET_KEY, paper=True)
option_data_client = OptionHistoricalDataClient(ALPACA_API_KEY, ALPACA_SECRET_KEY)

from alpaca.trading.requests import GetOptionContractsRequest
from alpaca.data.requests import OptionSnapshotRequest
from scipy.optimize import minimize
from sklearn.ensemble import RandomForestRegressor
from datetime import date
from alpaca.data.historical.option import OptionHistoricalDataClient
option_data_client = OptionHistoricalDataClient(ALPACA_API_KEY, ALPACA_SECRET_KEY)
from alpaca.data.requests import OptionChainRequest

def unpack_items(resp):
    """"
    Alpaca SDK responses vary by version:
    - list[Contract]
    - tuple(list[Contract], next_token)
    - object with .option_contracts / .contracts / .items
    """
    if resp is None:
        return []
    if isinstance(resp, tuple):
        return resp[0] if resp else []
    if isinstance(resp, list):
        return resp
    for attr in ("option_contracts", "contracts", "items"):
        if hasattr(resp, attr):
            return getattr(resp, attr) or []
    return resp  # last resort

def get_contract_symbol(contract):
    if contract is None:
        return None
    if isinstance(contract, dict):
        return contract.get("symbol") or contract.get("id")
    return getattr(contract, "symbol", None) or getattr(contract, "id", None)


# ===============================
# OPTION CHAIN ADAPTERS
# ===============================

class OptionChain:
    def __init__(self, calls: pd.DataFrame, puts: pd.DataFrame):
        self.calls = calls
        self.puts = puts


def build_chain_for_expiry(chain_df: pd.DataFrame, expiry_date):
    df = chain_df.copy()

    # Filter to expiry
    df = df[df["expiry"] == expiry_date]

    # Sanitize
    df = df.dropna(subset=["strike", "bid", "ask"])
    df["strike"] = pd.to_numeric(df["strike"], errors="coerce")
    df["bid"] = pd.to_numeric(df["bid"], errors="coerce")
    df["ask"] = pd.to_numeric(df["ask"], errors="coerce")

    # Split calls / puts
    calls = (
        df[df["type"].str.lower() == "call"]
        [["strike", "bid", "ask"]]
        .sort_values("strike")
        .reset_index(drop=True)
    )

    puts = (
        df[df["type"].str.lower() == "put"]
        [["strike", "bid", "ask"]]
        .sort_values("strike")
        .reset_index(drop=True)
    )

    return OptionChain(calls=calls, puts=puts)


def fetch_option_chain_alpaca(
    data_client: OptionHistoricalDataClient,
    underlying: str,
) -> pd.DataFrame:
    """
    Fetch latest option chain snapshots for an underlying and normalize into a flat DataFrame.
    """
    req = OptionChainRequest(underlying_symbol=underlying)  # name per alpaca-py docs :contentReference[oaicite:4]{index=4}
    chain = data_client.get_option_chain(req)

    # The exact shape depends on alpaca-py version; normalize defensively.
    rows = []
    for contract_symbol, snap in chain.items():  # could be dict-like
        q = getattr(snap, "latest_quote", None) or getattr(snap, "quote", None)
        t = getattr(snap, "latest_trade", None) or getattr(snap, "trade", None)
        g = getattr(snap, "greeks", None)

        # Contract details are often embedded; fall back to parsing symbol if needed.
        details = getattr(snap, "contract", None) or getattr(snap, "contract_details", None)

        rows.append({
            "contract_symbol": contract_symbol,
            "bid": getattr(q, "bid_price", None),
            "ask": getattr(q, "ask_price", None),
            "bid_size": getattr(q, "bid_size", None),
            "ask_size": getattr(q, "ask_size", None),
            "last": getattr(t, "price", None),
            "strike": getattr(details, "strike_price", None),
            "type": getattr(details, "type", None),           # 'call'/'put'
            "expiry": getattr(details, "expiration_date", None),
            "iv": getattr(g, "implied_volatility", None) if g else None,
            "delta": getattr(g, "delta", None) if g else None,
            "gamma": getattr(g, "gamma", None) if g else None,
            "vega": getattr(g, "vega", None) if g else None,
            "theta": getattr(g, "theta", None) if g else None,
        })

    df = pd.DataFrame(rows)

    # Clean types
    if "expiry" in df.columns:
        df["expiry"] = pd.to_datetime(df["expiry"]).dt.date
    if "strike" in df.columns:
        df["strike"] = pd.to_numeric(df["strike"], errors="coerce")

    return df

from alpaca.trading.requests import GetOptionContractsRequest
from alpaca.data.requests import OptionSnapshotRequest

from datetime import date

import re

_OCC_RE = re.compile(r"^[A-Z]{1,6}\d{6}([CP])\d{8}$")

def infer_cp_from_symbol(sym: str):
    """
    Attempts to infer Call/Put from OCC-like option symbol:
      UNDERLYING + YYMMDD + C/P + STRIKE(8 digits)
    Returns "Call"/"Put"/None.
    """
    if not sym or not isinstance(sym, str):
        return None
    m = _OCC_RE.match(sym)
    if not m:
        return None
    return "Call" if m.group(1) == "C" else "Put"


from datetime import date, timedelta
from datetime import date, timedelta
from alpaca.trading.requests import GetOptionContractsRequest
from alpaca.data.requests import OptionSnapshotRequest

def fetch_chain_via_contracts(trading_client, option_data_client, underlying_symbol: str) -> pd.DataFrame:
    """
    Returns normalized option chain DataFrame with columns:
    symbol, expiry (date), type ('call'/'put'), strike, bid, ask, iv
    """

    # ---------------------------
    # 1) Pull contracts (PAGINATED)
    # ---------------------------
    all_contracts = []
    page_token = None

    today = date.today()
    exp_gte = today + timedelta(days=MIN_DTE)
    exp_lte = today + timedelta(days=MAX_DTE)

    req = GetOptionContractsRequest(underlying_symbols=[underlying_symbol])

    # best-effort set request filters if supported by your alpaca-py version
    for k, v in [
        ("expiration_date_gte", exp_gte),
        ("expiration_date_lte", exp_lte),
        ("limit", 1000),
    ]:
        try:
            setattr(req, k, v)
        except Exception:
            pass

    while True:
        if page_token:
            for token_field in ("page_token", "pagination_token", "next_page_token"):
                try:
                    setattr(req, token_field, page_token)
                    break
                except Exception:
                    continue

        resp = trading_client.get_option_contracts(req)

        # unwrap contracts list
        if hasattr(resp, "option_contracts"):
            contracts = resp.option_contracts or []
        elif isinstance(resp, tuple):
            contracts = resp[0] or []
        else:
            contracts = resp or []

        all_contracts.extend(list(contracts))

        # next token (name varies)
        page_token = getattr(resp, "next_page_token", None) or getattr(resp, "next_token", None)

        print(f"[ALPACA_PAGE] got={len(contracts):,} total={len(all_contracts):,} next={bool(page_token)}")

        if not page_token:
            break

    if not all_contracts:
        print(f"[ALPACA] No contracts returned for {underlying_symbol}")
        return pd.DataFrame()

    expiries = sorted({c.expiration_date for c in all_contracts if getattr(c, "expiration_date", None)})
    print("[ALPACA] total contracts pulled:", len(all_contracts))
    print("[ALPACA] expiry min/max:", expiries[0], expiries[-1])
    print("[ALPACA] unique expiries sample:", expiries[:10])

    # ---------------------------
    # 2) Build meta list from contracts
    # ---------------------------
    meta = []
    symbols = []
    for c in all_contracts:
        sym = getattr(c, "symbol", None)
        exp = getattr(c, "expiration_date", None)
        strike = getattr(c, "strike_price", None)
        typ = getattr(c, "type", None)

        if not sym or exp is None or strike is None or typ is None:
            continue

        # normalize type to lowercase 'call'/'put'
        typ_str = str(typ).lower()
        if "call" in typ_str or typ_str == "c":
            typ_norm = "call"
        elif "put" in typ_str or typ_str == "p":
            typ_norm = "put"
        else:
            continue

        symbols.append(sym)
        meta.append((sym, exp, typ_norm, float(strike)))

    if not symbols:
        print(f"[ALPACA] Contracts parsed but no usable symbols for {underlying_symbol}")
        return pd.DataFrame()

    # ---------------------------
    # 3) Pull snapshots in CHUNKS (this is the missing piece)
    # ---------------------------
    # Many APIs cap how many symbols you can snapshot in one call.
    # If you send 360 at once, you often only get the first ~100 back.
    snap_map = {}

    # choose chunk size conservatively
    CHUNK = 75
    for i in range(0, len(symbols), CHUNK):
        chunk = symbols[i:i+CHUNK]
        try:
            snap_req = OptionSnapshotRequest(symbol_or_symbols=chunk)
            snaps = option_data_client.get_option_snapshots(snap_req)  # requires client method
        except Exception as e:
            print(f"[ALPACA] Snapshot chunk failed ({i}-{i+len(chunk)}): {e}")
            continue

        # snaps should be dict-like: {symbol: snapshot}
        if hasattr(snaps, "items"):
            for sym, snap in snaps.items():
                snap_map[sym] = snap

    print(f"[ALPACA] snapshots received: {len(snap_map):,} / {len(symbols):,}")

    # ---------------------------
    # 4) Normalize to DataFrame
    # ---------------------------
    rows = []
    for sym, exp, typ_norm, strike in meta:
        snap = snap_map.get(sym)
        if snap is None:
            continue

        quote = getattr(snap, "latest_quote", None) or getattr(snap, "quote", None)
        greeks = getattr(snap, "greeks", None)

        bid = getattr(quote, "bid_price", None) if quote else None
        ask = getattr(quote, "ask_price", None) if quote else None

        iv = None
        if greeks is not None:
            iv = getattr(greeks, "implied_volatility", None)
        if iv is None:
            iv = getattr(snap, "implied_volatility", None) or getattr(snap, "iv", None)

        rows.append({
            "symbol": sym,
            "expiry": exp,         # already date from contract
            "type": typ_norm,      # 'call'/'put'
            "strike": strike,
            "bid": float(bid) if bid is not None else None,
            "ask": float(ask) if ask is not None else None,
            "iv": float(iv) if iv is not None else None,
        })

    df = pd.DataFrame(rows)

    if df.empty:
        print(f"[ALPACA] Built 0 rows after snapshot join for {underlying_symbol}.")
        return df

    # Debug the actual expiry universe YOU WILL USE
    exps = sorted(df["expiry"].dropna().unique())
    print("[CHAIN] expiry min/max:", exps[0], exps[-1])
    print("[CHAIN] unique expiries (first 10):", exps[:10])
    print("[CHAIN] rows:", len(df))

    return df


def get_tickers_from_prompt(default="MS"):
    raw = input(f"Tickers (comma-separated) [{default}]: ").strip()
    if not raw:
        raw = default
    return [t.strip().upper() for t in raw.split(",") if t.strip()]


from dataclasses import dataclass
from datetime import date


@dataclass
class SimpleChain:
    calls: pd.DataFrame
    puts: pd.DataFrame

def normalize_chain_df(chain_df: pd.DataFrame) -> pd.DataFrame:
    # Standardize expected columns
    df = chain_df.copy()
    df.columns = [c.lower() for c in df.columns]

    # Ensure required cols
    for col in ["bid", "ask", "strike", "type", "expiry"]:
        if col not in df.columns:
            df[col] = None

    # Coerce numerics
    df["strike"] = pd.to_numeric(df["strike"], errors="coerce")
    df["bid"] = pd.to_numeric(df["bid"], errors="coerce")
    df["ask"] = pd.to_numeric(df["ask"], errors="coerce")

    # ---- PART 4: Normalize option type robustly ----
    # Handle: "Call"/"Put", "call"/"put", "C"/"P", mixed casing, None, weird values
    df["type"] = df["type"].astype(str).str.strip().str.lower()

    # Map common aliases
    df.loc[df["type"].isin(["c", "call"]), "type"] = "call"
    df.loc[df["type"].isin(["p", "put"]), "type"] = "put"

    # Kill anything not call/put (prevents empty-chain surprises later)
    df = df[df["type"].isin(["call", "put"])]

    # Drop rows missing required fields
    df = df.dropna(subset=["expiry", "strike", "bid", "ask"])

    return df


def chain_for_expiry(chain_df: pd.DataFrame, expiry: date) -> SimpleChain:
    df = normalize_chain_df(chain_df)
    df = df[df["expiry"] == expiry]
    calls = df[df["type"].str.lower().eq("call")][["strike", "bid", "ask"]].copy()
    puts  = df[df["type"].str.lower().eq("put")][["strike", "bid", "ask"]].copy()
    return SimpleChain(calls=calls, puts=puts)


class VolatilityEnsemble:
    def __init__(self, xgb_params=None, rf_params=None):
        self.xgb_model = xgb.XGBRegressor(**(xgb_params or {}))
        self.rf_model = RandomForestRegressor(**(rf_params or {}))
        self.weights = {'xgb': 0.5, 'rf': 0.5}

    def train(self, X_train, y_train):
        # Fit models
        self.xgb_model.fit(X_train, y_train)
        self.rf_model.fit(X_train, y_train)
        # Add your WFA logic here to update weights dynamically
        
    def predict(self, X_live):
        p_xgb = self.xgb_model.predict(X_live)
        p_rf = self.rf_model.predict(X_live)
        # Return the weighted ensemble prediction
        return (p_xgb * self.weights['xgb']) + (p_rf * self.weights['rf'])

# --- CONFIGURATION ---
TOTAL_AUM = 5000  # Your specific allowance
OPTIONS_BUDGET = TOTAL_AUM * 1.0  # Use full budget for the optimizer
MIN_DTE = 50   # Target 5-13 months out (Vega plays)
MAX_DTE = 450
MAX_SPREAD_PCT = 0.25 # Kill trade if spread is > 20% of price
WFA_STEP_DAYS = 25  # From your original
WFA_NUM_STEPS = 5   # From your original




# Dark mode bc its cool asf

plt.style.use('dark_background')
sns.set(style="dark", rc={
    "axes.facecolor": "#0E1117",
    "figure.facecolor": "#0E1117",
    "grid.color": "#2A3459",
    "grid.linewidth": 0.5,
    "text.color": "#E0E0E0",
    "axes.labelcolor": "#00FFCC",  # Cyan axis labels
    "xtick.color": "#E0E0E0",
    "ytick.color": "#E0E0E0"
})

from pandas.tseries.holiday import USFederalHolidayCalendar
from pandas.tseries.offsets import CustomBusinessDay


# DYNAMIC HOLIDAY GENERATION (No more hardcoding)
cal = USFederalHolidayCalendar()
# Generate holidays for a wide window (e.g., 2020 to 2030) to cover all backtests
holidays = cal.holidays(start='2020-01-01', end='2030-12-31')
HOLIDAYS_NP = np.array(holidays.date, dtype='datetime64[D]')

MARKET_INDEX = "^GSPC"
# ... (Old code fragment from lasso, disregard...)

SECTOR_ETF   = "XLK"
VIX_TICKER   = "^VIX"
TNX_TICKER   = "^TNX"
OIL_TICKER   = "CL=F"
USD_TICKER   = "DX-Y.NYB"

# Define the parameter grids for our top contestants
param_grids = {
    "XGB": {
        'n_estimators': [50, 100],
        'max_depth': [3, 4],
        'learning_rate': [0.05, 0.1],
        'reg_lambda': [1.0]
    },
    "RF": {
        'n_estimators': [100],
        'max_depth': [6, 8],
        'min_samples_leaf': [5, 10]
    }
}

import json

# --- [PART 3: JSON PACKAGING UTILS] ---
class NumpyEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (np.integer, int)): return int(obj)
        elif isinstance(obj, (np.floating, float)): return float(obj)
        elif isinstance(obj, np.ndarray): return obj.tolist()
        return super(NumpyEncoder, self).default(obj)

def save_batch_dashboard_json(run_folder, ticker, expiry, S0, sigma, z_score, regime, paths, opt_all, hedge_data, feat_imp):
    """
    Saves the enriched JSON payload for the dashboard.
    """
    path_summary = {
        "p95": np.percentile(paths, 95, axis=0).tolist(),
        "p05": np.percentile(paths, 5, axis=0).tolist(),
        "mean": np.mean(paths, axis=0).tolist(),
        "steps": list(range(paths.shape[1]))
    }

    trades_payload = []
    if not opt_all.empty:
        # Include full dictionary to capture Greeks/Metrics calculated in process_chain
        trades_payload = opt_all[opt_all["Action"] != "NONE"].to_dict(orient="records")

    payload = {
        "meta": {
            "ticker": ticker,
            "expiry": str(expiry),
            "spot_price": round(S0, 2),
            "regime": regime,
            "model_rv": round(sigma, 4),
            "z_score": round(z_score, 2)
        },
        "explainability": {
            "top_model_drivers": feat_imp  # Synced Name
        },
        "operational_risk": hedge_data,
        "charts": {"monte_carlo": path_summary},
        "opportunities": trades_payload
    }

    filename = f"{run_folder}/{ticker}_{expiry}_payload.json"
    with open(filename, "w") as f:
        json.dump(payload, f, cls=NumpyEncoder, indent=4)

# ---------------- TRADING DAYS ----------------
def get_trading_days(start_date, end_date):
    s = np.datetime64(pd.to_datetime(start_date).date(), 'D')
    e = np.datetime64(pd.to_datetime(end_date).date(), 'D')
    days = np.busday_count(s, e, holidays=HOLIDAYS_NP)
    return max(1, days + 1)

def download_global_macros():
    """Download macro bundle once at the start."""
    print(f"[SYSTEM] Downloading Global Macro Bundle...")
    macro_tkrs = ["SPY", "XLK", "^VIX", "^VVIX", "HYG", "IEI", "^TNX", 
                  "CL=F", "DX-Y.NYB", "XLP", "^IRX", "XLF", "XLE", "XLV", "IWM"]
    try:
        data = yf.download(macro_tkrs, start="2019-01-01", interval="1d", progress=False, auto_adjust=True)
        # Create a clean DataFrame
        macro_df = pd.DataFrame(index=data.index)
        # Mapping logic (same as your original, just vectorized)
        mapping = {
            "^VIX": "VIX", "^VVIX": "VVIX", "HYG": "HYG", "IEI": "IEI",
            "^TNX": "TNX_10Y", "SPY": "GSPC", "XLK": "XLK", "CL=F": "OIL",
            "DX-Y.NYB": "USD", "XLP": "XLP", "^IRX": "IRX",
            "XLF": "XLF", "XLE": "XLE", "XLV": "XLV", "IWM": "IWM"
        }
        for tkr, name in mapping.items():
            # Handle multi-level column index if necessary
            try:
                col_data = data['Close'][tkr]
            except KeyError:
                continue
            macro_df[name] = col_data
            if name in ["GSPC", "XLK", "OIL", "USD", "HYG", "XLE"]:
                macro_df[f"ret_{name.lower()}"] = np.log(macro_df[name] / (macro_df[name].shift(1) + 1e-9))
                macro_df[f"{name.lower()}_rv"] = macro_df[f"ret_{name.lower()}"].rolling(21).std() * np.sqrt(252)
        return macro_df.ffill().fillna(0)
    except Exception as e:
        print(f"[ERROR] Global Macro Fetch Failed: {e}")
        return pd.DataFrame()
    
def download_history(ticker):
    # We use 'today' as the end date. yfinance handles 'today' as 'up to the last available minute'
    today = datetime.date.today().strftime('%Y-%m-%d')
    
    print(f"\n[YFINANCE] Pulling Data for {ticker} (Latest available up to {today})")

    macro_tkrs = [ticker, "SPY", "XLK", "^VIX", "^VVIX", "HYG", "IEI", "^TNX", "CL=F", "DX-Y.NYB", "XLP", "^IRX", "XLF", "XLE", "XLV", "IWM"]
    
    # Force auto_adjust=True and specifically use 'period' to ensure we get a valid response
    data = yf.download(macro_tkrs, start="2019-01-01", end=today, interval="1d", progress=False, auto_adjust=True)

    if data.empty or ('Close' in data and ticker not in data['Close'].columns):
        print(f"[RETRY] Macro bundle failed for {ticker}. Trying single-fetch...")
        data = yf.download(ticker, period="max", interval="1d", progress=False, auto_adjust=True)

        
    if data.empty:
        raise ValueError(f"No data returned for {ticker}")

    df = pd.DataFrame(index=data.index)

    # Helper to safely grab columns from the MultiIndex
    def get_col(df_yf, col_name, tkr):
        try:
            return df_yf[col_name][tkr]
        except KeyError:
            return pd.Series(index=df_yf.index, dtype=float).fillna(0)

    df["close_price"] = get_col(data, 'Close', ticker)
    df[f"ret_{ticker.lower()}"] = np.log(df["close_price"] / (df["close_price"].shift(1) + 1e-9)).fillna(0)

    mapping = {
        "^VIX": "VIX", "^VVIX": "VVIX", "HYG": "HYG", "IEI": "IEI",
        "^TNX": "TNX_10Y", "SPY": "GSPC", "XLK": "XLK", "CL=F": "OIL",
        "DX-Y.NYB": "USD", "XLP": "XLP", "^IRX": "IRX",
        "XLF": "XLF", "XLE": "XLE", "XLV": "XLV", "IWM": "IWM"
    }

    for tkr, name in mapping.items():
        df[name] = get_col(data, 'Close', tkr)
        if name in ["GSPC", "XLK", "OIL", "USD", 
        "HYG", "IEI", "XLP", "IRX", "XLF", "XLE", "XLV", "IWM"]:
            df[f"ret_{name.lower()}"] = np.log(df[name] / (df[name].shift(1) + 1e-9)).fillna(0)
            df[f"{name.lower()}_rv"] = df[f"ret_{name.lower()}"].rolling(21).std() * np.sqrt(252)
            df[f"{name.lower()}_rv_vel"] = df[f"{name.lower()}_rv"].diff(5)

    df = df.dropna(subset=[f"ret_{ticker.lower()}"])
    df = df.ffill().fillna(0)
    
    print(f"Success. Latest Point: {df.index[-1].date()}")
    return df.sort_index()

def optimize_tarasque_portfolio(results_df, total_budget=5000):
    """Calculates the Efficient Frontier weights for the final portfolio."""
    print("\n--- Running Portfolio Optimization ---")
    
    # 1. Filter for valid data
    df = results_df.copy()
    df = df[df['Zscore'] > 0] # Only look at positive edges
    if df.empty: return df
    
    # 2. Metric: Expected Edge adjusted by Model Confidence (RMSE)
    df['alpha_score'] = df['Zscore'] / (df['RMSE'] + 1e-9)
    
    num_assets = len(df)
    init_weights = np.array([1.0 / num_assets] * num_assets)
    # Bounds: Max 15% allocation per single contract to prevent blowups
    bounds = tuple((0, 0.15) for _ in range(num_assets))
    
    def objective(weights):
        # Maximize Alpha Score per unit of risk (simplified variance)
        port_alpha = np.dot(weights, df['alpha_score'].values)
        port_risk = np.sqrt(np.dot(weights.T, weights)) 
        return -port_alpha / (port_risk + 1e-9) # Negative because we minimize

    constraints = ({'type': 'eq', 'fun': lambda x: np.sum(x) - 1.0})
    
    try:
        opt = minimize(objective, init_weights, method='SLSQP', bounds=bounds, constraints=constraints)
        df['Optimal_Weight'] = opt.x
        df['Capital_Allocation'] = df['Optimal_Weight'] * total_budget
    except Exception as e:
        print(f"[OPTIMIZER FAILED] Defaulting to equal weight. Error: {e}")
        df['Capital_Allocation'] = total_budget / num_assets
        
    return df.sort_values('Capital_Allocation', ascending=False)


def build_features(df, ticker, H_trading_days):
    df = df.copy()
    df.columns = [c.lower() for c in df.columns]

    if 'close' in df.columns and 'close_price' not in df.columns:
        df['close_price'] = df['close']

    ret_col = f"ret_{ticker.lower()}"

    # --- START STEP 2: VOLATILITY DECOMPOSITION ---
    # We strip out the Market (GSPC) component to find the "True Alpha" residual
    if "ret_gspc" in df.columns:
        # Call the helper to find current Beta and Residual Vol
        df['beta_spy'], df['res_vol'] = decompose_volatility(df, ret_col, "ret_gspc")

        # Volatility Velocity: Is the engine's unique risk accelerating?
        df['res_vol_vel'] = df['res_vol'].diff(5)
    else:
        df['beta_spy'], df['res_vol'], df['res_vol_vel'] = 1.0, 0.0, 0.0
    # --- END STEP 2 ---

    df["rv_1d"] = df[ret_col]**2
    df["rv_21d"] = df["rv_1d"].rolling(21).sum() * 252/21
    df["ewma_vol"] = df[ret_col].pow(2).ewm(span=21).mean() * 252

    # Technical Indicators
    ema_12 = df["close_price"].ewm(span=12, adjust=False).mean()
    ema_26 = df["close_price"].ewm(span=26, adjust=False).mean()
    df["macd_hist"] = ((ema_12 - ema_26) / (df["close_price"] + 1e-9)) * 100

    if 'vix' in df.columns:
        df["vix_basis"] = df["vix"] - df["vix"].rolling(21).mean()
        df["vix_skew_proxy"] = df["vvix"] / (df["vix"] + 1e-9) if 'vvix' in df.columns else 0
    else:
        df["vix_basis"], df["vix_skew_proxy"] = 0, 0

    df["ma_50"] = df["close_price"].rolling(window=50).mean()
    df["dist_ma_50"] = (df["close_price"] / (df["ma_50"] + 1e-9)) - 1.0

    plus_dm = df["close_price"].diff().clip(lower=0)
    minus_dm = df["close_price"].diff().clip(upper=0).abs()
    denom = plus_dm + minus_dm
    df["adx_strength"] = (plus_dm - minus_dm).abs() / (denom.rolling(14).mean() + 1e-9)

    df["vol_trend"] = df["rv_21d"] / (df["rv_21d"].rolling(63).mean() + 1e-9)
    df["rv_forward_H"] = df["rv_1d"].rolling(H_trading_days).sum().shift(-H_trading_days) * 252/H_trading_days
    df["log_rv_forward_H"] = np.log(df["rv_forward_H"] + 1e-9)

    df["ret_lag1"] = df[ret_col].shift(1)

    delta = df["close_price"].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    df["rsi_14"] = 100 - (100 / (1 + (gain / (loss + 1e-9))))

    vol_col = next((c for c in ['volume', 'vol'] if c in df.columns), None)
    if vol_col:
        df["vol_z_score"] = (df[vol_col] - df[vol_col].rolling(21).mean()) / (df[vol_col].rolling(21).std() + 1e-9)
    else:
        df["vol_z_score"] = 0

    df["rv_lag1"] = df["rv_21d"].shift(1)
    df["rv_lag5"] = df["rv_21d"].shift(5)
    df["vol_acceleration"] = (df["rv_21d"] - df["rv_lag1"]) / (df["rv_lag1"] + 1e-9)

    long_window = 252 * 5
    df["vol_z_long"] = (df["rv_21d"] - df["rv_21d"].rolling(long_window, min_periods=21).mean()) / \
                        (df["rv_21d"].rolling(long_window, min_periods=21).std() + 1e-9)

    df = df.dropna(subset=["log_rv_forward_H"])
    feature_cols = [c for c in df.columns if c not in ["rv_forward_H", "log_rv_forward_H", "date"]]
    df[feature_cols] = df[feature_cols].ffill().fillna(0)
    # Add these to build_features:
    df['day_of_week'] = df.index.dayofweek
    df['is_monday'] = (df['day_of_week'] == 0).astype(int)
    df['is_friday'] = (df['day_of_week'] == 4).astype(int)

    return df.copy()

def get_market_regime(live_row):
    adx = live_row["adx_strength"].iloc[0]
    vol = live_row["vol_trend"].iloc[0]
    if adx > 0.20 or vol > 1.3:
        return "TRENDING"
    return "RANGING"

from scipy.stats import norm
from scipy.optimize import brentq

class OptionMath:
    @staticmethod
    def bs_pricing(S, K, T, r, sigma, type_="call"):
        # Edge Case: If time is 0, return intrinsic value
        if T <= 1e-9:
            return max(0, S - K) if type_ == "call" else max(0, K - S)

        d1 = (np.log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*np.sqrt(T))
        d2 = d1 - sigma*np.sqrt(T)
        
        if type_ == "call":
            return S*norm.cdf(d1) - K*np.exp(-r*T)*norm.cdf(d2)
        else:
            # FIX: Added actual Put formula
            return K*np.exp(-r*T)*norm.cdf(-d2) - S*norm.cdf(-d1)
    
    @staticmethod
    def get_iv(S, K, T, r, price, type_="call"):
        # FIX: Check intrinsic first to avoid waste
        intrinsic = max(0, S - K) if type_ == "call" else max(0, K - S)
        
        # If market price is below intrinsic - bad data), IV is 0
        if price <= intrinsic + 1e-5:
            return 0.0

        # FIX: Define objective function properly nested
        def objective_function(sigma):
            # Must explicitly call the class method
            return OptionMath.bs_pricing(S, K, T, r, sigma, type_) - price
        
        try:
            # Attempt to find root between 0.01% and 500% IV
            return brentq(objective_function, 1e-4, 5.0, xtol=1e-6)
        except (ValueError, RuntimeError):
            # FIX: Return NaN on failure so your dataframe knows it failed
            return np.nan

def decompose_volatility(df, ticker_ret, benchmark_ret):
    # 63-day rolling Beta (1 quarter of data)
    rolling_cov = df[ticker_ret].rolling(63).cov(df[benchmark_ret])
    rolling_var = df[benchmark_ret].rolling(63).var()
    beta = rolling_cov / (rolling_var + 1e-9)

    # Residual Variance = Total Variance - (Beta^2 * Market Variance)
    total_var = df[ticker_ret].rolling(21).var()
    sys_var = (beta**2) * df[benchmark_ret].rolling(21).var()
    res_var = np.maximum(0, total_var - sys_var)

    return beta, np.sqrt(res_var * 252)

def process_chain(chain, S0, T, r, sigma_forecast, paths):
    rows = []
    prices_at_expiry = paths[:, -1]
    
    for opt_type, tbl in [("Call", chain.calls), ("Put", chain.puts)]:
        tbl = tbl.copy()
        for _, row in tbl.iterrows():
            K = row["strike"]
            ask = row["ask"]; bid = row["bid"]
            mid = (ask + bid) / 2 if (ask > 0 and bid > 0) else ask
            
            # --- SANITY CHECK 1: DEAD DATA ---
            if mid <= 0 or ask <= 0: continue
            
            # --- SANITY CHECK 2: STALE ITM DATA ---
            # If Mid is significantly below intrinsic value, yfinance data is stale
            intrinsic = max(0, S0 - K) if opt_type == "Call" else max(0, K - S0)
            if mid < (intrinsic * 0.98): continue 
            
            # --- SANITY CHECK 3: LIQUIDITY / SPREAD ---
            spread = ask - bid
            if spread / (mid + 1e-9) > 0.40: continue # Skip if spread > 40% of price
            
            mkt_iv = OptionMath.get_iv(S0, K, T, r, mid, opt_type.lower())
            model_px = OptionMath.bs_pricing(S0, K, T, r, sigma_forecast, opt_type.lower())
            
            if np.isnan(mkt_iv): continue

            d1 = (np.log(S0/K) + (r + 0.5*sigma_forecast**2)*T) / (sigma_forecast*np.sqrt(T))
            delta = norm.cdf(d1) if opt_type == "Call" else norm.cdf(d1) - 1
            
            # --- SANITY CHECK 4: MONEYNESS ---
            # Focus on high-conviction zones (Delta between 0.10 and 0.85)
            if abs(delta) < 0.10 or abs(delta) > 0.85: continue

            side = "NONE"
            if model_px > ask: side = "LONG"
            elif model_px < bid: side = "SHORT"
            
            entry_px = ask if side == "LONG" else bid
            if side != "NONE":
                if opt_type == "Call": payoffs = np.maximum(prices_at_expiry - K, 0)
                else: payoffs = np.maximum(K - prices_at_expiry, 0)
                
                p_returns = (payoffs - entry_px) / entry_px if side == "LONG" else (entry_px - payoffs) / entry_px
                mean_ret = np.mean(p_returns)
                var_ret = np.var(p_returns)
                kelly_f = max(0, mean_ret / (var_ret + 1e-9)) if var_ret > 0 else 0
                pop = np.mean(p_returns > 0)
            else:
                mean_ret, pop, kelly_f = 0, 0, 0

            rows.append({
                "Action": side, "Type": opt_type, "Strike": round(K, 1),
                "Delta": round(delta, 2), "Mkt_Px": round(mid, 2),
                "model_Px": round(model_px, 2), "Edge_Pct_Val": mean_ret,
                "PoP": f"{pop:.1%}", "Silo_Kelly": kelly_f, "IV": round(mkt_iv, 3)
            })
            
    return pd.DataFrame(rows)

def run_wfa_competition(train_pool, predictors):
    tscv = TimeSeriesSplit(n_splits=3)
    # Align test dates to the end of the dataset
    test_dates = train_pool.index[-WFA_NUM_STEPS*WFA_STEP_DAYS::WFA_STEP_DAYS]
    print(f"--- Running Optimized WFA (Latest Data: {train_pool.index[-1].date()}) ---")

    wfa_results = []
    # Explicitly separate the error tracking lists
    model_errors = {"XGB": [], "RF": []}

    for t_date in test_dates:
        train = train_pool[train_pool.index <= t_date]
        test = train_pool[train_pool.index > t_date].head(WFA_STEP_DAYS)
        if len(train) < 50 or len(test) < 1: continue

        X_tr, y_tr = train[predictors], train["log_rv_forward_H"]
        X_te, y_te = test[predictors], test["log_rv_forward_H"]

        step_min_rmse = float('inf')
        step_winner = ""
        best_params = {}

        # Iterate strictly through known keys to prevent variable shadowing
        for name in ["XGB", "RF"]:
            grid = param_grids[name]

            # SEED LOCKED
            #if name == "XGB":
                #base_model = xgb.XGBRegressor(random_state=42, n_jobs=-1)
            #else:
                #base_model = RandomForestRegressor(random_state=42, n_jobs=-1)
            # UNLOCKED (Stochastic)
            if name == "XGB":
                base_model = xgb.XGBRegressor(n_jobs=-1)
            else:
                base_model = RandomForestRegressor(n_jobs=-1)

            # Fit Grid Search
            grid_search = GridSearchCV(estimator=base_model, param_grid=grid,
                                       cv=tscv, scoring='neg_root_mean_squared_error', n_jobs=-1)
            grid_search.fit(X_tr, y_tr)

            # Predict independent of the other model
            preds_te = grid_search.predict(X_te)
            rmse = np.sqrt(mean_squared_error(y_te, preds_te))

            # Store SPECIFIC model error
            model_errors[name].append(rmse)

            # Check for Step Winner
            if rmse < step_min_rmse:
                step_min_rmse = rmse
                step_winner = name
                best_params = grid_search.best_params_

        print(f"[{t_date.date()}] Winner: {step_winner.ljust(5)} | RMSE: {step_min_rmse:.4f}")
        wfa_results.append({"Winner": step_winner, "RMSE": step_min_rmse, "Params": best_params})

    # Calculate final averages
    avg_errors = {
        "XGB": np.mean(model_errors["XGB"]) if model_errors["XGB"] else 1.0,
        "RF":  np.mean(model_errors["RF"])  if model_errors["RF"]  else 1.0
    }

    return pd.DataFrame(wfa_results), avg_errors

def run_monte_carlo(S0, sigma, T, rmse_vol, n_sims=5000):
    r = 0.042
    steps = max(10, int(T * 252))
    dt = T / steps
    paths = np.zeros((n_sims, steps + 1))
    paths[:, 0] = S0
    for t in range(1, steps + 1):
        stochastic_vol = np.maximum(0.01, sigma + np.random.normal(0, rmse_vol * np.sqrt(dt), n_sims))
        z = np.random.standard_normal(n_sims)
        paths[:, t] = paths[:, t-1] * np.exp((r - 0.5 * stochastic_vol**2) * dt + stochastic_vol * np.sqrt(dt) * z)
    p5d = np.mean(paths[:, min(5, steps)])
    p20d = np.mean(paths[:, min(20, steps)])
    tail_risk = np.percentile(paths[:, -1], 5)
    return paths, p5d, p20d, tail_risk



# [PART 3: Data Packaging]
# Place this inside your existing script, near plot_full_dashboard

def package_dashboard_payload(ticker, paths, opt_all, S0, sigma, p5d, p20d, tail_risk, z_score, regime):
    """
    Takes the exact same data you used for plotting, but packages it 
    into a clean JSON dictionary for a website to consume.
    """
    
    # 1. Compress Monte Carlo Paths (Websites can't handle 5000 paths x 252 steps)
    # We send only percentiles and the mean to keep it fast.
    path_summary = {
        "p95": np.percentile(paths, 95, axis=0).tolist(), # Top 5% outcome
        "p05": np.percentile(paths, 5, axis=0).tolist(), # Bottom 5% outcome
        "mean": np.mean(paths, axis=0).tolist(),         # Average outcome
        "steps": list(range(paths.shape[1]))             # X-Axis (Days)
    }

    # 2. Signals
    # Filter for the "Actionable" trades only
    if not opt_all.empty:
        signals = opt_all[opt_all["Action"] != "NONE"].copy()
        # Convert DataFrame to list of dictionaries
        trades_payload = signals[["Type", "Strike", "Mkt_Px", "model_Px", "Edge_Pct_Val", "PoP"]].to_dict(orient="records")
    else:
        trades_payload = []

    # 3. The Final "API Response"
    return {
        "meta": {
            "ticker": ticker,
            "spot_price": S0,
            "regime": regime, 
            "model_rv": round(sigma, 4),
            "z_score": round(z_score, 2),
            "forecast_5d": round(p5d, 2),
            "forecast_20d": round(p20d, 2),
            "stop_loss_95": round(tail_risk, 2)
        },
        "charts": {
            "monte_carlo": path_summary
            # Add other chart data here (e.g. Volatility Cone) if needed
        },
        "opportunities": trades_payload
    }

def plot_full_dashboard(paths, opt_all, S0, sigma, ticker, wfa_log, p5d, p20d, tail_risk, final_m, preds, rmse, H_trading, df_full):
    plt.close('all')
    fig = plt.figure(figsize=(24, 28))
    gs = gridspec.GridSpec(4, 2)
    ax1 = plt.subplot(gs[0, 0])
    x_axis = np.linspace(0, H_trading, paths.shape[1])
    for i in range(min(75, paths.shape[0])):
        ax1.plot(x_axis, paths[i, :], lw=0.6, alpha=0.15, color='gray')
    p95 = np.percentile(paths, 95, axis=0)
    p05 = np.percentile(paths, 5, axis=0)
    mean_projection = np.mean(paths, axis=0)
    ax1.fill_between(x_axis, p05, p95, color='cyan', alpha=0.1, label='95% Confidence Interval')
    ax1.plot(x_axis, mean_projection, color='cyan', lw=4, label='Mean Projection')
    final_idx = len(x_axis) - 1
    ax1.text(x_axis[final_idx], p95[final_idx], f' ${p95[final_idx]:.1f}', color='lime', fontweight='bold')
    ax1.text(x_axis[final_idx], p05[final_idx], f' ${p05[final_idx]:.1f}', color='red', fontweight='bold')
    f_text = (f"SPOT: ${S0:.2f}\n" f"5D Forecast: ${p5d:.2f}\n" f"20D Forecast: ${p20d:.2f}\n" f"STOP LOSS (95%): ${tail_risk:.2f}")
    ax1.text(0.05, 0.95, f_text, transform=ax1.transAxes, verticalalignment='top',
             bbox=dict(boxstyle='round', facecolor='black', alpha=0.8),
             color='white', fontweight='bold', fontsize=12)
    ax1.set_title(f"{ticker} Paths & Forecasts (H={H_trading})")
    ax1.legend(loc='lower left')
    ax2 = plt.subplot(gs[0, 1])
    if not opt_all.empty:
        c = opt_all[opt_all["Type"]=="Call"]; p = opt_all[opt_all["Type"]=="Put"]
        ax2.scatter(c["Strike"], c["Mkt_Px"], c='lime', marker='x', label='Mkt Price')
        ax2.scatter(c["Strike"], c["model_Px"], c='cyan', alpha=0.5, label='model Px')
        ax2.scatter(p["Strike"], p["Mkt_Px"], c='red', marker='x', label='Mkt Price')
        ax2.scatter(p["Strike"], p["model_Px"], c='orange', alpha=0.5, label='model Px')
    ax2.axvline(x=S0, color="white", ls="--", label="Spot")
    ax2.set_title("Price Map (Market vs Model Target)")
    ax2.legend()
    ax3 = plt.subplot(gs[1, 0])
    if not opt_all.empty:
        c = opt_all[opt_all["Type"]=="Call"]; p = opt_all[opt_all["Type"]=="Put"]
        ax3.scatter(c["Strike"], c["IV"], c='lime', alpha=0.6, label='Call IV')
        ax3.scatter(p["Strike"], p["IV"], c='red', alpha=0.6, label='Put IV')
    ax3.axhline(y=sigma, color='cyan', ls='--', label=f'Model RV Forecast ({sigma:.1%})')
    ax3.set_title("Implied Volatility (Market) vs Realized Volatility (Model)")
    ax3.legend()
    ax4 = plt.subplot(gs[1, 1])
    if not opt_all.empty:
        plot_df = opt_all.sort_values("Strike").head(15)
        pop_vals = [float(x.strip('%'))/100 for x in plot_df["PoP"]]
        ax4.bar([str(k) for k in plot_df["Strike"]], pop_vals, color='skyblue', alpha=0.7)
    ax4.set_ylim(0, 1.0)
    ax4.set_title("Model-Derived Probability of Profit")
    ax5 = plt.subplot(gs[2, 0])
    importance_values = None
    title_suffix = ""
    if hasattr(final_m, 'feature_importances_'):
        importance_values = final_m.feature_importances_
        title_suffix = "(Gini/Gain)"
    elif hasattr(final_m, 'coef_'):
        importance_values = np.abs(final_m.coef_)
        title_suffix = "(Abs Coefficients)"
    if importance_values is not None:
        idxs = np.argsort(importance_values)[::-1][:10]
        ax5.barh([preds[i] for i in idxs], importance_values[idxs], color='orange', alpha=0.8)
        ax5.invert_yaxis()
        ax5.set_title(f"Top 10 Predictors {title_suffix}")
    ax6 = plt.subplot(gs[2, 1])
    mkt_iv = opt_all['IV'].median() if not opt_all.empty and opt_all['IV'].median() > 0 else sigma
    T = H_trading / 252
    x_range = np.linspace(S0 * 0.4, S0 * 1.6, 500)
    market_pdf = norm.pdf(x_range, S0, S0 * mkt_iv * np.sqrt(T))
    model_pdf = norm.pdf(x_range, S0, S0 * sigma * np.sqrt(T))
    ax6.plot(x_range, market_pdf, label=f'Market Implied (IV: {mkt_iv:.1%})', color='lime', lw=2)
    ax6.plot(x_range, model_pdf, label=f'Model Forecast (RV: {sigma:.1%})', color='cyan', lw=3)
    ax6.fill_between(x_range, model_pdf, alpha=0.2, color='cyan')
    ax6.set_title("Expected Price Distribution")
    ax6.legend()
    ax7 = plt.subplot(gs[3, :])
    top_n = 15
    corr_preds = preds[:top_n] if len(preds) > top_n else preds
    corr_matrix = df_full[corr_preds].corr()
    sns.heatmap(corr_matrix, annot=True, cmap='coolwarm', fmt=".2f", ax=ax7, center=0,
                annot_kws={"size": 10}, cbar_kws={'label': 'Correlation Coefficient'})
    ax7.set_title(f"Predictor Correlation Matrix (Top {len(corr_preds)} Features)")
    plt.tight_layout()
    plt.savefig(f"Results/{ticker}_Dashboard.png")
    plt.close()

def get_robust_S0(yf_ticker, df_raw):
    try:
        hist_1d = yf_ticker.history(period="1d")
        if not hist_1d.empty:
            return float(hist_1d["Close"].iloc[-1])
        hist_5d = yf_ticker.history(period="5d")
        if not hist_5d.empty:
            return float(hist_5d["Close"].iloc[-1])
    except Exception as e:
        print(f"[SYSTEM WARNING] YFinance fetch failed: {e}")
    print("[SYSTEM] Using local df_raw fallback for S0.")
    return float(df_raw["close_price"].iloc[-1])

from sklearn.linear_model import LassoCV

def plot_pred_vs_real(eval_slice, preds, m_xgb, m_rf, m_lasso, w_xgb, w_rf):
    y_true = eval_slice["log_rv_forward_H"].values
    y_pred_ens = (
        m_xgb.predict(eval_slice[preds]) * w_xgb +
        m_rf.predict(eval_slice[preds]) * w_rf +
        m_lasso.predict(eval_slice[preds]) * 0.10
    )
    plt.figure(figsize=(8,6))
    plt.scatter(y_true, y_pred_ens, alpha=0.4)
    min_val = min(y_true.min(), y_pred_ens.min())
    max_val = max(y_true.max(), y_pred_ens.max())
    plt.plot([min_val, max_val], [min_val, max_val], linestyle='--')
    plt.xlabel("Realized log-RV (forward)")
    plt.ylabel("Predicted log-RV")
    plt.title("Predicted vs Realized (Out-of-sample slice)")
    plt.tight_layout()
    plt.show()


# ---------------- AUTO-HEDGE RECOMMENDATIONS (Platinum v5.1: Lasso + Unit Logic) ----------------
def auto_hedge_recommendations(df_full, final_m, preds, sigma_model, opt_all, TOTAL_AUM, ticker):
    print("\n=== Sparse Factor Hedge Reccomendation (Non Tail-Risk) ===\n")

    # --- 1. CONFIGURATION ---
    TRADE_UNIT_SIZE = 1000.0
    MIN_HEDGE_SIZE = 50.0  # Kill hedges smaller than $50 (reduces transaction costs)

    # --- 2. EXPANDED MACRO UNIVERSE ---
    potential_macros = [
        "ret_gspc", "ret_xlk", "ret_vix", "ret_hyg", "ret_iei",
        "ret_oil", "ret_usd", "ret_xlp", "ret_xlf", "ret_xle", "ret_xlv", "ret_iwm"
    ]
    macro_cols = [c for c in potential_macros if c in df_full.columns]
    etf_map = {
        "ret_gspc": "SPY", "ret_xlk": "XLK", "ret_vix": "VIXY", "ret_hyg": "HYG",
        "ret_iei": "IEF", "ret_oil": "USO", "ret_usd": "UUP", "ret_xlp": "XLP",
        "ret_xlf": "XLF", "ret_xle": "XLE", "ret_xlv": "XLV", "ret_iwm": "IWM"
    }

    reg_df = df_full[macro_cols + [f"ret_{ticker.lower()}"]].replace([np.inf, -np.inf], np.nan).dropna()
    if reg_df.empty:
        print("[ERROR] Not enough data for hedge regression.")
        return

    X = reg_df[macro_cols]
    y = reg_df[f"ret_{ticker.lower()}"]

    # --- 3. LASSO REGRESSION (Sparsity) ---
    # Automatically finds best alpha to zero out noise
    #model = LassoCV(cv=5, fit_intercept=False, random_state=42, max_iter=5000).fit(X, y)
    model = LassoCV(cv=5, fit_intercept=False, max_iter=5000).fit(X, y)
    r_squared = model.score(X, y)
    betas = pd.Series(model.coef_, index=macro_cols)

    # Only keep non-zero betas
    active_betas = betas[betas.abs() > 0.0001]

    # Risk Breakdown
    hedge_budget = TRADE_UNIT_SIZE * r_squared
    alpha_exposure = TRADE_UNIT_SIZE * (1 - r_squared)

    print(f"Systematic Risk: {r_squared:.1%} (Hedge Budget: ${hedge_budget:.0f})")
    print(f"Alpha Exposure:  {1-r_squared:.1%} (Unhedged:     ${alpha_exposure:.0f})")

    # --- 4. CONSTRUCT BASKET & FILTER ---
    if not active_betas.empty:
        # Initial Allocations
        weights = active_betas.abs() / active_betas.abs().sum()
        raw_allocations = weights * hedge_budget

        # Filter: Drop tiny positions
        final_allocations = raw_allocations[raw_allocations >= MIN_HEDGE_SIZE]

        # Re-normalize to ensure we still use the full hedge budget on the remaining liquid ETFs
        if not final_allocations.empty:
            final_weights = active_betas[final_allocations.index].abs() / active_betas[final_allocations.index].abs().sum()
            final_allocations = final_weights * hedge_budget
    else:
        final_allocations = pd.Series()

    # --- 5. OUTPUT SCENARIOS ---
    long_recipe = []
    short_recipe = []
    pie_labels, pie_sizes, pie_colors = [], [], []

    color_map = {
        "SPY": "#00FF00", "XLK": "#00FFFF", "VIXY": "#FF0000", "HYG": "#FF00FF",
        "IEF": "#0000FF", "USO": "#FFA500", "UUP": "#CCCCCC", "XLP": "#FFFF00",
        "XLF": "#CD7F32", "XLE": "#8B4513", "XLV": "#FF69B4", "IWM": "#808080",
        "Alpha": "#1A1A1A"
    }

    for col, amt in final_allocations.items():
        ticker_name = etf_map.get(col, col)
        beta_val = betas[col]

        # Direction Logic
        if beta_val > 0:
            long_action, short_action = "Short", "Long"
        else:
            long_action, short_action = "Long", "Short"

        pct = (amt / TRADE_UNIT_SIZE) * 100
        long_recipe.append(f"{long_action} {ticker_name} (${amt:.0f}) -> {pct:.1f}%")
        short_recipe.append(f"{short_action} {ticker_name} (${amt:.0f}) -> {pct:.1f}%")

        pie_labels.append(f"{long_action} {ticker_name}\n${amt:.0f}")
        pie_sizes.append(amt)
        pie_colors.append(color_map.get(ticker_name, "#FFFFFF"))

    # --- 6. VOLATILITY CHECK ---
    # We use the ensemble's feature importance for this, as Lasso might miss non-linear vol risk
    if hasattr(final_m, 'feature_importances_'):
        imp_df = pd.Series(final_m.feature_importances_, index=preds)
        vol_features = [p for p in imp_df.index if 'vol' in p or 'vix' in p]
        if imp_df[vol_features].sum() > 0.15 * imp_df.sum():
            vix_hedge = TRADE_UNIT_SIZE * 0.10
            print(f"\n[ALERT] High Volatility Importance. Adding VIX Hedge (${vix_hedge:.0f}).")
            long_recipe.append(f"Buy VIXY Calls (${vix_hedge:.0f}) [Panic Hedge]")
            short_recipe.append(f"Sell VIXY Calls (${vix_hedge:.0f}) [Panic Hedge]")

    # --- 7. VISUALIZATION ---
    pie_labels.append(f"Unhedged\n(Alpha)\n${alpha_exposure:.0f}")
    pie_sizes.append(alpha_exposure)
    pie_colors.append(color_map["Alpha"])

    plt.figure(figsize=(10, 6))
    wedges, texts, autotexts = plt.pie(pie_sizes, labels=pie_labels, colors=pie_colors,
                                       autopct='%1.0f%%', startangle=140, pctdistance=0.85,
                                       textprops={'color': "white", 'fontsize': 9, 'weight': 'bold'},
                                       wedgeprops={'edgecolor': '#0E1117', 'linewidth': 2})

    # Donut Hole
    plt.gcf().gca().add_artist(plt.Circle((0,0),0.70,fc='#0E1117'))
    plt.title(f"SPARSE HEDGE RECIPE: {ticker} (Per $1k Risk)", color="cyan", fontsize=14)
    plt.tight_layout()
    plt.show()

    # --- 8. FINAL PLAN ---
    print(f"\n=== HEDGE EXECUTION PLAN (Per $1,000 Position Value) ===")
    print("\n[SCENARIO A] You are LONG (Buying Calls or Stock):")
    if long_recipe:
        for step in long_recipe: print(f"  • {step}")
    else:
        print("  • No systematic hedges required (Pure Alpha).")

    print("\n[SCENARIO B] You are SHORT (Buying Puts or Shorting Stock):")
    if short_recipe:
        for step in short_recipe: print(f"  • {step}")
    else:
        print("  • No systematic hedges required (Pure Alpha).")


def analyze_z_continuum(ticker, continuum_data, run_folder):
    """Plots the Z-Score Term Structure for the ticker."""
    if continuum_data:
        plt.figure(figsize=(12, 5))
        d_val = [x['Days'] for x in continuum_data]
        z_val = [x['Z'] for x in continuum_data]
        
        plt.plot(d_val, z_val, marker='o', color='#00FFCC', ls='--', lw=2, label='Alpha Z-Score')
        plt.axhline(1.96, color='#FF3366', ls=':', label='95% Confidence Upper')
        plt.axhline(-1.96, color='#FF3366', ls=':', label='95% Confidence Lower')
        plt.axhline(0, color='white', lw=0.5)
        
        plt.fill_between(d_val, z_val, 0, where=(np.array(z_val) >= 0), color='#00FFCC', alpha=0.1)
        plt.fill_between(d_val, z_val, 0, where=(np.array(z_val) < 0), color='#FF3366', alpha=0.1)
        
        plt.title(f"{ticker} - Volatility Dissimilarity Continuum (Term Structure of Edge)", fontsize=14)
        plt.xlabel("Days to Expiration")
        plt.ylabel("Z-Score (Standard Deviations)")
        plt.legend()
        plt.grid(alpha=0.2)
        
        plt.savefig(f"{run_folder}/{ticker}_Continuum.png")
        plt.close()

    if continuum_data:
        plt.figure(figsize=(10, 4))
        d_val = [x['Days'] for x in continuum_data]; z_val = [x['Z'] for x in continuum_data]
        plt.plot(d_val, z_val, marker='o', color='#00FFCC', ls='--')
        plt.axhline(1.96, color='red', ls=':'); plt.axhline(-1.96, color='red', ls=':')
        plt.title(f"{ticker} - Z-Score Horizon Continuum")
        plt.savefig(f"Results/{ticker}_Continuum.png")
        plt.close()

def get_institutional_hedge_data(df_full, ticker):
    """Calculates sparse regression betas for the JSON payload."""
    potential_macros = ["ret_gspc", "ret_xlk", "ret_vix", "ret_hyg", "ret_iei", "ret_oil"]
    macro_cols = [c for c in potential_macros if c in df_full.columns]
    
    reg_df = df_full[macro_cols + [f"ret_{ticker.lower()}"]].dropna()
    if reg_df.empty: return {"systematic_risk": 0, "alpha_integrity": 1.0, "betas": {}}
    
    X = reg_df[macro_cols]
    y = reg_df[f"ret_{ticker.lower()}"]
    
    model = LassoCV(cv=5, fit_intercept=False, max_iter=5000).fit(X, y)
    r_squared = model.score(X, y)
    
    return {
        "systematic_risk_pct": round(float(r_squared), 4),
        "alpha_integrity_pct": round(float(1 - r_squared), 4),
        "betas": {feat: round(float(coef), 4) for feat, coef in zip(macro_cols, model.coef_) if abs(coef) > 1e-4}
    }

def main():
    # Create run folder and report
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    run_folder = f"Results/Run_{timestamp}"
    os.makedirs(run_folder, exist_ok=True)

    report_file = f"{run_folder}/Tarasque_Alpha_Report.csv"
    results_log = []

    TICKERS = get_tickers_from_prompt(default="MS")

    print("[BOOT] Starting run. TICKERS =", TICKERS)


    for ticker in TICKERS:
        try:
            print(f"\n>>> PROCESSING: {ticker}")

            # 1) Download history ONCE per ticker
            df_raw = download_history(ticker)
            continuum_data = []

            # 2) Fetch option chain ONCE per ticker
            chain_df = fetch_chain_via_contracts(trading_client, option_data_client, ticker)
            print(f"[CHAIN_RAW] rows={0 if chain_df is None else len(chain_df):,}")
            if chain_df is None or chain_df.empty:
                print(f"SKIP {ticker}: No option chain data from Alpaca")
                continue

            chain_df["expiry"] = pd.to_datetime(chain_df["expiry"], errors="coerce").dt.date

            print("[CHAIN] expiry min/max:", chain_df["expiry"].min(), chain_df["expiry"].max())
            print("[CHAIN] unique expiries (first 10):", sorted(chain_df["expiry"].dropna().unique())[:10])

            # Hard stop early if nothing came back
            if chain_df is None or chain_df.empty or "expiry" not in chain_df.columns:
                print(f"SKIP {ticker}: No option chain data from Alpaca")
                continue


            # Defensive: ensure expiry exists
            if "expiry" not in chain_df.columns:
                print(f"SKIP {ticker}: chain_df missing 'expiry' column. cols={list(chain_df.columns)}")
                continue

            # Normalize expiry to datetime64[ns] so vectorized DTE works reliably
            chain_df["expiry"] = pd.to_datetime(chain_df["expiry"], errors="coerce")
            chain_df = chain_df.dropna(subset=["expiry"])

            if chain_df.empty:
                print(f"SKIP {ticker}: all expiry values were invalid/NaT after parsing")
                continue

            # 3) Filter expiries by DTE window ONCE (datetime - datetime)
            today_ts = pd.Timestamp.today().normalize()
            chain_df["dte"] = (chain_df["expiry"] - today_ts).dt.days

            chain_df = chain_df[(chain_df["dte"] >= MIN_DTE) & (chain_df["dte"] <= MAX_DTE)]

            if chain_df.empty:
                print(f"SKIP {ticker}: No expiries in DTE window [{MIN_DTE},{MAX_DTE}]")
                continue

            # IMPORTANT: for later code that expects expiry as date objects:
            chain_df["expiry"] = chain_df["expiry"].dt.date

            # 2b) Hard stop if chain_df is empty or missing required columns
            if chain_df is None or chain_df.empty:
                print(f"SKIP {ticker}: empty chain_df from Alpaca")
                continue

            required_cols = {"expiry", "type", "strike", "bid", "ask"}
            missing = required_cols - set(chain_df.columns)
            if missing:
                print(f"SKIP {ticker}: chain_df missing columns: {sorted(missing)} | cols={list(chain_df.columns)}")
                continue


            # 4) Loop expiries ONCE (Alpaca expiries)
            for exp in sorted(chain_df["expiry"].unique()):
                try:
                    days = (exp - today).days
                    if days < 3:
                        continue

                    H_trading = get_trading_days(df_raw.index[-1], exp)
                    T_annualized = max(1/365, days / 365.0)

                    df_full = build_features(df_raw, ticker, H_trading)

                    exclude = [
                        "rv_forward_H", "log_rv_forward_H", f"ret_{ticker.lower()}",
                        "gspc", "xle", "oil", "usd", "vix", "tnx_10y", "hyg", "iei", "vvix",
                        "xlk", "xlp", "irx", "close_price", "ma_50", "rv_1d", "macd_hist",
                        "vix_basis", "xlf", "xlv", "iwm"
                    ]

                    preds = [c for c in df_full.columns if c not in exclude and not c.startswith("ret_")]

                    train_pool = df_full.dropna(subset=["log_rv_forward_H"])
                    live_state = df_full.iloc[-1:]

                    print(f"   [SYSTEM] Training Ensemble for {ticker} - {exp}...")
                    wfa_log, model_errors = run_wfa_competition(train_pool, preds)
                    avg_rmse = wfa_log["RMSE"].mean()

                    winner_list = wfa_log["Winner"].values
                    xgb_best = (
                        wfa_log[wfa_log["Winner"] == "XGB"].iloc[-1]["Params"]
                        if "XGB" in winner_list else {}
                    )

                    X_train = np.ascontiguousarray(train_pool[preds].values, dtype=np.float32)
                    y_train = np.ascontiguousarray(train_pool["log_rv_forward_H"].values, dtype=np.float32).flatten()
                    X_live  = np.ascontiguousarray(live_state[preds].values, dtype=np.float32)

                    m_xgb = xgb.XGBRegressor(n_jobs=-1, **xgb_best).fit(X_train, y_train)
                    m_rf  = RandomForestRegressor(n_jobs=-1).fit(X_train, y_train)

                    p_xgb = m_xgb.predict(X_live)[0]
                    p_rf  = m_rf.predict(X_live)[0]

                    xgb_err = float(np.mean(model_errors.get("XGB", 1.0)))
                    rf_err  = float(np.mean(model_errors.get("RF", 1.0)))

                    w_xgb = (1 / (xgb_err + 1e-6)) / ((1 / (xgb_err + 1e-6)) + (1 / (rf_err + 1e-6)))
                    w_rf  = 1 - w_xgb

                    sigma_model = np.sqrt(np.exp((p_xgb * w_xgb + p_rf * w_rf) + 0.5 * avg_rmse**2))

                    # Build chain object for this expiry (for process_chain)
                    chain_full = build_chain_for_expiry(chain_df, exp)

                    print(
                        f"   [CHAIN] {ticker} {exp} | "
                        f"calls={len(chain_full.calls):,} puts={len(chain_full.puts):,}"
                    )

                    if chain_full.calls.empty and chain_full.puts.empty:
                        print(f"SKIP {ticker} - {exp}: empty chain after filters")
                        continue

                    # Market IV proxy (if present)
                    mkt_iv = pd.to_numeric(
                        chain_df.loc[chain_df["expiry"] == exp, "iv"],
                        errors="coerce"
                    ).median()
                    if pd.isna(mkt_iv) or mkt_iv <= 0:
                        mkt_iv = sigma_model

                    vel_col = f"{ticker.lower()}_rv_vel"
                    rv_velocity = abs(float(live_state.get(vel_col, pd.Series([0])).iloc[0]))

                    z_score = (sigma_model - mkt_iv) / (avg_rmse * (1 + rv_velocity) + 1e-9)

                    current_S0 = float(live_state["close_price"].iloc[0])
                    regime = get_market_regime(live_state)

                    paths, p5d, p20d, tail_risk = run_monte_carlo(
                        current_S0, sigma_model, T_annualized, avg_rmse
                    )
                    opt_data = process_chain(
                        chain_full, current_S0, T_annualized, 0.042, sigma_model, paths
                    )

                    # Analytics
                    importance_vals = m_xgb.feature_importances_
                    top_idx = np.argsort(importance_vals)[-5:]
                    feat_imp_dict = {preds[i]: round(float(importance_vals[i]), 4) for i in top_idx}

                    hedge_results = get_institutional_hedge_data(df_full, ticker)

                    # Log for CSV report
                    results_log.append({
                        "Ticker": ticker,
                        "Expiry": str(exp),
                        "Days_to_Expiry": int(days),
                        "Zscore": round(float(z_score), 3),
                        "RMSE": round(float(avg_rmse), 4),
                        "MKTIV": round(float(mkt_iv), 4),
                        "MODELRV": round(float(sigma_model), 4),
                        "CallsUsed": int(len(chain_full.calls)),
                        "PutsUsed": int(len(chain_full.puts)),
                    })

                    # Save enriched JSON
                    print(f"   [DASHBOARD] Saving high-fidelity payload for {ticker}...")
                    save_batch_dashboard_json(
                        run_folder=run_folder,
                        ticker=ticker,
                        expiry=exp,
                        S0=current_S0,
                        sigma=sigma_model,
                        z_score=z_score,
                        regime=regime,
                        paths=paths,
                        opt_all=opt_data,
                        hedge_data=hedge_results,
                        feat_imp=feat_imp_dict
                    )

                    continuum_data.append({"Days": days, "Z": z_score})
                    print(f"SUCCESS: {ticker} - {exp} | Z: {z_score:.2f}")

                    time.sleep(0.25)

                except Exception as e:
                    print(f"SKIP {ticker} - {exp}: {e}")
                    continue

            # After all expiries for this ticker
            analyze_z_continuum(ticker, continuum_data, run_folder)

        except Exception as e:
            print(f"SKIP {ticker}: {e}")
            continue

    # Save full report
    pd.DataFrame(results_log).to_csv(report_file, index=False)
    print(f"\n[FINISH] Report saved as {report_file}")
if __name__ == "__main__":
    if not os.path.exists("Results"):
        os.makedirs("Results")
    main()
