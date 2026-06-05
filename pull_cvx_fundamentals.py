"""
pull_cvx_fundamentals.py — Fetch CVX (CIK 0000093410) XBRL company facts from
SEC EDGAR and transform into a filing-date-anchored CSV with no look-ahead.

Output: data_cache/sec_fundamentals/cvx_fundamentals.csv

Principle: every value is stamped with the SEC `filed` date (when it became
public), never the period-end. Comparatives republished in later filings are
deduped; restatements are kept on their own filed date and flagged.

Usage:
  python pull_cvx_fundamentals.py
"""
from __future__ import annotations

import json
import sys
import urllib.request
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import pandas as pd

CIK = "0000093410"
URL = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{CIK}.json"
UA = "Leo DiPietro leoharrisondipietro@gmail.com"

OUT_DIR = Path("data_cache/sec_fundamentals")
OUT_PATH = OUT_DIR / "cvx_fundamentals.csv"

# Revenue tag priority — CVX headline "Sales and other operating revenues"
# (NET of excise/VAT). ASC 606 tag is authoritative from ~2018; SalesRevenueNet
# carried the same line pre-606. `Revenues` is the broadest bucket (includes
# other income) — only use it as a last-resort fallback for years where neither
# of the first two is populated.
REVENUE_TAGS = [
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "SalesRevenueNet",
    "Revenues",
]
OCF_TAGS = [
    "NetCashProvidedByUsedInOperatingActivities",
    "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
]
EQUITY_TAG = "StockholdersEquity"  # Chevron-parent only
SHARES_TAG = "EntityCommonStockSharesOutstanding"  # dei, cover page


# ---------- fetch ----------

def fetch_json() -> dict:
    print(f"Fetching: {URL}")
    req = urllib.request.Request(URL, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


# ---------- normalization ----------

def to_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def usd_facts(facts_root: dict, tag: str) -> list[dict]:
    try:
        return facts_root["us-gaap"][tag]["units"]["USD"]
    except KeyError:
        return []


def shares_unit_facts(facts_root: dict) -> list[dict]:
    try:
        return facts_root["dei"][SHARES_TAG]["units"]["shares"]
    except KeyError:
        return []


def is_quarter_dur(d: int) -> bool:
    return 80 <= d <= 100


def is_h1_dur(d: int) -> bool:  # ~6 months (Jan-Jun YTD)
    return 170 <= d <= 195


def is_9mo_dur(d: int) -> bool:  # ~9 months (Jan-Sep YTD)
    return 260 <= d <= 285


def is_fy_dur(d: int) -> bool:
    return 350 <= d <= 380


def norm_flow(raw: list[dict], tag: str) -> list[dict]:
    out = []
    for f in raw:
        if "start" not in f or "end" not in f or "filed" not in f:
            continue
        if f.get("val") is None:
            continue
        start = to_date(f["start"])
        end = to_date(f["end"])
        out.append({
            "start": start,
            "end": end,
            "dur": (end - start).days,
            "filed": to_date(f["filed"]),
            "fy": f.get("fy"),
            "fp": f.get("fp"),
            "form": f.get("form"),
            "accn": f.get("accn"),
            "val": f["val"],
            "tag": tag,
        })
    return out


def norm_inst(raw: list[dict], tag: str) -> list[dict]:
    out = []
    for f in raw:
        if "end" not in f or "filed" not in f or f.get("val") is None:
            continue
        out.append({
            "end": to_date(f["end"]),
            "filed": to_date(f["filed"]),
            "fy": f.get("fy"),
            "fp": f.get("fp"),
            "form": f.get("form"),
            "accn": f.get("accn"),
            "val": f["val"],
            "tag": tag,
        })
    return out


# ---------- tag stitching ----------

def print_tag_coverage(label: str, tag: str, facts: list[dict]) -> None:
    if not facts:
        print(f"  {label} / {tag}: NO DATA")
        return
    ends = sorted({f["end"] for f in facts})
    q = sum(1 for f in facts if is_quarter_dur(f["dur"]))
    fy = sum(1 for f in facts if is_fy_dur(f["dur"]))
    other = len(facts) - q - fy
    print(f"  {label} / {tag}: {len(facts)} facts | end {ends[0]} -> {ends[-1]} | "
          f"~Q: {q} | ~FY: {fy} | other(YTD etc): {other}")


def pick_per_year_tag(by_tag: dict[str, list[dict]], priority: list[str]) -> dict[int, str]:
    """For each period-end calendar year, choose the highest-priority tag that
    has a Q or FY duration fact ending in that year. Uses end.year (the actual
    period), not the filing's fy attribute (which is the filing's fy and gets
    inherited by comparatives in later filings)."""
    year_tag: dict[int, str] = {}
    for tag in priority:
        for f in by_tag.get(tag, []):
            if not (is_quarter_dur(f["dur"]) or is_fy_dur(f["dur"])):
                continue
            yr = f["end"].year
            if yr not in year_tag:
                year_tag[yr] = tag
    return year_tag


def build_flow_series(facts_root: dict, priority: list[str], label: str):
    print(f"\n=== {label} tag coverage ===")
    by_tag = {}
    for tag in priority:
        norm = norm_flow(usd_facts(facts_root, tag), tag)
        by_tag[tag] = norm
        print_tag_coverage(label, tag, norm)

    year_tag = pick_per_year_tag(by_tag, priority)
    seam = sorted(year_tag.items())
    print(f"  Chosen {label} tag per period-end year: {seam}")

    quarter_facts: list[dict] = []
    fy_facts: list[dict] = []
    h1_facts: list[dict] = []
    ninem_facts: list[dict] = []
    for yr, chosen in year_tag.items():
        for f in by_tag[chosen]:
            if f["end"].year != yr:
                continue
            if is_quarter_dur(f["dur"]):
                quarter_facts.append(f)
            elif is_fy_dur(f["dur"]):
                fy_facts.append(f)
            elif is_h1_dur(f["dur"]) and f["end"].month == 6:
                h1_facts.append(f)
            elif is_9mo_dur(f["dur"]) and f["end"].month == 9:
                ninem_facts.append(f)
    return quarter_facts, fy_facts, h1_facts, ninem_facts, year_tag


# ---------- dedup (point-in-time, restatement-aware) ----------

def dedup_by_key(facts: list[dict], key_fn) -> tuple[list[dict], list[dict]]:
    """For each key, keep earliest-filed per distinct val.
    First distinct val = original (is_restatement=False).
    Later distinct vals at same key = restatement (is_restatement=True).
    Same val republished later (comparative): dropped.
    """
    groups: dict = defaultdict(list)
    for f in facts:
        groups[key_fn(f)].append(f)
    originals, restatements = [], []
    for _key, fs in groups.items():
        fs_sorted = sorted(fs, key=lambda x: x["filed"])
        seen_vals: set = set()
        for f in fs_sorted:
            v = f["val"]
            if v in seen_vals:
                continue
            rec = {**f, "is_restatement": bool(seen_vals)}
            if seen_vals:
                restatements.append(rec)
            else:
                originals.append(rec)
            seen_vals.add(v)
    return originals, restatements


# ---------- fp re-derivation ----------

def derive_fp(end_d: date, is_fy: bool = False) -> str:
    if is_fy:
        return "FY"
    m = end_d.month
    return {3: "Q1", 6: "Q2", 9: "Q3", 12: "Q4"}.get(m, "?")


def rekey_fy_fp(records: list[dict], is_fy: bool = False) -> list[dict]:
    """Rewrite fy/fp from period_end so they reflect the actual period (not the
    filing's fy/fp, which gets inherited by comparatives in later filings)."""
    out = []
    for r in records:
        out.append({**r,
                    "fy": r["end"].year,
                    "fp": derive_fp(r["end"], is_fy=is_fy)})
    return out


# ---------- Q4 derivation ----------

def derive_q4(quarter_originals: list[dict], fy_originals: list[dict],
              label: str) -> list[dict]:
    by_year_fp: dict = {}
    for f in quarter_originals:
        by_year_fp.setdefault(f["end"].year, {})[f["fp"]] = f
    fy_lookup = {f["end"].year: f for f in fy_originals}
    derived = []
    for yr, fps in sorted(by_year_fp.items()):
        if yr not in fy_lookup:
            continue
        if not all(p in fps for p in ("Q1", "Q2", "Q3")):
            continue
        if "Q4" in fps:
            continue
        fy_fact = fy_lookup[yr]
        q123 = fps["Q1"]["val"] + fps["Q2"]["val"] + fps["Q3"]["val"]
        q4 = fy_fact["val"] - q123
        derived.append({
            "start": date(yr, 10, 1),
            "end": date(yr, 12, 31),
            "dur": 92,
            "filed": fy_fact["filed"],
            "fy": yr,
            "fp": "Q4",
            "form": fy_fact["form"],
            "accn": fy_fact["accn"],
            "val": q4,
            "tag": fy_fact["tag"] + " (Q4 derived)",
            "is_restatement": False,
        })
        print(f"  [{label}] derived Q4 {yr}: FY={fy_fact['val']:,.0f} - "
              f"Q1+Q2+Q3={q123:,.0f} = {q4:,.0f} (filed {fy_fact['filed']}, "
              f"form {fy_fact['form']})")
    return derived


# ---------- Q2 / Q3 derivation from YTD (when 3-month is missing) ----------

def derive_q2_q3_from_ytd(q3mo_originals: list[dict], h1_ytd: list[dict],
                          ninem_ytd: list[dict], label: str) -> list[dict]:
    """When a flow is reported only YTD in 10-Qs (e.g., CVX's operating cash
    flow), derive standalone Q2/Q3 by subtraction:
      Q2 = YTD_6mo - Q1_3mo
      Q3 = YTD_9mo - YTD_6mo
    Skip any year where the 3-month fact already exists."""
    h1_dd, _ = dedup_by_key(h1_ytd, lambda f: f["end"])
    nm_dd, _ = dedup_by_key(ninem_ytd, lambda f: f["end"])
    h1_by_year = {f["end"].year: f for f in h1_dd}
    nm_by_year = {f["end"].year: f for f in nm_dd}

    by_year_fp: dict = {}
    for f in q3mo_originals:
        by_year_fp.setdefault(f["end"].year, {})[f["fp"]] = f

    derived = []
    for yr in sorted(set(h1_by_year) | set(nm_by_year)):
        fps = by_year_fp.get(yr, {})
        # Q2 from H1 - Q1
        if "Q2" not in fps and yr in h1_by_year and "Q1" in fps:
            h1 = h1_by_year[yr]
            q1 = fps["Q1"]
            q2_val = h1["val"] - q1["val"]
            derived.append({
                "start": date(yr, 4, 1),
                "end": date(yr, 6, 30),
                "dur": 91,
                "filed": h1["filed"],
                "fy": yr, "fp": "Q2", "form": h1["form"],
                "accn": h1["accn"], "val": q2_val,
                "tag": h1["tag"] + " (Q2 from YTD)",
                "is_restatement": False,
            })
            print(f"  [{label}] derived Q2 {yr}: H1_YTD={h1['val']:,.0f} - "
                  f"Q1={q1['val']:,.0f} = {q2_val:,.0f} (filed {h1['filed']}, "
                  f"form {h1['form']})")
        # Q3 from 9mo - H1
        if "Q3" not in fps and yr in nm_by_year and yr in h1_by_year:
            nm = nm_by_year[yr]
            h1 = h1_by_year[yr]
            q3_val = nm["val"] - h1["val"]
            derived.append({
                "start": date(yr, 7, 1),
                "end": date(yr, 9, 30),
                "dur": 92,
                "filed": nm["filed"],
                "fy": yr, "fp": "Q3", "form": nm["form"],
                "accn": nm["accn"], "val": q3_val,
                "tag": nm["tag"] + " (Q3 from YTD)",
                "is_restatement": False,
            })
            print(f"  [{label}] derived Q3 {yr}: 9mo_YTD={nm['val']:,.0f} - "
                  f"H1_YTD={h1['val']:,.0f} = {q3_val:,.0f} (filed {nm['filed']}, "
                  f"form {nm['form']})")
    return derived


# ---------- TTM ----------

def compute_ttm(quarters: list[dict], label: str) -> list[dict]:
    """Trailing-4-quarter rolling sums over consecutive quarters.
    Stamped with the latest constituent's filed/accn/form."""
    qs = sorted(quarters, key=lambda x: x["end"])
    out = []
    for i in range(3, len(qs)):
        win = qs[i - 3:i + 1]
        # Require ~12 months of coverage
        span = (win[-1]["end"] - win[0]["start"]).days
        if not (340 <= span <= 380):
            continue
        latest = max(win, key=lambda x: x["filed"])
        out.append({
            "end": win[-1]["end"],
            "filed": latest["filed"],
            "fy": win[-1]["fy"],
            "fp": win[-1]["fp"],
            "form": latest["form"],
            "accn": latest["accn"],
            "val": sum(q["val"] for q in win),
        })
    return out


# ---------- event assembly ----------

def to_events(records: list[dict], concept: str) -> list[dict]:
    return [{
        "filed": r["filed"],
        "accn": r["accn"],
        "fy": r["fy"],
        "fp": r["fp"],
        "form": r["form"],
        "period_end": r["end"],
        "concept": concept,
        "val": r["val"],
        "is_restatement": r.get("is_restatement", False),
    } for r in records]


def assemble_table(events: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(events)
    if df.empty:
        return df

    # Group by (filed, accn). Most filings produce one period_end for the
    # income/balance-sheet block; cover-page shares may carry a slightly
    # different end. Pick the financial-statement period_end (longest-end of
    # any non-shares concept) as the row anchor; shares value still folds in.
    rows = []
    for (filed, accn), g in df.groupby(["filed", "accn"], dropna=False):
        non_shares = g[g["concept"] != "shares"]
        period_end = (non_shares["period_end"].max()
                      if not non_shares.empty
                      else g["period_end"].max())
        # Derive fy/fp from the row's anchor period_end so they reflect the
        # actual period being published, not any individual fact's filing-fy
        # attribute (which can lag by one year for some tags).
        form = (g["form"].dropna().iloc[0] if g["form"].notna().any() else None)
        row = {
            "filed": filed,
            "accn": accn,
            "period_end": period_end,
            "fy": period_end.year,
            "fp": derive_fp(period_end.date() if hasattr(period_end, "date")
                            else period_end, is_fy=False),
            "form": form,
            "is_restatement": bool(g["is_restatement"].any()),
        }
        for c in ("revenue_q", "revenue_ttm", "ocf_q", "ocf_ttm",
                  "equity", "shares"):
            sub = g[g["concept"] == c]
            if not sub.empty:
                # If multiple values for the same concept at same (filed, accn),
                # this would be unexpected — take the one with greatest period_end.
                row[c] = sub.sort_values("period_end").iloc[-1]["val"]
            else:
                row[c] = None
        rows.append(row)

    out = pd.DataFrame(rows).sort_values("filed").reset_index(drop=True)
    out["filed"] = pd.to_datetime(out["filed"])
    out["period_end"] = pd.to_datetime(out["period_end"])

    # Forward-fill the step-series instantaneous items so each event row carries
    # the latest known equity / shares.
    out["equity"] = out["equity"].ffill()
    out["shares"] = out["shares"].ffill()

    cols = ["filed", "period_end", "fy", "fp", "form",
            "revenue_q", "revenue_ttm", "ocf_q", "ocf_ttm",
            "equity", "shares", "is_restatement", "accn"]
    return out[cols]


# ---------- validation ----------

def validate(df: pd.DataFrame, rev_quarters: list[dict],
             rev_fy: list[dict], equity_evts: list[dict]) -> None:
    print("\n=== VALIDATION ===")

    # 1. Q1 2024 sales (ASC 606 net) ≈ $46,580M
    q1_24 = [r for r in rev_quarters if r["end"] == date(2024, 3, 31)]
    if q1_24:
        v = q1_24[0]["val"] / 1e6
        flag = "OK" if 46000 <= v <= 47200 else "MISMATCH"
        print(f"  Q1 2024 revenue (ASC 606 net): ${v:,.0f}M  "
              f"[expect ~$46,580M] {flag}")
    else:
        print("  Q1 2024 revenue: NOT FOUND")

    # 2. Stockholders' equity at 12/31/2014 ≈ $155B
    eq_2014 = [e for e in equity_evts if e["end"] == date(2014, 12, 31)]
    if eq_2014:
        v = eq_2014[0]["val"] / 1e9
        flag = "OK" if 150 <= v <= 160 else "MISMATCH"
        print(f"  Equity 12/31/2014: ${v:,.1f}B  [expect ~$155B] {flag}")
    else:
        print("  Equity 12/31/2014: NOT FOUND")

    # 3. Quarterly flows re-sum to FY within rounding (per year, where complete)
    print("  Quarterly sum vs FY checks:")
    by_yr_q: dict = {}
    for r in rev_quarters:
        by_yr_q.setdefault(r["end"].year, {})[r["fp"]] = r["val"]
    fy_map = {r["end"].year: r["val"] for r in rev_fy}
    ok, bad = 0, 0
    for yr, fps in sorted(by_yr_q.items()):
        if yr not in fy_map:
            continue
        if not all(p in fps for p in ("Q1", "Q2", "Q3", "Q4")):
            continue
        s = sum(fps[p] for p in ("Q1", "Q2", "Q3", "Q4"))
        diff = s - fy_map[yr]
        tol = max(2e6, abs(fy_map[yr]) * 0.0005)  # $2M or 5 bp
        status = "OK" if abs(diff) <= tol else "MISMATCH"
        if status == "OK":
            ok += 1
        else:
            bad += 1
            print(f"    FY{yr}: Q-sum {s:,.0f} vs FY {fy_map[yr]:,.0f}, "
                  f"diff {diff:,.0f}  {status}")
    print(f"    {ok} FYs reconcile, {bad} mismatch")

    # 4. Sanity: shares around Q1 2024 cover page
    q1_24_event = df[(df["filed"] >= pd.Timestamp(2024, 4, 1))
                     & (df["filed"] <= pd.Timestamp(2024, 5, 31))
                     & (df["period_end"] == pd.Timestamp(2024, 3, 31))]
    if not q1_24_event.empty:
        sh = q1_24_event["shares"].iloc[0]
        flag = ("OK" if sh and 1.84e9 <= sh <= 1.86e9 else "MISMATCH")
        print(f"  Q1 2024 10-Q shares outstanding: {sh:,.0f}  "
              f"[expect 1,847,009,033] {flag}")
    else:
        print("  Q1 2024 10-Q row: NOT FOUND")


# ---------- main ----------

def main() -> int:
    facts_root = fetch_json()["facts"]

    (rev_q_raw, rev_fy_raw, rev_h1_raw, rev_9mo_raw,
     rev_year_tag) = build_flow_series(facts_root, REVENUE_TAGS, "Revenue")
    (ocf_q_raw, ocf_fy_raw, ocf_h1_raw, ocf_9mo_raw,
     ocf_year_tag) = build_flow_series(facts_root, OCF_TAGS, "Operating Cash Flow")

    print("\n=== Equity / Shares coverage ===")
    eq_raw = norm_inst(usd_facts(facts_root, EQUITY_TAG), EQUITY_TAG)
    sh_raw = norm_inst(shares_unit_facts(facts_root), SHARES_TAG)
    print(f"  Equity ({EQUITY_TAG}): {len(eq_raw)} facts, "
          f"end {min(f['end'] for f in eq_raw)} -> "
          f"{max(f['end'] for f in eq_raw)}")
    print(f"  Shares ({SHARES_TAG}): {len(sh_raw)} facts, "
          f"end {min(f['end'] for f in sh_raw)} -> "
          f"{max(f['end'] for f in sh_raw)}")

    # Dedup. Key is period_end: a single period can have one true value at
    # first filing; any later filing with a different value at the same
    # period_end is a restatement; same value republished as a comparative is
    # dropped.
    rev_q_orig, rev_q_rest = dedup_by_key(rev_q_raw, lambda f: f["end"])
    rev_fy_orig, rev_fy_rest = dedup_by_key(rev_fy_raw, lambda f: f["end"])
    ocf_q_orig, ocf_q_rest = dedup_by_key(ocf_q_raw, lambda f: f["end"])
    ocf_fy_orig, ocf_fy_rest = dedup_by_key(ocf_fy_raw, lambda f: f["end"])
    eq_orig, eq_rest = dedup_by_key(eq_raw, lambda f: f["end"])
    sh_orig, sh_rest = dedup_by_key(sh_raw, lambda f: f["end"])

    # Re-key fy/fp from period_end so labels reflect the actual period.
    rev_q_orig = rekey_fy_fp(rev_q_orig, is_fy=False)
    rev_q_rest = rekey_fy_fp(rev_q_rest, is_fy=False)
    rev_fy_orig = rekey_fy_fp(rev_fy_orig, is_fy=True)
    rev_fy_rest = rekey_fy_fp(rev_fy_rest, is_fy=True)
    ocf_q_orig = rekey_fy_fp(ocf_q_orig, is_fy=False)
    ocf_q_rest = rekey_fy_fp(ocf_q_rest, is_fy=False)
    ocf_fy_orig = rekey_fy_fp(ocf_fy_orig, is_fy=True)
    ocf_fy_rest = rekey_fy_fp(ocf_fy_rest, is_fy=True)

    print(f"\nDedup (original / restatement counts):")
    print(f"  Revenue Q: {len(rev_q_orig)} / {len(rev_q_rest)}")
    print(f"  Revenue FY: {len(rev_fy_orig)} / {len(rev_fy_rest)}")
    print(f"  OCF Q: {len(ocf_q_orig)} / {len(ocf_q_rest)}")
    print(f"  OCF FY: {len(ocf_fy_orig)} / {len(ocf_fy_rest)}")
    print(f"  Equity: {len(eq_orig)} / {len(eq_rest)}")
    print(f"  Shares: {len(sh_orig)} / {len(sh_rest)}")

    for label, rests in [("Revenue Q", rev_q_rest), ("Revenue FY", rev_fy_rest),
                         ("OCF Q", ocf_q_rest), ("OCF FY", ocf_fy_rest),
                         ("Equity", eq_rest), ("Shares", sh_rest)]:
        for r in rests:
            print(f"  RESTATEMENT [{label}] end={r['end']} fy={r.get('fy')} "
                  f"fp={r.get('fp')} val={r['val']:,.0f} filed={r['filed']}")

    # Q2/Q3 derivation from YTD (for tags where the 10-Q only carries YTD —
    # CVX's operating cash flow does this).
    print("\n=== Q2/Q3 derivation from YTD ===")
    rev_q23 = derive_q2_q3_from_ytd(rev_q_orig, rev_h1_raw, rev_9mo_raw, "Revenue")
    ocf_q23 = derive_q2_q3_from_ytd(ocf_q_orig, ocf_h1_raw, ocf_9mo_raw, "OCF")

    # Q4 derivation
    print("\n=== Q4 derivation ===")
    rev_q4 = derive_q4(rev_q_orig + rev_q23, rev_fy_orig, "Revenue")
    ocf_q4 = derive_q4(ocf_q_orig + ocf_q23, ocf_fy_orig, "OCF")

    rev_quarters_all = rev_q_orig + rev_q23 + rev_q4
    ocf_quarters_all = ocf_q_orig + ocf_q23 + ocf_q4

    # TTM
    rev_ttm = compute_ttm(rev_quarters_all, "Revenue")
    ocf_ttm = compute_ttm(ocf_quarters_all, "OCF")

    # Assemble events
    events = []
    events += to_events(rev_quarters_all, "revenue_q")
    events += to_events(rev_q_rest, "revenue_q")
    events += to_events(ocf_quarters_all, "ocf_q")
    events += to_events(ocf_q_rest, "ocf_q")
    events += to_events(eq_orig, "equity")
    events += to_events(eq_rest, "equity")
    events += to_events(sh_orig, "shares")
    events += to_events(sh_rest, "shares")
    events += to_events(rev_ttm, "revenue_ttm")
    events += to_events(ocf_ttm, "ocf_ttm")

    df = assemble_table(events)

    # Validate
    validate(df, rev_quarters_all, rev_fy_orig, eq_orig)

    # Write CSV
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_PATH, index=False)
    print(f"\nWrote {len(df)} rows -> {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
