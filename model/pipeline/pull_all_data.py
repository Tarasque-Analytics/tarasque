"""
pull_all_data.py — Pull WRDS/FRED/Alpaca data for all untested tickers at once.

Run this FIRST on Windows (where wrds is installed), then run batch_backtest.py.

Usage (from project root, on Windows):
    python -m model.pipeline.pull_all_data
"""
from .config import load_config
from .data_loader import fetch_dataset, append_recent_data
from .batch_backtest import get_untested_tickers, ALREADY_TESTED

def main():
    dc, mc, bc = load_config()

    # Set tickers to everything we need
    untested = get_untested_tickers()
    all_needed = list(ALREADY_TESTED) + untested
    dc.tickers = all_needed

    print(f"Pulling data for {len(all_needed)} tickers ({len(untested)} untested + {len(ALREADY_TESTED)} already tested)...")
    print(f"This may take a while for OptionMetrics vsurfd (year tables 2014-2025).\n")

    raw_data = fetch_dataset(dc, force_refresh=False)
    raw_data = append_recent_data(dc, raw_data)

    print("\n[DATA] Pull complete. Summary:")
    for key, df in raw_data.items():
        if hasattr(df, '__len__'):
            print(f"  {key:20s}: {len(df):>10,} rows")

    print("\nYou can now run the batch backtest:")
    print("  python -m model.pipeline.batch_backtest")


if __name__ == "__main__":
    main()
