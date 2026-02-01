import time
import json
import requests
import yfinance as yf
from fastapi import FastAPI, Header
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

app = FastAPI(title="Jarvis Patent Service", version="1.0")

# --- DATA MODELS ---

class PatentRequest(BaseModel):
    tickers: List[str] = Field(..., description="List of stock tickers, e.g. ['AAPL', 'TSLA']")
    max_patents: int = Field(default=5, description="Max patents to fetch per company")
    start_date: Optional[str] = Field(default="2023-01-01", description="Filter patents granted after this date (YYYY-MM-DD)")

class PatentResponse(BaseModel):
    ticker: str
    company_name: str
    patents: List[Dict[str, Any]]
    status: str
    error: Optional[str] = None

class ResolveRequest(BaseModel):
    ticker: str

# --- HELPER FUNCTIONS ---

def get_company_name(ticker: str) -> Optional[str]:
    """
    Resolves 'AAPL' -> 'Apple Inc.' using yfinance.
    """
    try:
        stock = yf.Ticker(ticker)
        # Try longName first, fallback to shortName
        return stock.info.get('longName') or stock.info.get('shortName')
    except Exception as e:
        print(f"yfinance error for {ticker}: {e}")
        return None

def fetch_patents_view(company_name: str, api_key: str, start_date: str, max_results: int) -> List[Dict]:
    """
    Queries PatentsView v1 API for patents assigned to the organization.
    """
    url = "https://search.patentsview.org/api/v1/patent/"
    
    headers = {
        "X-Api-Key": api_key,
        "Accept": "application/json"
    }

    # Query: Organization Name AND Date range
    query = {
        "_and": [
            {"_text_phrase": {"assignees.assignee_organization": company_name}},
            {"_gte": {"patent_date": start_date}}
        ]
    }

    # Fields to return
    fields = ["patent_id", "patent_title", "patent_date", "patent_abstract", "assignees.assignee_organization"]
    
    # Sorting: Newest first
    sort = [{"patent_date": "desc"}]
    
    # Pagination
    options = {"per_page": max_results, "page": 1}

    params = {
        "q": json.dumps(query),  # Safe JSON conversion
        "f": json.dumps(fields),
        "o": json.dumps(options),
        "s": json.dumps(sort)
    }

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=15)
        
        if resp.status_code == 200:
            data = resp.json()
            return data.get("patents", [])
        else:
            print(f"PatentsView Error ({resp.status_code}): {resp.text}")
            return []
            
    except Exception as e:
        print(f"Exception querying PatentsView: {e}")
        return []

# --- ENDPOINTS ---

@app.get("/health")
def health():
    return {"status": "ok", "service": "Jarvis Patent Service"}

@app.post("/patents", response_model=List[PatentResponse])
def get_patents(
    req: PatentRequest, 
    x_api_key: str = Header(..., alias="X-PatentsView-Key")
):
    results = []

    for ticker in req.tickers:
        clean_ticker = ticker.strip().upper()
        
        # 1. Resolve Name
        company_name = get_company_name(clean_ticker)
        
        if not company_name:
            results.append({
                "ticker": clean_ticker,
                "company_name": "Unknown",
                "patents": [],
                "status": "failed",
                "error": "Could not resolve company name via yfinance"
            })
            continue

        # 2. Fetch Patents
        # Gentle pacing for the API
        time.sleep(0.5) 
        
        patents = fetch_patents_view(
            company_name=company_name,
            api_key=x_api_key,
            start_date=req.start_date,
            max_results=req.max_patents
        )

        results.append({
            "ticker": clean_ticker,
            "company_name": company_name,
            "patents": patents,
            "status": "success" if patents else "no_data",
            "error": None
        })

    return results

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)