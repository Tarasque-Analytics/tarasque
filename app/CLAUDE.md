# Frontend — Volarbear app

React + Vite + Tailwind, served via React Router v7 (framework mode). This file covers the
**frontend only**; the backend lives at `backend/CLAUDE.md`, and the model at
`model/claude_context.md` (maintained by a different developer — don't assume it tracks frontend
changes).

## Layout

- `app/routes.ts` — file-based route config.
- `app/routes/<name>.tsx` — route modules (loader + default re-export of the page).
- `app/pages/<Name>.tsx` — page components rendered by their route module.
- `app/layouts/<Name>.tsx` — layout components (e.g. `ProtectedLayout`).
- `app/components/<area>/<name>.tsx` — UI grouped by page area (`equity/` = redesigned
  `/equity/:symbol` components, `ticker/` = legacy/being-replaced, `dashboard/`, `ui/` = shared).
- `app/context/<Name>Context.tsx` — React contexts + their hooks.
- `app/utils/` — data fetchers and shared types.
- `app/supabaseClient.ts` — Supabase JS client (auth only; data flows via FastAPI).

## Running

```bash
npm run dev           # Vite dev server on http://localhost:5173
npm run dev:backend   # FastAPI on :8000 (required for any data-backed page)
npm run typecheck     # react-router typegen && tsc
```

Anything under `ProtectedLayout` needs the backend running.

## Routing

Defined in [routes.ts](routes.ts):
- `/` → public landing (`navigation.tsx`).
- `/login`, `/register` → auth.
- Under `ProtectedLayout`:
  - `/dashboard`, `/macro`, `/sector/:sector`.
  - **`/equity/:symbol`** — the main DB-backed page (where most current work lives).
- `*` → 404.

### Auth gating — important to know

Auth is handled by Supabase: users sign up on the (locally-hosted) site, Supabase creates the
user record, and [ProtectedLayout](layouts/ProtectedLayout.tsx) checks the session **client-side
in a `useEffect`** (`supabase.auth.getUser()` → `navigate("/login")` on failure), **not** in a
loader. So the protected child loaders still run, fetch data, and SSR-render their pages — the
redirect happens afterward, on the client. Implication: hitting `/equity/AAPL` server-side hits
both API endpoints even when unauthenticated; you can verify the data path via `curl` without
logging in.

**Test/showcase credentials (planned, TBD):** goal is a shared `email + password` combo that
gives group access to a testing/showcase account, so reviewers can log in without going through
sign-up. The blocker is Supabase's **email-verification** step — it requires owning the inbox,
which prevents handing out credentials. Likely path is to pre-seed the showcase user with
`email_confirmed_at` already set (via the Supabase Auth admin API or a direct insert into
`auth.users` in a setup step), and/or disable email confirmation for the local stack in
`supabase/config.toml`. Local-only for now (not deployed); specific approach not decided yet.

## Equity page data flow

`/equity/:symbol` is the canonical example of the data architecture.

1. **Loader** ([routes/ticker.tsx](routes/ticker.tsx)) fetches the single DB-backed payload:
   - `loadEquityData(symbol)` → `GET /api/equity/:symbol` (Supabase-backed). **Non-fatal** — on
     failure the loader returns `equity: null` (it does **not** throw) so the page can render an
     explicit error state.
2. **Page** ([pages/Ticker.tsx](pages/Ticker.tsx)) reads `useLoaderData()`; when `equity` is `null`
   it renders [`EquityUnavailable`](components/equity/equity_unavailable.tsx), otherwise it wraps the
   section components in `EquityDataProvider` (DB).
3. **Components** consume the DB payload via:
   - `useEquityData()` → `EquitiesPayload | null`. Consumers **must handle `null`** (DB call may
     have failed).

## Equity page — redesign in progress

The page has been rebuilt around DB-backed components under `app/components/equity/`. The four
original file-backed `components/ticker/*` components (Attributes, Options, Predictors, MonteCarlo)
and the entire file-payload path (`/api/tickers*`, `loadTickerPayload`, `TickerDataContext`) were
**removed** in the file-data cleanup (issue #83) — `/api/equity/:symbol` is now the page's only data
source. The planned successors for what the legacy components showed: a metadata panel (#104) for
Attributes, and SHAP attributions re-homed to the separate `/model` page (#101–#103) for Predictors.

**First new component — the price-history chart**
([components/equity/price_history_chart.tsx](components/equity/price_history_chart.tsx)), the
pattern the rest of the redesign follows. New equity components live under
`app/components/equity/` (not the legacy `ticker/`). It reads `useEquityData()` end-to-end
(loader → `EquityDataContext` → component) and renders the close-price area line (OHLCV in the
tooltip), a `1M…MAX` range selector that filters the loaded history client-side, per-security
event-annotation lines from `events`, and a VRP-EWMA-21d sub-panel from `volatility_history`.
Two chart.js gotchas are documented inline and worth reusing: (1) an inline plugin must read its
data from `chart.options` — react-chartjs-2 does **not** refresh an inline-plugin **closure** on
re-render, so a closure goes stale and redraws the previous range's data; (2) canvas can't
resolve CSS variables, so graph colors are literals in the component while shared UI colors live
in `app/app.css`. `loadEquityList()` ([utils/database.ts](utils/database.ts)) → `GET /api/equities`
feeds ticker search/selection (the search box navigates to `/equity/:symbol`).

### Equity section components — shared structure (keep these aligned)

The `/equity/:symbol` page is a vertical stack of **section components** under
[components/equity/](components/equity/) — price history, forward-vol forecast, options chain,
contracts & skew. They deliberately share one skeleton; treat it as the standard and keep new
sections consistent with it:

- **Wrapper + placeholder come from [components/equity/section.tsx](components/equity/section.tsx)** —
  `Card` (the `.panel p-5` surface every section sits in) and `Empty` (the centered, muted
  loading/empty/unavailable placeholder). **Reuse these; don't re-declare a local `Card`/`Empty`.**
  They were previously copy-pasted per file and drifted (mismatched placeholder heights) — the shared
  module exists to prevent exactly that.
- **Each section defines a local `Header`** (title + `symbol` + sector badge + any controls). Header
  *content* is component-specific, but every section has one and renders it in its empty states too.
- **Data via `useEquityData()`, which may be `null`.** Two-tier empty handling, both inside
  `Card` + `Empty`: payload null → `"<Thing> data is currently unavailable."`; present-but-no-rows →
  `"No <thing> available for {symbol}."`.
- **Windowed sections fall back to the first available window rather than landing on empty.** When a
  section's data is split into selectable windows that may individually be absent (the distribution
  chart's lookbacks are the first case), keep the user's selected window if it has data, otherwise
  show the first (narrowest) window that does, and disable the empty windows in the toggle. Only fall
  through to the per-section `Empty` when *no* window has data. This keeps a default like `1Y` from
  showing empty when `5Y/MAX` would populate — the intended UX precedent for windowed sections.
- **Page-level fallback** when the *whole* payload is null is a separate component,
  [components/equity/equity_unavailable.tsx](components/equity/equity_unavailable.tsx) (rendered by
  [pages/Ticker.tsx](pages/Ticker.tsx) in place of the section stack) — not the per-section `Empty`.
- **Colors:** chart/graph colors stay as local literals per component (canvas can't read CSS vars);
  shared UI colors live in [app.css](app.css).

These are **major design choices meant to be standard across the section components.** When you change
one (a shared primitive, the empty-state contract, the header pattern), apply it to all four rather
than letting one diverge.

**What's available via `useEquityData()`** (`EquitiesPayload` from [utils/database.ts](utils/database.ts)):

| Field | Shape | What it is |
|---|---|---|
| `security` | `SecurityMeta?` | Company name + GICS sector/industry for the page header (resolved from `securities`; present whenever the payload is) |
| `price_history` | `PriceRecord[]` | Full available OHLCV history per security (paginated; ~12y for older listings) — source for the price-history chart (range selector filters client-side) |
| `volatility_history` | `VolatilityRecord[]` | ~5 years of vol/IV term structures, VRP wedge, forecast features (full column list in `backend/CLAUDE.md`) |
| `options_chain` | `OptionRecord[]` | Latest snapshot — strike/expiry/type + bid/ask/iv/delta |
| `ai_overview` | `AIOverview \| null` | Latest unflagged AI commentary, or null |
| `latest_shap_snapshot` | `SHAPSnapshot[]` | SHAP feature attributions per horizon |
| `events` | `EventRecord[]` | Per-security events (full history) — drawn as event-annotation lines on the price chart |
| `distribution_data` | `DistributionSet[]?` | Live (stock scope) — per `(metric, lookback)` RV/IV/VRP histograms computed in-Python from `volatility_history` (lookbacks `3M/6M/YTD/1Y/2Y/5Y/MAX`; undersized combos omitted). Drives the Historical Distribution chart, which toggles metric/lookback/scope client-side and falls back to the first available window. Sector/market deferred. See `backend/CLAUDE.md` |

The DB call is non-fatal; consumers **must handle `useEquityData()` returning `null`**.

### Planned — two-phase (progressive) loading for time-series panels

**Not implemented; captured for a future latency pass.** Today the loader awaits the whole
composite `/api/equity/:symbol` before first paint (~1.4 MB for AAPL: ~1 MB `volatility_history`
+ ~0.5 MB full `price_history`), even though each time-based component initially shows only its
default window (the price chart's 1Y is ~50–100 KB). Goal: **await a small "core", stream the
"rest."** React Router v7 has native deferred/streaming loaders, so this needs no new deps.

- **Backend:** make the time-series queries window-aware via a `range` (or `from`/`to`) param on
  `/api/equity/:symbol`. `range=1Y` → default-window slices (the *core*); `range=max` → full
  history (today's behavior, the *rest*). Touches `main.py` + `database.py` only.
- **Loader** ([routes/ticker.tsx](routes/ticker.tsx)): `await` the core fetch (blocks SSR/first
  paint, small) and return the full fetch as an **un-awaited promise** so React Router streams it
  after the shell — `return { core: await load(symbol, {range:"1Y"}), full: load(symbol, {range:"max"}) }`.
- **Context/components:** `EquityDataProvider` holds `{ core, full }` (`full` a promise). A shared
  hook — e.g. `useEquitySeries(section, range)` — returns the core slice synchronously when the
  requested `range` fits the core window, else resolves from `full` (already streaming; brief
  loading state until it lands). One contract for every time-based component: **default range =
  instant from core; longer ranges = from the streamed full set.** The awaited core window = the
  union of the above-the-fold components' default ranges.

Tradeoffs: two requests (slightly more total bytes if `full` is always prefetched), but the
blocking first-paint payload drops ~15–25×; queries must accept a window; needs a "full not here
yet" state for an early MAX click; real added loader/context complexity. Composes with column
projection (the core call can be windowed *and* projected → tiny). Lighter variant: await core
only and have each component background-`fetch` its full history after mount (simpler state, loses
SSR streaming). The price-history chart would be the reference implementation that establishes the
`useEquitySeries` contract.

## Utils & API client

- [utils/database.ts](utils/database.ts) — **canonical** equity spec and the only data-fetch util.
  Row interfaces mirror the Supabase tables (see `supabase/database_SQL_defs.sql`); `loadEquityData()`
  fetches `/api/equity/:symbol` and `loadEquityList()` fetches `/api/equities` (the ticker-search
  list). Numeric columns nullable in the DB are typed `… | null`. (The legacy `utils/tickers.ts`
  file-backed loaders were removed in the file-data cleanup, issue #83.)
- **`API_BASE_URL` is hardcoded** as `http://localhost:8000/api` in `utils/database.ts`. It must
  become env-driven for stg/prod — see `backend/CLAUDE.md` (Environments + Deployment).
- [supabaseClient.ts](supabaseClient.ts) — `@supabase/supabase-js` client. **Used only for auth**
  (`ProtectedLayout` calls `supabase.auth.getUser()`). Equity/data flow goes through the FastAPI
  backend, not directly to Supabase from the browser.

## Environments

Same single repo-root `.env` as the backend; Vite reads `VITE_SUPABASE_URL` /
`VITE_SUPABASE_PUBLISHABLE_KEY` (with `VITE_SUPABASE_ANON_KEY` as fallback). The dev/stg/prod
model and the planned Vite-mode + `.env.{development,staging,production}` config are documented
in `backend/CLAUDE.md` — not yet implemented.

## Conventions

- `routes/<name>.tsx` co-locates the loader and re-exports the page component as default.
  Keeps data loading next to the route declaration without bloating the page component.
- Page-scoped UI lives under `app/components/<area>/`; shared UI lives under `app/components/ui/`.
- Redesigned components share primitives in [app.css](app.css): `.panel` (card surface),
  `.segmented`/`.segmented-btn` (toggle groups), `.badge`/`.badge-sector`/`.badge-neutral`, plus
  `--text-*` / `--pos` / `--neg` / `--panel-border` tokens (with dark-mode variants). Rule of
  thumb: **shared UI colors → `app.css`; chart/graph-specific colors → local consts in the
  component** (canvas can't read CSS vars).
- Loader data is typed at the page boundary via `useLoaderData() as <T>` (e.g. `TickerLoaderData`
  exported from the route module). The codebase doesn't currently use React Router's generated
  `Route.LoaderData` types — keep that consistent unless migrating intentionally.