import { useMemo, useState } from "react";
import { Chart as ChartJS, LinearScale, PointElement, BubbleController, Tooltip } from "chart.js";
import type { ChartData, ChartOptions, ChartType, Plugin, Scale } from "chart.js";
import { Chart } from "react-chartjs-2";
import { useEquityData } from "~/context/EquityDataContext";
import type {
  EquitiesPayload,
  OptionRecord,
  PriceRecord,
  VolatilityRecord,
  SecurityMeta,
} from "~/utils/database";
import { Card, Empty } from "./section";

ChartJS.register(LinearScale, PointElement, BubbleController, Tooltip);

/* ── graph-specific palette (kept local to this chart; shared UI colors live in app.css) ──
   Canvas can't resolve CSS vars, so these are literals (same rule the price chart follows). */
const PUT_FILL = "rgba(226, 87, 79, 0.55)";
const PUT_BORDER = "rgba(200, 60, 52, 0.95)";
const CALL_FILL = "rgba(70, 169, 106, 0.55)";
const CALL_BORDER = "rgba(45, 140, 82, 0.95)";
const SMILE = "rgba(47, 111, 237, 0.75)"; // dashed implied-smile polyline
const SPOT_LINE = "#5b6470"; // dashed vertical spot marker
const IV_FILL = "rgba(176, 141, 62, 0.10)"; // gold — market IV expected-move band
const IV_EDGE = "rgba(176, 141, 62, 0.85)";
const RV_FILL = "rgba(31, 130, 120, 0.16)"; // teal — realized-vol expected-move band
const RV_EDGE = "rgba(20, 120, 110, 0.9)";
const PREMIUM_FILL = "rgba(176, 141, 62, 0.22)"; // the IV−RV rim = VRP premium
const GRID = "rgba(0, 0, 0, 0.05)";
const AXIS_TEXT = "#9ca3af"; // mirrors --text-muted (light) as a literal
const DOWNSIDE_LABEL = "#c0392b";
const UPSIDE_LABEL = "#2e8b57";

// Bubble radius range (px). 0-OI contracts stay visible at MIN_R; OI is sqrt-scaled to MAX_R so a
// few huge-OI strikes don't swamp the plot.
const MIN_R = 3;
const MAX_R = 18;

// Band horizon scaling. Per the spec's band width decision, edges are the LITERAL spot ± vol·spot
// (annualized vol applied directly — no horizon scaling). To switch to a DTE-scaled ±1σ expected
// move (matches the mockup's narrow bands), make this return Math.sqrt(dte / 252).
const bandScale = (_dte: number) => 1;

/* ── skew-bands plugin ──
   Draws the spot line, the two expected-move bands (gold IV, teal RV), the premium rim between
   them, the dashed implied-smile polyline, and the corner labels. It reads everything from
   chart.options (which react-chartjs-2 refreshes each render) rather than a closure — an inline
   closure goes stale and redraws the previous render's values. Module-level + stable, same pattern
   as the price chart's event-marker plugin. */
type SkewBands = {
  spot: number;
  spotLabel: string;
  iv?: { low: number; high: number } | null;
  rv?: { low: number; high: number } | null;
  smile: { strike: number; iv: number }[];
};

declare module "chart.js" {
  // `TType` must match chart.js's generic for declaration merging — intentionally unused here.
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  interface PluginOptionsByType<TType extends ChartType> {
    skewBands?: SkewBands;
  }
}

const fillBand = (
  ctx: CanvasRenderingContext2D,
  x: Scale,
  top: number,
  bottom: number,
  lo: number,
  hi: number,
  color: string,
) => {
  // Normalize endpoints so an inverted band (e.g. RV wider than IV, when premium is negative) still
  // fills correctly, and skip degenerate slivers.
  const xl = Math.min(x.getPixelForValue(lo), x.getPixelForValue(hi));
  const xh = Math.max(x.getPixelForValue(lo), x.getPixelForValue(hi));
  if (xh - xl < 0.5) return;
  ctx.fillStyle = color;
  ctx.fillRect(xl, top, xh - xl, bottom - top);
};

const vLine = (
  ctx: CanvasRenderingContext2D,
  x: Scale,
  top: number,
  bottom: number,
  at: number,
  color: string,
  dash: number[],
) => {
  const px = x.getPixelForValue(at);
  ctx.beginPath();
  ctx.setLineDash(dash);
  ctx.moveTo(px, top);
  ctx.lineTo(px, bottom);
  ctx.strokeStyle = color;
  ctx.lineWidth = 1.25;
  ctx.stroke();
  ctx.setLineDash([]);
};

const skewBandsPlugin: Plugin<"bubble"> = {
  id: "skewBands",
  beforeDatasetsDraw(chart) {
    // chart.options is deeply partial in chart.js's types; we always write a full SkewBands.
    const o = chart.options.plugins?.skewBands as SkewBands | undefined;
    if (!o) return;
    const { ctx, chartArea, scales } = chart;
    const x = scales.x;
    const y = scales.y;
    if (!x || !y) return;
    const { top, bottom, left, right } = chartArea;
    ctx.save();
    // Clip to the plot area so a band edge / line that runs past the x-range can't paint over the
    // axes or tick labels.
    ctx.beginPath();
    ctx.rect(left, top, right - left, bottom - top);
    ctx.clip();

    // Bands, painted widest-first so overlaps read correctly:
    //   gold IV interior → gold premium rims (IV outside RV) → teal RV interior on top.
    if (o.iv) {
      fillBand(ctx, x, top, bottom, o.iv.low, o.iv.high, IV_FILL);
      if (o.rv) {
        fillBand(ctx, x, top, bottom, o.iv.low, o.rv.low, PREMIUM_FILL);
        fillBand(ctx, x, top, bottom, o.rv.high, o.iv.high, PREMIUM_FILL);
      }
    }
    if (o.rv) fillBand(ctx, x, top, bottom, o.rv.low, o.rv.high, RV_FILL);

    // Edge lines: teal solid for RV, gold dashed for IV.
    if (o.rv) {
      vLine(ctx, x, top, bottom, o.rv.low, RV_EDGE, []);
      vLine(ctx, x, top, bottom, o.rv.high, RV_EDGE, []);
    }
    if (o.iv) {
      vLine(ctx, x, top, bottom, o.iv.low, IV_EDGE, [5, 4]);
      vLine(ctx, x, top, bottom, o.iv.high, IV_EDGE, [5, 4]);
    }

    // Spot line.
    vLine(ctx, x, top, bottom, o.spot, SPOT_LINE, [5, 5]);

    // Dashed implied-smile polyline through the bubble IVs (drawn behind the bubbles).
    if (o.smile.length > 1) {
      ctx.beginPath();
      ctx.setLineDash([4, 4]);
      ctx.lineWidth = 1.25;
      ctx.strokeStyle = SMILE;
      o.smile.forEach((p, i) => {
        const px = x.getPixelForValue(p.strike);
        const py = y.getPixelForValue(p.iv);
        if (i === 0) ctx.moveTo(px, py);
        else ctx.lineTo(px, py);
      });
      ctx.stroke();
      ctx.setLineDash([]);
    }
    ctx.restore();
  },
  afterDatasetsDraw(chart) {
    const o = chart.options.plugins?.skewBands as SkewBands | undefined;
    if (!o) return;
    const { ctx, chartArea, scales } = chart;
    const x = scales.x;
    if (!x) return;
    const { top, left, right } = chartArea;
    ctx.save();

    // Spot label at the top of the spot line.
    const sx = x.getPixelForValue(o.spot);
    ctx.font = "600 11px ui-monospace, SFMono-Regular, Menlo, monospace";
    ctx.fillStyle = SPOT_LINE;
    ctx.textAlign = sx > (left + right) / 2 ? "right" : "left";
    ctx.fillText(`spot ${o.spotLabel}`, sx + (ctx.textAlign === "right" ? -6 : 6), top + 11);

    // Downside / upside corner labels.
    ctx.font = "700 10px ui-sans-serif, system-ui, sans-serif";
    ctx.fillStyle = DOWNSIDE_LABEL;
    ctx.textAlign = "left";
    ctx.fillText("↓ DOWNSIDE INSURANCE", left + 4, top + 11);
    ctx.fillStyle = UPSIDE_LABEL;
    ctx.textAlign = "right";
    ctx.fillText("COST OF UPSIDE ↑", right - 4, top + 11);
    ctx.restore();
  },
};

/* ── formatters ── */
const usd = (n: number | null | undefined) =>
  n == null
    ? "—"
    : n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 });
const usdAxis = (n: number) => (Math.abs(n) >= 100 ? n.toFixed(0) : n.toFixed(1));
const pct = (n: number | null | undefined) => (n == null ? "—" : `${(n * 100).toFixed(1)}%`);
const compact = (n: number | null | undefined) =>
  n == null
    ? "—"
    : new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(n);

const dayDiff = (aISO: string, bISO: string) =>
  Math.round((Date.parse(aISO) - Date.parse(bISO)) / 86_400_000);

/* ── derived view model ── */
type SkewPoint = { strike: number; iv: number; oi: number; type: "C" | "P" };
type SkewExpiry = { expiryISO: string; dte: number; points: SkewPoint[] }; // OTM, sorted by strike
type SkewData = {
  spot: number;
  snapshotISO: string;
  expiries: SkewExpiry[]; // sorted by DTE ascending (front month first)
  ivAtmForDte: (dte: number) => number | null; // gold-band vol, matched to the expiry's horizon
  rv: number | null; // teal-band vol (realized)
};

// Closest ATM IV term-structure column for a given DTE.
const ivAtmColForDte = (v: VolatilityRecord, dte: number): number | null => {
  const opts: [number, number | null][] = [
    [30, v.iv_atm_30d],
    [60, v.iv_atm_60d],
    [91, v.iv_atm_91d],
    [182, v.iv_atm_182d],
  ];
  let best: number | null = null;
  let bestGap = Infinity;
  for (const [h, val] of opts) {
    if (val == null) continue;
    const gap = Math.abs(h - dte);
    if (gap < bestGap) {
      bestGap = gap;
      best = val;
    }
  }
  return best;
};

// Build the full multi-expiry view, or null if nothing is plottable (no spot, or no OTM contracts
// with IV). Skew is per-expiry, so each expiry keeps its own OTM smile and the selector picks which
// one to plot. The pipeline fetches ~30/60/90/180 DTE + monthlies, so there are several.
function buildData(equity: EquitiesPayload | null): SkewData | null {
  if (!equity) return null;

  const closes = (equity.price_history ?? []).filter((p: PriceRecord) => p.close != null);
  const spot = closes.length ? (closes[closes.length - 1].close as number) : null;
  if (spot == null) return null;

  const chain = (equity.options_chain ?? []).filter((o: OptionRecord) => o.iv != null);
  if (!chain.length) return null;

  // Latest snapshot only.
  const snapshotISO = chain.reduce(
    (m, o) => (o.snapshot_date > m ? o.snapshot_date : m),
    chain[0].snapshot_date,
  );

  // Group OTM contracts by expiry.
  const byExpiry = new Map<string, SkewPoint[]>();
  for (const o of chain) {
    if (o.snapshot_date !== snapshotISO) continue;
    const otm = o.option_type === "C" ? o.strike > spot : o.strike < spot;
    if (!otm) continue;
    const pt: SkewPoint = {
      strike: o.strike,
      iv: o.iv as number,
      oi: o.open_interest ?? 0,
      type: o.option_type,
    };
    const arr = byExpiry.get(o.expiry);
    if (arr) arr.push(pt);
    else byExpiry.set(o.expiry, [pt]);
  }

  const expiries: SkewExpiry[] = [...byExpiry.entries()]
    .map(([expiryISO, points]) => ({
      expiryISO,
      dte: Math.max(1, dayDiff(expiryISO, snapshotISO)),
      points: points.sort((a, b) => a.strike - b.strike),
    }))
    .filter((e) => e.points.length > 0)
    .sort((a, b) => a.dte - b.dte);
  if (!expiries.length) return null;

  const vol = (equity.volatility_history ?? []) as VolatilityRecord[];
  const latestVol = vol.length ? vol[vol.length - 1] : null; // backend orders by date asc

  return {
    spot,
    snapshotISO,
    expiries,
    ivAtmForDte: (dte) => (latestVol ? ivAtmColForDte(latestVol, dte) : null),
    rv: latestVol?.rv ?? null,
  };
}

/**
 * Contract Visualization & Skew chart for /equity/:symbol.
 *
 * A bubble scatter of the OTM options chain (x = strike, y = IV, r ∝ OI; red = puts left of spot,
 * green = calls right of spot) overlaid with the spot line and two expected-move bands — gold from
 * market IV (iv_atm) and teal from realized vol (rv), each at the literal spot ± vol·spot. The gap
 * between them is the VRP premium. Bands/spot/smile/labels are drawn by skewBandsPlugin, which
 * reads from chart.options so nothing goes stale on re-render. useEquityData() may be null.
 */
export default function ContractSkewChart() {
  const equity = useEquityData();
  const view = useMemo(() => buildData(equity), [equity]);
  const [selectedExpiry, setSelectedExpiry] = useState<string | null>(null);

  if (!view) {
    return (
      <Card>
        <Header symbol={equity?.symbol} sec={equity?.security} />
        <Empty>
          {equity
            ? `No options chain available for ${equity.symbol}.`
            : "Options data is currently unavailable."}
        </Empty>
      </Card>
    );
  }

  const { spot, expiries, ivAtmForDte, rv } = view;
  // Fall back to the front expiry if nothing is selected or the selection isn't in this payload
  // (e.g. after switching tickers) — graceful without a reset effect.
  const selected = expiries.find((e) => e.expiryISO === selectedExpiry) ?? expiries[0];
  const { points, dte } = selected;
  const ivAtm = ivAtmForDte(dte);

  // Axis bounds: x = spot ± 30%; y = [minIV − 5pp, maxIV + 5pp] (IV stored as a fraction).
  const xMin = spot * 0.7;
  const xMax = spot * 1.3;
  let minIV = Infinity;
  let maxIV = -Infinity;
  for (const p of points) {
    if (p.iv < minIV) minIV = p.iv;
    if (p.iv > maxIV) maxIV = p.iv;
  }
  const yMin = Math.max(0, minIV - 0.05);
  const yMax = maxIV + 0.05;

  // OI → radius (sqrt-scaled; 0-OI stays at MIN_R).
  const maxOI = points.reduce((m, p) => Math.max(m, p.oi), 0);
  const radius = (oi: number) =>
    maxOI <= 0 || oi <= 0 ? MIN_R : MIN_R + Math.sqrt(oi / maxOI) * (MAX_R - MIN_R);

  type Bubble = { x: number; y: number; r: number; oi: number };
  const toBubbles = (t: "C" | "P"): Bubble[] =>
    points
      .filter((p) => p.type === t)
      .map((p) => ({ x: p.strike, y: p.iv, r: radius(p.oi), oi: p.oi }));

  const data: ChartData<"bubble", Bubble[]> = {
    datasets: [
      {
        label: "Puts",
        data: toBubbles("P"),
        backgroundColor: PUT_FILL,
        borderColor: PUT_BORDER,
        borderWidth: 1,
      },
      {
        label: "Calls",
        data: toBubbles("C"),
        backgroundColor: CALL_FILL,
        borderColor: CALL_BORDER,
        borderWidth: 1,
      },
    ],
  };

  // Literal expected-move bands: spot ± vol·spot (bandScale === 1). One commented constant flips
  // this to a DTE-scaled ±1σ move if the literal bands read too wide.
  const s = bandScale(dte);
  const ivBand =
    ivAtm != null ? { low: spot - ivAtm * spot * s, high: spot + ivAtm * spot * s } : null;
  const rvBand = rv != null ? { low: spot - rv * spot * s, high: spot + rv * spot * s } : null;

  const options: ChartOptions<"bubble"> = {
    responsive: true,
    maintainAspectRatio: false,
    animation: false,
    interaction: { mode: "point", intersect: true },
    plugins: {
      legend: { display: false },
      tooltip: {
        callbacks: {
          title: (items) => {
            const b = items[0]?.raw as Bubble | undefined;
            const label = items[0]?.dataset.label === "Calls" ? "Call" : "Put";
            return b ? `$${b.x.toFixed(1)} ${label}` : "";
          },
          label: (ctx) => `IV: ${pct((ctx.raw as Bubble).y)}`,
          afterBody: (items) => {
            const b = items[0]?.raw as Bubble | undefined;
            return b ? [`OI: ${compact(b.oi)}`, `DTE: ${dte}`] : [];
          },
        },
      },
      skewBands: {
        spot,
        spotLabel: usd(spot),
        iv: ivBand,
        rv: rvBand,
        smile: points.map((p) => ({ strike: p.strike, iv: p.iv })),
      },
    },
    scales: {
      x: {
        type: "linear",
        min: xMin,
        max: xMax,
        grid: { color: GRID }, // vertical gridlines, like the black mockup
        ticks: { color: AXIS_TEXT, maxTicksLimit: 10, callback: (v) => usdAxis(Number(v)) },
      },
      y: {
        type: "linear",
        min: yMin,
        max: yMax,
        afterFit: (scale) => {
          scale.width = 52;
        },
        grid: { color: GRID },
        ticks: { color: AXIS_TEXT, callback: (v) => pct(Number(v)) },
      },
    },
  };

  // Premium summary (compact — the full stats sidebar from mockup #3 is a deferred follow-up).
  const ivHalf = ivAtm != null ? ivAtm * spot * s : null;
  const rvHalf = rv != null ? rv * spot * s : null;
  const premium = ivHalf != null && rvHalf != null ? ivHalf - rvHalf : null;

  return (
    <Card>
      <Header
        symbol={equity?.symbol}
        sec={equity?.security}
        expiries={expiries}
        selected={selected}
        onSelect={setSelectedExpiry}
      />

      {(ivHalf != null || rvHalf != null) && (
        <div className="mt-1 mb-3 flex flex-wrap items-baseline gap-x-4 gap-y-1 text-sm">
          {ivHalf != null && (
            <span className="text-(--text-secondary)">
              IV move <span className="font-semibold text-(--text-primary)">±{usd(ivHalf)}</span>
            </span>
          )}
          {rvHalf != null && (
            <span className="text-(--text-secondary)">
              RV move <span className="font-semibold text-(--text-primary)">±{usd(rvHalf)}</span>
            </span>
          )}
          {premium != null && (
            <span className={premium >= 0 ? "text-(--pos)" : "text-(--neg)"}>
              premium {premium >= 0 ? "+" : "−"}
              {usd(Math.abs(premium))}/side
            </span>
          )}
        </div>
      )}

      <div className="relative h-110">
        <Chart type="bubble" data={data} options={options} plugins={[skewBandsPlugin]} />
      </div>

      <BandLegend />
    </Card>
  );
}

/* ── header: title · subtitle · expiry selector · puts/calls chips ── */
function Header({
  symbol,
  sec,
  expiries,
  selected,
  onSelect,
}: {
  symbol?: string;
  sec?: SecurityMeta;
  expiries?: SkewExpiry[];
  selected?: SkewExpiry;
  onSelect?: (expiryISO: string) => void;
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <div className="flex flex-wrap items-center gap-x-2">
          <h2 className="text-2xl font-bold tracking-tight text-(--text-primary)">
            Contracts &amp; Skew
          </h2>
          {symbol && <span className="text-lg font-semibold text-(--text-muted)">{symbol}</span>}
          {sec?.gics_sector && <span className="badge badge-sector">{sec.gics_sector}</span>}
        </div>
        <p className="mt-0.5 text-sm text-(--text-muted)">
          OI-weighted IV across listed strikes
          {selected ? ` · expiry ${selected.expiryISO} (${selected.dte}d)` : ""}
        </p>
      </div>

      <div className="flex flex-col items-end gap-2">
        {expiries && expiries.length > 1 && onSelect && (
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold tracking-wide text-(--text-muted) uppercase">
              Expiry
            </span>
            <div className="segmented">
              {expiries.map((e) => (
                <button
                  key={e.expiryISO}
                  type="button"
                  className="segmented-btn"
                  data-active={selected?.expiryISO === e.expiryISO}
                  onClick={() => onSelect(e.expiryISO)}
                >
                  {e.dte}d
                </button>
              ))}
            </div>
          </div>
        )}
        <div className="flex items-center gap-3 text-xs font-medium text-(--text-secondary)">
          <span className="flex items-center gap-1.5">
            <span
              className="inline-block h-2.5 w-2.5 rounded-full"
              style={{ background: PUT_FILL, border: `1px solid ${PUT_BORDER}` }}
            />
            Puts
          </span>
          <span className="flex items-center gap-1.5">
            <span
              className="inline-block h-2.5 w-2.5 rounded-full"
              style={{ background: CALL_FILL, border: `1px solid ${CALL_BORDER}` }}
            />
            Calls
          </span>
          <span className="text-(--text-muted)">· size = OI</span>
        </div>
      </div>
    </div>
  );
}

/* ── footer band legend ── */
function Swatch({ color, border, dash }: { color: string; border?: string; dash?: boolean }) {
  if (dash) {
    return (
      <span
        className="inline-block h-0 w-4 align-middle"
        style={{ borderTop: `1.5px dashed ${color}` }}
      />
    );
  }
  return (
    <span
      className="inline-block h-2.5 w-4 rounded-sm align-middle"
      style={{ background: color, border: border ? `1px solid ${border}` : undefined }}
    />
  );
}

function BandLegend() {
  return (
    <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-(--text-muted)">
      <span className="flex items-center gap-1.5">
        <Swatch color={IV_FILL} border={IV_EDGE} /> IV band (spot ± IV)
      </span>
      <span className="flex items-center gap-1.5">
        <Swatch color={RV_FILL} border={RV_EDGE} /> RV band (spot ± RV)
      </span>
      <span className="flex items-center gap-1.5">
        <Swatch color={PREMIUM_FILL} /> IV-RV premium
      </span>
      <span className="flex items-center gap-1.5">
        <Swatch color={SMILE} dash /> implied smile
      </span>
      <span className="flex items-center gap-1.5">
        <Swatch color={SPOT_LINE} dash /> spot
      </span>
    </div>
  );
}
