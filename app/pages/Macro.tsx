// Macro dashboard — scaffolding pending finance-team content + a future /api/macro endpoint.
// 3-column layout mirrors /equity/:symbol (pages/Ticker.tsx): grid-cols-16 @ 3 / 10 / 3.
// Section components live under app/components/macro/. No data layer is wired in this pass; every
// section renders placeholder / Empty content. See app/CLAUDE.md ("Macro page").
import MacroAiOverview from "~/components/macro/macro_ai_overview";
import MacroEvents from "~/components/macro/macro_events";
import MacroRegimeOverview from "~/components/macro/macro_regime_overview";
import NextFomc from "~/components/macro/next_fomc";
import RegimeScatter from "~/components/macro/regime_scatter";
import SectorHeatmap from "~/components/macro/sector_heatmap";
import Watchlist from "~/components/macro/watchlist";
import WedgeDispersion from "~/components/macro/wedge_dispersion";
import { MacroDataProvider } from "~/context/MacroDataContext";
import { loadMacroPayload, type MacroDataPayload } from "~/utils/macro";
import { supabase } from "../supabaseClient";
import { useState, useEffect } from "react";

export default function Macro() {

  const [uid, setUID] = useState("")
  const [payload, setPayload] = useState<MacroDataPayload | null>(null)
  
  useEffect(() => {
    const fetchUser = async () => {
      const user = (await supabase.auth.getUser()).data.user?.id;
      setUID(user || "");
    };
    fetchUser();
  }, [])
  
  useEffect(() => {
    if (!uid) return;
    
    const fetchPayload = async () => {
      const data = await loadMacroPayload(uid);
      setPayload(data);
    };
    
    fetchPayload();
  }, [uid])

  console.log(payload)
  return (
    <MacroDataProvider data={payload}>
      <div className="grid grid-cols-16 gap-4">
        {/* Left col — FOMC + watchlist / stats */}
        <div className="col-span-3 flex flex-col gap-4">
          <NextFomc />
          <Watchlist />
        </div>

        {/* Center col — regime centerpiece */}
        <div className="col-span-10 flex flex-col gap-6">
          <MacroRegimeOverview />
          <RegimeScatter />
          <SectorHeatmap />
        </div>

        {/* Right col — commentary / events */}
        <div className="col-span-3 flex flex-col gap-6">
          <MacroAiOverview />
          <WedgeDispersion />
          <MacroEvents />
        </div>
      </div>
    </MacroDataProvider>
  );
}
