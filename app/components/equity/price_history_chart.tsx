import { useMemo, useState } from "react";
import type { ReactNode } from "react";
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Tooltip,
  Filler,
} from "chart.js";
import type {
  ChartData,
  ChartOptions,
  ChartType,
  Plugin,
  Scale,
  ScriptableContext,
} from "chart.js";
import { Chart } from "react-chartjs-2";
import { useEquityData } from "~/context/EquityDataContext";
import type {
  PriceRecord,
  VolatilityRecord,
  EventRecord,
  SecurityMeta,
} from "~/utils/database";

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Filler);

/* ── graph-specific palette (kept local to this chart; shared UI colors live in app.css) ── */
const LINE = "#2f6fed";
const LINE_FILL_TOP = "rgba(47, 111, 237, 0.22)";
const LINE_FILL_BOTTOM = "rgba(47, 111, 237, 0.01)";
const VRP_LINE = "#b08d3e";
const VRP_FILL = "rgba(176, 141, 62, 0.18)";
const EVENT_LINE = "rgba(120, 120, 120, 0.45)";
const EVENT_LABEL = "#8a8a8a";
const GRID = "rgba(0, 0, 0, 0.05)";
// Axis tick text. Canvas can't resolve CSS vars, so this mirrors --text-muted (light) as a
// literal rather than passing "var(--text-muted)" (which the canvas would ignore).
const AXIS_TEXT = "#9ca3af";

/* ── event-marker plugin ──
   Draws a vertical dashed line + staggered label per event. It reads its markers from
   chart.options (which react-chartjs-2 refreshes on every re-render) rather than a closure —
   an inline-plugin closure goes stale and keeps re-drawing the markers from the first render,
   which is why switching range used to plot the wrong year's events. Module-level + stable. */
type EventMarker = { index: number; label: string };

declare module "chart.js" {
  interface PluginOptionsByType<TType extends ChartType> {
    eventMarkers?: { markers: EventMarker[] };
  }
}

const eventMarkersPlugin: Plugin<"line"> = {
  id: "eventMarkers",
  afterDatasetsDraw(chart) {
    // chart.options is deeply partial in chart.js's types; we always write full markers.
    const markers = (chart.options.plugins?.eventMarkers?.markers ?? []) as EventMarker[];
    if (!markers.length) return;
    const { ctx, chartArea, scales } = chart;
    const xScale = scales.x;
    if (!xScale) return;
    ctx.save();
    ctx.font = "600 9px ui-sans-serif, system-ui, sans-serif";
    ctx.textAlign = "left";
    // Stagger labels across a few rows so adjacent / recurring labels don't collide and drop.
    const ROWS = 3;
    const ROW_H = 11;
    const rowRight = new Array(ROWS).fill(-Infinity);
    for (const m of [...markers].sort((a, b) => a.index - b.index)) {
      const x = xScale.getPixelForValue(m.index);
      if (x < chartArea.left || x > chartArea.right) continue;
      // vertical dashed line spanning the plot
      ctx.beginPath();
      ctx.setLineDash([4, 4]);
      ctx.moveTo(x, chartArea.top);
      ctx.lineTo(x, chartArea.bottom);
      ctx.strokeStyle = EVENT_LINE;
      ctx.lineWidth = 1;
      ctx.stroke();
      ctx.setLineDash([]);
      // place the label in the first row it fits
      const text = m.label.toUpperCase();
      const left = x + 4;
      for (let r = 0; r < ROWS; r++) {
        if (left > rowRight[r]) {
          ctx.fillStyle = EVENT_LABEL;
          ctx.fillText(text, left, chartArea.top + 10 + r * ROW_H);
          rowRight[r] = left + ctx.measureText(text).width + 6;
          break;
        }
      }
    }
    ctx.restore();
  },
};

/* ── formatters ── */
const usd = (n: number | null | undefined) =>
  n == null
    ? "—"
    : n.toLocaleString("en-US", {
        style: "currency",
        currency: "USD",
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      });

const usdAxis = (n: number) => (Math.abs(n) >= 100 ? `$${n.toFixed(0)}` : `$${n.toFixed(2)}`);

const compact = (n: number | null | undefined) =>
  n == null
    ? "—"
    : new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(n);

const parseDay = (iso: string) => new Date(`${iso}T00:00:00`);
const shortDate = (iso: string) =>
  parseDay(iso).toLocaleDateString("en-US", { month: "short", day: "numeric" });
const longDate = (iso: string) =>
  parseDay(iso).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
// "May '25" — unambiguous month+year for multi-year axes. The apostrophe stops "May 25" from
// reading as a day-of-month.
const monthYear = (iso: string) => {
  const d = parseDay(iso);
  return `${d.toLocaleDateString("en-US", { month: "short" })} '${String(d.getFullYear()).slice(2)}`;
};

/* ── range selector config ── */
type RangeKey = "1M" | "3M" | "6M" | "YTD" | "1Y" | "2Y" | "5Y" | "MAX";
const RANGES: { key: RangeKey; days: number | "ytd" | "max" }[] = [
  { key: "1M", days: 30 },
  { key: "3M", days: 91 },
  { key: "6M", days: 182 },
  { key: "YTD", days: "ytd" },
  { key: "1Y", days: 365 },
  { key: "2Y", days: 730 },
  { key: "5Y", days: 1825 },
  { key: "MAX", days: "max" },
];

function cutoffFor(range: RangeKey, latestISO: string): Date {
  const latest = parseDay(latestISO);
  const spec = RANGES.find((r) => r.key === range)!.days;
  if (spec === "max") return new Date(0);
  if (spec === "ytd") return new Date(`${latest.getFullYear()}-01-01T00:00:00`);
  const d = new Date(latest);
  d.setDate(d.getDate() - spec);
  return d;
}

function DownloadIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" className="h-4 w-4" aria-hidden="true">
      <path
        d="M10 3v9m0 0 3.5-3.5M10 12 6.5 8.5M4 15.5h12"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function Card({ children }: { children: ReactNode }) {
  return <div className="panel p-5">{children}</div>;
}

/**
 * Price-history chart for /equity/:symbol — first component of the redesigned page.
 *
 * Validates the DB pipeline end-to-end: loader → EquityDataContext → useEquityData().
 * Renders the close-price area line (OHLCV surfaced in the tooltip), event-annotation
 * markers from `events`, and a VRP EWMA-21d sub-panel from `volatility_history`.
 * useEquityData() may be null (DB call is non-fatal) — handled below.
 */
export default function PriceHistoryChart() {
  const equity = useEquityData();
  const [range, setRange] = useState<RangeKey>("1Y");

  const allRows = useMemo<PriceRecord[]>(
    () => (equity?.price_history ?? []).filter((p) => p.close != null),
    [equity],
  );

  const latestISO = allRows.length ? allRows[allRows.length - 1].date : "";

  // Rows within the selected range window.
  const rows = useMemo<PriceRecord[]>(() => {
    if (!allRows.length) return [];
    const cutoff = cutoffFor(range, latestISO);
    return allRows.filter((p) => parseDay(p.date) >= cutoff);
  }, [allRows, range, latestISO]);

  // VRP EWMA-21d sub-panel.
  // NOTE: in the current DB snapshot, volatility_history lags price_history (vol ends ~2025-05
  // while prices run to ~2026-05), so the two series share no dates. We therefore window the VRP
  // strip on the volatility series' OWN latest date instead of the price dates; the tooltip shows
  // the true vol date. When the vol feed catches up to prices, switch this to a date-keyed lookup
  // against the price window so the two x-axes line up as the design intends.
  const volRows = useMemo<VolatilityRecord[]>(() => {
    const withVrp = ((equity?.volatility_history ?? []) as VolatilityRecord[]).filter(
      (v) => v.vrp_wedge_ewma_21d != null,
    );
    if (!withVrp.length) return [];
    const volLatest = withVrp[withVrp.length - 1].date; // backend orders by date asc
    const cutoff = cutoffFor(range, volLatest);
    return withVrp.filter((v) => parseDay(v.date) >= cutoff);
  }, [equity, range]);
  const hasVrp = volRows.length > 0;

  // Per-security event markers placed on the visible axis. Events (event_history) may not land
  // exactly on a trading day, so snap each to the nearest visible session; drop events outside
  // the visible window.
  const eventMarkers = useMemo<EventMarker[]>(() => {
    if (!rows.length) return [];
    const times = rows.map((p) => parseDay(p.date).getTime());
    const first = times[0];
    const last = times[times.length - 1];
    const out: EventMarker[] = [];
    for (const e of (equity?.events ?? []) as EventRecord[]) {
      const t = parseDay(e.event_date).getTime();
      if (t < first || t > last) continue;
      let best = 0;
      let bestDiff = Infinity;
      for (let i = 0; i < times.length; i++) {
        const diff = Math.abs(times[i] - t);
        if (diff < bestDiff) {
          bestDiff = diff;
          best = i;
        }
      }
      // Append the year to each label (debug aid; reads fine on long ranges too).
      const yy = String(parseDay(e.event_date).getFullYear()).slice(2);
      out.push({ index: best, label: `${e.title} '${yy}` });
    }
    return out;
  }, [equity, rows]);

  if (!equity) {
    return (
      <Card>
        <div className="flex h-105 items-center justify-center text-sm text-(--text-secondary)">
          Price data is currently unavailable.
        </div>
      </Card>
    );
  }

  const sec = equity.security;
  const name = sec?.company_name || equity.symbol;

  if (allRows.length === 0) {
    return (
      <Card>
        <Header name={name} symbol={equity.symbol} sec={sec} range={range} onRange={setRange} rows={[]} />
        <div className="flex h-90 items-center justify-center text-sm text-(--text-secondary)">
          No price history available for {equity.symbol}.
        </div>
      </Card>
    );
  }

  const latest = rows[rows.length - 1];
  const oldest = rows.length > 1 ? rows[0] : latest;
  const change = (latest.close as number) - (oldest.close as number);
  const changePct = oldest.close ? (change / (oldest.close as number)) * 100 : 0;
  const up = change >= 0;

  const labels = rows.map((p) => p.date);

  // Past ~11 months a month name recurs across years; switch the x-axis to month+year so ticks
  // from different years can't be confused (the tooltip always shows the full date regardless).
  const spanDays =
    rows.length > 1
      ? (parseDay(rows[rows.length - 1].date).getTime() - parseDay(rows[0].date).getTime()) /
        86_400_000
      : 0;
  const showYear = spanDays > 330;

  // Pad the price axis ~6%, but never let the lower bound drop below 0 (some low-priced
  // equities would otherwise render a negative axis floor). High-priced names keep their
  // padded, non-zero min so the line isn't compressed against the top.
  let priceMin = Infinity;
  let priceMax = -Infinity;
  for (const p of rows) {
    const c = p.close as number;
    if (c < priceMin) priceMin = c;
    if (c > priceMax) priceMax = c;
  }
  const pricePad = (priceMax - priceMin || priceMax) * 0.06;
  const yMin = Math.max(0, priceMin - pricePad);
  const yMax = priceMax + pricePad;

  const priceData: ChartData<"line", (number | null)[], string> = {
    labels,
    datasets: [
      {
        label: "Close",
        data: rows.map((p) => p.close),
        borderColor: LINE,
        borderWidth: 1.75,
        pointRadius: 0,
        pointHoverRadius: 4,
        pointHoverBackgroundColor: LINE,
        tension: 0.15,
        fill: "start",
        backgroundColor: (ctx: ScriptableContext<"line">) => {
          const { chartArea, ctx: c } = ctx.chart;
          if (!chartArea) return LINE_FILL_TOP;
          const g = c.createLinearGradient(0, chartArea.top, 0, chartArea.bottom);
          g.addColorStop(0, LINE_FILL_TOP);
          g.addColorStop(1, LINE_FILL_BOTTOM);
          return g;
        },
      },
    ],
  };

  const priceOptions: ChartOptions<"line"> = {
    responsive: true,
    maintainAspectRatio: false,
    animation: false,
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: { display: false },
      tooltip: {
        callbacks: {
          title: (items) => (items.length ? longDate(items[0].label) : ""),
          label: (ctx) => `Close: ${usd(ctx.parsed.y)}`,
          afterBody: (items) => {
            const p = rows[items[0]?.dataIndex];
            if (!p) return [];
            return [
              `Open:   ${usd(p.open)}`,
              `High:   ${usd(p.high)}`,
              `Low:    ${usd(p.low)}`,
              `Volume: ${compact(p.volume)}`,
            ];
          },
        },
      },
      // Markers live in options (not a closure) so the stable plugin redraws the right set when
      // the range changes — see eventMarkersPlugin.
      eventMarkers: { markers: eventMarkers },
    },
    scales: {
      x: {
        grid: { display: false },
        ticks: {
          maxTicksLimit: 8,
          autoSkip: true,
          maxRotation: 0,
          color: AXIS_TEXT,
          callback(this: Scale, value) {
            const iso = this.getLabelForValue(value as number);
            return showYear ? monthYear(iso) : shortDate(iso);
          },
        },
      },
      y: {
        position: "left",
        min: yMin,
        max: yMax,
        afterFit: (scale) => {
          scale.width = 56;
        },
        grid: { color: GRID },
        ticks: { color: AXIS_TEXT, callback: (v) => usdAxis(Number(v)) },
      },
    },
  };

  const vrpData: ChartData<"line", (number | null)[], string> = {
    labels: volRows.map((v) => v.date),
    datasets: [
      {
        label: "VRP EWMA 21d",
        data: volRows.map((v) => v.vrp_wedge_ewma_21d),
        borderColor: VRP_LINE,
        backgroundColor: VRP_FILL,
        borderWidth: 1.25,
        pointRadius: 0,
        tension: 0.2,
        fill: "start",
        spanGaps: true,
      },
    ],
  };

  const vrpOptions: ChartOptions<"line"> = {
    responsive: true,
    maintainAspectRatio: false,
    animation: false,
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: { display: false },
      tooltip: {
        callbacks: {
          title: (items) => (items.length ? longDate(items[0].label) : ""),
          label: (ctx) =>
            `VRP EWMA 21d: ${ctx.parsed.y == null ? "—" : ctx.parsed.y.toFixed(3)}`,
        },
      },
    },
    scales: {
      x: { display: false, grid: { display: false } },
      y: {
        position: "left",
        afterFit: (scale) => {
          scale.width = 56;
        },
        grid: { color: GRID },
        ticks: {
          color: AXIS_TEXT,
          maxTicksLimit: 3,
          callback: (v) => Number(v).toFixed(2),
        },
      },
    },
  };

  return (
    <Card>
      <Header name={name} symbol={equity.symbol} sec={sec} range={range} onRange={setRange} rows={rows} />

      <div className="mt-2 mb-4 flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="text-4xl font-bold text-(--text-primary)">{usd(latest.close)}</span>
        <span className={`text-sm font-semibold ${up ? "text-(--pos)" : "text-(--neg)"}`}>
          {up ? "+" : "−"}
          {usd(Math.abs(change))} ({up ? "+" : "−"}
          {Math.abs(changePct).toFixed(2)}%)
        </span>
        <span className="text-sm text-(--text-muted)">· as of {longDate(latest.date)} · close</span>
      </div>

      <div className="relative h-75">
        <Chart type="line" data={priceData} options={priceOptions} plugins={[eventMarkersPlugin]} />
      </div>

      {hasVrp && (
        <div className="relative mt-1 h-22">
          <span className="absolute left-15 top-0 z-10 text-[10px] font-medium tracking-wide text-(--text-muted)">
            VRP EWMA 21d
          </span>
          <Chart type="line" data={vrpData} options={vrpOptions} />
        </div>
      )}
    </Card>
  );
}

/* ── header: name · ticker · sector badges · range selector · download ── */
function Header({
  name,
  symbol,
  sec,
  range,
  onRange,
  rows,
}: {
  name: string;
  symbol: string;
  sec: SecurityMeta | undefined;
  range: RangeKey;
  onRange: (r: RangeKey) => void;
  rows: PriceRecord[];
}) {
  const downloadCsv = () => {
    if (typeof document === "undefined" || !rows.length) return;
    const header = "date,open,high,low,close,adj_close,volume";
    const body = rows
      .map((p) => [p.date, p.open, p.high, p.low, p.close, p.adj_close, p.volume].join(","))
      .join("\n");
    const blob = new Blob([`${header}\n${body}`], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${symbol}_price_history_${range}.csv`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 0);
  };

  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <h2 className="text-2xl font-bold tracking-tight text-(--text-primary)">{name}</h2>
        <span className="text-lg font-semibold text-(--text-muted)">{symbol}</span>
        {sec?.gics_sector && <span className="badge badge-sector">{sec.gics_sector}</span>}
        {(sec?.gics_industry || sec?.gics_subindustry) && (
          <span className="badge badge-neutral">{sec.gics_industry || sec.gics_subindustry}</span>
        )}
      </div>

      <div className="flex items-center gap-2">
        <div className="segmented">
          {RANGES.map((r) => (
            <button
              key={r.key}
              type="button"
              className="segmented-btn"
              data-active={range === r.key}
              onClick={() => onRange(r.key)}
            >
              {r.key}
            </button>
          ))}
        </div>
        <button
          type="button"
          onClick={downloadCsv}
          aria-label="Download price history as CSV"
          className="rounded-md border border-(--panel-border) p-1.5 text-(--text-secondary) hover:bg-(--track-bg)"
        >
          <DownloadIcon />
        </button>
      </div>
    </div>
  );
}
