"""
FastAPI Backend for Volarbear Ticker Data
Serves ticker payloads and manages ticker information.

TODO: PostgreSQL Integration
- Install psycopg2-binary: pip install psycopg2-binary
- Create database models using SQLAlchemy
- Replace file-based data loading with database queries
- Add connection pooling for performance
- Implement caching layer (Redis) for frequently accessed tickers
"""
import json
import os
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from supabase import acreate_client
import asyncio
from contextlib import asynccontextmanager
import traceback
from backend import database
from backend.database import (
    get_security_data,
    get_volatility_history,
    get_price_history,
    get_options_chain,
    get_ai_overview,
    get_shap_snapshot,
    # get_distribution,  # TODO: re-enable once finance defines distribution structure (separate PR)
    get_events,
    get_latest_model_run,
    get_model,
)



@asynccontextmanager
async def lifespan(app: FastAPI):
    # initialize our supabase instance before server start
    
    # Load .env from project root (parent of backend directory)
    env_path = Path(__file__).parent.parent / ".env"
    if not env_path.exists():
        raise RuntimeError(f".env file not found at {env_path}")
    
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
    allow_origins=["http://localhost:5173", "http://localhost:3000"],  # Adjust for your frontend port
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Path to data directory relative to this file
DATA_DIR = Path(__file__).parent.parent / "app" / "assets" / "data"

# Change to PostgreSQL check when implemented
@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "ok"}


@app.get("/api/tickers")
async def get_available_tickers():
    """
    Get list of all available ticker symbols.
    
    Returns:
        list[str]: List of ticker symbols with available data
        
    TODO: When PostgreSQL is integrated:
        - Query all tickers from the database
        - Add filtering options (sector, market_cap, etc.)
        - Implement pagination for large datasets
    """
    try:
        tickers = []
        
        # Scan data directory for *_Payload.json files
        if DATA_DIR.exists():
            for file in DATA_DIR.glob("*_Payload.json"):
                # Extract ticker symbol from filename (e.g., "MS_Payload.json" -> "MS")
                ticker = file.stem.replace("_Payload", "")
                tickers.append(ticker)
        
        # Sort alphabetically for consistent ordering
        tickers.sort()
        
        return {"tickers": tickers, "count": len(tickers)}
    
    except Exception as e:
        print(f"Exception at get_available_tickers: {str(e)}", flush=True)
        raise HTTPException(status_code=500, detail="Error fetching tickers")


@app.get("/api/tickers/{symbol}")
async def get_ticker_data(symbol: str):
    """
    Get payload data for a specific ticker.
    
    Args:
        symbol (str): Ticker symbol (case-insensitive)
    
    Returns:
        dict: Ticker payload containing metadata, charts, opportunities, etc.
        
    TODO: When PostgreSQL is integrated:
        - Query ticker data from the database
        - Validate ticker_id against allowed tickers
        - Cache expensive computations
        - Add real-time data fetching from market APIs
    """
    # Normalize symbol to uppercase
    symbol = symbol.upper()
    
    # Construct file path
    file_path = DATA_DIR / f"{symbol}_Payload.json"
    
    # Check if file exists
    if not file_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"No data found for symbol: {symbol}"
        )
    
    try:
        # Read and return JSON file
        with open(file_path, "r") as f:
            data = json.load(f)
        return data
    
    except json.JSONDecodeError as e:
        print(f"Exception at get_ticker_data (JSONDecodeError) for {symbol}: {str(e)}", flush=True)
        raise HTTPException(
            status_code=500,
            detail=f"Invalid JSON format for {symbol}"
        )
    except Exception as e:
        print(f"Exception at get_ticker_data for {symbol}: {str(e)}", flush=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching data for {symbol}"
        )

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
                "volatility_history": list[dict],       # 5 years of vol/IV/forecast data
                "price_history": list[dict],            # full available OHLCV history (paginated)
                "options_chain": list[dict],            # Latest snapshot options
                "ai_overview": dict | None,             # Latest AI commentary
                "latest_shap_snapshot": list[dict],     # Latest SHAP features per horizon
                # "distribution_data": list[dict],      # temporarily disabled — pending finance input (separate PR)
                "events": list[dict]                    # Past year of events
            }
    """
    symbol = symbol.upper()
    try:
        security_metadata = await get_security_data(symbol)
        sec_id = security_metadata["security_id"]

        # gather everything async
        # NOTE: distributions temporarily removed from the unpack/gather (see distribution PR)
        vol_hist, price_hist, options, ai_overview, shap, events = await asyncio.gather(
            get_volatility_history(sec_id),
            get_price_history(sec_id),
            get_options_chain(sec_id),
            get_ai_overview(sec_id),
            get_shap_snapshot(sec_id),
            # get_distribution(sec_id),  # TODO: re-enable in distribution PR
            get_events(sec_id)
        )
        
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
            # "distribution_data": distributions,  # TODO: re-enable in distribution PR
            "events": events
        }
    except HTTPException:
        raise  # Re-raise HTTPException as-is to preserve status codes
    except Exception as e:
        print(f"Exception thrown: {str(e)}", flush=True)
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Equity data cannot be found for {symbol}")
    
    

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
        raise HTTPException(status_code=500, detail=f"Model data could not be found")
    
    # NOTE: and here
    return  {
        "runs": allRuns
    }

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
        return {
            "shap": latest_shap_snapshot
        }
        
    except Exception as e:
        print(f"Exception thrown: {str(e)}", flush=True)
        raise HTTPException(status_code=500, detail=f"Model data could not be found for symbol: {symbol}")

@app.get("/api/dashboard")
async def get_dashboard():
    return {}

@app.get("/api/sector/{sector}")
async def get_sector_data(sector: str):
    return {}

@app.get("/api/macro")
async def get_macro_data():
    return {}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
