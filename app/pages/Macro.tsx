// Macro dashboard — scaffolding pending finance-team content + a future /api/macro endpoint.
// 3-column layout mirrors /equity/:symbol (pages/Ticker.tsx): grid-cols-16 @ 3 / 10 / 3.
// Section components live under app/components/macro/. No data layer is wired in this pass; every
// section renders placeholder / Empty content. See app/CLAUDE.md ("Macro page").
export default function Macro() {
  return (
    <div className="grid grid-cols-16 gap-4">
      {/* Left col — watchlist / stats */}
      <div className="col-span-3 flex flex-col gap-4">{/* TODO(stage 3): watchlist */}</div>

      {/* Center col — regime centerpiece */}
      <div className="col-span-10 flex flex-col gap-6">
        {/* TODO(stage 2): next_fomc (#134) */}
        {/* TODO(stage 2): macro_regime_overview (#135) */}
        {/* TODO(stage 2): regime_scatter (#132/#133) */}
        {/* TODO(stage 3): sector_heatmap */}
      </div>

      {/* Right col — commentary / events */}
      <div className="col-span-3 flex flex-col gap-6">
        {/* TODO(stage 3): macro_ai_overview */}
        {/* TODO(stage 3): wedge_dispersion */}
        {/* TODO(stage 3): macro_events */}
      </div>
    </div>
  );
}
