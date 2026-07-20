import { useMemo, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";
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
import type { PriceRecord, VolatilityRecord, EventRecord, SecurityMeta } from "~/utils/database";
import { Card, Empty } from "~/components/ui/section";

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Filler);

/* ── graph-specific palette (kept local to this chart; shared UI colors live in app.css) ── */
const LINE = "#2f6fed";
const LINE_FILL_TOP = "rgba(47, 111, 237, 0.22)";
const LINE_FILL_BOTTOM = "rgba(47, 111, 237, 0.01)";
const VRP_LINE = "#b08d3e";
const VRP_FILL = "rgba(176, 141, 62, 0.18)";
const EVENT_LINE = "rgba(120, 120, 120, 0.45)";
const EVENT_LABEL = "#8a8a8a";
// Transient click-drag range selection. Canvas literals like the rest of this block (canvas
// can't read CSS vars); the HTML readout below reuses the --pos/--neg tokens instead.
const SELECT_LINE = "rgba(55, 65, 81, 0.7)";
const SELECT_BAND = "rgba(47, 111, 237, 0.1)";
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

/** Click-drag selection window, as a pair of indices into the visible `rows`. */
type SelectionRange = { start: number; end: number };

declare module "chart.js" {
  // `TType` must match chart.js's generic for declaration merging — intentionally unused here.
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  interface PluginOptionsByType<TType extends ChartType> {
    eventMarkers?: { markers: EventMarker[] };
    rangeSelection?: { selection: SelectionRange | null };
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

/* ── range-selection plugin ──
   Renders the transient click-drag window: a subtle shaded band beneath the line and two
   vertical dotted markers (with endpoint dots) on top. Like eventMarkers, it reads its state
   from chart.options — NOT a closure — so react-chartjs-2's per-render options refresh keeps it
   in sync with the live drag (a closure would redraw a stale window). Draws nothing when null. */
const rangeSelectionPlugin: Plugin<"line"> = {
  id: "rangeSelection",
  beforeDatasetsDraw(chart) {
    // chart.options is deeply partial in chart.js's types; we always write a full selection.
    const sel = chart.options.plugins?.rangeSelection?.selection as SelectionRange | null;
    if (!sel) return;
    const { ctx, chartArea, scales } = chart;
    const xScale = scales.x;
    if (!xScale) return;
    const x1 = xScale.getPixelForValue(sel.start);
    const x2 = xScale.getPixelForValue(sel.end);
    const left = Math.max(chartArea.left, Math.min(x1, x2));
    const right = Math.min(chartArea.right, Math.max(x1, x2));
    if (right <= left) return; // single-point window: no band, the marker line still draws below
    ctx.save();
    ctx.fillStyle = SELECT_BAND;
    ctx.fillRect(left, chartArea.top, right - left, chartArea.bottom - chartArea.top);
    ctx.restore();
  },
  afterDatasetsDraw(chart) {
    const sel = chart.options.plugins?.rangeSelection?.selection as SelectionRange | null;
    if (!sel) return;
    const { ctx, chartArea, scales, data } = chart;
    const xScale = scales.x;
    const yScale = scales.y;
    if (!xScale || !yScale) return;
    // Read close values from chart.data (refreshed each render) rather than a closure.
    const closes = data.datasets[0]?.data as (number | null)[] | undefined;
    ctx.save();
    for (const idx of [sel.start, sel.end]) {
      const x = xScale.getPixelForValue(idx);
      if (x < chartArea.left - 0.5 || x > chartArea.right + 0.5) continue;
      ctx.beginPath();
      ctx.setLineDash([4, 4]);
      ctx.moveTo(x, chartArea.top);
      ctx.lineTo(x, chartArea.bottom);
      ctx.strokeStyle = SELECT_LINE;
      ctx.lineWidth = 1;
      ctx.stroke();
      ctx.setLineDash([]);
      const v = closes?.[idx];
      if (v != null) {
        ctx.beginPath();
        ctx.arc(x, yScale.getPixelForValue(v), 3, 0, Math.PI * 2);
        ctx.fillStyle = LINE;
        ctx.fill();
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

/** Close-to-close stats for a drag selection over `rows[a..b]`. */
export interface SelectionStats {
  startDate: string;
  endDate: string;
  startClose: number;
  endClose: number;
  absChange: number;
  pctChange: number;
  up: boolean;
}

/**
 * Pure, testable seam for the drag-selection readout. `a`/`b` are indices into `rows` in either
 * drag order; the window is normalized to [min, max] and clamped to the data. Returns null only
 * for an empty `rows`. A single-point window (a === b, or a flat span) yields a zero change with
 * `up: true` — matching the header's `change >= 0` convention.
 */
export function computeSelectionStats(
  rows: PriceRecord[],
  a: number,
  b: number,
): SelectionStats | null {
  if (!rows.length) return null;
  const last = rows.length - 1;
  const lo = Math.max(0, Math.min(last, Math.min(a, b)));
  const hi = Math.max(0, Math.min(last, Math.max(a, b)));
  const start = rows[lo];
  const end = rows[hi];
  const startClose = start.close as number;
  const endClose = end.close as number;
  const absChange = endClose - startClose;
  const pctChange = startClose ? (absChange / startClose) * 100 : 0;
  return {
    startDate: start.date,
    endDate: end.date,
    startClose,
    endClose,
    absChange,
    pctChange,
    up: absChange >= 0,
  };
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

  // Transient click-drag range selection — non-null only while a drag is in progress. `start`/`end`
  // are indices into `rows` (anchor + live cursor, in drag order). The chart ref maps pointer
  // pixels → indices; the anchor ref holds the press index across moves.
  const [selection, setSelection] = useState<SelectionRange | null>(null);
  const priceChartRef = useRef<ChartJS<"line", (number | null)[], string> | null>(null);
  const dragAnchor = useRef<number | null>(null);

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
        <Empty>Price data is currently unavailable.</Empty>
      </Card>
    );
  }

  const sec = equity.security;
  const name = sec?.company_name || equity.symbol;

  if (allRows.length === 0) {
    return (
      <Card>
        <Header
          name={name}
          symbol={equity.symbol}
          sec={sec}
          range={range}
          onRange={setRange}
          rows={[]}
        />
        <Empty>No price history available for {equity.symbol}.</Empty>
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
        // Suppress the index-mode OHLCV tooltip while a drag selection is active so the two
        // don't fight; normal hover resumes the moment the selection clears on release.
        enabled: selection == null,
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
      // Same options-not-closure pattern for the live drag selection — see rangeSelectionPlugin.
      rangeSelection: { selection },
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
          label: (ctx) => `VRP EWMA 21d: ${ctx.parsed.y == null ? "—" : ctx.parsed.y.toFixed(3)}`,
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

  // ── drag-selection pointer interaction (mouse; touch is a nice-to-have, not wired) ──
  // Map a pointer's clientX to the nearest data index via the x-scale, clamped to the data.
  // Runs client-side only (event handlers), so direct DOM access here is SSR-safe.
  const indexFromPointer = (e: ReactPointerEvent<HTMLDivElement>): number | null => {
    const chart = priceChartRef.current;
    const xScale = chart?.scales.x;
    if (!chart || !xScale) return null;
    const px = e.clientX - chart.canvas.getBoundingClientRect().left;
    const raw = xScale.getValueForPixel(px);
    if (raw == null) return null;
    return Math.max(0, Math.min(rows.length - 1, Math.round(raw)));
  };

  const onSelectStart = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return; // primary (left/touch) only — ignore right/middle drags
    const idx = indexFromPointer(e);
    if (idx == null) return;
    e.preventDefault(); // suppress native text-selection / drag-ghost
    e.currentTarget.setPointerCapture(e.pointerId);
    dragAnchor.current = idx;
    setSelection({ start: idx, end: idx });
  };

  const onSelectMove = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (dragAnchor.current == null) return; // not dragging
    const idx = indexFromPointer(e);
    if (idx == null) return;
    e.preventDefault();
    setSelection({ start: dragAnchor.current, end: idx });
  };

  // Clear on release / cancel / lost capture (covers pointer leaving the plot mid-drag) — the
  // selection is shown ONLY during the gesture. Idempotent, so wiring it to several events is safe.
  const onSelectEnd = () => {
    if (dragAnchor.current == null) return;
    dragAnchor.current = null;
    setSelection(null);
  };

  const selStats = selection ? computeSelectionStats(rows, selection.start, selection.end) : null;

  return (
    <Card>
      <Header
        name={name}
        symbol={equity.symbol}
        sec={sec}
        range={range}
        onRange={setRange}
        rows={rows}
      />

      <div className="mt-2 mb-4 flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="text-4xl font-bold text-(--text-primary)">{usd(latest.close)}</span>
        <span className={`text-sm font-semibold ${up ? "text-(--pos)" : "text-(--neg)"}`}>
          {up ? "+" : "−"}
          {usd(Math.abs(change))} ({up ? "+" : "−"}
          {Math.abs(changePct).toFixed(2)}%) {range}
        </span>
        <span className="text-sm text-(--text-muted)">· as of {longDate(latest.date)} · close</span>
      </div>

      <div
        className={`relative h-75 ${selection ? "cursor-ew-resize select-none" : ""}`}
        onPointerDown={onSelectStart}
        onPointerMove={onSelectMove}
        onPointerUp={onSelectEnd}
        onPointerCancel={onSelectEnd}
        onLostPointerCapture={onSelectEnd}
      >
        <Chart
          ref={(c) => {
            priceChartRef.current = c ?? null;
          }}
          type="line"
          data={priceData}
          options={priceOptions}
          plugins={[eventMarkersPlugin, rangeSelectionPlugin]}
        />
        {selStats && (
          <div className="pointer-events-none absolute top-2 left-1/2 z-10 flex -translate-x-1/2 items-baseline gap-2 rounded-md border border-(--panel-border) bg-(--ui-background) px-2.5 py-1 text-xs shadow-sm">
            <span
              className={`font-semibold ${selStats.up ? "text-(--pos)" : "text-(--neg)"}`}
              aria-label={`${selStats.up ? "up" : "down"} ${usd(Math.abs(selStats.absChange))}, ${Math.abs(selStats.pctChange).toFixed(2)} percent`}
            >
              {selStats.up ? "+" : "−"}
              {usd(Math.abs(selStats.absChange))} ({selStats.up ? "+" : "−"}
              {Math.abs(selStats.pctChange).toFixed(2)}%) {selStats.up ? "↑" : "↓"}
            </span>
            <span className="text-(--text-muted)">
              {longDate(selStats.startDate)} – {longDate(selStats.endDate)}
            </span>
          </div>
        )}
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
