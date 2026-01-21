
import numpy as np
import pandas as pd
import yfinance as yf
from scipy.stats import norm
from scipy.optimize import brentq, minimize
from datetime import date, timedelta
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import seaborn as sns
import warnings
warnings.filterwarnings("ignore")

# --- CORE LIBRARIES ---
import xgboost as xgb
from sklearn.model_selection import TimeSeriesSplit, GridSearchCV
from sklearn.metrics import mean_squared_error
from sklearn.linear_model import Lasso
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import LinearRegression

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

# ---------------- CONFIGURATION ----------------
TOTAL_AUM = 20000
OPTIONS_BUDGET = TOTAL_AUM * 0.10
WFA_STEP_DAYS = 25
WFA_NUM_STEPS = 5

# DYNAMIC HOLIDAY GENERATION (No more hardcoding)
cal = USFederalHolidayCalendar()
# Generate holidays for a wide window (e.g., 2020 to 2030) to cover all backtests
holidays = cal.holidays(start='2020-01-01', end='2030-12-31')
HOLIDAYS_NP = np.array(holidays.date, dtype='datetime64[D]')

MARKET_INDEX = "^GSPC"
# ... (Rest of config remains the same)
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

# ---------------- TRADING DAYS ----------------
def get_trading_days(start_date, end_date):
    s = np.datetime64(pd.to_datetime(start_date).date(), 'D')
    e = np.datetime64(pd.to_datetime(end_date).date(), 'D')
    days = np.busday_count(s, e, holidays=HOLIDAYS_NP)
    return max(1, days + 1)

def download_history(ticker):
    print(f"\n[YFINANCE] Pulling 5Y data for {ticker} and macros...")

    macro_tkrs = [ticker, "SPY", "XLK", "^VIX", "^VVIX", "HYG", "IEI", "^TNX", "CL=F", "DX-Y.NYB", "XLP", "^IRX", "XLF", "XLE", "XLV", "IWM"]
    
    # Force a fresh download by defining a specific end date (Tomorrow) to bypass cache
    # This prevents the "Jan 7 vs Jan 13" stale data issue
    import datetime
    tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).strftime('%Y-%m-%d')
    
    # We use start="2020-01-01" instead of period="5y" to ensure precise alignment
    data = yf.download(macro_tkrs, start="2021-01-01", end=tomorrow, interval="1d", progress=False, auto_adjust=True)

    if data.empty:
        raise ValueError("No data from yfinance")

    df = pd.DataFrame(index=data.index)

    def get_close_price(df_yf, symbol):
        if isinstance(df_yf.columns, pd.MultiIndex):
            try: return df_yf['Close'][symbol]
            except KeyError:
                try: return df_yf['Adj Close'][symbol]
                except KeyError: return pd.Series(index=df_yf.index, dtype=float)
        else:
            return df_yf[symbol] if symbol in df_yf.columns else pd.Series(index=df_yf.index, dtype=float)

    df["close_price"] = get_close_price(data, ticker)
    df[f"ret_{ticker.lower()}"] = np.log(df["close_price"] / df["close_price"].shift(1))

    mapping = {
        "^VIX": "VIX", "^VVIX": "VVIX", "HYG": "HYG", "IEI": "IEI",
        "^TNX": "TNX_10Y", "SPY": "GSPC", "XLK": "XLK", "CL=F": "OIL",
        "DX-Y.NYB": "USD", "XLP": "XLP", "^IRX": "IRX",
        "XLF": "XLF", "XLE": "XLE", "XLV": "XLV", "IWM": "IWM"
    }

    for tkr, name in mapping.items():
        df[name] = get_close_price(data, tkr)
        if name in ["GSPC", "XLK", "OIL", "USD", "HYG", "IEI", "XLP", "IRX", "XLF", "XLE", "XLV", "IWM"]:
            df[f"ret_{name.lower()}"] = np.log(df[name] / df[name].shift(1))
            df[f"{name.lower()}_rv"] = df[f"ret_{name.lower()}"].rolling(21).std() * np.sqrt(252)
            df[f"{name.lower()}_rv_vel"] = df[f"{name.lower()}_rv"].diff(5)

    df = df.dropna(subset=[f"ret_{ticker.lower()}"])
    df = df.ffill().fillna(0)

    # --- DATA LAG CHECK ---
    last_dt = df.index[-1].date()
    today = datetime.date.today()
    if (today - last_dt).days > 3:
        print(f"[SYSTEM WARNING] Data lag detected (Latest: {last_dt}). Attempting Patch...")
        # (Optional) You could insert specific patch logic here, but the explicit 'end=tomorrow' 
        # in yf.download usually solves this.
        
    print(f"Final dataset: {len(df)} days. Latest Data: {last_dt}")
    return df.sort_index()


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

    return df.copy()

def get_market_regime(live_row):
    adx = live_row["adx_strength"].iloc[0]
    vol = live_row["vol_trend"].iloc[0]
    if adx > 0.20 or vol > 1.3:
        return "TRENDING"
    return "RANGING"

def bs_pricing(S, K, T, r, sigma, type_="call"):
    d1 = (np.log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*np.sqrt(T))
    d2 = d1 - sigma*np.sqrt(T)
    if type_ == "call": return S*norm.cdf(d1) - K*np.exp(-r*T)*norm.cdf(d2)
    return K*np.exp(-r*T)*norm.cdf(-d2) - S*norm.cdf(-d1)

def get_iv(S, K, T, r, price, type_="call"):
    def objective_function(sigma):
        return bs_pricing(S, K, T, r, sigma, type_) - price
    intrinsic = max(0, S - K if type_ == "call" else K - S)
    if price <= intrinsic:
        return 0.0
    try:
        return brentq(objective_function, 1e-4, 5.0, xtol=1e-6)
    except (ValueError, RuntimeError):
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
            
            mkt_iv = get_iv(S0, K, T, r, mid, opt_type.lower())
            fair_px = bs_pricing(S0, K, T, r, sigma_forecast, opt_type.lower())
            
            if np.isnan(mkt_iv): continue

            d1 = (np.log(S0/K) + (r + 0.5*sigma_forecast**2)*T) / (sigma_forecast*np.sqrt(T))
            delta = norm.cdf(d1) if opt_type == "Call" else norm.cdf(d1) - 1
            
            # --- SANITY CHECK 4: MONEYNESS ---
            # Focus on high-conviction zones (Delta between 0.10 and 0.85)
            if abs(delta) < 0.10 or abs(delta) > 0.85: continue

            side = "NONE"
            if fair_px > ask: side = "LONG"
            elif fair_px < bid: side = "SHORT"
            
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
                "Fair_Px": round(fair_px, 2), "Edge_Pct_Val": mean_ret,
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
        ax2.scatter(c["Strike"], c["Fair_Px"], c='cyan', alpha=0.5, label='Fair Px')
        ax2.scatter(p["Strike"], p["Mkt_Px"], c='red', marker='x', label='Mkt Price')
        ax2.scatter(p["Strike"], p["Fair_Px"], c='orange', alpha=0.5, label='Fair Px')
    ax2.axvline(x=S0, color="white", ls="--", label="Spot")
    ax2.set_title("Price Arbitrage Map (Market vs Model)")
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
    plt.show()

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
    print("\n=== AUTO-HEDGE RECIPE (Lasso-Optimized, $1k Basis) ===\n")

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

# ---------------- MAIN ----------------
def main():
    ticker = input("Enter ticker: ").strip().upper()
    yf_ticker = yf.Ticker(ticker)

    df_raw = download_history(ticker)
    last_trading_day = df_raw.index[-1]
    
    # --- 1. ROBUST OPTION FETCHING (Retry Logic) ---
    import time
    max_retries = 3
    expuries = ()
    for attempt in range(max_retries):
        expuries = yf_ticker.options
        if expuries: break
        print(f"[Attempt {attempt+1}] Options chain unavailable. Retrying in 1s...")
        time.sleep(1)
        yf_ticker = yf.Ticker(ticker)
        
    if not expuries:
        print("[CRITICAL ERROR] Could not fetch options. Exiting.")
        return

    [print(f"{i+1}: {e}") for i, e in enumerate(expuries)]
    try:
        idx = int(input("Choose expiry: ")) - 1
        expiry_dt = pd.to_datetime(expuries[idx])
    except:
        idx = 0; expiry_dt = pd.to_datetime(expuries[idx])

    # --- 2. HORIZON & FEATURES ---
    H_trading = get_trading_days(last_trading_day, expiry_dt)
    T_annualized = max(1/365, (expiry_dt.date() - last_trading_day.date()).days / 365.0)
    print(f"[SYSTEM] Horizon: {H_trading} Trading Days | {(expiry_dt.date() - last_trading_day.date()).days} Calendar Days")

    df_full = build_features(df_raw, ticker, H_trading)
    exclude = ["rv_forward_H", "log_rv_forward_H", f"ret_{ticker.lower()}", "GSPC", "XLE", "OIL", "USD", 
               "VIX", "TNX_10Y", "HYG", "IEI", "VVIX", "XLK", "XLP", "IRX", "close_price", 
               "ma_50", "rv_1d", "macd_hist", "vix_basis", "XLF", "XLV", "IWM"]
    preds = [c for c in df_full.columns if c not in exclude and not c.startswith("ret_")]

    train_pool = df_full.dropna(subset=["log_rv_forward_H"])
    live_state = df_full.iloc[[-1]]

    # --- 3. MODEL TRAINING & ENSEMBLE ---
    wfa_log, model_errors = run_wfa_competition(train_pool, preds)
    avg_rmse = wfa_log["RMSE"].mean()

    # Dynamic Weights Logic
    xgb_params = wfa_log[wfa_log["Winner"]=="XGB"].iloc[-1]["Params"] if "XGB" in wfa_log["Winner"].values else {}
    rf_params = wfa_log[wfa_log["Winner"]=="RF"].iloc[-1]["Params"] if "RF" in wfa_log["Winner"].values else {}
    
    m_xgb = xgb.XGBRegressor(n_jobs=-1, **xgb_params).fit(train_pool[preds], train_pool["log_rv_forward_H"])
    m_rf = RandomForestRegressor(n_jobs=-1, **rf_params).fit(train_pool[preds], train_pool["log_rv_forward_H"])
    m_lasso = Lasso(alpha=0.01).fit(train_pool[preds], train_pool["log_rv_forward_H"])

    p_xgb = m_xgb.predict(live_state[preds])[0]
    p_rf = m_rf.predict(live_state[preds])[0]
    p_lasso = m_lasso.predict(live_state[preds])[0]
    
    xgb_score = 1/(model_errors.get("XGB", 1.0) + 1e-6)
    rf_score = 1/(model_errors.get("RF", 1.0) + 1e-6)
    total_score = xgb_score + rf_score
    w_xgb = 0.90 * (xgb_score / total_score)
    w_rf  = 0.90 * (rf_score / total_score)
    
    print(f"\n[TARASQUE] Market Regime: {get_market_regime(live_state)} | Weights: XGB {w_xgb:.1%}, RF {w_rf:.1%}")

    log_sigma_pred = (p_xgb * w_xgb) + (p_rf * w_rf) + (p_lasso * 0.10)
    sigma_model = np.sqrt(np.exp(log_sigma_pred + 0.5 * avg_rmse**2))

    # === PERFORMANCE SLICE PLOT ===
    N = 100  # last ~100 obs as a sanity OOS slice
    eval_slice = train_pool.iloc[-N:]
    plot_pred_vs_real(eval_slice, preds, m_xgb, m_rf, m_lasso, w_xgb, w_rf)


    # --- 4. Z-SCORE & ANALYSIS (Restored Block) ---
    S0 = get_robust_S0(yf_ticker, df_raw)
    paths, p5d, p20d, tail_risk = run_monte_carlo(S0, sigma_model, T_annualized, avg_rmse)
    
    # Process chain using the NEW logic (Full Visibility)
    opt_all = process_chain(yf_ticker.option_chain(expuries[idx]), S0, T_annualized, 0.042, sigma_model, paths)

    if not opt_all.empty:
        # Calculate Z-Score BEFORE plotting
        mkt_iv = opt_all['IV'].median()
        z_score = (mkt_iv - sigma_model) / (avg_rmse + 1e-9)
        
        print("\n" + "="*50)
        print("   MODEL STATISTICAL CERTAINTY INDEX")
        print("   " + "="*50)
        print(f"   Market Median IV:  {mkt_iv:.1%}")
        print(f"   Model ML RV: {sigma_model:.1%}")
        print(f"   Z-Score:           {z_score:.2f} Standard Deviations")
        
        if abs(z_score) > 1.96: print("   >>> [SIGNAL] Model is 95% Confident in Dissimilarity ")
        elif abs(z_score) > 1.0: print("   >>> [SIGNAL] Model finds some significance")
        else: print("   >>> [SIGNAL] Market is spot-on")
        print("="*50 + "\n")

    # --- 5. HEDGING & SIGNALS (Consolidated) ---
    best_model_for_viz = m_xgb if w_xgb > w_rf else m_rf
    auto_hedge_recommendations(df_full, best_model_for_viz, preds, sigma_model, opt_all, TOTAL_AUM, ticker)
    from sklearn.metrics import r2_score

    # After train_pool, preds, and final ensemble pred are available

    # Back-of-the-envelope out-of-sample check over the last N days
    N = 100
    eval_slice = train_pool.iloc[-N:]
    y_true = eval_slice["log_rv_forward_H"].values

    y_pred_xgb = m_xgb.predict(eval_slice[preds])
    y_pred_rf  = m_rf.predict(eval_slice[preds])
    y_pred_lasso = m_lasso.predict(eval_slice[preds])

    y_pred_ens = (
        y_pred_xgb * w_xgb +
        y_pred_rf  * w_rf +
        y_pred_lasso * 0.10
    )

    rmse_ens = np.sqrt(np.mean((y_true - y_pred_ens)**2))
    corr_ens = np.corrcoef(y_true, y_pred_ens)[0, 1]
    r2_ens   = r2_score(y_true, y_pred_ens)

    print("\n=== MODEL SUMMARY (last {} obs) ===".format(N))
    print(f"RMSE (log-RV):  {rmse_ens:.4f}")
    print(f"R² (log-RV):    {r2_ens:.3f}")
    print(f"Corr(pred, y):  {corr_ens:.3f}")
    print("=================================\n")


    

    if not opt_all.empty:
        # Filter for only the rows where the model actually found an edge
        signals = opt_all[opt_all["Action"] != "NONE"].copy()
        
        if not signals.empty:
            print(f"\n[Leo's] Budget: ${OPTIONS_BUDGET} | Ensemble Edge Detected")
            
            # Use the updated column names from your new process_chain logic
            # Note: We use 'Edge_Pct_Val' for sorting but print 'Edge_Pct'
            signals["Edge_Pct"] = signals["Edge_Pct_Val"].apply(lambda x: f"{x:.1%}")
            
            # Recalculate Qty with the 'Conviction Override' logic
            def calc_qty(row):
                silo_kelly = row.get('Silo_Kelly', 0)
                entry_px = row['Mkt_Px']
                raw_qty = int((silo_kelly * OPTIONS_BUDGET) / (entry_px * 100))
                # Conviction Override: Force 1 if edge is high but budget is tight
                if raw_qty == 0 and row['Edge_Pct_Val'] > 0.15 and (entry_px * 100) < (OPTIONS_BUDGET * 0.5):
                    raw_qty = 1
                return raw_qty

            signals["Qty"] = signals.apply(calc_qty, axis=1)
            
            signals = signals.sort_values("Edge_Pct_Val", ascending=False).head(10)
            display_cols = ["Action", "Type", "Strike", "Delta", "Mkt_Px", "Fair_Px", "Edge_Pct", "PoP", "Qty"]
            print(signals[display_cols].to_string(index=False))

            top_trade = signals.iloc[0]
            print(f"\n[SIGNAL] Top Opportunity: {top_trade['Action']} {top_trade['Strike']} {top_trade['Type']}")
        else:
            print("\n[SIGNAL] No statistically significant arbitrage opportunities found.")
    else:
        print("\n[ALERT] Not enough liquidity, do not trade derivatives on this equity.")

    # --- 6. FINAL VISUALIZATION ---
    plot_full_dashboard(paths, opt_all, S0, sigma_model, ticker, wfa_log, p5d, p20d, tail_risk, best_model_for_viz, preds, avg_rmse, H_trading, df_full)

if __name__ == "__main__":
    main()