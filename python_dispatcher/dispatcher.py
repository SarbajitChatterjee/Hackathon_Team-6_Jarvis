# This script runs locally (or on a server). 
# It watches for PENDING portfolios and "fans out" the work by creating rows in track_requests.

# Prerequisite: You need your Supabase URL and Service Role Key (from Supabase Settings > API).

import os
import time
from supabase import create_client, Client
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# CONFIGURATION
SUPABASE_URL = os.getenv("SUPABASE_URL") # or "https://your-project.supabase.co"
SUPABASE_KEY = os.getenv("SUPABASE_KEY") # Use SERVICE_ROLE key to bypass RLS if needed

if not SUPABASE_URL or not SUPABASE_KEY:
    print("Error: Supabase credentials missing.")
    exit()

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def process_portfolios():
    print("👀 Watching for PENDING portfolios...")
    
    # 1. Fetch 'PENDING' portfolios
    response = supabase.table("portfolios").select("*").eq("status", "PENDING").execute()
    portfolios = response.data

    if not portfolios:
        return # No work to do

    for portfolio in portfolios:
        p_id = portfolio['id']
        tickers = portfolio['input_tickers'] # This is a list ['AAPL', 'MSFT']
        print(f"⚡ Processing Portfolio: {portfolio['name']} ({len(tickers)} tickers)")

        # 2. Update Portfolio to 'PROCESSING' so we don't pick it up again
        supabase.table("portfolios").update({"status": "PROCESSING"}).eq("id", p_id).execute()

        # 3. Insert rows into 'track_requests'
        requests_data = []
        for ticker in tickers:
            requests_data.append({
                "portfolio_id": p_id,
                "ticker": ticker,
                "status": "PENDING"  # n8n will pick this up
            })
        
        if requests_data:
            # Bulk insert is more efficient
            data = supabase.table("track_requests").insert(requests_data).execute()
            print(f"   ✅ Created {len(requests_data)} track_requests for {portfolio['name']}")

while True:
    try:
        process_portfolios()
    except Exception as e:
        print(f"❌ Error: {e}")
    
    time.sleep(5) # Poll every 5 seconds