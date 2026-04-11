import wrds
import pandas as pd
import os
from datetime import datetime
from dateutil.relativedelta import relativedelta

# --- 1. CONFIGURATION ---
START_DATE = "2016-03-01"
END_DATE = datetime.today().strftime('%Y-%m-%d')

# Change this to the exact drive letter of your M.2 SSD
BASE_DIR = r"D:\Tarasque_DB" 

os.makedirs(os.path.join(BASE_DIR, "options"), exist_ok=True)

# --- 2. AUTHENTICATION ---
print("[SYSTEM] Connecting to WRDS PostgreSQL...")
db = wrds.Connection() 
print("[SYSTEM] Connection established.")

# --- 3. TIME CHUNKING ---
# We chunk by month. If you ask WRDS for 10 years at once, it will kill the connection.
start = datetime.strptime(START_DATE, "%Y-%m-%d")
end = datetime.strptime(END_DATE, "%Y-%m-%d")

current = start

while current < end:
    next_month = current + relativedelta(months=1)
    chunk_end = next_month if next_month < end else end
    
    start_str = current.strftime("%Y-%m-%d")
    end_str = chunk_end.strftime("%Y-%m-%d")
    
    print(f"[EXTRACT] Querying OptionMetrics opprcd: {start_str} to {end_str}...")

    # --- 4. THE OPTIMIZED SQL QUERY ---
    # We force the WRDS servers to filter the garbage before it hits your network
    sql_query = f"""
            SELECT 
                secid, 
                date, 
                days, 
                delta, 
                impl_volatility
            FROM optionm.vsurfd
            WHERE date >= '{start_str}' 
            AND date < '{end_str}'
            AND days = 30 
            AND delta IN (50, 25, -25)
        """
    
    try:
        # Execute query and load directly into RAM
        df = db.raw_sql(sql_query)
        
        if not df.empty:
            # --- 5. PARTITIONED PARQUET STORAGE ---
            year_dir = os.path.join(BASE_DIR, "options", f"year={current.year}")
            month_dir = os.path.join(year_dir, f"month={current.month:02d}")
            os.makedirs(month_dir, exist_ok=True)
            
            file_path = os.path.join(month_dir, "data.parquet")
            
            # Write using pyarrow for maximum compression and M.2 write speed
            df.to_parquet(file_path, engine='pyarrow', compression='snappy', index=False)
            print(f"[SUCCESS] Saved {len(df)} rows to {file_path}")
        else:
            print(f"[SKIP] No tradable options found for {start_str}.")
            
    except Exception as e:
        print(f"[FATAL] WRDS connection or query failed at {start_str}: {e}")
        break 
        
    # Free up memory before the next loop
    del df 
    current = next_month

db.close()
print("[SYSTEM] Extraction loop complete.")