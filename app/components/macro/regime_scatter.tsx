import { useState } from "react";
import { Card, Empty } from "~/components/ui/section";
import RegimeLegend, { type RegimeLens } from "./regime_legend";
import { useMacroData } from "~/context/MacroDataContext";
import { Chart as ChartJS, LinearScale, PointElement, Tooltip, Legend } from 'chart.js';
import { Scatter } from 'react-chartjs-2'
import type { SectorData } from "~/utils/macro";
import ChartDataLabels from "chartjs-plugin-datalabels";

ChartJS.register(LinearScale, PointElement, Tooltip, Legend);
// Regime scatter — the centerpiece of /macro, two lenses of one component (#132 + #133), switched by
// a Lens toggle:
//   • Lens A "Cross-section regime" (#132): x = CAPM / market-reactivity β, y = Mincer–Zarnowitz β;
//     blobs sized by Σ market cap, with trails showing recent history.
//   • Lens B "Vol vs Value" (#133): x = valuation (% vs RAFI fair value, cap-weighted),
//     y = vol percentile 0–100; colored by sector, with the four named quadrants.
// Both lenses also carry a View (Sector ↔ Tickers) and Horizon (21d / 63d / 126d) toggle.
//
// Scaffolding only: the Lens/View/Horizon toggles are real (.segmented + local useState) but
// PRESENTATIONAL — switching the active option only, with NO data fetch/effect. The body is the
// quadrant frame (axis titles + corner labels + side legend) over an Empty "pending data" plot
// area. The actual Chart.js scatter, trails, and per-sector coloring land in the finance-team
// content pass (no chart is built here — see app/CLAUDE.md "Macro page").

type ViewKey = "sector" | "tickers";
type HorizonKey = "21d" | "63d" | "126d";

type LensConfig = {
  title: string;
  subtitle: string;
  axes: { x: string; y: string };
  // Corner labels exist for Lens B only (#133); null for Lens A (#132).
  corners: { tl: string; tr: string; bl: string; br: string } | null;
};

interface RegimeDataPoint {
  x: number
  y: number
  label: string
  radius: number
}

const LENSES: Record<RegimeLens, LensConfig> = {
  regime: {
    title: "Cross-section regime",
    subtitle: "CAPM β × Mincer–Zarnowitz β · blobs sized by Σ market cap, with trails",
    axes: { x: "Market-reactivity β (CAPM)", y: "Mincer–Zarnowitz β" },
    corners: {
      tl: "Stealth Event-Risk",
      tr: "Idiosync + Systematic",
      bl: "Genuinely Calm",
      br: "Mega-Cap Buffer",
    },
  },
  volvalue: {
    title: "Vol vs Value",
    subtitle: "Valuation × vol percentile · colored by sector",
    axes: { x: "Valuation — % vs RAFI fair value (cap-weighted)", y: "Vol percentile (0–100)" },
    corners: {
      tl: "Cheap & Feared",
      tr: "Rich & Anxious",
      bl: "Quietly Cheap",
      br: "Priced for Perfection",
    },
  },
};

const LENS_OPTS: readonly { key: RegimeLens; label: string }[] = [
  { key: "regime", label: "Regime" },
  { key: "volvalue", label: "Vol vs Value" },
];
const VIEW_OPTS: readonly { key: ViewKey; label: string }[] = [
  { key: "sector", label: "Sector" },
  { key: "tickers", label: "Tickers" },
];
const HORIZON_OPTS: readonly { key: HorizonKey; label: string }[] = [
  { key: "21d", label: "21d" },
  { key: "63d", label: "63d" },
  { key: "126d", label: "126d" },
];

export default function RegimeScatter() {
  // Presentational toggle state only — no data effects (scaffolding).
  const [lens, setLens] = useState<RegimeLens>("regime");
  const [view, setView] = useState<ViewKey>("sector");
  const [horizon, setHorizon] = useState<HorizonKey>("63d");

  const cfg = LENSES[lens];

  return (
    <Card>
      <Header
        cfg={cfg}
        lens={lens}
        setLens={setLens}
        view={view}
        setView={setView}
        horizon={horizon}
        setHorizon={setHorizon}
      />

      <div className="mt-4 flex flex-col gap-6 lg:flex-row lg:items-stretch">
        <div className="flex-1">
          <div className="flex gap-2">
            {/* y-axis title (rotated alongside the frame) */}
            <div className="flex items-center justify-center">
              <span className="rotate-180 text-xs font-medium text-(--text-muted) [writing-mode:vertical-rl]">
                {cfg.axes.y}
              </span>
            </div>

            <div className="flex-1">
              <QuadrantFrame corners={cfg.corners} horizon={horizon} lens={lens}/>
              {/* x-axis title */}
              <div className="mt-2 text-center text-xs font-medium text-(--text-muted)">
                {cfg.axes.x}
              </div>
            </div>
          </div>
        </div>

        <RegimeLegend lens={lens} />
      </div>
    </Card>
  );
}

/* ── quadrant frame: bordered plot area with crosshair midlines, optional corner labels, and an
   Empty placeholder standing in for the (deferred) scatter. Plain markup — no Chart.js. ── */
function QuadrantFrame({ corners, horizon, lens }: { corners: LensConfig["corners"]; horizon: HorizonKey; lens: RegimeLens }) {  
  const data = useMacroData()

  
  const tlQuandrant: RegimeDataPoint[] = []
  const trQuandrant: RegimeDataPoint[] = []
  const blQuandrant: RegimeDataPoint[] = []
  const brQuandrant: RegimeDataPoint[] = []
  
  if (lens == "regime"  && data?.sectors) {
    const sectors = data?.sectors
  
    const getQuandrantMzBetaVsMktBeta = (mktB: number | null, mzB: number | null) => {
      if (mktB === null || mzB === null) {
        return null
      }
      if (mktB < 1 && mzB < 1) {
        return blQuandrant
      } else if (mktB < 1 && mzB > 1) {
        return tlQuandrant
      } else if (mktB > 1 && mzB < 1) {
        return brQuandrant
      } else { // (mktB > 1 && mzB > 1)
        return trQuandrant
      }
    }

    // sort the sectors into the appropriate quandrants
    for (const sector of sectors) {
      const latest_vol = sector.vol_history[0] ? sector.vol_history[0] : {beta_mkt_252d: Math.random() * 2, beta_mz_h21: Math.random() * 2, beta_mz_h63: Math.random() * 2, beta_mz_h126: Math.random() * 2}
      let quadrant = null
      const mkt_beta = latest_vol.beta_mkt_252d
      let mz_beta: number | null = null
      switch (horizon) {
        case "21d":
          mz_beta = latest_vol.beta_mz_h21
          break;
        case "63d":
          mz_beta = latest_vol.beta_mz_h63
          break;
        case "126d":
          mz_beta = latest_vol.beta_mz_h126
          break;
      }

      quadrant = getQuandrantMzBetaVsMktBeta(mkt_beta, mz_beta)
      if (quadrant && mkt_beta && mz_beta) {
        const point_radii = Math.max(sector.mkt_cap / 100000000000 * 5, 5)
        console.log(point_radii)
        quadrant.push({x: mkt_beta, y: mz_beta, label: sector.name, radius: point_radii})
      } else {
        // console.log(`Error plotting ${sector.name}`)
      }
    }
  } else if (lens == "volvalue") {

  }

  // Pre-compute radius arrays for each dataset
  const tlRadii = tlQuandrant.map(p => p.radius)
  const trRadii = trQuandrant.map(p => p.radius)
  const blRadii = blQuandrant.map(p => p.radius)
  const brRadii = brQuandrant.map(p => p.radius)
  console.log(blRadii)



  return (
    <div className="relative rounded-lg border border-(--panel-border) h-80">
      {/* crosshair midlines splitting the four quadrants */}
      <div className="absolute inset-y-0 left-1/2 w-px bg-(--panel-border)" aria-hidden="true" />
      <div className="absolute inset-x-0 top-1/2 h-px bg-(--panel-border)" aria-hidden="true" />

      {/* corner labels (Lens B only) */}
      {corners && (
        <>
          <CornerLabel className="left-8 top-2 text-left">{corners.tl}</CornerLabel>
          <CornerLabel className="right-3 top-2 text-right">{corners.tr}</CornerLabel>
          <CornerLabel className="bottom-7 left-8 text-left">{corners.bl}</CornerLabel>
          <CornerLabel className="bottom-7 right-3 text-right">{corners.br}</CornerLabel>
        </>
      )}

      {/* placeholder plot area */}
      <div className="absolute inset-0 rounded-lg overflow-hidden">
        <Scatter
          options={{
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            plugins: {
              legend: {
                display: false
              }
            },
            scales: {
              x: {
                type: 'linear',
                position: 'bottom',
                min: 0,
                max: 2
              },
              y: {
                min: 0,
                max: 2
              }
            }
          }}
          data={{
            datasets: [
              {
                label: 'tlQuandrant',
                data: tlQuandrant,
                backgroundColor: 'rgba(75, 192, 192, 0.6)',
                pointRadius: tlRadii
              },
              {
                label: 'trQuadrant',
                data: trQuandrant,
                backgroundColor: 'rgba(153, 102, 255, 0.6)',
                pointRadius: trRadii
              },
              {
                label: 'blQuadrant',
                data: blQuandrant,
                backgroundColor: 'rgba(255, 159, 64, 0.6)',
                pointRadius: blRadii
              },
              {
                label: 'brQuadrant',
                data: brQuandrant,
                backgroundColor: 'rgba(255, 99, 132, 0.6)',
                pointRadius: brRadii 
              }
            ]
          }}
      />
      </div>
    </div>
  );
}

function CornerLabel({ className, children }: { className?: string; children: string }) {
  return (
    <span
      className={`absolute max-w-[45%] text-xs font-semibold text-(--text-secondary) ${className ?? ""}`}
    >
      {children}
    </span>
  );
}

/* ── header: active-lens title + subtitle, and the Lens / View / Horizon segmented toggles ── */
function Header({
  cfg,
  lens,
  setLens,
  view,
  setView,
  horizon,
  setHorizon,
}: {
  cfg: LensConfig;
  lens: RegimeLens;
  setLens: (k: RegimeLens) => void;
  view: ViewKey;
  setView: (k: ViewKey) => void;
  horizon: HorizonKey;
  setHorizon: (k: HorizonKey) => void;
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <div className="flex flex-wrap items-center gap-x-2">
          <h2 className="text-2xl font-bold tracking-tight text-(--text-primary)">{cfg.title}</h2>
          <span className="badge badge-neutral">Regime scatter</span>
        </div>
        <p className="mt-0.5 text-sm text-(--text-muted)">{cfg.subtitle}</p>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <Segmented label="Lens" options={LENS_OPTS} value={lens} onChange={setLens} />
        <Segmented label="View" options={VIEW_OPTS} value={view} onChange={setView} />
        <Segmented label="Horizon" options={HORIZON_OPTS} value={horizon} onChange={setHorizon} />
      </div>
    </div>
  );
}

/* ── one .segmented toggle group; marks the active option via data-active (mirrors the equity
   sections). Switches the active option only — no data side effects. ── */
function Segmented<T extends string>({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: readonly { key: T; label: string }[];
  value: T;
  onChange: (k: T) => void;
}) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-xs font-semibold tracking-wide text-(--text-muted) uppercase">
        {label}
      </span>
      <div className="segmented">
        {options.map((o) => (
          <button
            key={o.key}
            type="button"
            className="segmented-btn"
            data-active={value === o.key}
            onClick={() => onChange(o.key)}
          >
            {o.label}
          </button>
        ))}
      </div>
    </div>
  );
}
