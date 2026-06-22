import type { SHAPSnapshot, ModelRun } from "./database"

const API_BASE_URL = "http://localhost:8000/api";


// NOTE: Add and subtract from payload here
export interface ModelDataPayload {
  runs: ModelRun[];
  shap: SHAPSnapshot[] | null;
}

export async function loadModelData(symbol: string | undefined): Promise<ModelDataPayload> {
  try {
    const [modelRuns, modelData] = await Promise.all([
      fetch(`${API_BASE_URL}/model`),
      symbol ? fetch(`${API_BASE_URL}/model/${symbol}`) : Promise.resolve([]),
    ]);

    if (!modelRuns.ok) {
      throw new Error(`Failed to fetch model metadata: ${modelRuns.statusText}`);
    }

    if (modelData && modelData instanceof Response && !modelData.ok) {
      if (modelData.status === 404) {
        throw new Error(`No data found for symbol: ${symbol}`);
      }
      throw new Error(`Failed to fetch data for ${symbol}: ${modelData.statusText}`);
    }

    const runs = await modelRuns.json();
    const shap = modelData instanceof Response ? (await modelData.json()).shap : [];

    return {
      runs: runs,
      shap: shap
    };

  } catch (error) {
    console.error(`Error loading model data for ${symbol}:`, error);
    throw error;
  }
}
