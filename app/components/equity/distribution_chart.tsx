import { useMemo, useState } from "react";
import {
  Chart as ChartJS,
  BarController,
  BarElement,
  CategoryScale,
  LinearScale,
  Tooltip,
} from "chart.js";
import type { ChartData, ChartOptions, ChartType, Plugin } from "chart.js";
import { Chart } from "react-chartjs-2";
import { useEquityData } from "~/context/EquityDataContext";
import type { DistributionSet, SecurityMeta } from "~/utils/database";
import { Card, Empty } from "./section";

// A bar chart needs BarController + BarElement + CategoryScale (unlike the line charts elsewhere).
// BarController is registered like contract_skew_chart registers BubbleController for the generic
// <Chart> component.
ChartJS.register(BarController, BarElement, CategoryScale, LinearScale, Tooltip);

/* ── graph-specific palette (kept local; canvas can't read CSS vars — same convention as the
   price/forward-vol charts. Shared UI colors live in app.css). ── */
const BAR_FILL = "rgba(47, 111, 237, 0.28)"; // blue — histogram bars
const BAR_BORDER = "#2f6fed";
const CURRENT_LINE = "#0f766e"; // teal — current value marker (matches the model line elsewhere)
const MEAN_LINE = "#b08d3e"; // amber — mean
const SIGMA_LINE = "rgba(120, 120, 120, 0.55)"; // gray — ±1σ guides
const SIGMA_FILL = "rgba(120, 120, 120, 0.07)";
const GRID = "rgba(0, 0, 0, 0.05)";
const AXIS_TEXT = "#9ca3af"; // mirrors --text-muted (light)

/* ── metric / lookback / scope config ──
   Metrics map to the backend's distribution_data keys. Scope is stock-only for v1; Sector and
   Market render disabled ("coming soon") rather than being removed. */
const METRICS = [
  { key: "rv", label: "RV", long: "Realized volatility", unit: "%" },
  { key: "iv", label: "IV", long: "Implied volatility (ATM)", unit: "%" },
  { key: "vrp", label: "VRP", long: "Variance risk premium (wedge)", unit: "pp" },
] as const;
type MetricKey = (typeof METRICS)[number]["key"];

const LOOKBACKS = ["1Y", "2Y", "5Y", "MAX"] as const;
type LookbackKey = (typeof LOOKBACKS)[number];

const SCOPES = [
  { key: "stock", label: "Stock", enabled: true },
  { key: "sector", label: "Sector", enabled: false },
  { key: "market", label: "Market", enabled: false },
] as const;
type ScopeKey = (typeof SCOPES)[number]["key"];

const metricMeta = (m: MetricKey) => METRICS.find((x) => x.key === m)!;

// Volatility columns are stored as decimals (e.g. 0.21 = 21%); scale ×100 for readable %/pp,
// same convention as the forward-vol chart (iv/pfv ×100). The histogram shape is unchanged.
const SCALE = 100;

/* ── overlay plugin ──
   Draws the current-value marker, the mean line, and a ±1σ band over the bars. Like the
   price/forward-vol overlays it reads everything from chart.options (which react-chartjs-2
   refreshes each render) rather than a closure, so the markers track the selected metric/lookback
   instead of redrawing the previous selection's values.

   Bins are equal-width and contiguous, and a bar category scale (offset: true) lays the 10
   categories evenly across the plot — so a raw metric value maps linearly onto the x-axis:
   x = left + (v - min) / (max - min) · width. No per-bin pixel math needed. */
type DistMarkers = {
  min: number;
  max: number;
  current: number;
  mean: number;
  sigmaLow: number | null;
  sigmaHigh: number | null;
  currentLabel: string;
  meanLabel: string;
};

declare module "chart.js" {
  interface PluginOptionsByType<TType extends ChartType> {
    distMarkers?: DistMarkers;
  }
}

function drawTopLabel(
  ctx: CanvasRenderingContext2D,
  text: string,
  x: number,
  y: number,
  color: string,
  left: number,
  right: number,
) {
  ctx.fillStyle = color;
  const w = ctx.measureText(text).width;
  // Keep the label inside the plot: flip to the left of the line when it'd overflow the right edge.
  if (x + 4 + w > right) {
    ctx.textAlign = "right";
    ctx.fillText(text, Math.min(x - 4, right), y);
  } else {
    ctx.textAlign = "left";
    ctx.fillText(text, Math.max(x + 4, left), y);
  }
}

const distMarkersPlugin: Plugin<"bar"> = {
  id: "distMarkers",
  afterDatasetsDraw(chart) {
    const opts = chart.options.plugins?.distMarkers as DistMarkers | undefined;
    if (!opts) return;
    const { ctx, chartArea } = chart;
    const { left, right, top, bottom } = chartArea;
    const span = opts.max - opts.min || 1;
    const xForValue = (v: number) => {
      const frac = Math.max(0, Math.min(1, (v - opts.min) / span));
      return left + frac * (right - left);
    };
    ctx.save();

    // ±1σ band (best-effort — only when stdev was provided).
    if (opts.sigmaLow != null && opts.sigmaHigh != null) {
      const xLo = xForValue(opts.sigmaLow);
      const xHi = xForValue(opts.sigmaHigh);
      ctx.fillStyle = SIGMA_FILL;
      ctx.fillRect(xLo, top, xHi - xLo, bottom - top);
      ctx.strokeStyle = SIGMA_LINE;
      ctx.lineWidth = 1;
      ctx.setLineDash([3, 3]);
      for (const x of [xLo, xHi]) {
        ctx.beginPath();
        ctx.moveTo(x, top);
        ctx.lineTo(x, bottom);
        ctx.stroke();
      }
      ctx.setLineDash([]);
    }

    // Mean line (dashed amber).
    const xMean = xForValue(opts.mean);
    ctx.strokeStyle = MEAN_LINE;
    ctx.lineWidth = 1.5;
    ctx.setLineDash([5, 3]);
    ctx.beginPath();
    ctx.moveTo(xMean, top);
    ctx.lineTo(xMean, bottom);
    ctx.stroke();
    ctx.setLineDash([]);

    // Current-value line (solid teal, drawn last so it sits on top).
    const xCur = xForValue(opts.current);
    ctx.strokeStyle = CURRENT_LINE;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(xCur, top);
    ctx.lineTo(xCur, bottom);
    ctx.stroke();

    // Labels at the top of the plot; offset rows so current/mean don't collide.
    ctx.textBaseline = "top";
    ctx.font = "700 10px ui-sans-serif, system-ui, sans-serif";
    drawTopLabel(ctx, opts.meanLabel, xMean, top + 2, MEAN_LINE, left, right);
    drawTopLabel(ctx, opts.currentLabel, xCur, top + 15, CURRENT_LINE, left, right);

    ctx.restore();
  },
};

/**
 * Historical Distribution for /equity/:symbol — a 10-bin frequency histogram of the security's
 * own RV / IV / VRP over a selectable lookback, with the current value and mean overlaid.
 *
 * Reads the precomputed `distribution_data` sets via useEquityData() (loader → EquityDataContext →
 * here). All three toggles (metric / lookback / scope) filter the loaded sets client-side — no
 * refetch. useEquityData() may be null (DB call is non-fatal) — handled below. Stock scope only
 * for v1; Sector/Market are rendered disabled.
 */
export default function DistributionChart() {
  const equity = useEquityData();
  const [metric, setMetric] = useState<MetricKey>("rv");
  const [lookback, setLookback] = useState<LookbackKey>("1Y");
  const [scope, setScope] = useState<ScopeKey>("stock");

  const sets = (equity?.distribution_data ?? []) as DistributionSet[];
  const set = useMemo(
    () =>
      sets.find((s) => s.scope === scope && s.metric === metric && s.lookback === lookback) ?? null,
    [sets, scope, metric, lookback],
  );

  const sec = equity?.security;
  const symbol = equity?.symbol ?? "";
  const header = (
    <Header
      symbol={symbol}
      sec={sec}
      metric={metric}
      onMetric={setMetric}
      lookback={lookback}
      onLookback={setLookback}
      scope={scope}
      onScope={setScope}
    />
  );

  // Tier 1: whole payload missing (DB call failed).
  if (!equity) {
    return (
      <Card>
        {header}
        <Empty>Distribution data is currently unavailable.</Empty>
      </Card>
    );
  }

  // Tier 2: payload present, but no set for the current metric/lookback/scope (e.g. sparse history).
  if (!set || set.bins.length === 0) {
    return (
      <Card>
        {header}
        <Empty>No distribution available for {symbol}.</Empty>
      </Card>
    );
  }

  const unit = metricMeta(metric).unit;
  const fmt = (v: number) => `${(v * SCALE).toFixed(1)}${unit}`;
  const axisFmt = (v: number) => (v * SCALE).toFixed(1);

  const bins = set.bins;
  const min = bins[0].bin_low;
  const max = bins[bins.length - 1].bin_high;
  const total = bins.reduce((sum, b) => sum + b.count, 0);
  const stdev = set.stdev ?? null;
  const sigmaLow = stdev != null ? set.mean - stdev : null;
  const sigmaHigh = stdev != null ? set.mean + stdev : null;

  const data: ChartData<"bar", number[], string> = {
    labels: bins.map((b) => axisFmt(b.bin_low)),
    datasets: [
      {
        label: "Frequency",
        data: bins.map((b) => b.count),
        backgroundColor: BAR_FILL,
        borderColor: BAR_BORDER,
        borderWidth: 1,
        borderRadius: 2,
        // Near-1 so adjacent bars touch like a histogram (doesn't affect the category band centers
        // the overlay maps against).
        categoryPercentage: 0.98,
        barPercentage: 0.98,
      },
    ],
  };

  const options: ChartOptions<"bar"> = {
    responsive: true,
    maintainAspectRatio: false,
    animation: false,
    plugins: {
      legend: { display: false },
      tooltip: {
        callbacks: {
          title: (items) => {
            const b = bins[items[0]?.dataIndex ?? -1];
            return b ? `${axisFmt(b.bin_low)} – ${axisFmt(b.bin_high)}${unit}` : "";
          },
          label: (ctx) => `${ctx.parsed.y} day${ctx.parsed.y === 1 ? "" : "s"}`,
        },
      },
      distMarkers: {
        min,
        max,
        current: set.current_value,
        mean: set.mean,
        sigmaLow,
        sigmaHigh,
        currentLabel: `Now ${fmt(set.current_value)}`,
        meanLabel: `μ ${fmt(set.mean)}`,
      },
    },
    scales: {
      x: {
        grid: { display: false },
        ticks: { color: AXIS_TEXT, maxRotation: 0, autoSkip: true, maxTicksLimit: 6 },
        title: {
          display: true,
          text: `${metricMeta(metric).label} (${unit})`,
          color: AXIS_TEXT,
          font: { size: 10 },
        },
      },
      y: {
        beginAtZero: true,
        afterFit: (scale) => {
          scale.width = 40;
        },
        grid: { color: GRID },
        ticks: { color: AXIS_TEXT, maxTicksLimit: 5, precision: 0 },
        title: { display: true, text: "Days", color: AXIS_TEXT, font: { size: 10 } },
      },
    },
  };

  return (
    <Card>
      {header}

      <div className="relative mt-4 h-64">
        <Chart type="bar" data={data} options={options} plugins={[distMarkersPlugin]} />
      </div>

      <Stats set={set} fmt={fmt} total={total} />
    </Card>
  );
}

/* ── header: title · symbol · sector badge · subtitle · metric / lookback / scope toggles ── */
function Header({
  symbol,
  sec,
  metric,
  onMetric,
  lookback,
  onLookback,
  scope,
  onScope,
}: {
  symbol: string;
  sec: SecurityMeta | undefined;
  metric: MetricKey;
  onMetric: (m: MetricKey) => void;
  lookback: LookbackKey;
  onLookback: (l: LookbackKey) => void;
  scope: ScopeKey;
  onScope: (s: ScopeKey) => void;
}) {
  return (
    <div>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <h2 className="text-2xl font-bold tracking-tight text-(--text-primary)">
          Historical Distribution
        </h2>
        {symbol && <span className="text-lg font-semibold text-(--text-muted)">{symbol}</span>}
        {sec?.gics_sector && <span className="badge badge-sector">{sec.gics_sector}</span>}
      </div>
      <p className="mt-0.5 text-sm text-(--text-muted)">
        {metricMeta(metric).long} · own-history frequency
      </p>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <div className="segmented">
          {METRICS.map((m) => (
            <button
              key={m.key}
              type="button"
              className="segmented-btn"
              data-active={metric === m.key}
              onClick={() => onMetric(m.key)}
            >
              {m.label}
            </button>
          ))}
        </div>

        <div className="segmented">
          {LOOKBACKS.map((l) => (
            <button
              key={l}
              type="button"
              className="segmented-btn"
              data-active={lookback === l}
              onClick={() => onLookback(l)}
            >
              {l}
            </button>
          ))}
        </div>

        <div className="segmented">
          {SCOPES.map((s) => (
            <button
              key={s.key}
              type="button"
              className="segmented-btn disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:text-(--text-secondary)"
              data-active={scope === s.key}
              disabled={!s.enabled}
              title={s.enabled ? undefined : "Coming soon"}
              onClick={() => s.enabled && onScope(s.key)}
            >
              {s.label}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ── compact stats readout + legend below the chart ──
   Value colors mirror the chart palette; written as Tailwind arbitrary-value classes (not the JS
   consts) since Tailwind's JIT only detects static class literals. ── */
function Stats({
  set,
  fmt,
  total,
}: {
  set: DistributionSet;
  fmt: (v: number) => string;
  total: number;
}) {
  const pctl = Math.round(set.current_percentile);
  const ord = ordinal(pctl);
  return (
    <div className="mt-4">
      <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
        <StatRow label="Current" value={fmt(set.current_value)} valueClass="text-[#0f766e]" />
        <StatRow label="Percentile" value={`${pctl}${ord}`} valueClass="text-(--text-primary)" />
        <StatRow label="Mean" value={fmt(set.mean)} valueClass="text-[#b08d3e]" />
        <StatRow
          label="Std dev"
          value={set.stdev != null ? fmt(set.stdev) : "—"}
          valueClass="text-(--text-primary)"
        />
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-(--text-secondary)">
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block h-3 w-0.5 bg-[#0f766e]" /> Current
        </span>
        <span className="inline-flex items-center gap-1.5">
          <svg width="16" height="6" aria-hidden="true">
            <line x1="0" y1="3" x2="16" y2="3" stroke="#b08d3e" strokeWidth="1.5" strokeDasharray="4 2" />
          </svg>
          Mean
        </span>
        <span className="text-(--text-muted)">n = {total}</span>
      </div>
    </div>
  );
}

function StatRow({
  label,
  value,
  valueClass,
}: {
  label: string;
  value: string;
  valueClass: string;
}) {
  return (
    <div className="flex items-center justify-between gap-2 border-b border-(--panel-border) py-1.5 last:border-0">
      <span className="text-(--text-secondary)">{label}</span>
      <span className={`font-semibold tabular-nums ${valueClass}`}>{value}</span>
    </div>
  );
}

function ordinal(n: number): string {
  const v = n % 100;
  if (v >= 11 && v <= 13) return "th";
  switch (n % 10) {
    case 1:
      return "st";
    case 2:
      return "nd";
    case 3:
      return "rd";
    default:
      return "th";
  }
}
