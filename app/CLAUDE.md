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
- `app/components/<area>/<name>.tsx` — UI grouped by page area (`ticker/`, `dashboard/`, `ui/`).
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

**Current priority — the price-history chart.** Build it as the first new component on
`/equity/:symbol`. It validates the full data pipeline end-to-end on real DB data
(loader → `EquityDataContext` → component, reading `useEquityData().price_history`) and seeds
the pattern subsequent components will follow. While building it, confirm the available-tickers
flow too: `getAvailableTickers()` → `GET /api/tickers` feeds ticker search/selection and should
be exercised alongside.

**What's available via `useEquityData()`** (`EquitiesPayload` from [utils/database.ts](utils/database.ts)):

| Field | Shape | What it is |
|---|---|---|
| `price_history` | `PriceRecord[]` | Full available OHLCV history per security (paginated; ~12y for older listings) — source for the price-history chart (range selector filters client-side) |
| `volatility_history` | `VolatilityRecord[]` | ~5 years of vol/IV term structures, VRP wedge, forecast features (full column list in `backend/CLAUDE.md`) |
| `options_chain` | `OptionRecord[]` | Latest snapshot — strike/expiry/type + bid/ask/iv/delta |
| `ai_overview` | `AIOverview \| null` | Latest unflagged AI commentary, or null |
| `latest_shap_snapshot` | `SHAPSnapshot[]` | SHAP feature attributions per horizon |
| `events` | `EventRecord[]` | Per-security events from the past year |
| `distribution_data` | `DistributionBin[]?` | Currently disabled — see `backend/CLAUDE.md` |

The DB call is non-fatal; consumers **must handle `useEquityData()` returning `null`**.

The legacy file payload (`useTickerData()` / `loadTickerPayload` / `TickerDataContext`) is still
wired into the loader for the old components. As new components stop reading it, retire the
file-payload path entirely — including the `/api/tickers/:symbol` endpoint, the dual-fetch in
the route loader, and `TickerDataContext`.

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
- Loader data is typed at the page boundary via `useLoaderData() as <T>` (e.g. `TickerLoaderData`
  exported from the route module). The codebase doesn't currently use React Router's generated
  `Route.LoaderData` types — keep that consistent unless migrating intentionally.