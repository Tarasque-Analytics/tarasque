import type { SHAPSnapshot } from "./database"

const API_BASE_URL = "http://localhost:8000/api";


// NOTE: Add and subtract from payload here
export interface ModelDataPayload {
  version: string;
  run_date: string;
  spec_hash: string;
  n_tickers: number;
  horizons: string[];
  shap: SHAPSnapshot[];
}

export async function loadModelData(symbol: string): Promise<ModelDataPayload> {
  try {

    // For now just query both endpoints, if we move forward with this. We should just 
    const [modelMeta, modelData] = await Promise.all([
      fetch(`${API_BASE_URL}/model`),
      fetch(`${API_BASE_URL}/model/${symbol}`)
    ]);

    if (!modelMeta.ok) {
      throw new Error(`Failed to fetch model metadata: ${modelMeta.statusText}`);
    }

    if (!modelData.ok) {
      if (modelData.status === 404) {
        throw new Error(`No data found for symbol: ${symbol}`);
      }
      throw new Error(`Failed to fetch data for ${symbol}: ${modelData.statusText}`);
    }

    const metaData = await modelMeta.json();
    const data = await modelData.json();

    return {
      version: metaData.model_version,
      run_date: metaData.run_date,
      spec_hash: metaData.spec_hash,
      n_tickers: metaData.n_tickers,
      horizons: metaData.horizons,
      shap: data.shap
    };

  } catch (error) {
    console.error(`Error loading ticker data for ${symbol}:`, error);
    throw error;
  }
}
