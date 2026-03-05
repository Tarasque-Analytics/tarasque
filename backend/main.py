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

# Initialize FastAPI app
app = FastAPI(title="Volarbear Ticker API", version="1.0.0")

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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
