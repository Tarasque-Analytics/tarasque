"""
fetch_alpaca_vsurfd.py — pull today's option-chain snapshots from Alpaca,
project them onto the (DTE × delta) grid that OptionMetrics' vsurfd uses,
and append vsurfd-schema rows to the existing parquet.

This bridges the WRDS staleness (vsurfd capped at 2025-08-29) with fresh data
for the live forecast layer. Run it daily.

Schema match:
  vsurfd parquet columns: secid, date, days, delta, impl_volatility, ticker
  - days = DTE bucket (30, 60, 91, 182)
  - delta = signed delta scaled by 100 (50, 25, 10, -25, -10)
  - impl_volatility = IV at grid point (annualised, decimal — e.g. 0.31)
  - secid = OptionMetrics secid for the underlying (we synthesise for new tickers)

Usage:
  python -m model.pipeline.scripts.fetch_alpaca_vsurfd
  python -m model.pipeline.scripts.fetch_alpaca_vsurfd --tickers AAPL MSFT
  python -m model.pipeline.scripts.fetch_alpaca_vsurfd --no-append   # dry run
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv

from ..config import load_config
from ..data_loader import ParquetStore


# Same grid as vsurfd
DTE_GRID = [30, 60, 91, 182]      # days to expiration buckets
DELTA_GRID = [10, 25, 50, -25, -10]  # delta×100 (50=ATM call, -25=25-delta put)

DTE_TOLERANCE = 0.30   # accept contract within ±30% of target DTE
DELTA_TOLERANCE = 0.05 # accept contract within ±0.05 of target delta (0.5 to 0.55 for delta=50, etc.)

OCC_RE = re.compile(r"^([A-Z]+)(\d{6})([CP])(\d{8})$")


def parse_occ(symbol: str) -> dict | None:
    m = OCC_RE.match(symbol)
    if not m:
        return None
    root, yymmdd, cp, strike = m.groups()
    return {
        "root": root,
        "expiry": datetime.strptime(yymmdd, "%y%m%d").date(),
        "cp": cp,
        "strike": int(strike) / 1000.0,
    }


def project_to_grid(contracts: list[dict], today: date) -> list[dict]:
    """Project a list of valid contract dicts (with iv, delta, dte, cp) onto the
    (DTE_GRID × DELTA_GRID) grid. Returns one row per grid point with median IV
    of the contracts in the bucket. Skips grid points with no candidates.
    """
    if not contracts:
        return []
    df = pd.DataFrame(contracts)
    rows = []
    for tgt_dte in DTE_GRID:
        dte_lo, dte_hi = tgt_dte * (1 - DTE_TOLERANCE), tgt_dte * (1 + DTE_TOLERANCE)
        dte_band = df[(df["dte"] >= dte_lo) & (df["dte"] <= dte_hi)]
        if dte_band.empty:
            continue
        for tgt_delta in DELTA_GRID:
            target = tgt_delta / 100.0
            # call vs put filter
            if tgt_delta > 0:
                pool = dte_band[dte_band["cp"] == "C"]
            elif tgt_delta < 0:
                pool = dte_band[dte_band["cp"] == "P"]
            else:
                pool = dte_band  # delta=0 unused
            if pool.empty:
                continue
            band = pool[(pool["delta"] >= target - DELTA_TOLERANCE) &
                        (pool["delta"] <= target + DELTA_TOLERANCE)]
            if band.empty:
                continue
            iv_med = float(band["iv"].median())
            rows.append({"days": tgt_dte, "delta": tgt_delta, "impl_volatility": iv_med,
                         "n_contracts": int(len(band))})
    return rows


def fetch_one_ticker(client, ticker: str, today: date) -> pd.DataFrame:
    """Pull current option chain for `ticker`, return vsurfd-shaped rows for `today`."""
    from alpaca.data.requests import OptionChainRequest
    try:
        snap = client.get_option_chain(OptionChainRequest(underlying_symbol=ticker))
    except Exception as e:
        print(f"  [{ticker}] chain fetch FAILED: {type(e).__name__}: {e}")
        return pd.DataFrame()

    contracts = []
    for occ, c in snap.items():
        info = parse_occ(occ)
        if info is None:
            continue
        if info["root"] != ticker:
            continue  # spinoffs / adjusted
        if c.implied_volatility is None or c.greeks is None or c.greeks.delta is None:
            continue
        dte = (info["expiry"] - today).days
        if dte < 7 or dte > 365:
            continue  # outside our usable horizon
        iv = float(c.implied_volatility)
        if not np.isfinite(iv) or iv <= 0 or iv > 5:
            continue  # garbage
        contracts.append({
            "occ": occ, "cp": info["cp"], "strike": info["strike"],
            "expiry": info["expiry"], "dte": dte,
            "delta": float(c.greeks.delta), "iv": iv,
        })
    grid_rows = project_to_grid(contracts, today)
    out = pd.DataFrame(grid_rows)
    if out.empty:
        return out
    out["date"] = pd.Timestamp(today)
    out["ticker"] = ticker
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tickers", nargs="*", default=None,
                        help="Subset of tickers (default: full corpus)")
    parser.add_argument("--no-append", action="store_true",
                        help="Compute and print but don't write to parquet")
    parser.add_argument("--rate-sleep", type=float, default=0.05,
                        help="Sleep between ticker requests (sec)")
    args = parser.parse_args()

    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    key = os.environ.get("ALPACA_API_KEY")
    sec = os.environ.get("ALPACA_SECRET_KEY")
    if not key or not sec:
        print("[ERROR] ALPACA_API_KEY / ALPACA_SECRET_KEY missing in .env")
        return 1

    from alpaca.data.historical.option import OptionHistoricalDataClient
    client = OptionHistoricalDataClient(api_key=key, secret_key=sec)

    dc, _, _ = load_config()
    tickers = args.tickers or dc.tickers
    today = pd.Timestamp.today().normalize().date()

    print(f"[ALPACA-VSURFD] {len(tickers)} tickers, target date {today}")
    print(f"  DTE grid: {DTE_GRID}  delta grid: {DELTA_GRID}")
    print(f"  DTE ±{int(DTE_TOLERANCE*100)}%, delta ±{DELTA_TOLERANCE}")
    print()

    all_rows = []
    fail = []
    for i, tk in enumerate(tickers):
        rows = fetch_one_ticker(client, tk, today)
        if rows.empty:
            fail.append(tk)
            print(f"  [{i+1:3d}/{len(tickers)}] {tk}: 0 grid points")
        else:
            print(f"  [{i+1:3d}/{len(tickers)}] {tk}: {len(rows):2d} grid points (of {len(DTE_GRID)*len(DELTA_GRID)})")
            all_rows.append(rows)
        if args.rate_sleep:
            time.sleep(args.rate_sleep)

    if not all_rows:
        print("[ALPACA-VSURFD] No data pulled. Bailing.")
        return 1

    new_df = pd.concat(all_rows, ignore_index=True)
    new_df["impl_volatility"] = new_df["impl_volatility"].astype(float)
    new_df["days"] = new_df["days"].astype(int)
    new_df["delta"] = new_df["delta"].astype(int)

    print()
    print(f"[ALPACA-VSURFD] Total rows: {len(new_df):,}")
    print(f"  Successful tickers: {new_df['ticker'].nunique()}/{len(tickers)}")
    if fail:
        print(f"  Failed tickers ({len(fail)}): {fail}")
    print()
    print("Sample of pulled data (first 5 tickers, all grid points):")
    print(new_df.head(20).to_string(index=False))

    if args.no_append:
        print()
        print("[ALPACA-VSURFD] --no-append set; not writing parquet.")
        return 0

    # Append to existing vsurfd
    store = ParquetStore(dc.base_dir)
    existing = store.load("vsurfd")
    existing["date"] = pd.to_datetime(existing["date"], format="mixed")

    # Synthesize secid from existing mapping or use a sentinel for unknowns
    secid_map = (
        existing[["ticker", "secid"]]
        .dropna()
        .drop_duplicates(subset=["ticker"])
        .set_index("ticker")["secid"]
        .to_dict()
    )
    # Use existing secid; for new tickers, mark with a 9-prefixed synthetic ID so we can filter later
    next_synth = 9_000_001
    secids = []
    for tk in new_df["ticker"]:
        if tk in secid_map:
            secids.append(secid_map[tk])
        else:
            secids.append(next_synth)
            next_synth += 1
    new_df["secid"] = secids
    new_df = new_df[["secid", "date", "days", "delta", "impl_volatility", "ticker"]]

    # Drop existing rows for the same (ticker, date) — let new pull win
    mask = (existing["date"] == pd.Timestamp(today)) & (existing["ticker"].isin(new_df["ticker"]))
    n_overwrite = mask.sum()
    if n_overwrite:
        print(f"[ALPACA-VSURFD] Overwriting {n_overwrite} existing rows for date={today}")
        existing = existing[~mask]

    combined = pd.concat([existing, new_df], ignore_index=True)
    combined["date"] = pd.to_datetime(combined["date"], format="mixed")
    combined = combined.sort_values(["ticker", "date", "days", "delta"]).reset_index(drop=True)

    store.save(combined, "vsurfd", partition_cols=["ticker"])
    print(f"[ALPACA-VSURFD] Saved {len(combined):,} total rows -> {dc.base_dir}/vsurfd")
    print(f"  New max date in vsurfd: {combined['date'].max().date()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
