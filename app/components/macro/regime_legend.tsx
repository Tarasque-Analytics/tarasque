// Side legend for the /macro regime scatter (#132/#133), split out of regime_scatter.tsx. Content
// is lens-aware: Lens A (cross-section regime) explains the encodings (blob size = Σ market cap,
// trails = recent history, and the two beta axes); Lens B (vol vs value) describes the four
// valuation × vol-percentile quadrants. Presentational scaffolding — no data.

export type RegimeLens = "regime" | "volvalue";

// Lens A — what the scatter's marks encode.
const REGIME_NOTES = [
  { title: "Blob size", body: "Σ market cap of the group." },
  { title: "Trails", body: "Recent history — where the group has been moving." },
  { title: "X · Market-reactivity β", body: "CAPM beta to the market." },
  { title: "Y · Mincer–Zarnowitz β", body: "Forecast-vs-realized calibration." },
];

// Lens B — the four quadrants of valuation (x) × vol percentile (y).
const VOLVALUE_QUADRANTS = [
  { title: "Cheap & Feared", body: "Cheap vs fair value, high vol percentile." },
  { title: "Rich & Anxious", body: "Rich vs fair value, high vol percentile." },
  { title: "Quietly Cheap", body: "Cheap vs fair value, low vol percentile." },
  { title: "Priced for Perfection", body: "Rich vs fair value, low vol percentile." },
];

export default function RegimeLegend({ lens }: { lens: RegimeLens }) {
  const items = lens === "volvalue" ? VOLVALUE_QUADRANTS : REGIME_NOTES;
  const heading = lens === "volvalue" ? "Quadrants" : "Reading the chart";
  return (
    <aside className="shrink-0 lg:w-56">
      <div className="text-xs font-semibold tracking-wide text-(--text-muted) uppercase">
        {heading}
      </div>
      <ul className="mt-2 space-y-2">
        {items.map((it) => (
          <li key={it.title}>
            <div className="text-sm font-semibold text-(--text-primary)">{it.title}</div>
            <div className="text-xs text-(--text-secondary)">{it.body}</div>
          </li>
        ))}
      </ul>
    </aside>
  );
}
