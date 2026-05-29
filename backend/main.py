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
    get_events
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
        raise HTTPException(status_code=500, detail=f"Error fetching tickers: {str(e)}")


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
        raise HTTPException(
            status_code=500,
            detail=f"Invalid JSON format for {symbol}: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching data for {symbol}: {str(e)}"
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
                "volatility_history": list[dict],       # 5 years of vol/IV/forecast data
                "price_history": list[dict],            # 1 year of OHLCV data
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
        raise HTTPException(status_code=500, detail=f"Equity data cannot be found for {symbol}: {str(e)}")
    
    

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
