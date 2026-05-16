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
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from supabase import acreate_client, Client, AsyncClient
import asyncio
from contextlib import asynccontextmanager

supabase : AsyncClient = None

# Supabase
@asynccontextmanager
async def lifespan(app: FastAPI):
    # using global here to purely define the supabase once before the server starts up
    # the acreate_client is an async function and thus needs to be in a async function as well
    global supabase
    load_dotenv("..\\.env")
    
    url = os.environ.get("VITE_SUPABASE_URL")
    key = os.environ.get("VITE_SUPABASE_PUBLISHABLE_KEY")
    supabase = await acreate_client(url, key)
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

    
@app.on_event("startup")
async def get_supabase_client():
    load_dotenv("..\\..\\.env")
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    supabase = await acreate_client(url, key)
    return supabase

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
                "distribution_data": list[dict],        # Stock/sector/market distributions
                "events": list[dict]                    # Past year of events
            }
    """
    symbol = symbol.upper()
    try:
        security_metadata = await get_security_data(symbol)
        sec_id = security_metadata["security_id"]
        gics_sector = security_metadata["gics_sector"]
        (vol_hist, price_hist, options, ai_overview, shap, distributions, events) = await asyncio.gather(
            get_volatility_history(sec_id),
            get_price_history(sec_id),
            get_options_chain(sec_id),
            get_ai_overview(sec_id),
            get_shap_snapshot(sec_id),
            get_distribution(sec_id),
            get_events(symbol, gics_sector)
        )
        
        return {
            "symbol": symbol,
            "volatility_history": vol_hist,
            "price_history": price_hist,
            "options_chain": options,
            "ai_overview": ai_overview,
            "latest_shap_snapshot": shap,
            "distribution_data": distributions,
            "events": events
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Equity data cannot be found for {symbol}: {str(e)}")
    
    

@app.get("/api/dashboard")
async def get_dashboard():
    return {}

@app.get("/api/sector/{sector}")
async def get_sector_data():
    
    return {}

@app.get("/api/macro")
async def get_macro_data():
    return {}

async def get_security_data(symbol: str):
    symbol = symbol.upper()
    # Get the security_id
    try:
        response =  await (supabase.table("securities")
            .select("*")
            .eq("ticker", symbol)
            .execute()
        )
    except Exception as e:
        raise HTTPException(
            status_code=404,
            detail=f"Error fetching from securities table: {e}"
        )
    if not response.data:
        raise HTTPException(
            status_code=404,
            detail=f"No security found for symbol: {symbol}"
        )
    return response.data[0]

async def get_volatility_history(security_id: int):
    """Get 5 years of volatility data for a security"""
    five_years_ago = (datetime.now() - timedelta(days=365*5)).strftime('%Y-%m-%d')
    try:
        response = await (supabase.table("volatility_history") 
            .select("*") 
            .eq("security_id", security_id) 
            .gte("date", five_years_ago) 
            .order("date", desc=False) 
            .execute()
        )
    except Exception as e:
        print("Exception at vol")
        raise HTTPException(
            status_code=404,
            detail=f"Error fetching from volatility_history table: {e}"
        )
    return response.data

async def get_price_history(security_id: int):
    """Get 1 year of price data for a security"""
    one_year_ago = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
    
    try:
        response = await (supabase.table("prices_history")
            .select("*")
            .eq("security_id", security_id)
            .gte("date", one_year_ago)
            .order("date", desc=False)
            .execute())
    except Exception as e:
        print("Exception at price")
        raise HTTPException(
            status_code=404,
            detail=f"Error fetching from prices_history table: {e}"
        )
    
    return response.data

async def get_options_chain(security_id: int):
    """Get latest options chain for a security"""
    try:
        # Get the most recent snapshot date
        latest_snapshot = await (supabase.table("options_chain")
            .select("snapshot_date")
            .eq("security_id", security_id)
            .order("snapshot_date", desc=True)
            .limit(1)
            .execute())
        
        if not latest_snapshot.data:
            return []
        
        snapshot_date = latest_snapshot.data[0]["snapshot_date"]
        
        # Get all options for that snapshot
        response = await (supabase.table("options_chain")
            .select("*")
            .eq("security_id", security_id)
            .eq("snapshot_date", snapshot_date)
            .order("expiry", desc=False)
            .order("strike", desc=False)
            .execute())
    except Exception as e:
        print("Exception at options")        
        raise HTTPException(
            status_code=404,
            detail=f"Error fetching from options_chain table: {e}"
        )
    
    return response.data

async def get_ai_overview(
    security_id: int,
    model_version: str = "v1",
    prompt_version: str = "v1"
):
    """Get latest AI overview for a security"""
    try:
        response = await (supabase.table("ai_overview")
            .select("*")
            .eq("security_id", security_id)
            .eq("model_ver", model_version)
            .eq("prompt_ver", prompt_version)
            .eq("flagged", False)
            .order("date", desc=True)
            .limit(1)
            .execute())
    except Exception as e:
        print("Exception at ai")   
        raise HTTPException(
            status_code=404,
            detail=f"Error fetching from ai_overview_equity table: {e}"
        )
    
    return response.data[0] if response.data else None

async def get_shap_snapshot(security_id: int):
    """Get latest SHAP snapshot per horizon for a security"""
    try:
        # Get the most recent retrain date
        latest_retrain = await (supabase.table("shap_snapshot")
            .select("retrain_date")
            .eq("security_id", security_id)
            .order("retrain_date", desc=True)
            .limit(1)
            .execute())
        
        if not latest_retrain.data:
            return []
        
        retrain_date = latest_retrain.data[0]["retrain_date"]
        
        # Get all horizons for the latest retrain
        response = await (supabase.table("shap_snapshot")
            .select("*")
            .eq("security_id", security_id)
            .eq("retrain_date", retrain_date)
            .execute())
    except Exception as e:
        print("Exception at shap")   
        raise HTTPException(
            status_code=404,
            detail=f"Error fetching from shap_snapshot table: {e}"
        )
    
    return response.data

async def get_distribution(
    security_id: int,
    metric: str = "rv",
    lookback_days: int = 1260
):
    """Get distribution data (stock/sector/market scopes)"""
    try:
        response = await supabase.rpc(
            "get_distribution",
            {
                "p_security_id": security_id,
                "p_metric": metric,
                "p_lookback_days": lookback_days
            }
        )
    except Exception as e:
        print("Exception at distribution")   
        raise HTTPException(
            status_code=404,
            detail=f"Error calling get_distribution RPC: {e}"
        )
    return response.data

async def get_events(symbol: str, gics_sector: str):
    """Get events for the past year (market, sector, and ticker-specific)"""
    one_year_ago = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
    
    try:
        # Get all events from the past year
        response = await (supabase.table("events_history")
            .select("*")
            .gte("event_date", one_year_ago)
            .execute())
        
        if not response.data:
            return []
        
        events = response.data
        
        # Filter for market events OR sector events OR ticker events
        filtered_events = [
            e for e in events
            if (e["scope"] == "market"
                or (e["scope"] == "sector" and e["scope_value"] == gics_sector)
                or (e["scope"] == "ticker" and e["scope_value"] == symbol))
        ]
        
        # Sort by severity then date
        severity_order = {"crisis": 0, "major": 1, "notable": 2}
        filtered_events.sort(
            key=lambda x: (severity_order.get(x["severity"], 3), x["event_date"]),
            reverse=True
        )
    except Exception as e:
        print("Exception at events")   
        raise HTTPException(
            status_code=404,
            detail=f"Error fetching from events_history table: {e}"
        )
    
    return filtered_events

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
