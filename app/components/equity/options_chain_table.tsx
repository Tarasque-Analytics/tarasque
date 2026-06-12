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
  rowsFor: (expiryISO: string) => Row[]; // per-strike pivot for one expiry, sorted by strike asc
};

const toLeg = (o: OptionRecord): Leg => ({
  bid: o.bid,
  ask: o.ask,
  mid: o.mid,
  iv: o.iv,
  delta: o.delta,
  oi: o.open_interest,
  vol: o.volume,
});

// Pivot a single snapshot's contracts into the view model.
function viewFromContracts(
  spot: number,
  snapshotISO: string,
  contracts: OptionRecord[],
): ChainView | null {
  if (!contracts.length) return null;

  const expiries: Expiry[] = Array.from(new Set(contracts.map((o) => o.expiry)))
    .map((iso) => ({ iso, dte: Math.max(0, dayDiff(iso, snapshotISO)) }))
    .sort((a, b) => a.dte - b.dte);
  if (!expiries.length) return null;

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
    rowsFor,
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
  return viewFromContracts(spot, snapshotISO, snap);
}

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
  // Real data only — null when there's no spot or no contracts; the component renders an empty state.
  const view = useMemo(() => buildView(equity), [equity]);

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

  // Surface the concrete selected expiry (date + DTE) in the subtitle — the segmented buttons only
  // carry the DTE, so this keeps the full expiry date visible (mirrors contract_skew_chart.tsx).
  const selExpiry = view.expiries.find((e) => e.iso === selected);
  const subtitle = selExpiry
    ? `Listed contracts · expiry ${expiryLabel(selExpiry.iso)} (${selExpiry.dte}d) · sorted by strike`
    : "Listed contracts · sorted by strike";

  return (
    <Card>
      <Header
        symbol={equity?.symbol}
        sec={equity?.security}
        subtitle={subtitle}
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

/* ── header: title · symbol · sector badge · subtitle · expiry selector ── */
function Header({
  symbol,
  sec,
  subtitle,
  expiries,
  selected,
  onSelect,
}: {
  symbol?: string;
  sec?: SecurityMeta;
  subtitle?: string;
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
        </div>
        {subtitle && <p className="mt-0.5 text-sm text-(--text-muted)">{subtitle}</p>}
      </div>

      {expiries && expiries.length > 1 && onSelect && (
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold tracking-wide text-(--text-muted) uppercase">
            Expiry
          </span>
          {/* segmented DTE selector (mirrors contract_skew_chart.tsx); buttons labeled by DTE */}
          <div className="segmented">
            {expiries.map((e) => (
              <button
                key={e.iso}
                type="button"
                className="segmented-btn"
                data-active={selected === e.iso}
                onClick={() => onSelect(e.iso)}
              >
                {e.dte}d
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
