"""
beta_mz_entry_ladder.py -- Entry-timing FALSIFICATION test for the cooling leg.

The signal is computable only AFTER Friday close, so Friday-close entry is
theoretical; Monday-open is the earliest real entry. We already estimated the
Monday-lag tax at ~0.34%/signal. This walks the full entry ladder:

    Friday close (theoretical) | Monday open | Monday close | Tuesday open | scale-in 3d

The cooling leg holds ~40 BD, so a one-day entry shift should barely matter IF
this is a regime call. If the edge COLLAPSES when entry moves by a day, the
"signal" is a microstructure artifact, not a regime signal. We expect it to pass
-- which is exactly why it's worth proving.

Exit is held FIXED (close, 40 BD after the signal Friday's session) for every
convention, so only the ENTRY price varies.

Output: results/validation/beta_mz_entry_ladder.csv
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from ..config import load_config
from ..data_loader import ParquetStore
from .beta_mz_deep_dive import add_slope_signs
from .beta_mz_panel import load_per_ticker_weekly, aggregate_subset

REPO_ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = REPO_ROOT / "model" / "pipeline" / "results" / "validation"
START_DATE = pd.Timestamp("2015-01-01")
HOLD_BD = 40


def load_ohlc(ticker: str) -> pd.DataFrame:
    dc, _, _ = load_config()
    oh = ParquetStore(dc.base_dir).load("ohlcv")
    oh["date"] = pd.to_datetime(oh["date"], format="mixed")
    sub = oh[oh["ticker"] == ticker].drop_duplicates("date", keep="last").sort_values("date")
    return sub.set_index("date")[["openprc", "prc"]].dropna()


def cooling_events(bmz: pd.DataFrame) -> list:
    ev = bmz[bmz["sign_change_w12"] & (bmz["sign_lag_w12"] > 0) & (bmz["sign_w12"] < 0)]
    return ev["asof"].sort_values().tolist()


def entry_returns(ohlc: pd.DataFrame, events: list, hold: int) -> pd.DataFrame:
    """For each cooling event, long-bet log return under each entry convention.
    Exit fixed at close, hold BD after the signal-Friday session."""
    idx = ohlc.index
    o = ohlc["openprc"].to_numpy(float)
    c = ohlc["prc"].to_numpy(float)
    rows = []
    for d in events:
        fri = idx.searchsorted(d, side="right") - 1   # last session <= event Friday
        if fri < 0 or fri + hold >= len(idx) or fri + 3 >= len(idx):
            continue
        exit_px = c[fri + hold]
        entries = {
            "FRI_CLOSE": c[fri],
            "MON_OPEN": o[fri + 1],
            "MON_CLOSE": c[fri + 1],
            "TUE_OPEN": o[fri + 2],
            "SCALE_3D": np.mean([o[fri + 1], o[fri + 2], o[fri + 3]]),
        }
        row = {"event": d.date().isoformat()}
        for k, ep in entries.items():
            row[k] = float(np.log(exit_px / ep)) if ep > 0 else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    bmz = add_slope_signs(aggregate_subset(load_per_ticker_weekly()), 12)
    events = cooling_events(bmz)
    print(f"[BMZ_ENTRY] {len(events)} cooling events | hold {HOLD_BD} BD | "
          f"exit fixed, entry varies")

    conv = ["FRI_CLOSE", "MON_OPEN", "MON_CLOSE", "TUE_OPEN", "SCALE_3D"]
    out_rows = []
    for tk in ("SPY", "QQQ", "IWM"):
        ohlc = load_ohlc(tk)
        ohlc = ohlc[ohlc.index >= START_DATE]
        er = entry_returns(ohlc, events, HOLD_BD)
        print(f"\n  === {tk} (n={len(er)} bets) ===")
        base = er["FRI_CLOSE"]
        for k in conv:
            r = er[k].dropna()
            sharpe = r.mean() / r.std(ddof=1) if len(r) > 1 and r.std() > 0 else np.nan
            tax_vs_fri = float((base - er[k]).mean())   # +ve = this entry gives up vs Fri close
            print(f"    {k:10s}: mean {r.mean():+.3%}  median {r.median():+.3%}  "
                  f"hit {np.mean(r>0):.0%}  per-bet Sharpe {sharpe:+.2f}  "
                  f"tax vs FRI {tax_vs_fri:+.3%}")
            out_rows.append({"index": tk, "entry": k, "n": len(r), "mean": float(r.mean()),
                             "median": float(r.median()), "hit_rate": float(np.mean(r > 0)),
                             "per_bet_sharpe": float(sharpe), "tax_vs_fri_close": tax_vs_fri})
    df = pd.DataFrame(out_rows)
    df.to_csv(OUT_DIR / "beta_mz_entry_ladder.csv", index=False)

    # verdict: does the edge survive Monday-open and beyond?
    spy = df[df["index"] == "SPY"].set_index("entry")
    surv = (spy.loc[["MON_OPEN", "MON_CLOSE", "TUE_OPEN"], "mean"] > 0).all() and \
           (spy.loc[["MON_OPEN", "MON_CLOSE", "TUE_OPEN"], "hit_rate"] >= 0.7).all()
    print(f"\n  VERDICT (SPY): edge {'SURVIVES' if surv else 'COLLAPSES'} the entry ladder "
          f"-> {'regime call, not microstructure' if surv else 'microstructure-sensitive (red flag)'}")
    print(f"  Mon-open tax vs Fri-close (SPY): {spy.loc['MON_OPEN','tax_vs_fri_close']:+.3%}")
    print(f"\n[BMZ_ENTRY] Wrote output to {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
