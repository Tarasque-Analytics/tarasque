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

1. **Loader** ([routes/ticker.tsx](routes/ticker.tsx)) fetches **both** payloads in parallel via
   `Promise.allSettled`:
   - `loadTickerPayload(symbol)` → `GET /api/tickers/:symbol` (legacy file payload).
     **Required** — loader throws a 404 Response if it fails.
   - `loadEquityData(symbol)` → `GET /api/equity/:symbol` (Supabase-backed). **Non-fatal** —
     falls back to `null` so the page still renders if the DB call is down.
2. **Page** ([pages/Ticker.tsx](pages/Ticker.tsx)) reads `useLoaderData()` and wraps children in
   **both** providers: `TickerDataProvider` (file) and `EquityDataProvider` (DB).
3. **Components** consume whichever provider has what they need:
   - `useTickerData()` → parsed file payload (`meta` / `hedging` / `explainability` /
     `monteCarloData` / `opportunities`). Throws if used outside its provider.
   - `useEquityData()` → `EquitiesPayload | null`. Consumers **must handle `null`** (DB call may
     have failed).

## Equity page — redesign in progress

The four existing `/equity/:symbol` ticker components ([Attributes](components/ticker/attributes.tsx),
[Options](components/ticker/options.tsx), [Predictors](components/ticker/predictors.tsx),
[MonteCarlo](components/ticker/monte_carlo.tsx)) are slated for **near-complete rewrite** as part
of a design pivot. Treat them as legacy to be replaced — **don't** anchor on them for structure,
style, or content; new components follow new designs. The data-flow scaffolding above (loader,
providers, hooks) stays as-is.

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
in `app/app.css`. `getAvailableTickers()` → `GET /api/tickers` feeds ticker search/selection
(the search box navigates to `/equity/:symbol`).

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
| `distribution_data` | `DistributionBin[]?` | Currently disabled — see `backend/CLAUDE.md` |

The DB call is non-fatal; consumers **must handle `useEquityData()` returning `null`**.

The legacy file payload (`useTickerData()` / `loadTickerPayload` / `TickerDataContext`) is still
wired into the loader for the old components. As new components stop reading it, retire the
file-payload path entirely — including the `/api/tickers/:symbol` endpoint, the dual-fetch in
the route loader, and `TickerDataContext`.

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

- [utils/database.ts](utils/database.ts) — **canonical** equity spec. Row interfaces mirror the
  Supabase tables (see `supabase/database_SQL_defs.sql`); `loadEquityData()` fetches
  `/api/equity/:symbol`. Numeric columns nullable in the DB are typed `… | null`.
- [utils/tickers.ts](utils/tickers.ts) — legacy file-backed loaders only: `getAvailableTickers`,
  `loadTickerPayload`. (The equity types previously duplicated here were removed — `database.ts`
  is canonical.)
- **`API_BASE_URL` is hardcoded** as `http://localhost:8000/api` in both utils files. It must
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