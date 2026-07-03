"""
FastAPI backend for the Volarbear app.

Serves per-equity volatility/options data to the frontend from Supabase via the `database.py`
query helpers. Main endpoint: GET /api/equity/{symbol} (composite payload); GET /api/equities
lists active tickers for the search. See backend/CLAUDE.md for the data-source overview.
"""

import asyncio
import os
import traceback
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from backend import database
from backend.database import (
    get_active_tickers,
    get_ai_overview,
    get_events,
    get_latest_model_run,
    get_model,
    get_options_chain,
    get_price_history,
    get_security_data,
    get_shap_snapshot,
    get_volatility_history,
)
from backend.distributions import build_distribution_data
from supabase import acreate_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    # initialize our supabase instance before server start

    # Load .env from project root (parent of backend directory)
    env_path = Path(__file__).parent.parent / ".env"

    if env_path.exists():
        load_dotenv(env_path)

    url = os.environ.get("VITE_SUPABASE_URL")
    key = os.environ.get("VITE_SUPABASE_PUBLISHABLE_KEY")

    if not url or not key:
        raise RuntimeError(
            "Missing required environment variables. "
            f"VITE_SUPABASE_URL found: {bool(url)}, VITE_SUPABASE_PUBLISHABLE_KEY found: {bool(key)}"
        )

    supabase_client = await acreate_client(url, key)
    database.initialize_db(supabase_client)
    yield
    # In the future if anything needs to be done after closing the app, put it here


# Initialize FastAPI app
app = FastAPI(title="Volarbear Ticker API", version="1.0.0", lifespan=lifespan)

# Add CORS middleware to allow requests from the React frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "https://tarasqueanalytics.com",
        "https://www.tarasqueanalytics.com",
    ],  # Adjust for your frontend port
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Change to PostgreSQL check when implemented
@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "ok"}


@app.get("/api/equity/{symbol}")
async def get_equity_data(symbol: str):
    """
    Fetch comprehensive equity intelligence data for a given ticker symbol.

    This endpoint aggregates multiple data sources into a single payload for the
    /equity/:symbol page. All queries execute in parallel for optimal performance.

    Args:
        symbol (str): Ticker symbol (case-insensitive). E.g., 'AAPL', 'msft'

    Returns:
        dict: Composite equity data payload with the following structure:
            {
                "symbol": str,                          # Normalized uppercase ticker
                "security": dict,                       # Metadata: company_name, gics_sector/industry
                "volatility_history": list[dict],       # full available vol/IV/forecast history (paginated)
                "price_history": list[dict],            # full available OHLCV history (paginated)
                "options_chain": list[dict],            # Latest snapshot options
                "ai_overview": dict | None,             # Latest AI commentary
                "latest_shap_snapshot": list[dict],     # Latest SHAP features per horizon
                "distribution_data": list[dict],        # Stock-scope RV/IV/VRP histograms per lookback
                "events": list[dict]                    # Past year of events
            }
    """
    symbol = symbol.upper()
    try:
        security_metadata = await get_security_data(symbol)
        sec_id = security_metadata["security_id"]

        # gather everything async
        vol_hist, price_hist, options, ai_overview, shap, events = await asyncio.gather(
            get_volatility_history(sec_id),
            get_price_history(sec_id),
            get_options_chain(sec_id),
            get_ai_overview(sec_id),
            get_shap_snapshot(sec_id),
            get_events(sec_id),
        )

        # Distributions are computed in plain Python from the vol_hist we already fetched — no
        # second DB query and NOT part of the gather (the old cross-sectional get_distribution RPC
        # hit a 57014 statement timeout). build_distribution_data never raises (returns [] on no
        # data), so it can't fail this composite payload. Stock scope only; sector/market deferred.
        distribution_data = build_distribution_data(vol_hist)

        return {
            "symbol": symbol,
            # Curated security metadata for the page header (company name + sector/industry
            # badges). get_security_data already loaded the full row to resolve security_id.
            "security": {
                "security_id": sec_id,
                "ticker": security_metadata.get("ticker"),
                "company_name": security_metadata.get("company_name"),
                "gics_sector": security_metadata.get("gics_sector"),
                "gics_industry": security_metadata.get("gics_industry"),
                "gics_subindustry": security_metadata.get("gics_subindustry"),
                "sector_etf": security_metadata.get("sector_etf"),
            },
            "volatility_history": vol_hist,
            "price_history": price_hist,
            "options_chain": options,
            "ai_overview": ai_overview,
            "latest_shap_snapshot": shap,
            "distribution_data": distribution_data,
            "events": events,
        }
    except HTTPException:
        raise  # Re-raise HTTPException as-is to preserve status codes
    except Exception as e:
        print(f"Exception thrown: {str(e)}", flush=True)
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Equity data cannot be found for {symbol}")


@app.get("/api/equities")
async def get_available_equities():
    """List active equity ticker symbols (DB-backed) for the ticker search.

    Returns:
        dict: {"equities": list[str], "count": int}
    """
    equities = await get_active_tickers()
    return {"equities": equities, "count": len(equities)}


@app.get("/api/model-runs/latest")
async def get_latest_model_run_data():
    """Latest model run for the navbar status bubble: {model_version, run_date}.

    Drives the version pill + "Last refresh" date. 404 if no runs exist yet (the frontend
    falls back to a placeholder).
    """
    run = await get_latest_model_run()
    if run is None:
        raise HTTPException(status_code=404, detail="No model runs found")
    return run


@app.get("/api/model")
async def getModel():
    """Fetch all global model metadata.

    Returns metadata about all model runs (not tied to any specific ticker).
    Used by the /model landing page to display model versions, training dates,
    and other global run information.

    Returns:
        dict: Model runs data with structure:
            {
                "runs": list[dict]  # Each run has:
                    {
                        "model_version": str,
                        "run_date": str,
                    }
            }

    Raises:
        HTTPException: 404 if no model runs exist in the database.
        HTTPException: 500 if model data cannot be retrieved.
    """

    try:
        # NOTE: as we decide on the shape of the payload, just add or subtract fields here
        allRuns = await asyncio.gather(get_model())
    except Exception as e:
        print(f"Exception thrown: {str(e)}", flush=True)
        raise HTTPException(status_code=500, detail="Model data could not be found")

    # NOTE: and here
    return {"runs": allRuns}


@app.get("/api/model/{symbol}")
async def getModelDataForSymbol(symbol: str):
    """Fetch model output data (SHAP features) for a specific ticker symbol.

    Retrieves the latest SHAP (SHapley Additive exPlanations) snapshot for a given symbol,
    which provides feature importance and model interpretability for model predictions
    across different horizons. Used by the /model/:symbol page.

    Args:
        symbol (str): Ticker symbol (case-insensitive). E.g., 'AAPL', 'msft'

    Returns:
        dict: Model output payload with structure:
            {
                "shap": list[dict]  # Latest SHAP features per horizon
            }

    Raises:
        HTTPException: 404 if the ticker symbol is not found or has no model data.
        HTTPException: 500 if model data cannot be retrieved.
    """
    try:
        security_metadata = await get_security_data(symbol)
        sec_id = security_metadata["security_id"]

        # NOTE: as we decide on the shape of the payload, just add or subtract fields here
        latest_shap_snapshot = await asyncio.gather(get_shap_snapshot(sec_id))

        # NOTE: and here
        return {"shap": latest_shap_snapshot}

    except Exception as e:
        print(f"Exception thrown: {str(e)}", flush=True)
        raise HTTPException(
            status_code=500, detail=f"Model data could not be found for symbol: {symbol}"
        )


@app.get("/api/dashboard")
async def get_dashboard():
    return {}


@app.get("/api/sector/{sector}")
async def get_sector_data(sector: str):
    return {}


@app.get("/api/macro/sectors")
async def get_macro_sectors():
    
    xlk, xly, xlp, xle, xlf, xlv, xli, xlb, xlre, xlu = await asyncio.gather(
        get_volatility_history(922996),      # XLK - Technology
        get_volatility_history(1000229),     # XLY - Consumer Discretionary
        get_volatility_history(1027928),     # XLP - Consumer Staples
        get_volatility_history(1104652),     # XLE - Energy
        get_volatility_history(1097914),     # XLF - Financials
        get_volatility_history(1158140),     # XLV - Health Care
        get_volatility_history(1193125),     # XLI - Industrials
        get_volatility_history(1209210),     # XLB - Materials
        get_volatility_history(1623815),     # XLRE - Real Estate
        get_volatility_history(1485465),     # XLU - Utilities
    )
    
    return {
        "xlk": xlk,
        "xly": xly,
        "xlp": xlp,
        "xle": xle,
        "xlf": xlf,
        "xlv": xlv,
        "xli": xli,
        "xlb": xlb,
        "xlre": xlre,
        "xlu": xlu,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
