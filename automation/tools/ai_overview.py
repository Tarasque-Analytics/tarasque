"""

Automation to run daily not yet implemented.

This script prompts an external LLM to generate an open-ended summary of 
a given ticker based on metrics it was provided

"""
import os
import asyncio
import argparse
import sys
from fastapi import HTTPException
from datetime import datetime, timezone
from backend.distributions import build_distribution_data
from openrouter import OpenRouter
from ..db import WriteClient
from ..config import load_config

async def ai_slop(symbol: str, apply: bool = False):
    cfg = load_config()
    db = WriteClient(cfg.supabase, dry_run=False)
    await db.connect()
    symbol = symbol.upper()
    try:
        security_id_map = await db.resolve_security_ids([symbol])
        sec_id = security_id_map.get(symbol)

        vol_task = db._client.table("volatility_history").select("*").eq("security_id", sec_id).execute()
        price_task = db._client.table("prices_history").select("*").eq("security_id", sec_id).execute()
        event_task = db._client.table("event_history").select("*").eq("security_id", sec_id).execute()
        vol_resp, price_resp, event_resp = await asyncio.gather(vol_task, price_task, event_task)
        vol_hist = vol_resp.data or []
        price_hist = price_resp.data or []
        events = event_resp.data or []
        
    except HTTPException:
        raise  # Re-raise HTTPException as-is to preserve status codes
    except Exception as e:
        print(f"Exception thrown: {str(e)}", flush=True)
        raise HTTPException(status_code=500, detail=f"Equity data cannot be found for {symbol}")
        # Distributions are computed in plain Python from the vol_hist we already fetched — no
        # second DB query and NOT part of the gather (the old cross-sectional get_distribution RPC
        # hit a 57014 statement timeout). build_distribution_data never raises (returns [] on no
        # data), so it can't fail this composite payload. Stock scope only; sector/market deferred.
    distribution_data = build_distribution_data(vol_hist)
    
    # Tentative code for LLM. Replace if we're changing to another LLM, like an in-house model
    request = f"""
    
    Here are the statistics for a given ticker. You are to give an open ended summary
    interpretation of what they mean, avoiding giving any suggestions because that would be 
    very illegal.
    
    ticker: {symbol}
    volume history: {vol_hist[:5]}
    price history: {price_hist[:5]}
    events: {events[:5]}
    """
    async with OpenRouter(api_key = os.environ.get("llm_api_key")) as client:
        response = await client.chat.send_async(
            model = "nvidia/nemotron-3-ultra-550b-a55b:free",
            messages = [
                {"role": "user",
                    "content": request
                    }
            ]
        )
    
        actual_text = response.choices[0].message.content
        # Construct a database row matching the SQL definitions
        supabase_stuff = [{
            "security_id": sec_id,
            "content": actual_text,
            "model_ver": "nvidia/nemotron-3-ultra-550b-a55b:free",
            "prompt_ver": "7/19/26",
            "headline": "replace this text!",
            "generated_at": datetime.now(timezone.utc).isoformat()
        }]
     # Write 2 supabase using db.py    
        written = await db.upsert_ai_overview(supabase_stuff)
        return written
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m automation.tools.ai_overview",
        description="Generate and store open-ended daily AI interpretations."
    )
    parser.add_argument("--ticker", required=True, type=str, help="Target ticker (e.g. AAPL)")
    parser.add_argument("--apply", action="store_true", help="Perform live LLM prompts and write to Supabase.")
    args = parser.parse_args(argv)
    
    return asyncio.run(ai_slop(args.ticker, apply=args.apply))



if __name__ == "__main__":
    sys.exit(main())