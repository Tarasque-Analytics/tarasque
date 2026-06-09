// Serves as the default page when no symbol has been specified. Shows details about the
// latest model run (version, run/retrain date, n_tickers, horizons, notes)

import ModelInfo from "~/components/model/model_info"
import ModelSearch from "~/components/ui/model_search"
export default function ModelLanding() {
  return (
    <div className="flex min-h-[60vh] items-center justify-center">
      <div className="w-full max-w-md space-y-2">
        <h3>Latest Model Run</h3>
        <ModelInfo/>
        <ModelSearch/>
      </div>
    </div>
  );
}
