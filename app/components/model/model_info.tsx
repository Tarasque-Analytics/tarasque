// Lists the model information of a run: version, run/retrain date, n_tickers, horizons, notes
// in a nice box with each piece of information on a seperate line
// Contains a search bar for symbols that redirects you to model/:symbol

function DataRow({ label, value }: { label: string; value: string | number | null }) {
  return (
    <div className="flex justify-between py-1">
      <span className="text-sm text-gray-300">{label}</span>
      <span className="text-sm text-white font-medium">{value ?? "N/A"}</span>
    </div>
  );
}

export default function ModelInfo() {
  return (
    <div className="panel p-5 space-y-0 text-sm">
      {/* Model Run Info */}
      <DataRow label="Version" value="67.420.69"/>
      <DataRow label="Date Ran" value="6/8/2026"/>
      <DataRow label="Horizons" value="[21, 63, 126]"/>
      <DataRow label="Notes" value="These are placebo values for now"/>
    </div>
  )
}