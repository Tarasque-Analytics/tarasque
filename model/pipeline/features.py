"""
features.py — Transform raw datasets into a model-ready feature matrix.

Architecture ported from volarbmodel_backtest.py (DataIngestion :138-248,
VolArbModel.prepare_features :371-386).  New features added per
summary_march16.md analysis.

All features are point-in-time (no look-ahead).  The only forward-looking
columns are the targets ``y_{h}`` which use ``.shift(-h)``.
"""
import numpy as np
import pandas as pd
from typing import Dict, List, Optional

from .config import DataConfig, ModelConfig, SECTOR_ETF_MAP
from .utils import days_to_next_fomc, days_to_next_cpi, days_to_next_nfp
from .models import GarchForecaster


class FeatureBuilder:
    """
    Builds the complete feature matrix for a single ticker.

    Parameters
    ----------
    data_config : DataConfig
    model_config : ModelConfig
    """

    def __init__(self, data_config: DataConfig, model_config: ModelConfig):
        self.dc = data_config
        self.mc = model_config

    # ═══════════════════════════════════════════════════════════════════
    # PUBLIC
    # ═══════════════════════════════════════════════════════════════════

    def build(
        self,
        ticker: str,
        raw_data: Dict[str, pd.DataFrame],
    ) -> pd.DataFrame:
        """
        Master build: returns a DatetimeIndex DataFrame with all features
        and forward-looking target columns.
        """
        # 1. Prepare OHLCV pivots
        ohlcv = raw_data["ohlcv"].copy()
        ohlcv["date"] = pd.to_datetime(ohlcv["date"], format="mixed")

        closes, highs, lows, opens, adj_closes = self._pivot_ohlcv(ohlcv)

        if ticker not in closes.columns:
            raise ValueError(f"Ticker {ticker} not found in OHLCV data.")

        df = pd.DataFrame(index=closes.index)
        df[f"close_{ticker}"] = closes[ticker]

        # 2. Garman-Klass realised volatility (backtest :219-224)
        # Raw H/L/O/C are OK for intraday GK — same-day ratios unaffected by splits.
        # EWMA vol inside uses adj_closes for cross-day returns.
        df = self._add_rv_features(df, ticker, closes, highs, lows, opens, adj_closes)

        # 3. GARCH(1,1) conditional vol — feature input, not ensemble component
        adj_ret = np.log(adj_closes[ticker] / adj_closes[ticker].shift(1)).dropna()
        df = self._add_garch_features(df, adj_ret)

        # 4. Returns — use split-adjusted close for target return series
        df["ret_TARGET"] = np.log(adj_closes[ticker] / adj_closes[ticker].shift(1))

        # 5. Technical indicators (backtest :227-237) — use adj_closes
        df = self._add_technicals(df, ticker, adj_closes, highs, lows)

        # 6. Factor ETF returns — adj_closes fixes VIXY reverse-split contamination
        df = self._add_factor_returns(df, adj_closes)

        # 7. Volatility dynamics (backtest :377-379)
        df = self._add_vol_dynamics(df)

        # 8. Event gravity features (backtest :192-214)
        df = self._add_event_features(df, ticker, raw_data)

        # 9. Options-derived features (new — from OptionMetrics surface)
        if "vsurfd" in raw_data and not raw_data["vsurfd"].empty:
            df = self._add_options_features(df, ticker, raw_data["vsurfd"])

        # 9b. Open interest features (new — from OptionMetrics opprcd)
        if "oi_25delta" in raw_data and not raw_data["oi_25delta"].empty:
            df = self._add_oi_features(df, ticker, raw_data["oi_25delta"])

        # 10. Macro features (new — from FRED data)
        if "fred" in raw_data and not raw_data["fred"].empty:
            df = self._add_macro_features(df, raw_data["fred"])

        # 11. Factor decomposition (new — beta, residual vol)
        df = self._add_factor_decomposition(df, closes, ticker)

        # 12. Price regime (new — summary_march16.md:40)
        df = self._add_price_regime(df, closes, ticker)

        # 13. Sector coupling (new — summary_march16.md:43,61)
        df = self._add_sector_coupling(df, closes, ticker, raw_data)

        # 14. Targets (backtest :373-375)
        df = self._add_targets(df)

        # Drop rows where ANY target is NaN (tail rows that lack enough future
        # data for the longer horizons, e.g. last 126 rows for y_126).
        target_cols = [f"y_{h}" for h in self.mc.horizons if f"y_{h}" in df.columns]
        df = df.dropna(subset=target_cols)

        return df

    def get_predictor_columns(self, df: pd.DataFrame) -> List[str]:
        """
        Return feature column names (exclude targets, raw prices, date).

        Mirrors the backtest's predictor selection logic (:382-384) but
        extended for new feature prefixes.

        Explicit exclusions (updated 2026-04-23):
          rv_TARGET          — literal alias for rv_21d (VIF=inf); always exclude
          iv_atm_30d         — contained inside vrp_wedge (VIF=121); VIF too high
                               even for ElasticNet; vrp_wedge is the economically
                               meaningful quantity (relative to RV)
          vol_trend          — rv_21d / rolling_mean(rv_21d); numerically redundant
                               with vol_regime_zscore which is the standardised form
          put_call_abs_skew  — r=0.92 with put_call_skew_30d; signed skew sufficient
          tech_ATR           — Spearman r=0.949 with rv_21d; no incremental signal

        Re-included (ElasticNet handles correlated groups — no arbitrary zeroing):
          rv_5d, rv_10d, rv_63d   — short/medium RV windows; ElasticNet shrinks the
                                    RV cluster proportionally instead of picking one
          corr_sector_21d/252d    — rolling stock-sector correlation; captures regime-
          sector_wedge              specific coupling tightness. JPM H63/H126 R² dropped
                                    0.17 points after VIF exclusion. Signal is real for
                                    financials/energy even when collinear with ETF ret/mom.
        """
        exclude_prefixes = ("y_", "close_")
        include_prefixes = (
            "ret_", "rv_", "vol_", "tech_", "event_", "iv_",
            "put_call_", "term_", "vrp_", "macro_", "beta_",
            "res_", "price_", "corr_", "sector_", "ewma_", "mom21_",
            "garch_", "oi_", "fear_",
        )
        exclude_exact = {
            "rv_TARGET",              # literal alias for rv_21d (VIF=inf)
            "iv_atm_30d",             # contained inside vrp_wedge (VIF=121)
            "vol_trend",              # ratio form of vol_regime_zscore
            "put_call_abs_skew_30d",  # Spearman r=0.92 with put_call_skew_30d
            "tech_ATR",               # Spearman r=0.949 with rv_21d
        }
        cols = []
        for c in df.columns:
            if c in exclude_exact:
                continue
            if any(c.startswith(p) for p in exclude_prefixes):
                continue
            if any(c.startswith(p) for p in include_prefixes):
                cols.append(c)
        return cols

    # ═══════════════════════════════════════════════════════════════════
    # PRIVATE — OHLCV prep
    # ═══════════════════════════════════════════════════════════════════

    def _pivot_ohlcv(self, ohlcv: pd.DataFrame):
        """Pivot long-form OHLCV into wide DataFrames indexed by date.

        Returns raw price pivots (closes, highs, lows, opens) for intraday
        GK calculations, plus ``adj_closes`` — split-adjusted closes
        reconstructed from CRSP total return.  Use adj_closes for all
        cross-day return calculations (EWMA vol, RSI, MACD, factor returns)
        so that stock splits do not inject phantom volatility.
        """
        # Normalise column names (CRSP uses openprc/askhi/bidlo/prc)
        col_map = {}
        if "openprc" in ohlcv.columns:
            col_map = {"openprc": "open", "askhi": "high", "bidlo": "low", "prc": "close"}
        ohlcv = ohlcv.rename(columns=col_map)

        # Handle CRSP's negative price convention (negative = bid/ask avg)
        for c in ["open", "high", "low", "close"]:
            if c in ohlcv.columns:
                ohlcv[c] = ohlcv[c].abs()

        # CRSP msenames join can produce duplicate (date, ticker) rows when
        # name-date ranges overlap for the same permno. Keep the last record.
        ohlcv = ohlcv.drop_duplicates(subset=["date", "ticker"], keep="last")

        closes = ohlcv.pivot(index="date", columns="ticker", values="close").ffill()
        highs = ohlcv.pivot(index="date", columns="ticker", values="high").ffill()
        lows = ohlcv.pivot(index="date", columns="ticker", values="low").ffill()
        opens = ohlcv.pivot(index="date", columns="ticker", values="open").ffill()

        # ── Split-adjusted closes ────────────────────────────────────────
        # CRSP 'ret' is already adjusted for splits and dividends.
        # Reconstruct adjusted close: cumulative product of (1+ret) forward,
        # then scale so that adj_close[-1] == close[-1].
        # ffill(limit=1) avoids propagating stale returns over long gaps.
        if "ret" in ohlcv.columns:
            rets = (
                ohlcv.pivot(index="date", columns="ticker", values="ret")
                .ffill(limit=1)
                .fillna(0.0)
            )
            cum = (1.0 + rets).cumprod()
            # Scale per-ticker so adj_close[-1] == close[-1]
            last_raw = closes.iloc[-1]
            last_cum = cum.iloc[-1].replace(0, np.nan)
            adj_closes = cum * (last_raw / last_cum)
            # Align to closes index (handles any extra/missing dates)
            adj_closes = adj_closes.reindex(closes.index).ffill()
        else:
            # Fallback: no ret column, use raw closes (pre-CRSP data sources)
            adj_closes = closes.copy()

        return closes, highs, lows, opens, adj_closes

    # ═══════════════════════════════════════════════════════════════════
    # PRIVATE — Feature groups
    # ═══════════════════════════════════════════════════════════════════

    def _add_rv_features(self, df, ticker, closes, highs, lows, opens, adj_closes):
        """Garman-Klass RV at multiple windows.

        GK uses raw same-day H/L/O/C (intraday ratios, unaffected by splits).
        EWMA vol uses adj_closes for cross-day returns (split-safe).
        """
        log_hl = np.log(highs[ticker] / lows[ticker])
        log_co = np.log(closes[ticker] / opens[ticker])
        gk_var = 0.5 * (log_hl ** 2) - (2 * np.log(2) - 1) * (log_co ** 2)

        for w in self.mc.rv_windows:
            df[f"rv_{w}d"] = np.sqrt(gk_var.rolling(window=w).mean()) * np.sqrt(252)

        # Canonical target RV (21d) used by the backtest
        df["rv_TARGET"] = df["rv_21d"]

        # EWMA vol — use split-adjusted returns (cross-day, split-sensitive)
        adj_ret = np.log(adj_closes[ticker] / adj_closes[ticker].shift(1))
        df["ewma_vol"] = np.sqrt(adj_ret.pow(2).ewm(span=21).mean() * 252)

        return df

    def _add_garch_features(self, df, adj_ret: pd.Series) -> pd.DataFrame:
        """
        GARCH(1,1)-skewt conditional volatility as a predictor feature.

        Fits once on the full adj_ret series.  h_t at each date uses only
        returns up to t, so there is no observation-level lookahead.
        Parameters are estimated on the full series (mild lookahead, standard
        for a feature input).

        Adds:
          garch_cond_vol   — annualised conditional vol (the GARCH 'h_t' series)
        """
        cond_vol = GarchForecaster.cond_vol_series(
            adj_ret, dist=self.mc.garch_dist,
        )
        df["garch_cond_vol"] = cond_vol.reindex(df.index)
        return df

    def _add_technicals(self, df, ticker, closes, highs, lows):
        """RSI, ATR, MACD histogram."""
        close = closes[ticker]

        # RSI (backtest :227-231)
        delta = close.diff()
        gain = delta.where(delta > 0, 0).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / (loss + 1e-9)
        df["tech_RSI"] = 100 - (100 / (1 + rs))

        # ATR dropped — Spearman=0.949 with rv_21d, redundant for tree and Lasso models

        # MACD histogram (new)
        ema12 = close.ewm(span=12).mean()
        ema26 = close.ewm(span=26).mean()
        macd_line = ema12 - ema26
        signal_line = macd_line.ewm(span=9).mean()
        df["tech_MACD_hist"] = macd_line - signal_line

        return df

    def _add_factor_returns(self, df, closes):
        """Log returns and 21d momentum for the initial 6 factor ETFs."""
        for etf in self.dc.initial_factor_etfs:
            if etf in closes.columns:
                df[f"ret_{etf}"] = np.log(closes[etf] / closes[etf].shift(1))
                # 21d momentum: sustained trend context — is TLT in a grind or a spike?
                df[f"mom21_{etf}"] = np.log(closes[etf] / closes[etf].shift(21))
        return df

    def _add_vol_dynamics(self, df):
        """Vol trend, velocity, vol-of-vol, regime z-score, 21d change.

        New features (2026-04-03) motivated by residual analysis:
          vol_regime_zscore — how many std-devs above/below 252d mean is current
                              vol? Addresses ACF=0.96: model persistently wrong in
                              extreme regimes (COVID, 2018Q4) because it lacks
                              explicit regime context.
          vol_chg_21d       — signed 21-day change in rv_21d. Captures the slow
                              drift into/out of vol regimes (AR(1) persistence).
                              Different from vol_vel which is .diff(5).abs().
        """
        rv = df["rv_TARGET"]

        df["vol_trend"]  = rv / (rv.rolling(63).mean() + 1e-9)
        df["vol_vel"]    = rv.diff(5).abs()
        df["vol_of_vol"] = rv.rolling(21).std()

        # regime z-score: where in the historical vol distribution are we?
        rv_mean_252 = rv.rolling(252).mean()
        rv_std_252  = rv.rolling(252).std()
        df["vol_regime_zscore"] = (rv - rv_mean_252) / (rv_std_252 + 1e-9)

        # signed 21d vol momentum (direction + magnitude of regime drift)
        df["vol_chg_21d"] = rv - rv.shift(21)

        return df

    def _add_event_features(self, df, ticker, raw_data):
        """FOMC gravity, earnings gravity, dividend gravity."""
        # FOMC gravity (backtest :194-195)
        df["event_fed_gravity"] = df.index.to_series().apply(
            lambda d: 1.0 / (days_to_next_fomc(d) + 1)
        )

        # Earnings gravity (backtest :198-214)
        earnings = raw_data.get("earnings", pd.DataFrame())
        df = self._merge_event_gravity(
            df, earnings, ticker,
            date_col="rdq", ticker_col="tic",
            feature_name="event_earn_gravity",
        )

        # Dividend gravity (new — summary_march16.md:34)
        dividends = raw_data.get("dividends", pd.DataFrame())
        df = self._merge_event_gravity(
            df, dividends, ticker,
            date_col="datadate", ticker_col="tic",
            feature_name="event_div_gravity",
        )

        # CPI release gravity (BLS macro event)
        df["event_cpi_gravity"] = df.index.to_series().apply(
            lambda d: 1.0 / (days_to_next_cpi(d) + 1)
        )

        # NFP release gravity (BLS Employment Situation)
        df["event_nfp_gravity"] = df.index.to_series().apply(
            lambda d: 1.0 / (days_to_next_nfp(d) + 1)
        )

        return df

    def _merge_event_gravity(
        self, df, events_df, ticker,
        date_col, ticker_col, feature_name,
    ):
        """Compute inverse-distance gravity to next event date."""
        if events_df.empty or ticker_col not in events_df.columns:
            df[feature_name] = 0.0
            return df

        ev = events_df[events_df[ticker_col] == ticker].copy()
        if ev.empty:
            df[feature_name] = 0.0
            return df

        ev[date_col] = pd.to_datetime(ev[date_col])
        ev = ev.sort_values(date_col).drop_duplicates(subset=[date_col])

        # merge_asof: for each row in df, find the next event date
        temp = df[[]].copy()
        temp["date_key"] = pd.to_datetime(temp.index)

        merged = pd.merge_asof(
            temp.sort_values("date_key"),
            ev[[date_col]].rename(columns={date_col: "event_date"}),
            left_on="date_key",
            right_on="event_date",
            direction="forward",
        )
        days_to = (merged["event_date"] - merged["date_key"]).dt.days
        days_to = days_to.fillna(100).clip(lower=0, upper=100)
        df[feature_name] = (1.0 / (days_to + 1)).values

        return df

    def _add_options_features(self, df, ticker, vsurfd):
        """ATM IV, put-call skew, term structure slope, VRP wedge."""
        vs = vsurfd[vsurfd["ticker"] == ticker].copy()
        if vs.empty:
            for col in ["iv_atm_30d", "put_call_skew_30d",
                        "term_structure_slope", "vrp_wedge", "iv_atm_z_score"]:
                df[col] = np.nan
            return df

        vs["date"] = pd.to_datetime(vs["date"])
        vs = vs.set_index("date")

        # ATM IV: delta=50, 30 DTE
        # ffill limit=5: allow up to 5 missing trading days (e.g. holidays,
        # thin option markets).  Beyond that, leave NaN so the backtest
        # imputation handles it rather than carrying stale values for months.
        atm_30 = vs[(vs["days"] == 30) & (vs["delta"] == 50)]["impl_volatility"]
        atm_30 = atm_30.groupby(atm_30.index).first()
        df["iv_atm_30d"] = atm_30.reindex(df.index).ffill(limit=5)

        # Put-call skew: IV(delta=-25) - IV(delta=25) at 30 DTE
        put_25 = vs[(vs["days"] == 30) & (vs["delta"] == -25)]["impl_volatility"]
        put_25 = put_25.groupby(put_25.index).first()
        call_25 = vs[(vs["days"] == 30) & (vs["delta"] == 25)]["impl_volatility"]
        call_25 = call_25.groupby(call_25.index).first()
        skew = put_25.reindex(df.index).ffill(limit=5) - call_25.reindex(df.index).ffill(limit=5)
        df["put_call_skew_30d"] = skew
        # bilateral skew: VRP analysis showed U-shape — both tails of skew
        # (extreme put buying AND extreme call buying) precede elevated RV.
        df["put_call_abs_skew_30d"] = skew.abs()

        # Term structure slope: IV(91 DTE) - IV(30 DTE) at delta=50
        atm_91 = vs[(vs["days"] == 91) & (vs["delta"] == 50)]["impl_volatility"]
        atm_91 = atm_91.groupby(atm_91.index).first()
        df["term_structure_slope"] = (
            atm_91.reindex(df.index).ffill(limit=5) - df["iv_atm_30d"]
        )

        # VRP wedge: market IV - model RV
        df["vrp_wedge"] = df["iv_atm_30d"] - df["rv_TARGET"]

        # IV ATM z-score
        iv_mean = df["iv_atm_30d"].rolling(63).mean()
        iv_std = df["iv_atm_30d"].rolling(63).std()
        df["iv_atm_z_score"] = (df["iv_atm_30d"] - iv_mean) / (iv_std + 1e-9)

        return df

    def _add_oi_features(self, df, ticker, oi_data):
        """Open interest features at 25-delta: put/call ratio, fear intensity.

        fear_intensity_25d = IV skew x log(OI_put / OI_call)
        Multiplicative interaction: requires both price asymmetry (skew)
        AND quantity asymmetry (OI ratio) to fire.  If puts are expensive
        but nobody is buying them, or OI is skewed but pricing is flat,
        the signal stays near zero.
        """
        oi = oi_data[oi_data["ticker"] == ticker].copy()
        if oi.empty:
            for col in ["oi_put_call_ratio_25d", "fear_intensity_25d",
                        "oi_hedge_pressure_chg_5d"]:
                df[col] = np.nan
            return df

        oi["date"] = pd.to_datetime(oi["date"])

        # Aggregate to daily put/call totals
        put_oi = (oi[oi["cp_flag"] == "P"]
                  .groupby("date")["total_oi"].sum()
                  .sort_index())
        call_oi = (oi[oi["cp_flag"] == "C"]
                   .groupby("date")["total_oi"].sum()
                   .sort_index())

        put_oi = put_oi.reindex(df.index).ffill(limit=5)
        call_oi = call_oi.reindex(df.index).ffill(limit=5)

        # Put/call OI ratio
        ratio = put_oi / (call_oi + 1e-6)
        df["oi_put_call_ratio_25d"] = ratio

        # Fear intensity: skew x log(OI ratio)
        oi_log_ratio = np.log(put_oi / (call_oi + 1e-6))
        skew = df.get("put_call_skew_30d")
        if skew is not None:
            df["fear_intensity_25d"] = skew * oi_log_ratio
        else:
            df["fear_intensity_25d"] = np.nan

        # Hedging pressure momentum: 5d change in put/call ratio
        df["oi_hedge_pressure_chg_5d"] = ratio.diff(5)

        return df

    def _add_macro_features(self, df, fred):
        """Treasury rates, yield curve slope, credit spread, breakevens."""
        fred = fred.copy()
        fred["date"] = pd.to_datetime(fred["date"])
        fred = fred.set_index("date").sort_index()

        # Reindex to match df dates, forward-fill
        fred = fred.reindex(df.index, method="ffill")

        # Yield curve slope: prefer 10y-2y; fall back to 10y-3mo (^IRX proxy)
        if "treasury_10y" in fred.columns:
            if "treasury_2y" in fred.columns:
                df["macro_yield_curve_slope"] = fred["treasury_10y"] - fred["treasury_2y"]
            elif "treasury_3mo" in fred.columns:
                df["macro_yield_curve_slope"] = fred["treasury_10y"] - fred["treasury_3mo"]

        # HY spread level and momentum
        if "hy_spread" in fred.columns:
            df["macro_hy_spread"] = fred["hy_spread"]
            df["macro_hy_spread_chg_5d"] = fred["hy_spread"].diff(5)

        # Breakeven inflation
        if "breakeven_5y" in fred.columns:
            df["macro_breakeven_5y"] = fred["breakeven_5y"]

        # 5yr/5yr forward inflation expectation (T5YIFR)
        # Captures structural inflation regime independent of near-term noise.
        # High + rising = market pricing persistent inflation (risk-off for equities,
        # elevated vol). Low + falling = deflationary fear (2020-shock style).
        # More informative than breakeven_5y for distinguishing regime *type*.
        if "inflation_forward_5y5y" in fred.columns:
            infl = fred["inflation_forward_5y5y"]
            df["macro_inflation_fwd_5y5y"] = infl
            # 21d momentum: directional shift in long-run inflation view
            df["macro_inflation_fwd_chg_21d"] = infl.diff(21)
            # bilateral shock magnitude: rising OR falling fast = regime transition uncertainty
            df["macro_inflation_fwd_abs_chg_21d"] = infl.diff(21).abs()
            # slower drift: captures structural regime shifts without 21d noise
            df["macro_inflation_fwd_chg_63d"] = infl.diff(63)
            # zscore: "living with inflation" — level relative to recent 252d norm.
            # After 18mo at 2.8%, zscore returns toward 0 even as level stays elevated,
            # telling the model the market has repriced around this level.
            infl_mean = infl.rolling(252).mean()
            infl_std  = infl.rolling(252).std()
            df["macro_inflation_fwd_zscore"] = (infl - infl_mean) / (infl_std + 1e-9)

        # Dollar index returns
        if "dollar_index" in fred.columns:
            df["macro_dollar_ret"] = np.log(
                fred["dollar_index"] / fred["dollar_index"].shift(1)
            )

        return df

    def _add_factor_decomposition(self, df, closes, ticker):
        """Rolling beta to SPY, residual vol, residual vol velocity."""
        if "SPY" not in closes.columns:
            for col in ["beta_spy", "res_vol", "res_vol_vel"]:
                df[col] = np.nan
            return df

        ret_stock = np.log(closes[ticker] / closes[ticker].shift(1))
        ret_spy = np.log(closes["SPY"] / closes["SPY"].shift(1))

        window = 63

        # Rolling beta
        cov = ret_stock.rolling(window).cov(ret_spy)
        var_spy = ret_spy.rolling(window).var()
        df["beta_spy"] = cov / (var_spy + 1e-12)

        # Residual vol = vol of (stock return - beta * spy return)
        residuals = ret_stock - df["beta_spy"] * ret_spy
        df["res_vol"] = residuals.rolling(window).std() * np.sqrt(252)

        # Residual vol velocity
        df["res_vol_vel"] = df["res_vol"].diff(5)

        return df

    def _add_price_regime(self, df, closes, ticker):
        """Drawdown from 252-day peak (summary_march16.md:40)."""
        df["price_regime"] = closes[ticker] / closes[ticker].rolling(252).max() - 1
        return df

    def _add_sector_coupling(self, df, closes, ticker, raw_data):
        """
        Rolling correlation with the stock's sector ETF.

        Uses GICS sector code from Compustat to look up the correct
        sector ETF.  Falls back to SPY if GICS unavailable.
        """
        sector_etf = self._get_sector_etf(ticker, raw_data)

        if sector_etf not in closes.columns:
            for col in ["corr_sector_21d", "corr_sector_252d", "sector_wedge"]:
                df[col] = np.nan
            return df

        ret_stock = np.log(closes[ticker] / closes[ticker].shift(1))
        ret_sector = np.log(closes[sector_etf] / closes[sector_etf].shift(1))

        df["corr_sector_21d"] = ret_stock.rolling(21).corr(ret_sector)
        df["corr_sector_252d"] = ret_stock.rolling(252).corr(ret_sector)
        df["sector_wedge"] = df["corr_sector_21d"] - df["corr_sector_252d"]

        return df

    def _get_sector_etf(self, ticker: str, raw_data: Dict) -> str:
        """Look up the sector ETF for a ticker via GICS code."""
        meta = raw_data.get("compustat_meta", pd.DataFrame())
        if meta.empty or "tic" not in meta.columns:
            return "SPY"

        row = meta[meta["tic"] == ticker]
        if row.empty or "gsector" not in row.columns:
            return "SPY"

        gsector = str(int(row["gsector"].dropna().iloc[-1]))
        return SECTOR_ETF_MAP.get(gsector, "SPY")

    # ═══════════════════════════════════════════════════════════════════
    # PRIVATE — Targets
    # ═══════════════════════════════════════════════════════════════════

    def _add_targets(self, df):
        """
        Forward-looking RV targets at each horizon (log-transformed).

        Uses rv_{h}d.shift(-h) so the target window [t+1, t+h] has zero
        sample overlap with rv_21d[t] = [t-20, t].  The old rolling().mean()
        approach produced targets that shared 20/21 days with the primary
        feature, inflating in-sample R².
        """
        for h in self.mc.horizons:
            col = f"rv_{h}d"
            if col not in df.columns:
                # Fallback: shouldn't happen if rv_windows includes all horizons
                raw_target = df["rv_TARGET"].shift(-h)
            else:
                raw_target = df[col].shift(-h)
            df[f"y_{h}"] = np.log(raw_target + 1e-9)
        return df
