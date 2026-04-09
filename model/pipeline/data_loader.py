"""
data_loader.py — Unified data acquisition from WRDS (historical) and
Alpaca/yfinance (recent).

Replaces database_build_script.py and the DataIngestion class from
volarbmodel_backtest.py.  Monthly chunking pattern preserved from
database_build_script.py:28-77.
"""
import os
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from typing import List, Optional, Dict

from .config import DataConfig


# ═══════════════════════════════════════════════════════════════════════════
# WRDS LOADER
# ═══════════════════════════════════════════════════════════════════════════

class WRDSLoader:
    """Queries WRDS PostgreSQL with monthly chunking and retry logic."""

    def __init__(self, config: DataConfig):
        self.config = config
        self._db = None

    # -- connection management ------------------------------------------

    @staticmethod
    def _read_pgpass_credentials() -> tuple:
        """
        Read WRDS username and password.

        Priority:
          1. pgpass.conf  (Windows: %APPDATA%\\postgresql\\pgpass.conf,
                           Unix:    ~/.pgpass)
          2. WRDS_USERNAME / WRDS_PASSWORD env vars  (set in model/.env)

        Returns (username, password) or ("", "") if neither source found.
        """
        import sys
        if sys.platform == "win32":
            appdata = os.getenv("APPDATA", "")
            pgpass_path = Path(appdata) / "postgresql" / "pgpass.conf"
        else:
            pgpass_path = Path.home() / ".pgpass"

        if pgpass_path.exists():
            # Format: hostname:port:database:username:password
            with open(pgpass_path) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split(":")
                    if len(parts) >= 5 and "wharton" in parts[0]:
                        return parts[3], parts[4]

        # Fall back to env vars (populated by load_dotenv in config.py)
        username = os.getenv("WRDS_USERNAME", "")
        password = os.getenv("WRDS_PASSWORD", "")
        if username and password and password != "YOUR_WRDS_PASSWORD_HERE":
            print("[WRDS] Using credentials from .env (no pgpass.conf found)")
            return username, password

        return "", ""

    @property
    def db(self):
        if self._db is None:
            import wrds
            print("[WRDS] Connecting to PostgreSQL...")
            username, password = self._read_pgpass_credentials()
            if username and password:
                self._db = wrds.Connection(
                    wrds_username=username,
                    wrds_password=password,
                )
            else:
                # Fall back to interactive login if pgpass not found
                self._db = wrds.Connection()
            print("[WRDS] Connection established.")
        return self._db

    def close(self):
        if self._db is not None:
            self._db.close()
            self._db = None

    # -- resolve end date -----------------------------------------------

    def _resolve_end(self) -> str:
        if self.config.end_date == "today":
            return datetime.today().strftime("%Y-%m-%d")
        return self.config.end_date

    # -- monthly chunking (from database_build_script.py:28-77) ---------

    def _chunked_query(
        self,
        sql_template: str,
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Execute *sql_template* in monthly chunks.

        The template must contain ``{start}`` and ``{end}`` placeholders.
        """
        start = start or self.config.start_date
        end = end or self._resolve_end()

        frames: list[pd.DataFrame] = []
        current = datetime.strptime(start, "%Y-%m-%d")
        end_dt = datetime.strptime(end, "%Y-%m-%d")

        while current < end_dt:
            next_month = current + relativedelta(months=1)
            chunk_end = min(next_month, end_dt)

            sql = sql_template.format(
                start=current.strftime("%Y-%m-%d"),
                end=chunk_end.strftime("%Y-%m-%d"),
            )
            label = current.strftime("%Y-%m")
            try:
                df = self.db.raw_sql(sql)
                if df is not None and not df.empty:
                    frames.append(df)
                    print(f"  [{label}] {len(df):,} rows")
                else:
                    print(f"  [{label}] no data")
            except Exception as e:
                print(f"  [{label}] ERROR: {e}")

            current = next_month

        if frames:
            return pd.concat(frames, ignore_index=True)
        return pd.DataFrame()

    # ── CRSP Daily Stock File ─────────────────────────────────────────

    def fetch_crsp_daily(self, tickers: Optional[List[str]] = None) -> pd.DataFrame:
        """
        OHLCV + returns + shares outstanding for target tickers AND
        all factor ETFs.
        """
        all_tickers = list(set(
            (tickers or self.config.tickers) + self.config.all_factor_etfs
        ))
        ticker_str = ", ".join(f"'{t}'" for t in all_tickers)

        print(f"[CRSP] Fetching daily stock data for {len(all_tickers)} symbols...")

        sql = f"""
            SELECT a.permno, b.ticker, a.date,
                   a.openprc, a.askhi, a.bidlo,
                   a.prc, a.vol, a.ret, a.shrout
            FROM crsp.dsf a
            JOIN crsp.msenames b
                ON a.permno = b.permno
                AND b.namedt <= a.date
                AND a.date <= b.nameendt
            WHERE b.ticker IN ({ticker_str})
                AND a.date >= '{{start}}'
                AND a.date < '{{end}}'
            ORDER BY b.ticker, a.date
        """
        return self._chunked_query(sql)

    # ── CRSP Daily S&P Index ──────────────────────────────────────────

    def fetch_crsp_index(self) -> pd.DataFrame:
        print("[CRSP] Fetching S&P composite index returns...")
        sql = """
            SELECT date, vwretd, ewretd, sprtrn
            FROM crsp.dsi
            WHERE date >= '{start}' AND date < '{end}'
            ORDER BY date
        """
        return self._chunked_query(sql)

    # ── OptionMetrics Vol Surface ─────────────────────────────────────

    def fetch_vsurfd(self, tickers: Optional[List[str]] = None) -> pd.DataFrame:
        """
        IV surface across multiple DTEs and deltas.

        WRDS stores vsurfd as year-partitioned tables (vsurfd2021, vsurfd2022, ...).
        Two-step: (1) map tickers -> SECIDs via secnmd, (2) query each year table.
        """
        tickers = tickers or self.config.tickers
        ticker_str = ", ".join(f"'{t}'" for t in tickers)

        print("[OPTIONM] Mapping tickers to SECIDs...")
        secid_df = self.db.raw_sql(f"""
            SELECT secid, ticker
            FROM optionm.secnmd
            WHERE ticker IN ({ticker_str})
        """)
        if secid_df.empty:
            print("[OPTIONM] No SECID mappings found.")
            return pd.DataFrame()

        secid_str = ", ".join(str(int(s)) for s in secid_df["secid"].unique())
        days_str = ", ".join(str(d) for d in self.config.vsurfd_days)
        delta_str = ", ".join(str(d) for d in self.config.vsurfd_deltas)

        start_year = int(self.config.start_date[:4])
        end_year = datetime.today().year

        print(f"[OPTIONM] Fetching vol surface for {len(secid_df['secid'].unique())} SECIDs "
              f"(years={start_year}-{end_year}, "
              f"days={self.config.vsurfd_days}, deltas={self.config.vsurfd_deltas})...")

        frames: list[pd.DataFrame] = []
        for year in range(start_year, end_year + 1):
            sql = f"""
                SELECT secid, date, days, delta, impl_volatility
                FROM optionm.vsurfd{year}
                WHERE secid IN ({secid_str})
                    AND days IN ({days_str})
                    AND delta IN ({delta_str})
                ORDER BY secid, date, days, delta
            """
            try:
                df = self.db.raw_sql(sql)
                if df is not None and not df.empty:
                    frames.append(df)
                    print(f"  [vsurfd{year}] {len(df):,} rows")
                else:
                    print(f"  [vsurfd{year}] no data")
            except Exception as e:
                print(f"  [vsurfd{year}] ERROR: {e}")

        if not frames:
            return pd.DataFrame()

        combined = pd.concat(frames, ignore_index=True)
        combined = combined.merge(secid_df[["secid", "ticker"]], on="secid", how="left")
        return combined

    # ── Compustat: GICS sector codes ──────────────────────────────────

    def fetch_compustat_meta(self, tickers: Optional[List[str]] = None) -> pd.DataFrame:
        """
        GICS sector codes via comp.company (static) joined to comp.funda (ticker mapping).
        comp.funda does not carry gsector; comp.company does.
        """
        tickers = tickers or self.config.tickers
        ticker_str = ", ".join(f"'{t}'" for t in tickers)

        print("[COMPUSTAT] Fetching GICS sector codes...")
        sql = f"""
            SELECT DISTINCT a.gvkey, b.tic, a.gsector, a.ggroup, a.gind, a.gsubind, a.sic
            FROM comp.company a
            JOIN comp.funda b ON a.gvkey = b.gvkey
            WHERE b.tic IN ({ticker_str})
                AND b.indfmt = 'INDL' AND b.datafmt = 'STD'
                AND b.popsrc = 'D' AND b.consol = 'C'
            ORDER BY b.tic
        """
        try:
            return self.db.raw_sql(sql)
        except Exception as e:
            print(f"[COMPUSTAT] GICS fetch failed: {e}")
            return pd.DataFrame()

    # ── Compustat: Earnings dates ─────────────────────────────────────

    def fetch_earnings_dates(self, tickers: Optional[List[str]] = None) -> pd.DataFrame:
        tickers = tickers or self.config.tickers
        ticker_str = ", ".join(f"'{t}'" for t in tickers)

        print("[COMPUSTAT] Fetching quarterly earnings report dates...")
        sql = f"""
            SELECT tic, datadate, rdq
            FROM comp.fundq
            WHERE tic IN ({ticker_str})
                AND rdq >= '{self.config.start_date}'
                AND indfmt = 'INDL' AND datafmt = 'STD'
                AND popsrc = 'D' AND consol = 'C'
            ORDER BY tic, rdq
        """
        return self.db.raw_sql(sql)

    # ── Compustat: Dividend dates ─────────────────────────────────────

    def fetch_dividend_dates(self, tickers: Optional[List[str]] = None) -> pd.DataFrame:
        tickers = tickers or self.config.tickers
        ticker_str = ", ".join(f"'{t}'" for t in tickers)

        print("[COMPUSTAT] Fetching dividend payment data...")
        sql = f"""
            SELECT tic, datadate, dvpsx_f
            FROM comp.funda
            WHERE tic IN ({ticker_str})
                AND dvpsx_f IS NOT NULL AND dvpsx_f > 0
                AND datadate >= '{self.config.start_date}'
                AND indfmt = 'INDL' AND datafmt = 'STD'
                AND popsrc = 'D' AND consol = 'C'
            ORDER BY tic, datadate
        """
        return self.db.raw_sql(sql)

    # ── FRED via WRDS ─────────────────────────────────────────────────

    def fetch_fred_yfinance(self) -> pd.DataFrame:
        """
        Macro data via yfinance (full history from config.start_date).

        Recovers without any API key:
          treasury_10y  (^TNX  - CBOE 10-year Treasury yield)
          treasury_3mo  (^IRX  - CBOE 13-week T-bill yield, used as short-rate proxy)

        Recovers with FRED_API_KEY in model/.env (free key at fred.stlouisfed.org):
          hy_spread      (BAMLH0A0HYM2 - ICE BofA US HY Option-Adjusted Spread)
          breakeven_5y   (T5YIE - 5-year Breakeven Inflation Rate)
          dollar_index   (DTWEXBGS - Nominal Broad USD Index)
        """
        import yfinance as yf

        start = self.config.start_date
        end = self._resolve_end()
        frames: list = []

        proxy_map = {
            "^TNX": "treasury_10y",
            "^IRX": "treasury_3mo",
        }
        for yf_ticker, label in proxy_map.items():
            try:
                hist = yf.download(yf_ticker, start=start, end=end, progress=False, auto_adjust=True)
                if not hist.empty:
                    s = hist["Close"].squeeze() / 100.0
                    s.name = label
                    s.index = pd.to_datetime(s.index).tz_localize(None)
                    frames.append(s)
                    print(f"  [yfinance] {yf_ticker} -> {label}: {len(s)} rows")
            except Exception as e:
                print(f"  [yfinance] {yf_ticker} failed: {e}")

        fred_api_key = os.getenv("FRED_API_KEY", "")
        if fred_api_key:
            try:
                from fredapi import Fred
                fred_client = Fred(api_key=fred_api_key)
                fred_series = {
                    "BAMLH0A0HYM2": "hy_spread",
                    "T5YIE":        "breakeven_5y",
                    "DTWEXBGS":     "dollar_index",
                    # 5yr/5yr forward inflation expectation: what the bond market
                    # expects inflation to be in years 5-10. Strips near-term noise.
                    # Separates deflationary collapse (2008/2020 shock) from structural
                    # inflation regimes (2022). Genuinely uncorrelated with HY spread
                    # and yield curve at turning points.
                    "T5YIFR":       "inflation_forward_5y5y",
                }
                for series_id, label in fred_series.items():
                    try:
                        s = fred_client.get_series(series_id, start, end)
                        s.name = label
                        s.index = pd.to_datetime(s.index).tz_localize(None)
                        frames.append(s)
                        print(f"  [FRED API] {series_id} -> {label}: {len(s)} rows")
                    except Exception as e:
                        print(f"  [FRED API] {series_id} failed: {e}")
            except ImportError:
                print("  [FRED API] fredapi not installed - pip install fredapi")
        else:
            print("  [FRED] No FRED_API_KEY in .env - HY spread / breakeven skipped")
            print("         Free key: https://fred.stlouisfed.org/docs/api/api_key.html")

        if not frames:
            return pd.DataFrame()

        combined = pd.concat(frames, axis=1).sort_index()
        combined = combined.ffill()
        combined.index.name = "date"
        return combined.reset_index()

    def fetch_fred(self) -> pd.DataFrame:
        """Fetch all configured FRED macro series."""
        # Quick check — fail fast if fred.data doesn't exist in this subscription.
        try:
            self.db.raw_sql("SELECT 1 FROM fred.data LIMIT 1")
        except Exception:
            print("[FRED] fred.data not available in this WRDS subscription.")
            print("[FRED] Falling back to yfinance + FRED API...")
            return self.fetch_fred_yfinance()

        print(f"[FRED] Fetching {len(self.config.fred_series)} macro series...")

        frames: list[pd.DataFrame] = []
        for series_code, label in self.config.fred_series.items():
            sql = f"""
                SELECT date, value
                FROM fred.data
                WHERE series_id = '{series_code}'
                    AND date >= '{{start}}'
                    AND date < '{{end}}'
                ORDER BY date
            """
            df = self._chunked_query(sql)
            if not df.empty:
                df = df.rename(columns={"value": label})
                df["date"] = pd.to_datetime(df["date"])
                frames.append(df.set_index("date")[[label]])
                print(f"  {series_code} -> {label}: {len(df)} rows")

        if frames:
            combined = pd.concat(frames, axis=1).sort_index()
            combined = combined.ffill()  # forward-fill weekends/holidays
            return combined.reset_index()
        return pd.DataFrame()


# ═══════════════════════════════════════════════════════════════════════════
# PARQUET STORE
# ═══════════════════════════════════════════════════════════════════════════

class ParquetStore:
    """Read/write partitioned Parquet files organised by data type."""

    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir)

    def _path(self, data_type: str) -> Path:
        return self.base_dir / data_type

    def save(self, df: pd.DataFrame, data_type: str, partition_cols=None):
        import shutil
        path = self._path(data_type)

        if partition_cols:
            # Clear existing partition directories so pyarrow doesn't accumulate
            # duplicate files across multiple force-refresh runs.
            if path.exists():
                shutil.rmtree(path)
            path.mkdir(parents=True, exist_ok=True)
            df.to_parquet(
                path, engine="pyarrow", compression="snappy",
                partition_cols=partition_cols, index=False,
            )
        else:
            path.mkdir(parents=True, exist_ok=True)
            df.to_parquet(
                path / "data.parquet", engine="pyarrow",
                compression="snappy", index=False,
            )
        print(f"[STORE] Saved {len(df):,} rows -> {path}")

    def load(self, data_type: str, tickers: list = None) -> pd.DataFrame:
        path = self._path(data_type)
        if not path.exists():
            return pd.DataFrame()
        filters = [("ticker", "in", tickers)] if tickers else None
        return pd.read_parquet(path, engine="pyarrow", filters=filters)

    def exists(self, data_type: str) -> bool:
        path = self._path(data_type)
        if not path.exists():
            return False
        # Check for actual parquet files (not just empty dirs)
        return any(path.rglob("*.parquet"))


# ═══════════════════════════════════════════════════════════════════════════
# ALPACA / YFINANCE CONTINUATION
# ═══════════════════════════════════════════════════════════════════════════

class AlpacaContinuation:
    """Append recent data from Alpaca + yfinance + FRED API."""

    def __init__(self, config: DataConfig):
        self.config = config
        self._stock_client = None

    @property
    def stock_client(self):
        if self._stock_client is None:
            from alpaca.data.historical import StockHistoricalDataClient
            self._stock_client = StockHistoricalDataClient(
                os.getenv("ALPACA_API_KEY"),
                os.getenv("ALPACA_SECRET_KEY"),
            )
        return self._stock_client

    def fetch_recent_ohlcv(
        self, tickers: List[str], since_date: str,
    ) -> pd.DataFrame:
        """Fetch OHLCV from Alpaca for dates after *since_date*."""
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame
        from alpaca.data.enums import Adjustment

        symbols = list(set(tickers + self.config.all_factor_etfs))
        start_dt = datetime.strptime(since_date, "%Y-%m-%d") + timedelta(days=1)

        print(f"[ALPACA] Fetching bars for {len(symbols)} symbols since {since_date}...")
        req = StockBarsRequest(
            symbol_or_symbols=symbols,
            timeframe=TimeFrame.Day,
            start=start_dt,
            adjustment=Adjustment.ALL,
            feed="sip",
        )
        try:
            bars = self.stock_client.get_stock_bars(req).df
        except Exception as e:
            print(f"[ALPACA] Error: {e}")
            return pd.DataFrame()

        if bars.empty:
            return pd.DataFrame()

        bars = bars.reset_index()

        # Reshape to match CRSP column names
        result = pd.DataFrame()
        result["ticker"] = bars["symbol"]
        result["date"] = pd.to_datetime(bars["timestamp"]).dt.normalize()  # datetime64, no time component
        result["openprc"] = bars["open"]
        result["askhi"] = bars["high"]
        result["bidlo"] = bars["low"]
        result["prc"] = bars["close"]
        result["vol"] = bars["volume"]
        # ret and shrout not available from Alpaca; compute ret downstream
        result["ret"] = np.nan
        result["shrout"] = np.nan
        result["permno"] = np.nan

        print(f"[ALPACA] Fetched {len(result):,} bar rows.")
        return result

    def fetch_recent_fred(self, since_date: str) -> pd.DataFrame:
        """
        Use yfinance proxies for treasury rates and fredapi for others.
        """
        import yfinance as yf

        end_str = datetime.today().strftime("%Y-%m-%d")
        start_dt = (datetime.strptime(since_date, "%Y-%m-%d")
                    + timedelta(days=1)).strftime("%Y-%m-%d")

        frames: list[pd.DataFrame] = []

        # yfinance proxies for treasury rates
        proxy_map = {
            "^IRX": "treasury_3mo",   # 3-month T-Bill
            "^TNX": "treasury_10y",   # 10-year Treasury
        }
        for yf_ticker, label in proxy_map.items():
            try:
                hist = yf.Ticker(yf_ticker).history(start=start_dt, end=end_str)
                if not hist.empty:
                    df = pd.DataFrame({
                        "date": hist.index,
                        label: hist["Close"].values / 100.0,
                    })
                    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
                    frames.append(df.set_index("date"))
            except Exception as e:
                print(f"[yfinance] {yf_ticker} failed: {e}")

        if frames:
            combined = pd.concat(frames, axis=1).sort_index().ffill()
            return combined.reset_index()
        return pd.DataFrame()


# ═══════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ═══════════════════════════════════════════════════════════════════════════

def fetch_dataset(
    config: DataConfig,
    include_options: bool = True,
    include_macro: bool = True,
    force_refresh: bool = False,
) -> Dict[str, pd.DataFrame]:
    """
    Master fetch function.

    Returns a dict of DataFrames keyed by data type:
    ``ohlcv``, ``vsurfd``, ``fred``, ``earnings``, ``dividends``,
    ``compustat_meta``, ``crsp_index``.
    """
    store = ParquetStore(config.base_dir)
    result: Dict[str, pd.DataFrame] = {}
    loader = WRDSLoader(config)

    try:
        # ── OHLCV ────────────────────────────────────────────────────
        if force_refresh or not store.exists("ohlcv"):
            df = loader.fetch_crsp_daily()
            if not df.empty:
                store.save(df, "ohlcv", partition_cols=["ticker"])
        result["ohlcv"] = store.load("ohlcv", tickers=config.tickers + config.all_factor_etfs)

        # ── Vol surface ──────────────────────────────────────────────
        if include_options:
            if force_refresh or not store.exists("vsurfd"):
                df = loader.fetch_vsurfd()
                if not df.empty:
                    store.save(df, "vsurfd", partition_cols=["ticker"])
            result["vsurfd"] = store.load("vsurfd", tickers=config.tickers)

        # ── FRED macro ───────────────────────────────────────────────
        if include_macro:
            if force_refresh or not store.exists("fred"):
                df = loader.fetch_fred()
                if not df.empty:
                    store.save(df, "fred")
            result["fred"] = store.load("fred")

        # ── Earnings dates ───────────────────────────────────────────
        if force_refresh or not store.exists("events/earnings"):
            df = loader.fetch_earnings_dates()
            if not df.empty:
                store.save(df, "events/earnings")
        result["earnings"] = store.load("events/earnings")

        # ── Dividend dates ───────────────────────────────────────────
        if force_refresh or not store.exists("events/dividends"):
            df = loader.fetch_dividend_dates()
            if not df.empty:
                store.save(df, "events/dividends")
        result["dividends"] = store.load("events/dividends")

        # ── Compustat meta ───────────────────────────────────────────
        if force_refresh or not store.exists("compustat_meta"):
            try:
                df = loader.fetch_compustat_meta()
                if not df.empty:
                    store.save(df, "compustat_meta")
            except Exception as e:
                print(f"[ERROR] Compustat meta fetch failed: {e}")
        result["compustat_meta"] = store.load("compustat_meta")

        # ── CRSP index ───────────────────────────────────────────────
        if force_refresh or not store.exists("crsp_index"):
            df = loader.fetch_crsp_index()
            if not df.empty:
                store.save(df, "crsp_index")
        result["crsp_index"] = store.load("crsp_index")

    finally:
        loader.close()

    return result


def append_recent_data(
    config: DataConfig,
    existing_data: Dict[str, pd.DataFrame],
) -> Dict[str, pd.DataFrame]:
    """
    Detect the last date in each dataset, fetch the gap from
    Alpaca/yfinance/FRED, and concatenate.  Saves updated Parquet.
    """
    store = ParquetStore(config.base_dir)
    cont = AlpacaContinuation(config)

    # ── OHLCV continuation ───────────────────────────────────────────
    ohlcv = existing_data.get("ohlcv", pd.DataFrame())
    if not ohlcv.empty and "date" in ohlcv.columns:
        # .astype(str).str[:10] handles any mix of date/datetime/timestamp formats
        last_date = pd.to_datetime(ohlcv["date"].astype(str).str[:10]).max().strftime("%Y-%m-%d")
        recent = cont.fetch_recent_ohlcv(config.tickers, since_date=last_date)
        if not recent.empty:
            combined = pd.concat([ohlcv, recent], ignore_index=True)
            # Normalize to tz-naive UTC dates — Alpaca returns tz-aware, CRSP is tz-naive.
            combined["date"] = pd.to_datetime(combined["date"], utc=True).dt.tz_localize(None)
            combined = combined.drop_duplicates(
                subset=["date", "ticker"], keep="last",
            )
            store.save(combined, "ohlcv", partition_cols=["ticker"])
            existing_data["ohlcv"] = combined
            print(f"[CONTINUE] OHLCV extended to {combined['date'].max()}")

    # ── FRED continuation ────────────────────────────────────────────
    fred = existing_data.get("fred", pd.DataFrame())
    if not fred.empty and "date" in fred.columns:
        last_date = pd.to_datetime(fred["date"].astype(str).str[:10]).max().strftime("%Y-%m-%d")
        recent = cont.fetch_recent_fred(since_date=last_date)
        if not recent.empty:
            combined = pd.concat([fred, recent], ignore_index=True)
            combined["date"] = pd.to_datetime(combined["date"])
            combined = combined.drop_duplicates(subset=["date"], keep="last")
            store.save(combined, "fred")
            existing_data["fred"] = combined

    return existing_data
