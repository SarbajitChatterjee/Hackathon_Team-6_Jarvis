# ==============================================================================
# Version: 1.6.1
# Maintainer: Jarvis DevOps Team
# Context: Microservice for fetching financial data for Fama-French models and AI Analysis.
#
# ------------------------------------------------------------------------------
# ARCHITECTURAL DECISION RECORD (ADR)
# ------------------------------------------------------------------------------
# 1. PRICE DATA SOURCE:
#    - DECISION: Use Yahoo Finance v8 Chart API (`/v8/finance/chart`).
#    - REASON: The standard `yfinance.history()` wrapper is unstable and often blocked.
#      The Chart API is the backend for the Yahoo website charts and is highly reliable.
#      It natively provides "adjusted close" prices, which are critical for return calculations.
#
# 2. FUNDAMENTAL DATA STRATEGY (CLOUD-AWARE HYBRID):
#    - PRIMARY: FinViz (Web Scraping).
#      - REASON: Provides P/E, Market Cap, and Sector data without strict rate limits.
#      - CONSTRAINT: FinViz often blocks Cloud IPs (AWS/Azure) with "Challenge Pages".
#    - FALLBACK 1: Yahoo Ticker.info (Official Wrapper).
#      - REASON: Used specifically when FinViz returns empty tables (Cloud Block).
#      - ROLE: Fills critical missing fields like 'Sector' and 'Market Cap'.
#    - SECONDARY: AlphaVantage (Official API).
#      - REASON: Provides qualitative data ('longBusinessSummary') that FinViz lacks.
#      - CONSTRAINT: Free tier limited to 25 requests/day. Logic includes explicit rate-limit handling.
#
# 3. COMPANY NAME RESOLUTION:
#    - CHALLENGE: The standard Yahoo Search API (`/v1/search`) is heavily blocked (429 errors).
#    - SOLUTION: We extract the legal company name from the Chart API metadata (Source 1),
#      falling back to the `yfinance` wrapper (Source 2), and finally FinViz (Source 3).
# 
# 4. FALLBACK CHAIN:
#    - FinViz (Primary) -> Often blocks Cloud IPs.
#    - Yahoo Ticker.info (Fallback) -> Used ONLY if FinViz fails. Fills Sector/MarketCap.
#    - AlphaVantage (Secondary) -> Always used for Description (25/day limit).
# ==============================================================================

from __future__ import annotations

# --- Standard Library Imports ---
import os
import time
import random
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Literal, Optional, Dict, Any

# --- Third-Party Imports ---
import numpy as np            # Required for vectorized Log Return calculations
import pandas as pd           # Data manipulation and DataFrame construction
import requests               # HTTP requests (Synchronous)
from bs4 import BeautifulSoup # HTML Parsing for FinViz
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
import yfinance as yf         # Official Yahoo wrapper (used as fallback)

# ==============================================================================
# CONFIGURATION & LOGGING
# ==============================================================================

# Configure logging to stdout (Standard Output)
# This ensures logs are captured by Docker/Kubernetes/CloudWatch drivers.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("JarvisDataService")

APP_TITLE = "Jarvis Market Data Service"
APP_VERSION = "1.6.1"

# [STRATEGY] User-Agent Rotation
# We use a curated list of "Desktop" User-Agents.
# Why? FinViz and Yahoo often serve simplified "Mobile" pages to mobile UAs,
# which lack the data tables we need to scrape. We need to look like a Chrome/Mac user.
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0"
]

app = FastAPI(title=APP_TITLE, version=APP_VERSION)


# ==============================================================================
# DATA MODELS (Pydantic)
# ==============================================================================

class PortfolioRequest(BaseModel):
    """
    Request payload for batch data ingestion.
    Validates input before processing to prevent SQL injection or logic errors.
    """
    batch_id: Optional[str] = Field(default=None, description="Trace ID for logging/debugging.")
    tickers: List[str] = Field(..., min_length=1, description="List of ticker symbols (e.g., ['IBM', 'GE']).")
    start_date: str = Field(..., description="ISO 8601 (YYYY-MM-DD) or US Format (MM/DD/YYYY).")
    end_date: str = Field(..., description="ISO 8601 (YYYY-MM-DD) or US Format (MM/DD/YYYY).")
    interval: Literal["1d", "1wk", "1mo"] = "1d"
    
    # Calculation Flags
    include_returns: bool = Field(default=True, description="If True, calculates Simple and Log returns.")
    strict: bool = True
    
    # Resilience Settings
    retries: int = 3
    backoff_base_seconds: float = 0.5


class ResolveRequest(BaseModel):
    """Payload for resolving a single ticker to its legal company name."""
    ticker: str


class CompanyNameResponse(BaseModel):
    """Standardized response for name resolution."""
    ticker: str
    company_name: str


@dataclass
class FetchResult:
    """Internal DTO to standardize results from different fetch strategies."""
    df: pd.DataFrame
    source: str


# ==============================================================================
# UTILITY FUNCTIONS
# ==============================================================================

def _to_unix_utc_midnight(s: str) -> int:
    """
    Normalizes input date strings (ISO or US format) to Unix Timestamp (UTC Midnight).
    Required by Yahoo Finance API parameters 'period1' and 'period2'.
    
    Args:
        s (str): Date string (e.g., "2023-01-01" or "01/01/2023")
    
    Returns:
        int: Unix timestamp
    """
    s = s.strip()
    try:
        # Detect format based on separator
        dt = datetime.strptime(s, "%m/%d/%Y") if "/" in s else datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        # Fallback for edge cases, defaults to today to prevent crash
        logger.error(f"Date parse failed for {s}, defaulting to now.")
        dt = datetime.now()
        
    # Force UTC timezone for consistency across servers
    dt_utc = datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)
    return int(dt_utc.timestamp())


def _require_api_key(x_api_key: Optional[str]) -> None:
    """
    Middleware-style check for Service API Key.
    Only enforced if SERVICE_API_KEY environment variable is set.
    """
    expected = os.getenv("SERVICE_API_KEY")
    if expected and x_api_key != expected:
        logger.warning("Unauthorized access attempt (Invalid API Key).")
        raise HTTPException(status_code=401, detail="Invalid API key")


# ==============================================================================
# CORE LOGIC A: PRICE & RETURNS (Quantitative)
# ==============================================================================

def _fetch_chart(
    ticker: str, 
    start_date: str, 
    end_date: str, 
    interval: str, 
    retries: int, 
    backoff: float
) -> FetchResult:
    """
    Fetches OHLCV data using the undocumented Yahoo Finance v8 Chart API.
    
    Features:
    - Robust 429 (Too Many Requests) handling with exponential backoff.
    - Automatic User-Agent rotation.
    - Returns a clean DataFrame with 'datetime' and 'close'.
    """
    period1 = _to_unix_utc_midnight(start_date)
    period2 = _to_unix_utc_midnight(end_date) + 86400 # Add 24h buffer to include end_date

    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    params = {
        "period1": period1, 
        "period2": period2, 
        "interval": interval, 
        "events": "div,splits", 
        "includeAdjustedClose": "true" # Critical for Total Return calculations
    }
    
    # Rotate UA for every request to look like distinct users
    headers = {"User-Agent": random.choice(USER_AGENTS)}

    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=10)
            
            # [HANDLING 429s]: Yahoo soft-bans IPs that hit too fast.
            # We catch this specifically and wait longer than normal.
            if r.status_code == 429:
                logger.warning(f"[CHART] 429 Rate Limit for {ticker}. Retrying in {backoff * (2**attempt)}s...")
                time.sleep(backoff * (2 ** attempt))
                continue
                
            r.raise_for_status()
            
            data = r.json()
            
            # [VALIDATION]: Ensure the payload actually contains chart data
            result_block = (data.get("chart", {}).get("result") or [None])[0]
            if not result_block: 
                raise ValueError("Empty chart result payload (Ticker might be delisted)")

            ts = result_block.get("timestamp", [])
            quote = result_block.get("indicators", {}).get("quote", [{}])[0]
            
            # Construct DataFrame
            df = pd.DataFrame({
                "datetime": pd.to_datetime(ts, unit="s", utc=True).strftime("%Y-%m-%d"),
                "close": quote.get("close")
            })
            
            # Data Cleaning: Drop rows where close is NaN (market holidays/glitches)
            df.dropna(subset=["close"], inplace=True)
            
            return FetchResult(df=df, source="chart")

        except Exception as e:
            # Only raise on the final attempt
            if attempt == retries - 1: 
                logger.error(f"[CHART] Final failure for {ticker}: {e}")
                raise e
            time.sleep(backoff)
    
    raise ValueError("Max retries reached")


# ==============================================================================
# CORE LOGIC B: COMPANY INFO (Qualitative / Hybrid)
# ==============================================================================

def _fetch_finviz_data(ticker: str, session: requests.Session) -> dict:
    """
    [PRIMARY STRATEGY] Scrapes company fundamentals from FinViz.
    
    ANTI-BOT MEASURES:
    - Uses a 'Session' to maintain cookies.
    - Sends 'Human-Like' headers (Referer: Google, Accept-Language: en-US).
    - Detects 'Challenge Pages' (Cloudflare blocks) by checking for table existence.
    """
    url = f"https://finviz.com/quote.ashx?t={ticker}"
    
    # Emulate a real browser navigating from Google Search
    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Referer": "https://www.google.com/",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
    }
    
    try:
        r = session.get(url, headers=headers, timeout=10)
        if r.status_code != 200: return {}

        soup = BeautifulSoup(r.text, 'html.parser')
        
        # [VALIDATION]: Check if the main data table exists.
        # If missing, we likely hit a Captcha/Bot check page (Common on AWS IPs).
        table = soup.find('table', class_='snapshot-table2')
        if not table:
            logger.warning(f"[FINVIZ] Table missing for {ticker}. Possible Cloud IP Block.")
            return {}

        data = {}
        for row in table.find_all('tr'):
            cols = row.find_all('td')
            for i in range(0, len(cols), 2):
                if i+1 < len(cols):
                    data[cols[i].text.strip()] = cols[i+1].text.strip()

        # [LENIENT PARSING]: We need at least the Sector to call this a success.
        if "Sector" not in data:
            return {}

        # Helper to parse "2.5B", "100M", etc.
        def parse_mc(s):
            if not s or s == "-": return 0
            s = s.replace(",", "")
            mult = {"T": 1e12, "B": 1e9, "M": 1e6, "K": 1e3}
            for suffix, m in mult.items():
                if suffix in s.upper():
                    try: return int(float(s.upper().replace(suffix, "")) * m)
                    except: pass
            return 0

        return {
            "sector": data.get("Sector"),
            "marketCap": parse_mc(data.get("Market Cap")),
            # Safe float conversion: handle "-" or missing keys
            "forwardPE": float(data.get("Forward P/E")) if data.get("Forward P/E") not in ["-", None] else None,
            "dividendYield": float(data.get("Dividend %").replace("%", ""))/100 if data.get("Dividend %") not in ["-", None] else 0.0
        }
    except Exception as e:
        logger.error(f"[FINVIZ] Error parsing {ticker}: {e}")
        return {}


def _fetch_yahoo_fallback(ticker: str) -> dict:
    """
    [FALLBACK STRATEGY] Uses yfinance when FinViz blocks us.
    
    Why: FinViz blocks Data Center IPs (AWS/Azure). Yahoo is more lenient with official wrappers.
    Fills: Sector, MarketCap, ForwardPE, DividendYield.
    """
    try:
        # yfinance.Ticker().info fetches the JSON summary
        yf_ticker = yf.Ticker(ticker)
        info = yf_ticker.info
        
        return {
            "sector": info.get("sector"),
            "marketCap": info.get("marketCap", 0),
            "forwardPE": info.get("forwardPE"),
            "dividendYield": info.get("dividendYield")
        }
    except Exception as e:
        logger.warning(f"[YAHOO-FALLBACK] Failed for {ticker}: {e}")
        return {}


def _fetch_alphavantage_data(ticker: str) -> dict:
    """
    [SECONDARY STRATEGY] Fetches qualitative data (Description) from AlphaVantage.
    
    NOTE: This API has a strict 25 request/day limit on the free tier.
    We explicitly check for the "API call frequency" error message.
    """
    api_key = os.getenv("ALPHA_VANTAGE_API_KEY")
    if not api_key: return {}

    url = "https://www.alphavantage.co/query"
    params = {"function": "OVERVIEW", "symbol": ticker, "apikey": api_key}
    
    try:
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
        
        # [RATE LIMIT CHECK]: AlphaVantage returns a 200 OK with a specific Note field on error
        if "Note" in data and "API call frequency" in data["Note"]:
            logger.error(f"[ALPHAVANTAGE] Rate Limit Hit for {ticker} (25/day limit).")
            return {"error": "RateLimit"}
            
        return {
            "longBusinessSummary": data.get("Description"),
            "targetMeanPrice": float(data.get("AnalystTargetPrice")) if data.get("AnalystTargetPrice") not in ["None", None] else None
        }
    except Exception as e:
        logger.error(f"[ALPHAVANTAGE] Error {ticker}: {e}")
        return {}


def _fetch_company_info_hybrid(ticker: str, session: requests.Session) -> dict:
    """
    Orchestrator Pattern with 3-Layer Redundancy.
    
    Flow:
    1. Try FinViz (Preferred, Unlimited).
    2. If FinViz fails (Cloud Block), Try Yahoo Fallback (Fills Sector/MarketCap).
    3. Always try AlphaVantage (For Description), unless Rate Limited.
    """
    result = {"longBusinessSummary": None, "sector": None, "marketCap": 0, "source": "Failed"}
    
    # --- Step 1: FinViz (Primary) ---
    finviz = _fetch_finviz_data(ticker, session)
    if finviz:
        result.update(finviz)
        result["source"] = "FinViz"
    
    # --- Step 2: Yahoo Fallback (If FinViz blocked) ---
    # Logic: If we still don't have a Sector, FinViz likely failed.
    if not result["sector"]:
        logger.info(f"[{ticker}] FinViz data missing/blocked. Engaging Yahoo Fallback...")
        yahoo = _fetch_yahoo_fallback(ticker)
        if yahoo:
            # Only fill missing fields (don't overwrite if FinViz worked partially)
            if not result["sector"]: result["sector"] = yahoo.get("sector")
            if not result["marketCap"]: result["marketCap"] = yahoo.get("marketCap")
            if not result["forwardPE"]: result["forwardPE"] = yahoo.get("forwardPE")
            
            # Update source tracking
            if result["source"] == "Failed": 
                result["source"] = "YahooFallback"
            else:
                result["source"] += "+Yahoo"

    # --- Step 3: AlphaVantage (Secondary) ---
    av = _fetch_alphavantage_data(ticker)
    if av and "error" not in av:
        result.update(av)
        
        # [FIXED LOGIC]: Ensure source reflects AlphaVantage success even if FinViz failed
        if result["source"] == "Failed":
             result["source"] = "AlphaVantage"
        else:
             result["source"] += "+AlphaVantage"
             
    elif av.get("error") == "RateLimit":
        result["source"] += "(AV Limit)"

    return result


# ==============================================================================
# CORE LOGIC C: NAME RESOLUTION
# ==============================================================================

def _get_name_from_chart_api(ticker: str) -> Optional[str]:
    """
    Extracts company name from Yahoo Chart API Metadata.
    This is the most reliable method as it bypasses the blocked 'quoteSummary' endpoint.
    """
    try:
        # Request minimal data (range=1d) just to get the metadata block
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=1d"
        headers = {"User-Agent": random.choice(USER_AGENTS)}
        r = requests.get(url, headers=headers, timeout=5)
        
        if r.status_code == 200:
            meta = r.json()['chart']['result'][0]['meta']
            # Prefer official longName, fallback to shortName
            return meta.get('longName') or meta.get('shortName')
    except Exception:
        pass
    return None

# ==============================================================================
# API ENDPOINTS
# ==============================================================================

@app.post("/company/name", response_model=CompanyNameResponse)
def resolve_company_profile(req: ResolveRequest, x_api_key: Optional[str] = Header(default=None)):
    """
    [ENDPOINT] Resolves a ticker to its official legal name.
    
    Strategy Hierarchy:
    1. Chart API Metadata (Fastest, High Reliability).
    2. yfinance .info (Official, but often blocked by 429s).
    3. FinViz Scraper (Fallback for last resort).
    """
    _require_api_key(x_api_key)
    ticker = req.ticker.strip().upper()
    
    # STRATEGY 1: Chart API
    name = _get_name_from_chart_api(ticker)
    if name: 
        logger.info(f"[RESOLVE] Success (ChartAPI): {ticker} -> {name}")
        return {"ticker": ticker, "company_name": name}

    # STRATEGY 2: yfinance (Likely to fail if IP is soft-banned, but good backup)
    try:
        yf_ticker = yf.Ticker(ticker)
        info = yf_ticker.info
        name = info.get("longName") or info.get("shortName")
        if name: return {"ticker": ticker, "company_name": name}
    except Exception: pass

    # STRATEGY 3: FinViz (Scraping Fallback)
    # Only runs if both Yahoo methods fail (rare).
    try:
        logger.info(f"[{ticker}] Trying FinViz Name Resolution Fallback...")
        session = requests.Session()
        # Re-use the existing scraper logic but tailored for the Title tag
        headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Referer": "https://www.google.com/"
        }
        url = f"https://finviz.com/quote.ashx?t={ticker}"
        r = session.get(url, headers=headers, timeout=5)
        
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, 'html.parser')
            title = soup.find('title')
            # Format: "IBM - International Business Machines - Stock Price..."
            if title and title.text:
                parts = title.text.split(" - ")
                if len(parts) >= 2:
                    # Clean: "International Business Machines"
                    clean_name = parts[1].split(" Stock Price")[0].strip()
                    logger.info(f"[RESOLVE] Success (FinViz Cleaned): {ticker} -> {clean_name}")
                    return {"ticker": ticker, "company_name": clean_name}
    except Exception: pass
    
    # Default: Return ticker if all else fails
    logger.warning(f"[{ticker}] Name Resolution Failed. Returning ticker.")
    return {"ticker": ticker, "company_name": ticker}


@app.post("/portfolio/json")
def portfolio_json(req: PortfolioRequest, x_api_key: Optional[str] = Header(default=None)):
    """
    [ENDPOINT] Main Data Ingestion.
    Fetches Price Data (Quantitative) and Company Info (Qualitative).
    """
    _require_api_key(x_api_key)
    tickers = [t.upper() for t in req.tickers]
    output = []
    
    # Use a shared Session for connection pooling (faster scraping)
    session = requests.Session()
    
    for t in tickers:
        # [THROTTLING] Random sleep between 5s-15s.
        # This is critical to prevent Yahoo/FinViz from banning the IP.
        sleep_time = random.uniform(5.0, 15.0)
        logger.info(f"Processing {t}... sleeping {sleep_time:.2f}s")
        time.sleep(sleep_time)
        
        # 1. Fetch Price Data
        try:
            res = _fetch_chart(t, req.start_date, req.end_date, req.interval, req.retries, req.backoff_base_seconds)
            df = res.df.copy()
            
            # --- Returns Engine ---
            # Calculates Simple Returns (daily %) and Log Returns (for statistical models)
            if req.include_returns and not df.empty:
                df['simple_return'] = df['close'].pct_change()
                df['log_return'] = np.log(df['close'] / df['close'].shift(1))
                df.fillna(0, inplace=True) # First row will be NaN/Inf
            
            ohlcv = df.replace({float('nan'): None}).to_dict(orient="records")
        except Exception as e:
            logger.error(f"Price fetch failed for {t}: {e}")
            ohlcv = []

        # 2. Fetch Company Info (Hybrid + Fallback)
        info = _fetch_company_info_hybrid(t, session)
        
        output.append({
            "ticker": t,
            "batch_id": req.batch_id,
            "raw_ohlcv": ohlcv,
            "raw_tickerinfo": info
        })

    return output


# ==============================================================================
# ENTRY POINT
# ==============================================================================
if __name__ == "__main__":
    import uvicorn
    # Host 0.0.0.0 is required for Docker containers to be accessible externally
    # Port 8000 is standard for FastAPI
    uvicorn.run(app, host="0.0.0.0", port=8000)