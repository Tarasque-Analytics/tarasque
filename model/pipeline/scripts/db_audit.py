"""
db_audit.py -- Backend (Supabase) state-of-the-data health check.

Complements the send-script audit. The send-script audit verifies the WRITE
PATH is correct. This audit verifies the STATE of the data is what we'd
expect. The two can diverge (partial writes from old failed runs, FK orphans,
stale tickers, legacy column drift, untouched tables).

Checks, in order of severity:
  1. Row counts per table (sanity floor)
  2. New fwd_premium_ewma_* coverage (verify the backfill stuck)
  3. Per-ticker freshness  (any tickers stuck at stale dates?)
  4. Cross-table integrity  (securities vs volatility_history vs prices_history)
  5. Legacy column drift    (iv_atm vs iv_atm_30d divergence)
  6. shap_snapshot table population
  7. options_chain table population
  8. Range checks on key vol columns
  9. Sample latest row per ticker (visual spot check)
"""
from __future__ import annotations

import io
import sys

import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from model.pipeline.db import SupabaseClient


def hdr(s: str):
    print("\n" + "=" * 78)
    print(f" {s}")
    print("=" * 78)


def main():
    db = SupabaseClient()

    # ── 1. ROW COUNTS PER TABLE ──────────────────────────────────────────────
    hdr("1. ROW COUNTS PER TABLE")
    tables = ["securities", "model_runs", "volatility_history", "prices_history",
              "event_history", "macro_calendar", "shap_snapshot", "options_chain",
              "ai_overview"]
    counts = {}
    for t in tables:
        try:
            r = db.client.table(t).select("*", count="exact").limit(1).execute()
            counts[t] = r.count
            print(f"  {t:22s} {r.count:>10,d}")
        except Exception as e:
            counts[t] = None
            print(f"  {t:22s}  ERROR: {str(e)[:80]}")

    # ── 2. NEW fwd_premium_ewma_* COVERAGE ───────────────────────────────────
    hdr("2. NEW fwd_premium_ewma_* COVERAGE (post-backfill)")
    total = counts.get("volatility_history") or 0
    for col in ("fwd_premium_ewma_21d", "fwd_premium_ewma_63d", "fwd_premium_ewma_126d"):
        try:
            nn = db.client.table("volatility_history").select(
                "security_id", count="exact").not_.is_(col, "null").limit(1).execute()
            pct = nn.count / total * 100 if total else 0
            flag = "OK" if pct > 95 else "LOW" if pct > 60 else "BAD"
            print(f"  {col:30s} non-null {nn.count:>8,d} / {total:>8,d}  "
                  f"({pct:5.1f}%)  {flag}")
        except Exception as e:
            print(f"  {col}: ERROR {str(e)[:80]}")

    # ── 3. PER-TICKER FRESHNESS ──────────────────────────────────────────────
    hdr("3. PER-TICKER FRESHNESS (max date in volatility_history per ticker)")
    sec = db.client.table("securities").select("security_id,ticker").execute()
    sec_df = pd.DataFrame(sec.data)
    # Use a single grouped query via RPC; if not available, sample a few and report
    # via pure-table API (avoiding ~93 round trips by paging).
    # Workaround: pull last 14 days of vol rows, take max date per ticker.
    today = pd.Timestamp.today().normalize()
    cutoff = (today - pd.Timedelta(days=21)).strftime("%Y-%m-%d")
    recent = db.client.table("volatility_history").select(
        "security_id,date").gte("date", cutoff).execute()
    rec_df = pd.DataFrame(recent.data)
    if rec_df.empty:
        print("  WARNING: no rows in last 21 days at all")
    else:
        rec_df["date"] = pd.to_datetime(rec_df["date"])
        max_per_sec = rec_df.groupby("security_id")["date"].max().reset_index()
        max_per_sec = max_per_sec.merge(sec_df, on="security_id", how="left")
        max_per_sec["days_stale"] = (today - max_per_sec["date"]).dt.days
        # Tickers in securities but NO recent rows
        missing = set(sec_df["security_id"]) - set(max_per_sec["security_id"])
        missing_tk = sec_df[sec_df["security_id"].isin(missing)]["ticker"].tolist()
        median_max = max_per_sec["date"].median()
        worst = max_per_sec.nlargest(5, "days_stale")
        print(f"  median latest date across {len(max_per_sec)} tickers: "
              f"{median_max.date()}  ({(today - median_max).days} days stale)")
        print(f"  tickers with NO data in last 21 days: {len(missing)}"
              + (f"  ({missing_tk})" if missing_tk and len(missing_tk) <= 8 else ""))
        print(f"  5 stalest tickers (in last 21 days window):")
        for _, r in worst.iterrows():
            print(f"     {r['ticker']:6s} last_date={r['date'].date()}  "
                  f"days_stale={r['days_stale']}")

    # ── 4. CROSS-TABLE INTEGRITY ─────────────────────────────────────────────
    hdr("4. CROSS-TABLE INTEGRITY")
    sec_ids = set(sec_df["security_id"])
    # All distinct security_ids in volatility_history (sample-based check)
    vh_ids_sample = db.client.table("volatility_history").select(
        "security_id").limit(50000).execute()
    vh_ids = set(r["security_id"] for r in vh_ids_sample.data)
    ph_ids_sample = db.client.table("prices_history").select(
        "security_id").limit(50000).execute()
    ph_ids = set(r["security_id"] for r in ph_ids_sample.data)

    print(f"  securities table size:              {len(sec_ids)} tickers")
    print(f"  distinct security_ids in vol_hist:  {len(vh_ids)} (sample of 50k rows)")
    print(f"  distinct security_ids in prices:    {len(ph_ids)} (sample of 50k rows)")
    vh_orphans = vh_ids - sec_ids
    ph_orphans = ph_ids - sec_ids
    sec_missing_vh = sec_ids - vh_ids
    sec_missing_ph = sec_ids - ph_ids
    if vh_orphans:
        print(f"  WARNING: {len(vh_orphans)} security_id(s) in vol_hist with no matching "
              f"securities row: {sorted(vh_orphans)[:10]}")
    else:
        print(f"  no vol_hist orphans")
    if ph_orphans:
        print(f"  WARNING: {len(ph_orphans)} security_id(s) in prices with no matching "
              f"securities row: {sorted(ph_orphans)[:10]}")
    else:
        print(f"  no prices orphans")
    if sec_missing_vh:
        sec_missing_vh_tk = sec_df[sec_df["security_id"].isin(sec_missing_vh)]["ticker"].tolist()
        print(f"  NOTE: {len(sec_missing_vh)} ticker(s) in securities missing from vol_hist sample: "
              f"{sec_missing_vh_tk[:10]}")
    if sec_missing_ph:
        sec_missing_ph_tk = sec_df[sec_df["security_id"].isin(sec_missing_ph)]["ticker"].tolist()
        print(f"  NOTE: {len(sec_missing_ph)} ticker(s) in securities missing from prices sample: "
              f"{sec_missing_ph_tk[:10]}")

    # ── 5. LEGACY iv_atm DRIFT ───────────────────────────────────────────────
    hdr("5. LEGACY iv_atm DRIFT vs iv_atm_30d")
    try:
        sample = db.client.table("volatility_history").select(
            "iv_atm,iv_atm_30d").not_.is_("iv_atm", "null").not_.is_(
            "iv_atm_30d", "null").limit(5000).execute()
        s = pd.DataFrame(sample.data)
        if s.empty:
            print("  iv_atm has NO non-null rows -- column is effectively dead")
        else:
            diff = (s["iv_atm"] - s["iv_atm_30d"]).abs()
            print(f"  sampled {len(s):,} rows where both are non-null")
            print(f"  |iv_atm - iv_atm_30d|: mean {diff.mean():.6f}  max {diff.max():.6f}  "
                  f"(near-zero => duplicate)")
    except Exception as e:
        print(f"  iv_atm not queryable: {e}")

    # ── 6. shap_snapshot POPULATION ──────────────────────────────────────────
    hdr("6. shap_snapshot TABLE POPULATION")
    n_shap = counts.get("shap_snapshot") or 0
    if n_shap == 0:
        print("  shap_snapshot is EMPTY -- nothing populating it yet.")
        print("  Frontend Explainer panel will need either:")
        print("    (a) population pipeline pointing here, OR")
        print("    (b) read from volatility_history.shap_h{21,63,126}_top10 instead.")
    else:
        try:
            r = db.client.table("shap_snapshot").select(
                "horizon,snapshot_date,retrain_date").order(
                "snapshot_date", desc=True).limit(5).execute()
            print(f"  {n_shap:,} rows total")
            print("  most recent 5:")
            for x in r.data:
                print(f"    horizon={x['horizon']:3d}  "
                      f"snapshot={x['snapshot_date']}  retrain={x['retrain_date']}")
        except Exception as e:
            print(f"  ERROR: {e}")
    # Also check shap_h*_top10 coverage in volatility_history (fallback source)
    try:
        nn = db.client.table("volatility_history").select(
            "security_id", count="exact").not_.is_("shap_h126_top10", "null").limit(1).execute()
        print(f"  fallback: vol_hist.shap_h126_top10 non-null on {nn.count:,} / {total:,} rows "
              f"({nn.count/total*100:.1f}%)")
    except Exception as e:
        print(f"  fallback check ERROR: {e}")

    # ── 7. options_chain POPULATION ──────────────────────────────────────────
    hdr("7. options_chain TABLE POPULATION")
    n_chain = counts.get("options_chain") or 0
    if n_chain == 0:
        print("  options_chain is EMPTY -- expected, ingestion not yet wired.")
        print("  Skew panel + Options Chain table on the equity page will be blocked")
        print("  until live-chain ingestion lands (user noted: 15-min-lagged target).")
    else:
        r = db.client.table("options_chain").select(
            "snapshot_date,security_id", count="exact").order(
            "snapshot_date", desc=True).limit(5).execute()
        print(f"  {n_chain:,} rows  latest snapshots: "
              + ", ".join(f"{x['snapshot_date']}" for x in r.data))

    # ── 8. RANGE CHECKS on key vol columns ───────────────────────────────────
    hdr("8. RANGE CHECKS (latest 7d of vol_hist)")
    cutoff7 = (today - pd.Timedelta(days=7)).strftime("%Y-%m-%d")
    chk = db.client.table("volatility_history").select(
        "iv_atm_30d,pfv_cal_21,pfv_cal_63,pfv_cal_126,"
        "fwd_premium_21d,fwd_premium_ewma_21d,vrp_wedge_ewma_21d").gte(
        "date", cutoff7).execute()
    c = pd.DataFrame(chk.data)
    if c.empty:
        print("  no rows in last 7 days (off-hours? holiday?)")
    else:
        print(f"  {len(c):,} rows over last 7 days")
        for col in c.columns:
            v = c[col].dropna()
            if len(v) == 0:
                print(f"    {col:24s} ALL NULL")
                continue
            extreme = ""
            if col.startswith("iv_atm") or col.startswith("pfv_"):
                if (v < 0).any() or (v > 5).any():
                    extreme = f"  WARN: out-of-range ({(v<0).sum()} neg, {(v>5).sum()} >5)"
            print(f"    {col:24s} min {v.min():+.3f}  med {v.median():+.3f}  "
                  f"max {v.max():+.3f}  non-null {len(v):>4d}{extreme}")

    # ── 9. SAMPLE LATEST ROW PER FAMILIAR TICKER ─────────────────────────────
    hdr("9. SAMPLE LATEST ROW PER TICKER (spot-check)")
    spot_tickers = ["XOM", "AAPL", "NVDA", "JPM", "TSLA", "SPY", "QQQ"]
    sec_spot = sec_df[sec_df["ticker"].isin(spot_tickers)]
    rows = []
    for _, sr in sec_spot.iterrows():
        r = db.client.table("volatility_history").select(
            "date,iv_atm_30d,pfv_cal_21,fwd_premium_21d,fwd_premium_ewma_21d,model_run_id"
        ).eq("security_id", sr["security_id"]).order(
            "date", desc=True).limit(1).execute()
        if r.data:
            x = r.data[0]; x["ticker"] = sr["ticker"]; rows.append(x)
    if rows:
        df = pd.DataFrame(rows)[["ticker","date","iv_atm_30d","pfv_cal_21",
                                  "fwd_premium_21d","fwd_premium_ewma_21d","model_run_id"]]
        print(df.to_string(index=False))

    print("\n[DB AUDIT] Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
