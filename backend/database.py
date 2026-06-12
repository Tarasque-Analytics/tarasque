"""
Database operations for Volarbear Ticker API
Handles all Supabase queries for equity data
"""

from datetime import datetime, timedelta
from fastapi import HTTPException
from supabase import AsyncClient

# Global supabase instance - initialized in main.py
supabase: AsyncClient = None


def initialize_db(client: AsyncClient):
    """Initialize the database module with a supabase client"""
    global supabase
    supabase = client


async def get_security_data(symbol: str):
    """Get security metadata (ID, sector, etc.) for a ticker symbol"""
    symbol = symbol.upper()
    try:
        response = await (supabase.table("securities")
            .select("*")
            .eq("ticker", symbol)
            .execute()
        )
    except Exception as e:
        print(f"Exception at get_security_data: {str(e)}", flush=True)
        raise HTTPException(
            status_code=500,
            detail="Error fetching from securities table"
        )
    if not response.data:
        print(f"Symbol not found: {symbol}", flush=True)
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
        print(f"Exception at get_volatility_history: {str(e)}", flush=True)
        raise HTTPException(
            status_code=500,
            detail="Error fetching from volatility_history table"
        )
    return response.data


async def get_price_history(security_id: int):
    """Get the full available price history for a security (oldest -> newest).

    Pages through PostgREST's per-request row cap so the entire multi-year history is
    returned (some securities go back ~12 years), powering the chart's range selector
    (1M/3M/6M/YTD/1Y/2Y/5Y/MAX); the frontend filters the window client-side. Paging by
    ascending date keeps it correct even if the server caps rows per request.
    """
    PAGE = 1000
    rows: list = []
    offset = 0
    try:
        while True:
            response = await (supabase.table("prices_history")
                .select("*")
                .eq("security_id", security_id)
                .order("date", desc=False)
                .range(offset, offset + PAGE - 1)
                .execute()
            )
            batch = response.data or []
            rows.extend(batch)
            if len(batch) < PAGE:
                break
            offset += PAGE
    except Exception as e:
        print(f"Exception at get_price_history: {str(e)}", flush=True)
        raise HTTPException(
            status_code=500,
            detail="Error fetching from prices_history table"
        )

    return rows


async def get_options_chain(security_id: int):
    """Get latest options chain for a security"""
    try:
        # Get the most recent snapshot date
        latest_snapshot = await (supabase.table("options_chain")
            .select("snapshot_date")
            .eq("security_id", security_id)
            .order("snapshot_date", desc=True)
            .limit(1)
            .execute()
        )
        
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
            .execute()
        )
    except Exception as e:
        print(f"Exception at get_options_chain: {str(e)}", flush=True)
        raise HTTPException(
            status_code=500,
            detail="Error fetching from options_chain table"
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
            .or_("flagged.is.null,flagged.eq.false")
            .order("generated_at", desc=True)
            .limit(1)
            .execute()
        )
    except Exception as e:
        print(f"Exception at get_ai_overview: {str(e)}", flush=True)
        raise HTTPException(
            status_code=500,
            detail="Error fetching from ai_overview table"
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
            .execute()
        )
        
        if not latest_retrain.data:
            return []
        
        retrain_date = latest_retrain.data[0]["retrain_date"]
        
        # Get all horizons for the latest retrain
        response = await (supabase.table("shap_snapshot")
            .select("*")
            .eq("security_id", security_id)
            .eq("retrain_date", retrain_date)
            .execute()
        )
    except Exception as e:
        print(f"Exception at get_shap_snapshot: {str(e)}", flush=True)
        raise HTTPException(
            status_code=500,
            detail="Error fetching from shap_snapshot table"
        )
    
    return response.data


# TODO: re-enable in a separate PR once finance defines the distribution structure.
# The get_distribution RPC currently hits a Postgres statement timeout (code 57014).
# async def get_distribution(
#     security_id: int,
#     metric: str = "rv",
#     lookback_days: int = 1260
# ):
#     """Get distribution data (stock/sector/market scopes)"""
#     try:
#         response = await supabase.rpc(
#             "get_distribution",
#             {
#                 "p_security_id": security_id,
#                 "p_metric": metric,
#                 "p_lookback_days": lookback_days
#             }
#         ).execute()
#     except Exception as e:
#         print(f"Exception at get_distribution: {str(e)}", flush=True)
#         raise HTTPException(
#             status_code=500,
#             detail="Error fetching from get_distribution RPC"
#         )
#     return response.data


async def get_events(security_id: int):
    """Get all per-security events (event_history) for a security, oldest -> newest.

    Returns the full history (not just the past year) so the price-history chart can draw
    event-annotation lines across any selected range; the frontend filters to the visible
    window. Per-security events are sparse, so a single request suffices.
    """
    try:
        response = await (supabase.table("event_history")
            .select("*")
            .eq("security_id", security_id)
            .order("event_date", desc=False)
            .execute()
        )
    except Exception as e:
        print(f"Exception at get_events: {str(e)}", flush=True)
        raise HTTPException(
            status_code=500,
            detail="Error fetching from event_history table"
        )

    return response.data


async def get_latest_model_run():
    """Latest model run (version + run date) for the navbar status bubble.

    Returns the most recent row from model_runs as {model_version, run_date}, or None if the
    table is empty. model_runs needs the anon SELECT RLS policy to be readable through the Data
    API (already applied; same gotcha as event_history — see backend/CLAUDE.md).
    """
    try:
        response = await (supabase.table("model_runs")
            .select("model_version, run_date")
            .order("run_date", desc=True)
            .order("id", desc=True)
            .limit(1)
            .execute()
        )
    except Exception as e:
        # Log the raw error server-side; return a generic detail so internal Supabase/PostgREST
        # error text (schema/table internals) isn't leaked to API clients.
        print(f"Exception at get_latest_model_run: {str(e)}", flush=True)
        raise HTTPException(
            status_code=500,
            detail="Error fetching from model_runs table"
        )

    return response.data[0] if response.data else None
