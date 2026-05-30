import { useMemo, useState } from "react";
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Tooltip,
  Filler,
} from "chart.js";
import type { ChartData, ChartOptions, Plugin, Scale, ScriptableContext } from "chart.js";
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

function Card({ children }: { children: React.ReactNode }) {
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

  // VRP EWMA-21d aligned to the visible price dates (lookup by date, null when missing).
  const vrpSeries = useMemo<(number | null)[]>(() => {
    const byDate = new Map<string, number | null>();
    for (const v of (equity?.volatility_history ?? []) as VolatilityRecord[]) {
      byDate.set(v.date, v.vrp_wedge_ewma_21d);
    }
    return rows.map((p) => byDate.get(p.date) ?? null);
  }, [equity, rows]);
  const hasVrp = vrpSeries.some((v) => v != null);

  // Event markers positioned onto the visible category axis (matched by date).
  const eventMarkers = useMemo(() => {
    const indexByDate = new Map(rows.map((p, i) => [p.date, i]));
    return ((equity?.events ?? []) as EventRecord[])
      .map((e) => ({ index: indexByDate.get(e.event_date), label: e.title }))
      .filter((m): m is { index: number; label: string } => m.index != null);
  }, [equity, rows]);

  if (!equity) {
    return (
      <Card>
        <div className="flex h-[420px] items-center justify-center text-sm text-(--text-secondary)">
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
        <div className="flex h-[360px] items-center justify-center text-sm text-(--text-secondary)">
          No price history available for {equity.symbol}.
        </div>
      </Card>
    );
  }

  const latest = allRows[allRows.length - 1];
  const prev = allRows.length > 1 ? allRows[allRows.length - 2] : latest;
  const dayChange = (latest.close as number) - (prev.close as number);
  const dayChangePct = prev.close ? (dayChange / (prev.close as number)) * 100 : 0;
  const up = dayChange >= 0;

  /* ── event annotation plugin (inline; no extra dependency) ── */
  const eventPlugin: Plugin<"line"> = {
    id: "eventMarkers",
    afterDatasetsDraw(chart) {
      const { ctx, chartArea, scales } = chart;
      const xScale = scales.x;
      if (!xScale) return;
      for (const m of eventMarkers) {
        const x = xScale.getPixelForValue(m.index);
        if (x < chartArea.left || x > chartArea.right) continue;
        ctx.save();
        ctx.beginPath();
        ctx.setLineDash([4, 4]);
        ctx.moveTo(x, chartArea.top);
        ctx.lineTo(x, chartArea.bottom);
        ctx.strokeStyle = EVENT_LINE;
        ctx.lineWidth = 1;
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = EVENT_LABEL;
        ctx.font = "600 9px ui-sans-serif, system-ui, sans-serif";
        ctx.textAlign = "left";
        ctx.fillText(m.label.toUpperCase(), x + 4, chartArea.top + 10);
        ctx.restore();
      }
    },
  };

  const labels = rows.map((p) => p.date);

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
    },
    scales: {
      x: {
        grid: { display: false },
        ticks: {
          maxTicksLimit: 8,
          autoSkip: true,
          maxRotation: 0,
          color: "var(--text-muted)",
          callback(this: Scale, value) {
            return shortDate(this.getLabelForValue(value as number));
          },
        },
      },
      y: {
        position: "left",
        grace: "6%",
        afterFit: (scale) => {
          scale.width = 56;
        },
        grid: { color: GRID },
        ticks: { color: "var(--text-muted)", callback: (v) => usdAxis(Number(v)) },
      },
    },
  };

  const vrpData: ChartData<"line", (number | null)[], string> = {
    labels,
    datasets: [
      {
        label: "VRP EWMA 21d",
        data: vrpSeries,
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
          color: "var(--text-muted)",
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
          {usd(Math.abs(dayChange))} ({up ? "+" : "−"}
          {Math.abs(dayChangePct).toFixed(2)}%)
        </span>
        <span className="text-sm text-(--text-muted)">· as of {longDate(latest.date)} · close</span>
      </div>

      <div className="relative h-[300px]">
        <Chart type="line" data={priceData} options={priceOptions} plugins={[eventPlugin]} />
      </div>

      {hasVrp && (
        <div className="relative mt-1 h-[88px]">
          <span className="absolute left-[60px] top-0 z-10 text-[10px] font-medium tracking-wide text-(--text-muted)">
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
    URL.revokeObjectURL(url);
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
