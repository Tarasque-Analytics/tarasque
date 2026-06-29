import { useMemo, useState } from "react";
import {
  Chart as ChartJS,
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
import type { VolatilityRecord } from "~/utils/database";
import { Card, Empty } from "~/components/ui/section";

ChartJS.register(LinearScale, PointElement, LineElement, Tooltip, Filler);

/* ── graph-specific palette (kept local to this chart; shared UI colors live in app.css).
   Canvas can't resolve CSS vars, so these are literals — same convention as the price chart. ── */
const MODEL_LINE = "#0f766e"; // teal — pfv_cal model forecast (solid)
const IV_LINE = "#3b82f6"; // blue — implied vol (dashed)
const WEDGE_FILL = "rgba(193, 168, 120, 0.22)"; // tan — IV/model premium shading
const WEDGE_TEXT = "#9a7b33"; // amber-brown — wedge/ratio readouts + on-chart callout
const SEL_LABEL = "#374151"; // selected-horizon "H=.." label (mirrors --text-secondary)
const AXIS_TEXT = "#9ca3af"; // mirrors --text-muted (light)
const GRID = "rgba(0, 0, 0, 0.05)";

/* ── horizon definitions ──
   RV/model horizons are in TRADING days (252/yr); the IV columns are in CALENDAR days
   (365.25/yr), so each model horizon maps to a differently-named IV column describing the
   SAME horizon (21 trading ≈ 30 cal, 63 ≈ 91, 126 ≈ 182). Both series are plotted at the
   trading-day x — the mismatch is a column-name mapping, not an x-offset. */
const HORIZONS = [
  { h: 21, cal: 30, model: "pfv_cal_21", iv: "iv_atm_30d" },
  { h: 63, cal: 91, model: "pfv_cal_63", iv: "iv_atm_91d" },
  { h: 126, cal: 182, model: "pfv_cal_126", iv: "iv_atm_182d" },
] as const;

type HorizonKey = (typeof HORIZONS)[number]["h"];

type HorizonPoint = {
  h: HorizonKey;
  cal: number;
  model: number | null; // annualized %, or null if the source column is missing
  iv: number | null; // annualized %, or null
};

/* ── overlay plugin ──
   Draws the per-horizon "H=.." labels (selected one bolded) and the "<ratio>× wedge" callout
   between the curves at the selected horizon. Like the price chart's eventMarkers plugin it
   reads everything from chart.options (which react-chartjs-2 refreshes each render) rather than
   a closure, so it never redraws stale positions after the selected horizon changes. */
type OverlayLabel = { x: number; modelY: number | null; selected: boolean };
type OverlayCallout = { x: number; ivY: number; modelY: number; ratioText: string } | null;

declare module "chart.js" {
  // `TType` must match chart.js's generic for declaration merging — intentionally unused here.
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  interface PluginOptionsByType<TType extends ChartType> {
    fvfOverlay?: { labels: OverlayLabel[]; callout: OverlayCallout };
  }
}

const fvfOverlayPlugin: Plugin<"line"> = {
  id: "fvfOverlay",
  afterDatasetsDraw(chart) {
    // chart.options is deeply partial in chart.js's types; we always write the full shape.
    const opts = chart.options.plugins?.fvfOverlay as
      | { labels: OverlayLabel[]; callout: OverlayCallout }
      | undefined;
    if (!opts) return;
    const { ctx, scales } = chart;
    const xScale = scales.x;
    const yScale = scales.y;
    if (!xScale || !yScale) return;
    ctx.save();

    // "H=.." labels just below each model point.
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    for (const l of opts.labels) {
      if (l.modelY == null) continue;
      const px = xScale.getPixelForValue(l.x);
      const py = yScale.getPixelForValue(l.modelY) + 12;
      ctx.font = l.selected
        ? "700 11px ui-sans-serif, system-ui, sans-serif"
        : "500 10px ui-sans-serif, system-ui, sans-serif";
      ctx.fillStyle = l.selected ? SEL_LABEL : AXIS_TEXT;
      ctx.fillText(`H=${l.x}`, px, py);
    }

    // "<ratio>× wedge" callout between the curves at the selected horizon (live IV/σ̂ ratio).
    const c = opts.callout;
    if (c) {
      const px = xScale.getPixelForValue(c.x) + 10;
      const py = (yScale.getPixelForValue(c.ivY) + yScale.getPixelForValue(c.modelY)) / 2;
      ctx.textAlign = "left";
      ctx.textBaseline = "middle";
      ctx.fillStyle = WEDGE_TEXT;
      ctx.font = "700 13px ui-sans-serif, system-ui, sans-serif";
      ctx.fillText(`${c.ratioText} wedge`, px, py - 7);
      ctx.fillStyle = AXIS_TEXT;
      ctx.font = "500 10px ui-sans-serif, system-ui, sans-serif";
      ctx.fillText("IV / model premium", px, py + 8);
    }
    ctx.restore();
  },
};

/* ── formatters ── */
const pct = (v: number | null) => (v == null ? "—" : `${v.toFixed(1)}%`);
const pp = (v: number | null) =>
  v == null ? "—" : `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(1)} pp`;
const ratioFmt = (v: number | null) => (v == null ? "—" : `${v.toFixed(2)}×`);

const parseDay = (iso: string) => new Date(`${iso}T00:00:00`);
const longDate = (iso: string) =>
  parseDay(iso).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });

/**
 * Forward Vol Forecast for /equity/:symbol — volatility term-structure chart.
 *
 * Plots the model's predicted RV (pfv_cal) against the market's implied vol across three
 * horizons (H = 21 / 63 / 126), with the premium (wedge) shaded between, plus a selector-driven
 * side panel. Reads the latest `volatility_history` row via useEquityData() (loader →
 * EquityDataContext → here); useEquityData() may be null (DB call is non-fatal) — handled below.
 */
export default function ForwardVolForecast() {
  const equity = useEquityData();
  const [selectedH, setSelectedH] = useState<HorizonKey>(126);

  // Most recent volatility row that actually carries a model term structure. Falls back through
  // earlier rows if the very latest is missing the pfv_cal columns.
  const row = useMemo<VolatilityRecord | null>(() => {
    const rows = (equity?.volatility_history ?? []) as VolatilityRecord[];
    for (let i = rows.length - 1; i >= 0; i--) {
      const r = rows[i];
      if (r.pfv_cal_21 != null || r.pfv_cal_63 != null || r.pfv_cal_126 != null) return r;
    }
    return null;
  }, [equity]);

  // Build the three horizon points (annualized decimals → %); null columns become null points.
  const points = useMemo<HorizonPoint[]>(() => {
    if (!row) return [];
    return HORIZONS.map((d) => {
      const model = row[d.model];
      const iv = row[d.iv];
      return {
        h: d.h,
        cal: d.cal,
        model: model == null ? null : model * 100,
        iv: iv == null ? null : iv * 100,
      };
    });
  }, [row]);

  const selected = points.find((p) => p.h === selectedH) ?? null;
  const haveSel = selected != null && selected.model != null && selected.iv != null;
  const selWedge = haveSel ? (selected!.iv as number) - (selected!.model as number) : null;
  const selRatio =
    haveSel && (selected!.model as number) !== 0
      ? (selected!.iv as number) / (selected!.model as number)
      : null;

  if (!equity) {
    return (
      <Card>
        <Header selectedH={selectedH} onSelect={setSelectedH} asOf={null} />
        <Empty>Forward vol data is currently unavailable.</Empty>
      </Card>
    );
  }

  if (!row || points.every((p) => p.model == null && p.iv == null)) {
    return (
      <Card>
        <Header selectedH={selectedH} onSelect={setSelectedH} asOf={null} />
        <Empty>No volatility term structure available for {equity.symbol}.</Empty>
      </Card>
    );
  }

  // Y axis: floor pinned at 0, top auto-fit to the plotted values with ~12% padding. X axis fixed.
  const ys: number[] = [];
  for (const p of points) {
    if (p.model != null) ys.push(p.model);
    if (p.iv != null) ys.push(p.iv);
  }
  const yLo = Math.min(...ys);
  const yHi = Math.max(...ys);
  const yMax = yHi + (yHi - yLo || yHi) * 0.12;

  const isSel = (ctx: ScriptableContext<"line">) =>
    (ctx.raw as { x: number } | undefined)?.x === selectedH;

  const data: ChartData<"line", { x: number; y: number }[]> = {
    datasets: [
      {
        label: "Model forecast",
        data: points.filter((p) => p.model != null).map((p) => ({ x: p.h, y: p.model as number })),
        borderColor: MODEL_LINE,
        backgroundColor: MODEL_LINE,
        borderWidth: 2,
        cubicInterpolationMode: "monotone",
        pointStyle: "circle",
        pointBackgroundColor: MODEL_LINE,
        pointBorderColor: MODEL_LINE,
        pointRadius: (ctx) => (isSel(ctx) ? 6 : 4),
        pointHoverRadius: (ctx) => (isSel(ctx) ? 7 : 5),
        fill: false,
        order: 2,
      },
      {
        label: "Implied vol",
        data: points.filter((p) => p.iv != null).map((p) => ({ x: p.h, y: p.iv as number })),
        borderColor: IV_LINE,
        backgroundColor: WEDGE_FILL,
        borderWidth: 2,
        borderDash: [6, 4],
        cubicInterpolationMode: "monotone",
        pointStyle: "crossRot",
        pointBorderColor: IV_LINE,
        pointBorderWidth: 2,
        pointRadius: (ctx) => (isSel(ctx) ? 8 : 6),
        pointHoverRadius: (ctx) => (isSel(ctx) ? 9 : 7),
        // Shade the premium: fill from the IV curve down to the model curve (dataset index 0).
        fill: { target: 0, above: WEDGE_FILL, below: WEDGE_FILL },
        order: 1,
      },
    ],
  };

  const options: ChartOptions<"line"> = {
    responsive: true,
    maintainAspectRatio: false,
    animation: false,
    interaction: { mode: "x", intersect: false },
    plugins: {
      legend: { display: false },
      tooltip: {
        callbacks: {
          title: (items) => {
            if (!items.length) return "";
            const p = points.find((pt) => pt.h === items[0].parsed.x);
            return p ? `H = ${p.h}d  (≈ ${p.cal}d cal)` : `H = ${items[0].parsed.x}d`;
          },
          label: (ctx) =>
            `${ctx.dataset.label}: ${ctx.parsed.y == null ? "—" : ctx.parsed.y.toFixed(1)}%`,
          afterBody: (items) => {
            const p = points.find((pt) => pt.h === items[0]?.parsed.x);
            if (!p || p.model == null || p.iv == null) return [];
            const r = p.model === 0 ? null : p.iv / p.model;
            return ["", `Wedge: ${pp(p.iv - p.model)}`, `Ratio: ${ratioFmt(r)}`];
          },
        },
      },
      // Overlay reads from options (not a closure) so labels/callout track the selected horizon.
      fvfOverlay: {
        labels: points.map((p) => ({ x: p.h, modelY: p.model, selected: p.h === selectedH })),
        callout:
          haveSel && selRatio != null
            ? {
                x: selected!.h,
                ivY: selected!.iv as number,
                modelY: selected!.model as number,
                ratioText: ratioFmt(selRatio),
              }
            : null,
      },
    },
    scales: {
      x: {
        type: "linear",
        // Curves end at the last data point (H=126); the right margin past it mirrors the
        // pre-21d margin on the left (min=10 → ~11d before the first point), so 126 + 11 ≈ 137.
        min: HORIZONS[0].h - 11,
        max: HORIZONS.at(-1)!.h + 11,
        grid: { display: false },
        afterBuildTicks: (axis: Scale) => {
          axis.ticks = HORIZONS.map((d) => ({ value: d.h }));
        },
        ticks: {
          color: AXIS_TEXT,
          autoSkip: false,
          callback: (v) => `${v}d`,
        },
      },
      y: {
        min: 0,
        max: yMax,
        afterFit: (scale) => {
          scale.width = 52;
        },
        grid: { color: GRID },
        ticks: {
          color: AXIS_TEXT,
          maxTicksLimit: 5,
          callback: (v) => `${Number(v).toFixed(0)}%`,
        },
      },
    },
  };

  return (
    <Card>
      <Header selectedH={selectedH} onSelect={setSelectedH} asOf={row.date} />

      <div className="mt-4 flex flex-col gap-4 lg:flex-row">
        <div className="relative h-80 min-w-0 flex-1">
          <Chart type="line" data={data} options={options} plugins={[fvfOverlayPlugin]} />
        </div>
        {/* Right column: info table on top, legend pinned to the bottom (mt-auto). The column
            stretches to the chart height on lg, so the legend bottom-aligns with the chart. */}
        <div className="flex flex-col lg:w-56">
          <Panel
            selectedH={selectedH}
            model={selected?.model ?? null}
            iv={selected?.iv ?? null}
            wedge={selWedge}
            ratio={selRatio}
          />
          <Legend />
        </div>
      </div>
    </Card>
  );
}

/* ── header: title · subtitle · HORIZON selector ── */
function Header({
  selectedH,
  onSelect,
  asOf,
}: {
  selectedH: HorizonKey;
  onSelect: (h: HorizonKey) => void;
  asOf: string | null;
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h2 className="text-2xl font-bold tracking-tight text-(--text-primary)">
          Forward Vol Forecast
        </h2>
        <p className="mt-0.5 text-sm text-(--text-muted)">
          pfv_cal model · annualized · term structure
          {asOf && <span> · as of {longDate(asOf)}</span>}
        </p>
      </div>

      <div className="flex items-center gap-2">
        <span className="text-xs font-semibold tracking-wide text-(--text-muted) uppercase">
          Horizon
        </span>
        <div className="segmented">
          {HORIZONS.map((d) => (
            <button
              key={d.h}
              type="button"
              className="segmented-btn"
              data-active={selectedH === d.h}
              onClick={() => onSelect(d.h)}
            >
              {d.h}d
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ── right panel: "AT H = <selected>" breakdown, driven by the selector.
   Value colors mirror the chart palette above; they're written as Tailwind arbitrary-value
   classes (not the JS consts) because Tailwind's JIT only detects static class literals. ── */
function Panel({
  selectedH,
  model,
  iv,
  wedge,
  ratio,
}: {
  selectedH: HorizonKey;
  model: number | null;
  iv: number | null;
  wedge: number | null;
  ratio: number | null;
}) {
  return (
    <div className="w-full rounded-lg border border-(--panel-border) bg-(--track-bg) p-4">
      <div className="text-xs font-semibold tracking-wide text-(--text-muted) uppercase">
        At H = {selectedH}d
      </div>
      <div className="mt-3 text-sm">
        <PanelRow label="Model σ̂" value={pct(model)} valueClass="text-[#0f766e]" />
        <PanelRow label="Implied σ" value={pct(iv)} valueClass="text-[#3b82f6]" />
        <PanelRow label="Wedge" value={pp(wedge)} valueClass="text-[#9a7b33]" />
        <PanelRow label="Ratio (IV/σ̂)" value={ratioFmt(ratio)} valueClass="text-[#9a7b33]" />
      </div>
    </div>
  );
}

function PanelRow({
  label,
  value,
  valueClass,
}: {
  label: string;
  value: string;
  valueClass: string;
}) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-(--panel-border) py-2 first:pt-0 last:border-0 last:pb-0">
      <span className="text-(--text-secondary)">{label}</span>
      <span className={`font-semibold tabular-nums ${valueClass}`}>{value}</span>
    </div>
  );
}

/* ── custom legend (chart.js legend disabled so we control colors/markers) ── */
function Legend() {
  return (
    <div className="mt-auto flex flex-col gap-2 pt-4 text-xs text-(--text-secondary)">
      <span className="inline-flex items-center gap-2">
        <svg width="22" height="8" aria-hidden="true">
          <line x1="0" y1="4" x2="22" y2="4" stroke={MODEL_LINE} strokeWidth="2.5" />
        </svg>
        Model forecast (pfv_cal)
      </span>
      <span className="inline-flex items-center gap-2">
        <svg width="22" height="8" aria-hidden="true">
          <line
            x1="0"
            y1="4"
            x2="22"
            y2="4"
            stroke={IV_LINE}
            strokeWidth="2.5"
            strokeDasharray="5 3"
          />
        </svg>
        Implied vol (mid-mkt)
      </span>
      <span className="inline-flex items-center gap-2">
        <span className="inline-block h-3 w-3 rounded-sm bg-[rgba(193,168,120,0.22)]" />
        Wedge / premium
      </span>
    </div>
  );
}
