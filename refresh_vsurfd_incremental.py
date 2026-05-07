"""
refresh_vsurfd_incremental.py — surgical append-only update for vsurfd.

Pulls vsurfd2025 (date > existing_max) + vsurfd2026 from WRDS, appends to the
existing parquet. Avoids the 6-8h full re-pull when the cache is just stale.

Usage:
  python refresh_vsurfd_incremental.py
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
from model.pipeline.config import load_config
from model.pipeline.data_loader import ParquetStore, WRDSLoader


def main() -> int:
    dc, _, _ = load_config()
    store = ParquetStore(dc.base_dir)

    # Load existing vsurfd to find max date and the secid->ticker mapping
    existing = store.load("vsurfd")
    existing["date"] = pd.to_datetime(existing["date"], format="mixed")
    existing_max = existing["date"].max()
    secid_map = (
        existing[["secid", "ticker"]]
        .drop_duplicates()
        .reset_index(drop=True)
    )
    print(f"[VSURFD] Existing parquet: {len(existing):,} rows, "
          f"max date = {existing_max.date()}, "
          f"{secid_map['secid'].nunique()} secids, "
          f"{secid_map['ticker'].nunique()} tickers")

    secid_str = ", ".join(str(int(s)) for s in secid_map["secid"].unique())
    days_str = ", ".join(str(d) for d in dc.vsurfd_days)
    delta_str = ", ".join(str(d) for d in dc.vsurfd_deltas)

    print("[WRDS] Connecting via WRDSLoader (uses pgpass / env creds)...")
    loader = WRDSLoader(dc)
    db = loader.db

    today_year = datetime.today().year
    cutoff = (existing_max + pd.Timedelta(days=1)).strftime("%Y-%m-%d")

    frames = []
    for year in range(existing_max.year, today_year + 1):
        # for the year that already has data, use date > existing_max
        # for new years, no date filter (pull all)
        if year == existing_max.year:
            where = f"AND date > '{cutoff}'"
        else:
            where = ""
        sql = f"""
            SELECT secid, date, days, delta, impl_volatility
            FROM optionm.vsurfd{year}
            WHERE secid IN ({secid_str})
                AND days IN ({days_str})
                AND delta IN ({delta_str})
                {where}
            ORDER BY secid, date, days, delta
        """
        try:
            print(f"[WRDS] vsurfd{year}{' (incremental)' if year == existing_max.year else ' (full)'}...")
            df = db.raw_sql(sql)
            if df is not None and not df.empty:
                frames.append(df)
                print(f"  -> {len(df):,} rows; date range "
                      f"{pd.to_datetime(df['date']).min().date()} -> "
                      f"{pd.to_datetime(df['date']).max().date()}")
            else:
                print(f"  -> empty.")
        except Exception as e:
            print(f"  -> ERROR: {e}")

    loader.close()

    if not frames:
        print("[VSURFD] No new rows. Nothing to append.")
        return 1

    new_rows = pd.concat(frames, ignore_index=True)
    new_rows = new_rows.merge(secid_map, on="secid", how="left")
    print(f"[VSURFD] {len(new_rows):,} new rows to append.")

    # Append to existing and dedupe (in case overlap)
    combined = pd.concat([existing, new_rows], ignore_index=True)
    combined = combined.drop_duplicates(
        subset=["secid", "date", "days", "delta"], keep="last"
    )
    combined["date"] = pd.to_datetime(combined["date"], format="mixed")
    combined = combined.sort_values(["ticker", "date", "days", "delta"]).reset_index(drop=True)

    store.save(combined, "vsurfd", partition_cols=["ticker"])
    print(f"[VSURFD] Saved {len(combined):,} total rows to {dc.base_dir}/vsurfd")
    print(f"[VSURFD] New max date: {combined['date'].max().date()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
