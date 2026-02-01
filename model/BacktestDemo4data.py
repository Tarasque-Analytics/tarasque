import warnings
import logging
import os
import numpy as np
import pandas as pd
import yfinance as yf
import xgboost as xgb
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_squared_error
import time

# --- [1] CONFIGURATION ---

MODE = 'SECTOR_SWEEP'  # Change this so the output filename becomes unique

if MODE == 'SECTOR_SWEEP':
    # The "Titan" from every major sector
    TICKERS = [
        'MS',    # Financials (Baseline)
        'MSFT',  # Tech / Growth (The Engine)
        'XOM',   # Energy (Inflation Hedge)
        'KO',    # Staples (Defensive / "Cola")
        'PG',    # Staples (The safety trade)
        'JNJ',   # Healthcare (Low Beta)
        'CAT',   # Industrials (Real Economy)
        'AMZN',  # Consumer Discretionary (The Spender)
        'NEE'    # Utilities (Bond Proxy)
    ]
    N_ESTIMATORS = 500      
    MAX_DEPTH = 6           
    RETRAIN_STEP = 5        
    N_JOBS = -1         

START_DATE = '2020-01-01' 
WARMUP_YEARS = 3          
FORWARD_WINDOW = 21       

# --- [2] SILENCE ---
os.environ['PYTHONWARNINGS'] = 'ignore'
warnings.filterwarnings("ignore")
logging.getLogger('yfinance').setLevel(logging.CRITICAL)

# --- [3] ROBUST DATA INGESTION ---
def download_data(ticker):
    print(f"\n--> [I/O] Downloading Deep History for {ticker}...")
    try:
        start_dl = str(int(START_DATE[:4]) - WARMUP_YEARS) + "-01-01"
        
        # 1. Download Ticker and Macros SEPARATELY 
        # (This prevents a bad macro from killing the main ticker)
        macros = ["SPY", "^VIX", "^TNX", "CL=F", "DX-Y.NYB", "XLK", "HYG"]
        
        # Download Main Ticker
        df_main = yf.download(ticker, start=start_dl, progress=False, auto_adjust=True)
        if df_main.empty:
            print(f"    [FAIL] Could not download {ticker}. Check spelling.")
            return None
            
        # Download Macros
        df_macro = yf.download(macros, start=start_dl, progress=False, auto_adjust=True)
        
        # Flatten Macros if MultiIndex
        if isinstance(df_macro.columns, pd.MultiIndex):
            # Try to grab 'Close' level
            try:
                df_macro = df_macro['Close']
            except:
                pass # Already flat?

        # 2. Merge Data
        # We align everything to the Main Ticker's index
        clean = pd.DataFrame(index=df_main.index)
        
        # Handle Main Ticker Column (New YF format often returns Ticker as col name)
        if isinstance(df_main.columns, pd.MultiIndex):
             clean['close_price'] = df_main['Close'][ticker] # Try standard MultiIndex
        elif ticker in df_main.columns:
             clean['close_price'] = df_main[ticker]
        elif 'Close' in df_main.columns:
             clean['close_price'] = df_main['Close']
        else:
             print(f"    [FAIL] Column format weird for {ticker}: {df_main.columns}")
             return None

        # 3. Safely Add Macros (With Fallbacks)
        def add_macro(name, yf_name):
            if yf_name in df_macro.columns:
                clean[name] = df_macro[yf_name]
            else:
                print(f"    [WARN] Macro '{yf_name}' missing. Filling with 0.")
                clean[name] = 0.0 # Fill with 0 instead of NaN so we don't drop rows

        add_macro('SPY', 'SPY')
        add_macro('VIX', '^VIX')
        add_macro('TNX', '^TNX')
        
        # 4. Feature Engineering
        clean = clean.ffill().dropna() # Fill missing macro days (holidays)
        
        clean[f'ret_{ticker}'] = np.log(clean['close_price'] / clean['close_price'].shift(1))
        clean['rv_21d'] = clean[f'ret_{ticker}'].rolling(21).std() * np.sqrt(252)
        clean['target_rv'] = clean['rv_21d'].shift(-FORWARD_WINDOW)
        
        # Vol Dynamics
        clean['vol_trend'] = clean['rv_21d'] / (clean['rv_21d'].rolling(63).mean() + 1e-9)
        clean['vol_accel'] = clean['rv_21d'].diff(5)
        clean['vol_jumps'] = (clean['rv_21d'] - clean['rv_21d'].shift(1)) / (clean['rv_21d'].shift(1) + 1e-9)
        
        # Macro Features
        spy_ret = clean['SPY'].pct_change()
        clean['beta_spy'] = clean[f'ret_{ticker}'].rolling(63).cov(spy_ret) / (spy_ret.rolling(63).var() + 1e-9)
        clean['vix_regime'] = clean['VIX'] / clean['VIX'].rolling(252).mean()
        clean['rate_stress'] = clean['TNX'].diff(21)
        
        clean = clean.dropna()
        
        if len(clean) < 500:
            print(f"    [FAIL] Not enough data after processing ({len(clean)} rows).")
            return None
            
        print(f"    [OK] Ready. {len(clean)} rows.")
        return clean
        
    except Exception as e:
        print(f"    [ERROR] Critical Failure: {e}")
        return None

# --- [4] THE HEAVY LIFTER ---
def run_heavy_backtest(ticker):
    df = download_data(ticker)
    if df is None: return []
    
    start_idx = df.index.searchsorted(pd.Timestamp(START_DATE))
    
    print(f"--> [EXEC] Starting Walk-Forward on {ticker}")
    history_log = []
    features = ['rv_21d', 'vol_trend', 'vol_accel', 'vol_jumps', 'beta_spy', 'vix_regime', 'rate_stress']
    
    steps = range(start_idx, len(df) - FORWARD_WINDOW, RETRAIN_STEP)
    total_steps = len(steps)
    start_time = time.time()
    
    for i, t in enumerate(steps):
        # A. EXPANDING WINDOW
        X_train = df[features].iloc[:t]
        y_train = np.log(df['target_rv'].iloc[:t] + 1e-9)
        
        # B. TRAIN
        # GPU ENABLED (Uncomment 'tree_method' lines if on the Rig)
        xgb_m = xgb.XGBRegressor(
            n_estimators=N_ESTIMATORS, 
            max_depth=MAX_DEPTH, 
            n_jobs=N_JOBS, 
            # tree_method='hist', device='cuda', # UNCOMMENT FOR BUDDY'S RIG
            random_state=42
        )
        rf_m = RandomForestRegressor(n_estimators=N_ESTIMATORS, max_depth=MAX_DEPTH, n_jobs=N_JOBS, random_state=42)
        
        xgb_m.fit(X_train, y_train)
        rf_m.fit(X_train, y_train)
        
        # RMSE for Z-Score
        recent_X = X_train.iloc[-63:]
        recent_y = y_train.iloc[-63:]
        preds_in = (xgb_m.predict(recent_X) + rf_m.predict(recent_X)) / 2
        rmse = np.sqrt(mean_squared_error(recent_y, preds_in))
        
        # C. PREDICT
        chunk_end = min(t + RETRAIN_STEP, len(df) - FORWARD_WINDOW)
        X_live = df[features].iloc[t : chunk_end]
        if X_live.empty: break
        
        p_xgb = xgb_m.predict(X_live)
        p_rf = rf_m.predict(X_live)
        rv_pred = np.exp((p_xgb + p_rf) / 2)
        
        # D. LOG
        dates_live = df.index[t : chunk_end]
        for k, d in enumerate(dates_live):
            actual = df['target_rv'].iloc[t+k]
            proxy = df['rv_21d'].iloc[t+k] 
            z = (rv_pred[k] - proxy) / (rmse + 1e-9)
            win = 1 if np.sign(z) == np.sign(actual - proxy) else 0
            
            history_log.append({
                "Date": d, "Ticker": ticker, "Z_Score": z,
                "Forecast": rv_pred[k], "Actual": actual, "Win": win
            })
            
        if i % 10 == 0:
            elapsed = time.time() - start_time
            pct = (i / total_steps) * 100
            print(f"    [{pct:.1f}%] Rows: {len(X_train)} | Time: {elapsed:.1f}s")

    return history_log

if __name__ == "__main__":
    print(f"=== VOLARBEAR 'HEAVY' BACKTEST ENGINE ===")
    all_results = []
    for tkr in TICKERS:
        res = run_heavy_backtest(tkr)
        all_results.extend(res)
        
    if all_results:
        final_df = pd.DataFrame(all_results)
        final_df.to_csv(f"VolarBear_Heavy_Backtest_{MODE}.csv", index=False)
        print(f"\n[SUCCESS] Generated {len(final_df)} rows. Accuracy: {final_df['Win'].mean():.1%}")
    else:
        print("\n[FAIL] No data generated.")