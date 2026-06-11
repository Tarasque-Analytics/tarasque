"""
sync_sp500.py — maintain the S&P 500 reference list and add missing constituents to `securities`.

Two jobs:
  1. --refresh : rebuild the reference CSV (automation/data/sp500.csv) from Wikipedia's
     "List of S&P 500 companies" table, with each ticker mapped to its authoritative SEC CIK
     (from automation/company_tickers.json). Keeps BOTH share classes (e.g. GOOGL & GOOG).
  2. (default) : read the CSV and UPSERT any constituents whose CIK is not yet in `securities`
     (security_id = CIK, matching the CIK remap). Defaults to a PREVIEW; pass --apply to write.

`securities.security_id` is the CIK (per the remap), so the table is one-row-per-company: the 3
dual-class pairs (GOOGL/GOOG, FOXA/FOX, NWSA/NWS) collapse to one row each (the first/already-present
class wins). The dropped class is still kept in the CSV for reference.

Usage (from repo root):
    python -m automation.tools.sync_sp500 --refresh         # rebuild the CSV (needs network)
    python -m automation.tools.sync_sp500                    # preview what would be added (no writes)
    python -m automation.tools.sync_sp500 --apply            # add missing rows to hosted securities
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
from pathlib import Path

from ..config import load_config
from ..db import WriteClient

WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
PKG_DIR = Path(__file__).resolve().parent.parent          # automation/
DATA_DIR = PKG_DIR / "data"
CSV_PATH = DATA_DIR / "sp500.csv"
CIK_FILE = PKG_DIR / "company_tickers.json"

CSV_FIELDS = ["ticker", "company_name", "gics_sector", "gics_sub_industry", "cik"]

# GICS sector name → SPDR sector ETF (matches the existing securities.sector_etf values).
SECTOR_ETF = {
    "Information Technology": "XLK",
    "Health Care": "XLV",
    "Financials": "XLF",
    "Consumer Discretionary": "XLY",
    "Communication Services": "XLC",
    "Industrials": "XLI",
    "Consumer Staples": "XLP",
    "Energy": "XLE",
    "Utilities": "XLU",
    "Real Estate": "XLRE",
    "Materials": "XLB",
}


def _norm_ticker(sym: str) -> str:
    """Normalize to yfinance/SEC form: dots → dashes, upper (e.g. 'BRK.B' → 'BRK-B')."""
    return str(sym).replace(".", "-").strip().upper()


def _load_cik_map() -> dict[str, int]:
    data = json.loads(CIK_FILE.read_text(encoding="utf-8"))
    return {v["ticker"].upper(): int(v["cik_str"]) for v in data.values()}


# ── 1) refresh the reference CSV ───────────────────────────────────────────────────────────────
def refresh_csv() -> list[dict]:
    """Fetch the S&P 500 table from Wikipedia, map to SEC CIK, write the reference CSV."""
    import requests  # lazy — only needed for --refresh
    import pandas as pd
    from io import StringIO

    resp = requests.get(WIKI_URL, headers={"User-Agent": "Mozilla/5.0 volarbmodel-research"}, timeout=30)
    resp.raise_for_status()
    df = pd.read_html(StringIO(resp.text))[0]
    cik_map = _load_cik_map()

    rows: list[dict] = []
    unmatched: list[str] = []
    for _, x in df.iterrows():
        ticker = _norm_ticker(x["Symbol"])
        cik = cik_map.get(ticker)
        if cik is None and pd.notna(x.get("CIK")):
            cik = int(x["CIK"])           # fallback to Wikipedia's CIK column
        if cik is None:
            unmatched.append(ticker)
        rows.append({
            "ticker": ticker,
            "company_name": str(x["Security"]).strip(),
            "gics_sector": str(x["GICS Sector"]).strip(),
            "gics_sub_industry": str(x["GICS Sub-Industry"]).strip(),
            "cik": cik,
        })

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        w.writerows(rows)

    print(f"[sync_sp500] wrote {CSV_PATH} — {len(rows)} members"
          + (f", {len(unmatched)} unmatched: {unmatched}" if unmatched else ", all CIK-matched"))
    return rows


def read_csv() -> list[dict]:
    if not CSV_PATH.exists():
        sys.exit(f"[sync_sp500] {CSV_PATH} not found — run with --refresh first.")
    with open(CSV_PATH, encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ── 2) sync missing constituents into securities ────────────────────────────────────────────────
def _build_rows(
    members: list[dict],
    existing_by_id: dict[int, dict],
    *,
    include_existing: bool,
) -> tuple[list[dict], list[str], list[str]]:
    """
    Return (rows, skipped_existing, dropped_dupe_cik), deduped by CIK (one row per company).

    include_existing=False → only CIKs not yet in securities (the "add missing" pass).
    include_existing=True  → every member (add missing + refresh existing). For an existing row we
                             PRESERVE its current ticker and active flag, and only refresh the
                             metadata columns from the reference (never silently rename a ticker).
    """
    rows: list[dict] = []
    seen_cik: set[int] = set()
    skipped: list[str] = []
    dropped: list[str] = []
    for m in members:
        if not m.get("cik"):
            continue
        cik = int(m["cik"])
        cur = existing_by_id.get(cik)
        if cur is not None and not include_existing:
            skipped.append(m["ticker"])
            continue
        if cik in seen_cik:
            dropped.append(m["ticker"])     # second share class of a company already in the batch
            continue
        seen_cik.add(cik)
        rows.append({
            "security_id": cik,
            "ticker": (cur["ticker"] if cur and cur.get("ticker") else m["ticker"]),
            "company_name": m["company_name"] or None,
            "gics_sector": m["gics_sector"] or None,
            "gics_subindustry": m["gics_sub_industry"] or None,
            "sector_etf": SECTOR_ETF.get(m["gics_sector"], None),
            "active": (cur["active"] if cur else True),
        })
    return rows, skipped, dropped


def _diff(row: dict, cur: dict) -> list[str]:
    """Which metadata columns would change for an existing row."""
    changed = []
    for col in ("company_name", "gics_sector", "gics_subindustry", "sector_etf"):
        if (cur.get(col) or None) != (row.get(col) or None):
            changed.append(col)
    return changed


async def sync(apply: bool, update_existing: bool = False) -> int:
    members = read_csv()
    cfg = load_config()
    # Always connect a real client (we have creds): we read existing rows to plan; writes gated by `apply`.
    db = WriteClient(cfg.supabase, dry_run=False)
    await db.connect()
    try:
        existing = await db.securities_detail()
        existing_by_id = {r["security_id"]: r for r in existing}
        rows, skipped, dropped = _build_rows(members, existing_by_id, include_existing=update_existing)

        if not update_existing:
            print(f"[sync_sp500] members={len(members)}  already present={len(skipped)}  "
                  f"dual-class dropped={len(dropped)} {dropped}  to-add={len(rows)}")
            for r in rows[:8]:
                print(f"    + {r['ticker']:6s} cik={r['security_id']:>9}  {r['gics_sector']:<24} {r['company_name']}")
            if len(rows) > 8:
                print(f"    … and {len(rows) - 8} more")
        else:
            # Report only the rows that actually change (existing rows with stale metadata).
            changing = [(r, _diff(r, existing_by_id[r["security_id"]]))
                        for r in rows if r["security_id"] in existing_by_id
                        and _diff(r, existing_by_id[r["security_id"]])]
            new_rows = [r for r in rows if r["security_id"] not in existing_by_id]
            print(f"[sync_sp500] update-existing: members={len(members)}  upsert rows={len(rows)}  "
                  f"changing={len(changing)}  new={len(new_rows)}  dual-class dropped={dropped}")
            for r, cols in changing[:12]:
                cur = existing_by_id[r["security_id"]]
                print(f"    ~ {r['ticker']:6s} {', '.join(cols)}"
                      f"  [{cur.get('gics_sector')!r}->{r['gics_sector']!r}]")
            if len(changing) > 12:
                print(f"    … and {len(changing) - 12} more changing")

        if not apply:
            print("[sync_sp500] PREVIEW only — re-run with --apply to write.")
            return 0

        written = await db.upsert_securities(rows)
        print(f"[sync_sp500] upserted {written} securities rows.")
        return written
    finally:
        await db.close()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m automation.tools.sync_sp500",
        description="Maintain the S&P 500 reference CSV and add missing constituents to securities.",
    )
    p.add_argument("--refresh", action="store_true",
                   help="Rebuild automation/data/sp500.csv from Wikipedia (needs network). No DB writes.")
    p.add_argument("--apply", action="store_true",
                   help="Write to securities (default is preview only).")
    p.add_argument("--update-existing", action="store_true",
                   help="Also refresh metadata (GICS/company_name/etf) on rows already present, "
                        "not just add missing. Preserves existing ticker/active.")
    args = p.parse_args(argv)

    if args.refresh:
        refresh_csv()
    asyncio.run(sync(apply=args.apply, update_existing=args.update_existing))
    return 0


if __name__ == "__main__":
    sys.exit(main())
