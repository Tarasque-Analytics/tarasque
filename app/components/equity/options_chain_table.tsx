import { useMemo, useState } from "react";
import type { ReactNode } from "react";
import { useEquityData } from "~/context/EquityDataContext";
import type {
  EquitiesPayload,
  OptionRecord,
  PriceRecord,
  SecurityMeta,
} from "~/utils/database";

/**
 * Options Chain table for /equity/:symbol — the standard CALLS | STRIKE | PUTS ladder for one
 * expiry at a time, sorted by strike. Reads useEquityData() end-to-end (loader →
 * EquityDataContext → component); useEquityData() may be null (DB call is non-fatal).
 *
 * Shares its data source with the contract/skew chart (useEquityData().options_chain). Where the
 * skew chart shows OTM-only contracts, this table shows the FULL strike ladder (ITM + OTM, both
 * legs per strike) — do not port the skew chart's OTM filter here.
 *
 * TODO (post-merge, coordinated with contract_skew_chart.tsx): the small helpers below — dayDiff
 * (DTE), latest-snapshot pick, distinct-expiry list, spot = latest non-null close — are duplicated
 * in both components by design (the two were built on parallel branches). Once both land, lift them
 * into a shared app/utils/options.ts and have both components import it. Kept inline for now so the
 * branches stay independent.
 */

/* ── component-specific colors (shared UI colors live in app.css; this amber row tint is specific
   to the chain table). Low-alpha so it layers over both light and dark surfaces. ── */
const ATM_TINT = "rgba(234, 179, 8, 0.10)"; // shaded ATM (nearest-strike) row — translucent yellow
// Row hover is a neutral off-white gray, a touch darker than the even-row stripe — applied as a
// Tailwind arbitrary class on each row: hover:bg-black/[0.04] (dark: white/[0.045]).

/* ── formatters (kept local; mirrors price/skew chart conventions) ── */
const DASH = "—";
const pctIV = (n: number | null | undefined) => (n == null ? DASH : `${(n * 100).toFixed(1)}%`);
const price2 = (n: number | null | undefined) => (n == null ? DASH : n.toFixed(2));
const delta2 = (n: number | null | undefined) => (n == null ? DASH : n.toFixed(2));
const intSep = (n: number | null | undefined) =>
  n == null ? DASH : n.toLocaleString("en-US", { maximumFractionDigits: 0 });
const strikeFmt = (k: number) => `$${k.toLocaleString("en-US", { maximumFractionDigits: 2 })}`;

const parseDay = (iso: string) => new Date(`${iso}T00:00:00`);
const expiryLabel = (iso: string) =>
  parseDay(iso).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
// Date-only ISO strings parse as UTC midnight, so the difference is always a whole-day multiple.
const dayDiff = (aISO: string, bISO: string) =>
  Math.round((Date.parse(aISO) - Date.parse(bISO)) / 86_400_000);

/* ── view model ── */
type Leg = {
  bid: number | null;
  ask: number | null;
  mid: number | null;
  iv: number | null;
  delta: number | null;
  oi: number | null;
  vol: number | null;
};
type Row = { strike: number; call: Leg | null; put: Leg | null };
type Expiry = { iso: string; dte: number };
type ChainView = {
  spot: number;
  snapshotISO: string;
  expiries: Expiry[]; // sorted by DTE asc; [0] = nearest expiry (the default)
  dteMin: number;
  dteMax: number;
  rowsFor: (expiryISO: string) => Row[]; // per-strike pivot for one expiry, sorted by strike asc
  isMock: boolean;
};

// Only the fields the table needs — lets the dev fixture supply plain objects without faking
// id/security_id/last.
type ContractLite = Pick<
  OptionRecord,
  "expiry" | "option_type" | "strike" | "bid" | "ask" | "mid" | "iv" | "delta" | "open_interest" | "volume"
>;

const toLeg = (o: ContractLite): Leg => ({
  bid: o.bid,
  ask: o.ask,
  mid: o.mid,
  iv: o.iv,
  delta: o.delta,
  oi: o.open_interest,
  vol: o.volume,
});

// Pivot a single snapshot's contracts into the view model. Shared by live data and the dev fixture.
function viewFromContracts(
  spot: number,
  snapshotISO: string,
  contracts: ContractLite[],
  isMock: boolean,
): ChainView | null {
  if (!contracts.length) return null;

  const expiries: Expiry[] = Array.from(new Set(contracts.map((o) => o.expiry)))
    .map((iso) => ({ iso, dte: Math.max(0, dayDiff(iso, snapshotISO)) }))
    .sort((a, b) => a.dte - b.dte);
  if (!expiries.length) return null;

  const dtes = expiries.map((e) => e.dte);

  const rowsFor = (expiryISO: string): Row[] => {
    const byStrike = new Map<number, Row>();
    for (const o of contracts) {
      if (o.expiry !== expiryISO) continue;
      let row = byStrike.get(o.strike);
      if (!row) {
        row = { strike: o.strike, call: null, put: null };
        byStrike.set(o.strike, row);
      }
      if (o.option_type === "C") row.call = toLeg(o);
      else row.put = toLeg(o);
    }
    return Array.from(byStrike.values()).sort((a, b) => a.strike - b.strike);
  };

  return {
    spot,
    snapshotISO,
    expiries,
    dteMin: Math.min(...dtes),
    dteMax: Math.max(...dtes),
    rowsFor,
    isMock,
  };
}

// Build the view from live payload data, or null if nothing is plottable (no spot / no contracts).
function buildView(equity: EquitiesPayload | null): ChainView | null {
  if (!equity) return null;

  const closes = (equity.price_history ?? []).filter((p: PriceRecord) => p.close != null);
  const spot = closes.length ? (closes[closes.length - 1].close as number) : null;
  if (spot == null) return null;

  const chain = equity.options_chain ?? [];
  if (!chain.length) return null;

  // Payload is the "latest snapshot", but guard against mixed snapshot_dates by keeping the newest.
  const snapshotISO = chain.reduce(
    (m, o) => (o.snapshot_date > m ? o.snapshot_date : m),
    chain[0].snapshot_date,
  );
  const snap = chain.filter((o) => o.snapshot_date === snapshotISO);
  return viewFromContracts(spot, snapshotISO, snap, false);
}

/* ── dev fixture ──
   options_chain is empty across the hosted DB (0 rows for every ticker — same wall the skew chart
   hit), so this synthesizes a realistic multi-expiry chain (Black–Scholes prices/deltas, a
   downside-skewed IV smile, an OI/VOL bell around ATM) to develop the table against. Deterministic
   (no Date.now()/Math.random()) so SSR and client agree. Used ONLY in dev (import.meta.env.DEV)
   AND only when live data is absent — production renders the real empty state, never this.
   TODO (before deploy): remove this fixture / the IS_DEV fallback once the options feed is
   populated. Test data should live in the Supabase seed / migrations, not here. */
const IS_DEV = Boolean(import.meta.env?.DEV);

// Standard normal CDF (Abramowitz & Stegun 7.1.26) — for the fixture's BS prices/deltas only.
const Phi = (x: number) => {
  const t = 1 / (1 + 0.2316419 * Math.abs(x));
  const d = 0.3989422804014327 * Math.exp((-x * x) / 2);
  const p =
    d * t * (0.31938153 + t * (-0.356563782 + t * (1.781477937 + t * (-1.821255978 + t * 1.330274429))));
  return x >= 0 ? 1 - p : p;
};

// TZ-safe whole-day add: parse + emit in UTC so the result is identical on server and client.
const addDays = (iso: string, n: number) => {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
};

function makeMock(): { spot: number; snapshotISO: string; contracts: ContractLite[] } {
  const spot = 177.01; // matches the skew-chart fixture and the design-mockup ladder
  const snapshotISO = "2026-05-29";
  const dteList = [30, 60, 90, 120];
  const contracts: ContractLite[] = [];

  for (let di = 0; di < dteList.length; di++) {
    const dte = dteList[di];
    const expiry = addDays(snapshotISO, dte);
    const t = dte / 365;
    for (let k = 150; k <= 207.5; k += 2.5) {
      const m = (k - spot) / spot; // moneyness
      // Downside-skewed smile with a mild term-structure tilt.
      const iv = Math.min(0.5, Math.max(0.18, 0.225 + 0.9 * m * m - 0.18 * m - 0.02 * (t - 0.16)));
      const srt = iv * Math.sqrt(t);
      const d1 = (Math.log(spot / k) + 0.5 * iv * iv * t) / srt;
      const d2 = d1 - srt;
      const bell = Math.exp(-((m / 0.07) ** 2) / 2);
      const scale = 1 - 0.12 * di; // nearer expiries carry more open interest
      for (const type of ["C", "P"] as const) {
        const px = type === "C" ? spot * Phi(d1) - k * Phi(d2) : k * Phi(-d2) - spot * Phi(-d1);
        const mid = Math.max(0.05, Math.round(px * 100) / 100);
        const half = Math.min(0.3, Math.max(0.005, mid * 0.02));
        const bid = Math.max(0.05, Math.round((mid - half) * 100) / 100);
        const ask = Math.round((bid + Math.max(0.01, half * 2)) * 100) / 100;
        const delta = type === "C" ? Phi(d1) : Phi(d1) - 1;
        contracts.push({
          expiry,
          option_type: type,
          strike: Math.round(k * 100) / 100,
          bid,
          ask,
          mid,
          iv: Math.round(iv * 1e4) / 1e4,
          delta: Math.round(delta * 100) / 100,
          open_interest: Math.round(300 + 24000 * bell * scale),
          volume: Math.round(40 + 8000 * bell * bell * scale),
        });
      }
    }
  }
  return { spot, snapshotISO, contracts };
}
const MOCK = makeMock();
const MOCK_VIEW = viewFromContracts(MOCK.spot, MOCK.snapshotISO, MOCK.contracts, true);

/* ── gradient de-emphasis ──
   Low-value contracts (near-zero premium / far OTM) fade toward gray; valuable contracts (ATM and
   ITM, where premium is large) stay full strength. Keyed on premium relative to spot so it scales
   across tickers. Returns a per-leg opacity in [0.4, 1]. */
const LOW_R = 0.0006; // prem/spot at/below which a leg is fully faded
const HIGH_R = 0.005; // prem/spot at/above which a leg is full strength
const legOpacity = (leg: Leg | null, spot: number) => {
  if (!leg) return 1;
  const prem =
    leg.mid ?? (leg.bid != null && leg.ask != null ? (leg.bid + leg.ask) / 2 : leg.bid ?? 0);
  const e = Math.min(1, Math.max(0, (prem / spot - LOW_R) / (HIGH_R - LOW_R)));
  return 0.4 + 0.6 * e;
};

function Card({ children }: { children: ReactNode }) {
  return <div className="panel p-5">{children}</div>;
}

export default function OptionsChainTable() {
  const equity = useEquityData();
  const live = useMemo(() => buildView(equity), [equity]);
  // In dev, fall back to the fixture whenever there's no live view (even with the DB down) so the
  // table can be developed without an options feed. Production (IS_DEV false) shows real empty states.
  const view = live ?? (IS_DEV ? MOCK_VIEW : null);

  // Selected expiry: default to the nearest (expiries[0], sorted by DTE asc). Self-heals if the
  // previously-picked expiry isn't present in the current view.
  const [picked, setPicked] = useState<string | null>(null);
  const selected =
    view && picked && view.expiries.some((e) => e.iso === picked) ? picked : view?.expiries[0]?.iso ?? "";

  const rows = useMemo<Row[]>(
    () => (view && selected ? view.rowsFor(selected) : []),
    [view, selected],
  );

  // ATM = strike nearest spot.
  const atmStrike = useMemo<number | null>(() => {
    if (!view || !rows.length) return null;
    let best = rows[0].strike;
    let bestGap = Infinity;
    for (const r of rows) {
      const gap = Math.abs(r.strike - view.spot);
      if (gap < bestGap) {
        bestGap = gap;
        best = r.strike;
      }
    }
    return best;
  }, [view, rows]);

  if (!view) {
    return (
      <Card>
        <Header symbol={equity?.symbol} sec={equity?.security} />
        <div className="flex h-64 items-center justify-center text-sm text-(--text-secondary)">
          {equity
            ? `No options chain available for ${equity.symbol}.`
            : "Options data is currently unavailable."}
        </div>
      </Card>
    );
  }

  const dteRange =
    view.dteMin === view.dteMax ? `${view.dteMin} DTE` : `${view.dteMin}–${view.dteMax} DTE`;

  return (
    <Card>
      <Header
        symbol={equity?.symbol}
        sec={equity?.security}
        subtitle={`Listed contracts · ${dteRange} · sorted by strike`}
        isMock={view.isMock}
        expiries={view.expiries}
        selected={selected}
        onSelect={setPicked}
      />

      <div className="mt-4 overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <thead>
            {/* group headers: CALLS (green) | STRIKE | PUTS (red) */}
            <tr className="border-b border-(--panel-border)">
              <th
                colSpan={6}
                className="px-2 pb-1 text-left text-xs font-semibold tracking-wide text-(--pos)"
              >
                CALLS
              </th>
              <th className="border-x border-(--panel-border) px-3 pb-1 text-center text-xs font-semibold tracking-wide text-(--text-muted)">
                STRIKE
              </th>
              <th
                colSpan={6}
                className="px-2 pb-1 text-right text-xs font-semibold tracking-wide text-(--neg)"
              >
                PUTS
              </th>
            </tr>
            {/* column labels */}
            <tr className="border-b border-(--panel-border) text-[11px] font-medium text-(--text-muted)">
              {(["Δ", "OI", "VOL", "IV", "BID", "ASK"] as const).map((h) => (
                <th key={`c-${h}`} className="px-2 py-1.5 text-right font-medium">
                  {h}
                </th>
              ))}
              <th className="border-x border-(--panel-border) px-3 py-1.5 text-center font-medium">$</th>
              {(["BID", "ASK", "IV", "VOL", "OI", "Δ"] as const).map((h) => (
                <th key={`p-${h}`} className="px-2 py-1.5 text-right font-medium">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const isAtm = row.strike === atmStrike;
              const callOp = legOpacity(row.call, view.spot);
              const putOp = legOpacity(row.put, view.spot);
              const rowCls = isAtm
                ? ""
                : "even:bg-black/[0.018] dark:even:bg-white/[0.02] hover:bg-black/[0.04] dark:hover:bg-white/[0.045]";
              return (
                <tr
                  key={row.strike}
                  className={rowCls}
                  style={isAtm ? { background: ATM_TINT } : undefined}
                >
                  {/* CALLS: Δ | OI | VOL | IV | BID | ASK */}
                  <Num v={delta2(row.call?.delta)} muted op={callOp} />
                  <Num v={intSep(row.call?.oi)} muted op={callOp} />
                  <Num v={intSep(row.call?.vol)} muted op={callOp} />
                  <Num v={pctIV(row.call?.iv)} muted op={callOp} />
                  <Num v={price2(row.call?.bid)} op={callOp} />
                  <Num v={price2(row.call?.ask)} op={callOp} />

                  {/* STRIKE */}
                  <td className="border-x border-(--panel-border) px-3 py-1.5 text-center font-semibold tabular-nums text-(--text-primary)">
                    {strikeFmt(row.strike)}
                  </td>

                  {/* PUTS: BID | ASK | IV | VOL | OI | Δ */}
                  <Num v={price2(row.put?.bid)} op={putOp} />
                  <Num v={price2(row.put?.ask)} op={putOp} />
                  <Num v={pctIV(row.put?.iv)} muted op={putOp} />
                  <Num v={intSep(row.put?.vol)} muted op={putOp} />
                  <Num v={intSep(row.put?.oi)} muted op={putOp} />
                  <Num v={delta2(row.put?.delta)} muted op={putOp} />
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

/* ── one numeric cell. BID/ASK render bold/primary; greeks (muted) render lighter. The per-leg
   opacity layers the gradient de-emphasis on top. ── */
function Num({ v, muted, op }: { v: ReactNode; muted?: boolean; op: number }) {
  return (
    <td
      className={`px-2 py-1.5 text-right tabular-nums ${
        muted ? "text-(--text-secondary)" : "font-semibold text-(--text-primary)"
      }`}
      style={{ opacity: op }}
    >
      {v}
    </td>
  );
}

/* ── header: title · symbol · sector badge · subtitle · expiry dropdown ── */
function Header({
  symbol,
  sec,
  subtitle,
  isMock,
  expiries,
  selected,
  onSelect,
}: {
  symbol?: string;
  sec?: SecurityMeta;
  subtitle?: string;
  isMock?: boolean;
  expiries?: Expiry[];
  selected?: string;
  onSelect?: (iso: string) => void;
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <div className="flex flex-wrap items-center gap-x-2">
          <h2 className="text-2xl font-bold tracking-tight text-(--text-primary)">Options Chain</h2>
          {symbol && <span className="text-lg font-semibold text-(--text-muted)">{symbol}</span>}
          {sec?.gics_sector && <span className="badge badge-sector">{sec.gics_sector}</span>}
          {isMock && <span className="badge badge-neutral">sample data</span>}
        </div>
        {subtitle && <p className="mt-0.5 text-sm text-(--text-muted)">{subtitle}</p>}
      </div>

      {expiries && expiries.length > 0 && (
        <label className="flex items-center gap-2 text-xs font-medium text-(--text-muted)">
          Expiry
          <select
            aria-label="Select expiry"
            value={selected}
            onChange={(e) => onSelect?.(e.target.value)}
            className="rounded-md border border-(--panel-border) bg-(--ui-background) px-2.5 py-1.5 text-xs font-medium text-(--text-primary)"
          >
            {expiries.map((e) => (
              <option key={e.iso} value={e.iso}>
                {expiryLabel(e.iso)} · {e.dte} DTE
              </option>
            ))}
          </select>
        </label>
      )}
    </div>
  );
}
