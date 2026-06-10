// Lists the model information of a run: version, run/retrain date, n_tickers, horizons, notes
// in a nice box with each piece of information on a seperate line
// Contains a search bar for symbols that redirects you to model/:symbol
import { useEffect, useState } from "react";
import { loadLatestModelRun } from "~/utils/database";

function DataRow({ label, value }: { label: string; value: string | number | null }) {
  return (
    <div className="model-data-row">
      <span className="model-data-row-label">{label}</span>
      <span className="model-data-row-value">{value ?? "N/A"}</span>
    </div>
  );
}

export default function ModelInfo() {
  const [runDate, setRunDate] = useState("")
  const [version, setVersion] = useState("")
  
  useEffect(() => {
    loadLatestModelRun().then((run) => {
      setRunDate(run?.run_date || "")
      setVersion(run?.model_version || "")
    })
  }, [])

  return (
    <div className="panel p-5 space-y-0 text-sm">
      {/* Model Run Info */}
      <DataRow label="Version" value={version} />
      <DataRow label="Date Ran" value={runDate} />
    </div>
  );
}
