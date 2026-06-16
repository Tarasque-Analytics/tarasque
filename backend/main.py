"""
FastAPI backend for the Volarbear app.

Serves per-equity volatility/options data to the frontend from Supabase via the `database.py`
query helpers. Main endpoint: GET /api/equity/{symbol} (composite payload); GET /api/equities
lists active tickers for the search. See backend/CLAUDE.md for the data-source overview.
"""
import os
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from supabase import acreate_client
import asyncio
from contextlib import asynccontextmanager
import traceback
from openrouter import OpenRouter
from backend import database
from backend.database import (
    get_active_tickers,
    get_security_data,
    get_volatility_history,
    get_price_history,
    get_options_chain,
    get_ai_overview,
    get_shap_snapshot,
    # get_distribution,  # TODO: re-enable once finance defines distribution structure (separate PR)
    get_events,
    get_latest_model_run
)



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
    allow_origins=["http://localhost:5173", "http://localhost:3000"],  # Adjust for your frontend port
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Change to PostgreSQL check when implemented
@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "ok"}

@app.get("/api/equity/aislop")
async def ai_overview():
    with OpenRouter(api_key = os.environ.get("llm_api_key")) as client:
        response = client.chat.send(
            model = "nvidia/nemotron-3-ultra-550b-a55b:free",
            messages = [
                {"role": "user",
                 "content": """Create jokes based on the "I am at a very Chinese time in my life" meme, where daily habits and logic are completely overtaken by Chinese cultural norms.

Each joke must follow this exact structure: [Mundane setup] + [Hilariously practical/traditional Chinese reaction] + "That is how Chinese my mind has become."""
                    }
            ]
        )
        return response.choices[0].message.content
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
