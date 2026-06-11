# Options Import — Design Plan (yfinance → options_chain)

> **Status: PLAN ONLY — no implementation yet.** This documents the standalone, daily-forward
> options import that unblocks the frontend options chain. Read alongside [`PLAN.md`](PLAN.md); where
> they differ on options sourcing, **this doc wins** (it supersedes PLAN.md's Alpaca-for-options
> assumption — see §9).
>
> _Drafted 2026-06-09. Decisions from kickoff Q&A are in §1._

---

## 1. Scope & decisions

A **standalone** process (also callable from the pipeline) that, once per day, fetches a small,
deliberately-scoped options chain for a set of equities and writes it to `options_chain`. Everything
else reads from the DB — the vendor is called **at most once per (security, day)**.

| Decision | Choice | Why |
|---|---|---|
| Provider | **yfinance** (free) | We only need **current-day** data for the **frontend**. Has bid/ask/last/volume/OI/IV. |
| Greeks | **Compute `delta` in-house** (Black-Scholes) | yfinance gives no greeks; we have IV + spot + DTE, so BS delta is trivial and provider-independent. |
| Expiries | **Term points 30/60/90/180 DTE + front 1–2 monthlies** | Covers a useful term structure + liquid near-term expiries for the chain display. |
| History | **Daily-forward only** | No historical options backfill needed here. |
| Consumer | **Frontend** (`options_chain` → backend `get_options_chain` → `OptionRecord`) | — |

**Explicit non-goals (important):**
- **Not the model's IV source.** The model needs *historical* options data and keeps its own data
  path (WRDS/Parquet). This import is **decoupled** from the model — it does **not** resolve the
  post-WRDS IV seam in PLAN §7.5.4. (If that changes later, this same table can feed it.)
- **Not the "opportunities"/edge view.** `app/components/ticker/options.tsx` consumes a derived
  `{mkt_px, model_px, edge_pct}` shape — that's model pricing on top of the raw chain, a separate
  downstream step. This import produces only the **raw** `options_chain` rows (`OptionRecord`).

---

## 2. Data flow

```
yfinance Ticker(symbol)
  .options                      → all available expiry strings
  select_expiries(...)          → {nearest to 30/60/90/180 DTE} ∪ {front 1–2 monthlies}
  .option_chain(expiry)         → calls/puts DataFrames (one HTTP call per expiry)
  fast_info.last_price          → spot (for strike-band scoping + BS delta)
        │
        ▼  normalize per row
  OptionRecord{snapshot_date=run_date, expiry, strike, option_type, bid, ask, mid,
               last, volume, open_interest, iv, delta(=BS from spot,strike,DTE,iv,r)}
        │  filter strikes to ±strike_band_pct of spot
        ▼
  resolve security_id  (ticker → securities.security_id)
        ▼
  upsert options_chain  (service-role; on_conflict
                         security_id,snapshot_date,expiry,option_type,strike)   ← idempotent
        ▼
  backend get_options_chain() → frontend OptionRecord[]   (reads DB only)
```

Cost per ticker/day ≈ `1 (.options) + 1 (spot) + ~4–6 (.option_chain per expiry)` HTTP calls. Strike
filtering is client-side (free). For ~10 tickers that's ~60 calls/day total — trivial, and skipped
entirely on a same-day re-run.

---

## 3. yfinance → `options_chain` column mapping

yfinance `option_chain(expiry)` returns `calls` and `puts` DataFrames with columns:
`contractSymbol, lastTradeDate, strike, lastPrice, bid, ask, volume, openInterest,
impliedVolatility, inTheMoney, contractSize, currency` (plus change/%change).

| `options_chain` column | Source | Notes |
|---|---|---|
| `security_id` | resolved from `securities` | FK; CRSP PERMNO in this project (e.g. AAPL=320193) |
| `snapshot_date` | `ctx.run_date` (US business date) | one snapshot/day |
| `expiry` | the selected expiry (date) | from `.options` |
| `strike` | `strike` | numeric(10,2) |
| `option_type` | `'C'` for calls / `'P'` for puts | per the table's CHECK constraint |
| `bid` | `bid` | NULL if missing |
| `ask` | `ask` | NULL if missing |
| `mid` | `(bid+ask)/2` if both > 0 else NULL | derived; illiquid contracts often have 0/blank quotes |
| `last` | `lastPrice` | |
| `volume` | `volume` | NaN → NULL |
| `open_interest` | `openInterest` | NaN → NULL (yfinance OI is prior-session) |
| `iv` | `impliedVolatility` | NaN/≤0 → NULL |
| `delta` | **computed** (Black-Scholes, §5) | NULL when IV missing or DTE ≤ 0 |

Defensive parsing: yfinance columns occasionally shift/empty; the normalizer reads by name with
`.get`-style access and coerces NaN→None so a missing column degrades to NULL rather than crashing.

---

## 4. Expiry selection (preset A + front monthlies)

Pure function over the available expiry list + today (`automation/expiry_selection.py`):

1. Compute DTE for every available expiry.
2. **Term points:** for each target in `term_dte_targets = [30, 60, 90, 180]`, pick the expiry with
   the smallest `|DTE − target|`.
3. **Front monthlies:** detect standard monthlies (a Friday with day-of-month 15–21 = 3rd Friday);
   take the next `front_monthlies = 2`.
4. Union (2) ∪ (3), dedupe, sort ascending. That's the fetch set.

All knobs live in config (§7) so the preset is tunable without code changes. Edge cases: fewer
available expiries than targets → just use what exists; never error on a thin chain.

## 5. Delta via Black-Scholes (`automation/black_scholes.py`)

Self-contained, dependency-free (uses `math.erf` for the normal CDF — no scipy), so `automation`
stays independent of the `model/` package. (The model's `model/pipeline/utils.py` BS is the
conceptual reference; we don't import it, to keep the package boundary clean.)

```
d1 = (ln(S/K) + (r − q + σ²/2)·T) / (σ·√T)        T = DTE/365, σ = iv
call_delta =  N(d1)            put_delta = N(d1) − 1     (q ≈ 0 dividend-yield approximation)
```

- `r` (risk-free): config `risk_free_rate` (default ~0.045). Optional TODO: source the 3-mo rate
  from yfinance `^IRX` once per run (we're already using yfinance) for a touch more accuracy.
- `q` (dividend yield): approximated as 0 — slightly biases delta for high-dividend names; acceptable
  for a display value. Flag if a consumer needs precision.
- Guards: `iv ≤ 0`, `T ≤ 0`, or `S/K ≤ 0` → `delta = NULL` (don't fabricate).

## 6. Strike scoping & security resolution

- **Strikes:** after fetching an expiry, keep strikes within `±strike_band_pct` of spot (default
  0.30), optionally capped to `max_strikes_per_side`. Filtering is client-side (no extra calls).
- **Spot:** `Ticker.fast_info.last_price` (fallback: last `history(period="1d")` close). Used for
  both the strike band and BS delta.
- **security_id:** resolve ticker → `securities.security_id` by reading `securities` (the FK target).
  Tickers absent from `securities` are skipped with a clear warning (a chain with no FK can't be
  written). The standalone runner can target an explicit `--tickers` list or default to
  `securities.active`.

## 7. Idempotency, config, and the standalone/pipeline split

- **Writes:** service-role client (`db.py`), `upsert on_conflict
  (security_id, snapshot_date, expiry, option_type, strike)` — re-running a day overwrites in place,
  never duplicates (matches the table's unique constraint).
- **Freshness/skip:** if today's snapshot already exists for a security, skip the fetch
  (`--force` overrides). Same rule the pipeline stage uses.
- **One reusable core, two callers:**
  - pure functions (no DB, no async): `expiry_selection`, `black_scholes`, and the yfinance
    provider's `fetch_chain(ticker, expiries, scope) -> list[OptionRecord-dict]`; plus the per-security
    orchestration in `options_import.py`.
  - **Standalone runner** `automation/tools/fetch_options.py` (`python -m automation.tools.fetch_options
    --tickers AAPL MSFT [--dry-run] [--force]`) wires config → resolve → fetch → upsert via
    `asyncio.run`. **This is the shipped entry point.**
  - **Pipeline stage** (planned): when the orchestrator is built, its `fetch_options` stage will call
    the *same* `options_import` core + `upsert_options_chain` + freshness skip — no logic duplicated.

Config (`automation/config.py`) — add an `OptionsImportConfig` (provider-agnostic naming so a future
swap to Polygon/Tradier is a config change):

```
provider: str = "yfinance"
term_dte_targets: list[int] = [30, 60, 90, 180]
front_monthlies: int = 2
strike_band_pct: float = 0.30
max_strikes_per_side: int | None = None
risk_free_rate: float = 0.045
max_retries: int = 3            # yfinance can rate-limit / return empty
backoff_base_seconds: float = 1.0
```

---

## 8. Files (implemented)

- `automation/black_scholes.py` — pure BS delta (math.erf normal CDF).
- `automation/expiry_selection.py` — term-point + monthly selection (pure).
- `automation/providers/options_provider.py` — `OptionsProvider` protocol + `YFinanceOptionsProvider`
  (`list_expiries`, `fetch_spot`, `fetch_chain` → normalized rows w/ delta filled).
- `automation/options_import.py` — reusable per-security import core.
- `automation/tools/fetch_options.py` — standalone CLI runner (the shipped entry point).
- `automation/tests/test_expiry_selection.py`, `test_black_scholes.py` — pure-function tests.
- `automation/config.py` — `OptionsImportConfig` + `load_config`.
- `automation/db.py` — secret-key write client: `connect`, `upsert_options_chain`,
  `options_snapshot_exists`, `resolve_security_ids`.
- `automation/requirements.txt`, `.env.example` — yfinance dep; yfinance needs **no key** (only
  `SUPABASE_*` for writes).

Deferred to when the orchestrator is built: the `fetch_options` **pipeline stage** (a thin wrapper over
`options_import`), and the Alpaca **prices** provider.

---

## 9. Supersedes / relationship to PLAN.md

- PLAN.md §1b/§4.3/§5 assumed **Alpaca** for options. **This doc changes the options source to
  yfinance** (Alpaca had no OI/volume and is overkill for current-day display data). Alpaca remains
  the plan for **prices** (`fetch_prices`).
- PLAN.md §7.5.4 (post-WRDS IV seam, model side) is **unaffected and still open** — this import does
  not feed the model.

## 10. Risks & caveats

- **yfinance is unofficial** — can break or rate-limit. Mitigations: retries/backoff, defensive
  parsing, NULL-on-missing, and the DB cache (a failed fetch leaves yesterday's snapshot intact).
  Provider-agnostic config means swapping to a paid source later is a config change.
- **OI is prior-session** in yfinance, and quotes can be stale/zero for illiquid strikes — acceptable
  for display; documented so consumers don't over-trust thin contracts.
- **Delta is approximate** (q≈0, single `r`). Fine for a UI greeks column; revisit if used in pricing.

## 11. Open items (need your call before implementation)

- **Validation target:** local Supabase stack (seeded — has the 10 securities incl. AAPL=320193 and
  a mock options snapshot to overwrite) vs hosted **stg**. Needs the matching `SUPABASE_URL` +
  `SUPABASE_SECRET_KEY`.
- **Test tickers:** explicit `--tickers` (e.g. AAPL, MSFT) vs default to `securities.active` (the
  seeded 10). Tickers must exist in `securities` to resolve the FK.
```
