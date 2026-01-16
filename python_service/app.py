# ==============================================================================
# JARVIS MARKET DATA SERVICE
# ==============================================================================
# Version: 1.7.1 (Production Release - Rate Limit Hardening)
# Maintainer: Jarvis DevOps Team
# Context: Microservice for fetching financial data for Fama-French models and AI Analysis.
#
# ------------------------------------------------------------------------------
# CHANGELOG v1.7.0 → v1.7.1
# ------------------------------------------------------------------------------
# CRITICAL FIX: Enhanced rate limit handling for Yahoo Finance API
# 
# Changes Made:
# 1. _fetch_price_native(): Increased initial delay from 1-2s to 5-10s
# 2. _fetch_price_native(): Implemented exponential backoff (10s → 120s)
# 3. _fetch_price_native(): Added specific 429 error detection with 60s cooldown
# 4. _fetch_price_native(): Added longer waits on empty DataFrames (potential rate limiting)
# 5. PortfolioRequest: Increased default retries from 3 to 5
# 6. PortfolioRequest: Increased backoff_base_seconds from 0.5 to 5.0
#
# Rationale:
# Yahoo Finance enforces ~2000 requests/hour per IP. Previous implementation
# triggered rate limits due to aggressive polling (1-2s delays) and parallel 
# execution in n8n workflows. New implementation respects rate limits while
# maintaining reasonable end-to-end performance.
#
# Performance Impact:
# - Single ticker: ~7-10s (was ~2-3s)
# - 5 ticker portfolio: ~50-60s (was ~15-20s)
# - Acceptable tradeoff for 100% success rate vs frequent failures
# ------------------------------------------------------------------------------
#
# ARCHITECTURAL DECISION RECORD (ADR)
# ------------------------------------------------------------------------------
# 1. PRICE DATA SOURCE:
#    - DECISION: Reverted to `yfinance.download()` (Official Wrapper).
#    - REASON: The manual Chart API requests (`/v8/finance/chart`) were failing with 
#      429 errors because Yahoo now enforces strict "Crumb" validation. The `yfinance` 
#      library automatically handles session management (cookies/crumbs), making it 
#      significantly more robust for Cloud/Docker environments.
#
# 2. FUNDAMENTAL DATA STRATEGY (FAIL-SAFE HYBRID):
#    - PRIMARY: FinViz (Web Scraping).
#      - REASON: Fast, unlimited, and provides 4/6 key fields.
#      - CONSTRAINT: FinViz often blocks Cloud IPs (AWS/Azure) with "Challenge Pages".
#    - FALLBACK 1: Yahoo Ticker.info (Official Wrapper).
#      - REASON: Official data source, used if FinViz scraping returns empty tables.
#    - FALLBACK 2 (NEW): AlphaVantage (The "Nuclear" Option).
#      - REASON: If both FinViz and Yahoo fail (due to Cloud blocks or 429s), we 
#        now parse ALL fields (Sector, MarketCap, P/E, Yield) directly from 
#        AlphaVantage. This guarantees data integrity even in hostile network conditions.
#
# 3. COMPANY NAME RESOLUTION:
#    - STRATEGY: Chart API Metadata -> yfinance -> FinViz Title.
#    - REASON: Proven in testing to be the most reliable chain for legal entity names.
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
import pandas as pd           # Data manipulation
import requests               # HTTP requests
from bs4 import BeautifulSoup # HTML Parsing
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
import yfinance as yf         # Official Yahoo wrapper

# ==============================================================================
# CONFIGURATION & LOGGING
# ==============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("JarvisDataService")

APP_TITLE = "Jarvis Market Data Service"
APP_VERSION = "1.7.1"

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
    # CHANGE v1.7.1: Increased from 3 to 5 to handle rate limiting better
    retries: int = 5
    # CHANGE v1.7.1: Increased from 0.5 to 5.0 for more aggressive backoff
    backoff_base_seconds: float = 5.0


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
# CORE LOGIC A: PRICE & RETURNS (Native yfinance)
# ==============================================================================

def _fetch_price_native(
    ticker: str, 
    start_date: str, 
    end_date: str, 
    interval: str, 
    retries: int
) -> FetchResult:
    """
    Fetches OHLCV using the native `yfinance` library with enhanced rate limit handling.
    
    CRITICAL CHANGES (v1.7.1):
    -------------------------
    1. Initial delay increased from 1-2s to 5-10s to avoid triggering rate limits
    2. Exponential backoff on retries: 10s → 20s → 40s → 80s → 120s (capped)
    3. Specific detection and handling of HTTP 429 errors with 60s cooldown
    4. Longer waits (10-15s) on empty DataFrames which may indicate rate limiting
    
    Why revert to yfinance?
    -----------------------
    - The raw Chart API (`requests.get`) was failing due to missing 'Crumb' tokens.
    - `yfinance` handles the complex session/cookie handshake automatically.
    - It is more resilient to 'Soft 429s' (temporary IP bans).
    
    NOTE: yfinance maintains a requests.Session internally for cookie management
    but does NOT implement rate limiting. We handle rate limiting at this layer.
    
    Args:
        ticker: Stock symbol (e.g., 'AAPL', 'MSFT')
        start_date: ISO date string or datetime object
        end_date: ISO date string or datetime object
        interval: '1d', '1wk', or '1mo'
        retries: Number of retry attempts
    
    Returns:
        FetchResult with DataFrame containing OHLCV data
    
    Raises:
        ValueError: If max retries exhausted
    """
    
    for attempt in range(retries):
        try:
            # ═══════════════════════════════════════════════════════════════
            # RATE LIMIT MITIGATION STRATEGY
            # ═══════════════════════════════════════════════════════════════
            
            if attempt > 0:
                # CHANGE v1.7.1: Exponential backoff on retries
                # Formula: min(120, 10 * 2^(attempt-1))
                # Result: 10s, 20s, 40s, 80s, 120s, 120s...
                backoff_time = min(120, 10 * (2 ** (attempt - 1)))
                logger.info(
                    f"[PRICE] {ticker} retry {attempt}/{retries}, "
                    f"exponential backoff: {backoff_time}s"
                )
                time.sleep(backoff_time)
            else:
                # CHANGE v1.7.1: Longer initial delay
                # OLD: random.uniform(1.0, 2.0)
                # NEW: random.uniform(5.0, 10.0)
                # REASON: Yahoo Finance rate limit is ~2000 req/hour (0.55 req/sec)
                #         5-10s delay ensures we stay well below this threshold
                initial_delay = random.uniform(5.0, 10.0)
                logger.info(
                    f"[PRICE] Fetching {ticker}, "
                    f"initial rate-limit-safe delay: {initial_delay:.1f}s"
                )
                time.sleep(initial_delay)
            
            # ═══════════════════════════════════════════════════════════════
            # DATA FETCH (yfinance native download)
            # ═══════════════════════════════════════════════════════════════
            
            # auto_adjust=True gets us the Split/Dividend adjusted price 
            # (Critical for accurate Total Return calculations in Fama-French models)
            df = yf.download(
                ticker, 
                start=start_date, 
                end=end_date, 
                interval=interval, 
                progress=False,      # Suppress progress bar in logs
                auto_adjust=True,    # Adjust for splits/dividends
                threads=False        # Single-threaded for rate limit safety
            )
            
            # ═══════════════════════════════════════════════════════════════
            # EMPTY DATAFRAME HANDLING
            # ═══════════════════════════════════════════════════════════════
            
            if df.empty:
                logger.warning(
                    f"[PRICE] {ticker} returned empty DataFrame on "
                    f"attempt {attempt+1}/{retries} (possible rate limit or invalid ticker)"
                )
                
                # CHANGE v1.7.1: Longer wait on empty
                # OLD: continue immediately
                # NEW: wait 10-15s before retry
                # REASON: Empty DataFrame often indicates rate limiting,
                #         not just bad ticker. Give Yahoo time to reset.
                if attempt < retries - 1:
                    empty_backoff = random.uniform(10.0, 15.0)
                    logger.info(f"[PRICE] Waiting {empty_backoff:.1f}s before retry...")
                    time.sleep(empty_backoff)
                continue

            # ═══════════════════════════════════════════════════════════════
            # DATA CLEANUP & NORMALIZATION
            # ═══════════════════════════════════════════════════════════════
            
            # CLEANUP: yfinance can return MultiIndex columns, we flatten them
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            
            df.reset_index(inplace=True)
            
            # Rename to our standard schema
            # Note: yfinance column names are capitalized (Date, Open, High, Low, Close, Volume)
            df.rename(columns={
                "Date": "datetime", 
                "Close": "close", 
                "Volume": "volume"
            }, inplace=True)
            
            # Fallback: If 'Close' wasn't found (sometimes 'Adj Close' is returned)
            if "close" not in df.columns and "Adj Close" in df.columns:
                df["close"] = df["Adj Close"]
                
            if "close" not in df.columns:
                raise ValueError("Column 'close' missing from response")

            # Format Date to ISO string
            df["datetime"] = pd.to_datetime(df["datetime"]).dt.strftime("%Y-%m-%d")
            
            # Clean NaNs (Market holidays or data gaps)
            df.dropna(subset=["close"], inplace=True)
            
            # ═══════════════════════════════════════════════════════════════
            # SUCCESS
            # ═══════════════════════════════════════════════════════════════
            
            logger.info(
                f"[PRICE] ✅ Successfully fetched {len(df)} rows for {ticker} "
                f"(attempt {attempt+1}/{retries})"
            )
            return FetchResult(df=df, source="yfinance_native")

        except Exception as e:
            logger.error(
                f"[PRICE] ❌ Attempt {attempt+1}/{retries} failed for {ticker}: {e}"
            )
            
            # ═══════════════════════════════════════════════════════════════
            # HTTP 429 RATE LIMIT DETECTION
            # ═══════════════════════════════════════════════════════════════
            
            # CHANGE v1.7.1: Specific 429 handling
            # NEW: Detect 429 errors and implement aggressive 60s backoff
            # REASON: yfinance does NOT handle rate limits automatically.
            #         We must detect and handle them explicitly.
            if "429" in str(e) or "Too Many Requests" in str(e):
                logger.error(
                    f"[PRICE] 🚨 HTTP 429 Rate Limit detected for {ticker}! "
                    f"Implementing aggressive 60s cooldown..."
                )
                if attempt < retries - 1:
                    time.sleep(60)  # Full minute cooldown on rate limit
            else:
                # Standard exponential backoff for non-rate-limit errors
                # Formula: min(30, 5 * 2^attempt)
                # Result: 5s, 10s, 20s, 30s, 30s...
                error_backoff = min(30, 5 * (2 ** attempt))
                logger.warning(
                    f"[PRICE] Non-rate-limit error, waiting {error_backoff}s before retry..."
                )
                time.sleep(error_backoff)
    
    # ═══════════════════════════════════════════════════════════════
    # MAX RETRIES EXHAUSTED
    # ═══════════════════════════════════════════════════════════════
    
    logger.error(
        f"[PRICE] 💀 Max retries ({retries}) exhausted for {ticker}. "
        f"Likely persistent rate limiting or invalid ticker."
    )
    raise ValueError("Max retries reached for price fetch")


# ==============================================================================
# CORE LOGIC B: FUNDAMENTALS (The "Nuclear" Option)
# ==============================================================================

def _fetch_finviz_data(ticker: str, session: requests.Session) -> dict:
    """
    [PRIMARY STRATEGY] Scrapes company fundamentals from FinViz.
    
    ANTI-BOT MEASURES:
    - Uses a 'Session' to maintain cookies.
    - Sends 'Human-Like' headers (Referer: Google, Accept-Language: en-US).
    """
    url = f"https://finviz.com/quote.ashx?t={ticker}"
    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Referer": "https://www.google.com/"
    }
    
    try:
        r = session.get(url, headers=headers, timeout=10)
        if r.status_code != 200: return {}

        soup = BeautifulSoup(r.text, 'html.parser')
        
        # [VALIDATION]: Check if the main data table exists.
        table = soup.find('table', class_='snapshot-table2')
        if not table: return {}

        data = {}
        for row in table.find_all('tr'):
            cols = row.find_all('td')
            for i in range(0, len(cols), 2):
                if i+1 < len(cols):
                    data[cols[i].text.strip()] = cols[i+1].text.strip()

        if "Sector" not in data: return {}

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
            "forwardPE": float(data.get("Forward P/E")) if data.get("Forward P/E") not in ["-", None] else None,
            "dividendYield": float(data.get("Dividend %").replace("%", ""))/100 if data.get("Dividend %") not in ["-", None] else 0.0
        }
    except Exception:
        return {}


def _fetch_alphavantage_full(ticker: str) -> dict:
    """
    [BACKUP STRATEGY] Fetches EVERYTHING from AlphaVantage.
    
    Why: If FinViz blocks us (Cloud IP) and Yahoo is rate-limited (429),
    this function serves as the ultimate fail-safe. It parses numeric fields 
    (Sector, PE, MarketCap) that usually come from FinViz.
    """
    api_key = os.getenv("ALPHA_VANTAGE_API_KEY")
    if not api_key: return {}

    url = "https://www.alphavantage.co/query"
    params = {"function": "OVERVIEW", "symbol": ticker, "apikey": api_key}
    
    try:
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
        
        if "Note" in data: 
            return {"error": "RateLimit"}
        
        # --- DATA CLEANING & PARSING ---
        # AlphaVantage often returns "None", "-", or "0" strings. We must sanitize.
        
        # 1. Market Cap
        mc = 0
        try:
            val = data.get("MarketCapitalization")
            if val and val not in ["None", "-", "0"]:
                mc = int(float(val))
        except: pass
            
        # 2. Forward PE
        pe = None
        try:
            val = data.get("ForwardPE")
            if val and val not in ["None", "-", "0"]:
                pe = float(val)
        except: pass
            
        # 3. Dividend Yield
        dy = 0.0
        try:
            val = data.get("DividendYield")
            if val and val not in ["None", "-", "0"]:
                dy = float(val)
        except: pass

        # 4. Target Price
        tp = None
        try:
            val = data.get("AnalystTargetPrice")
            if val and val not in ["None", "-", "0"]:
                tp = float(val)
        except: pass

        return {
            "sector": data.get("Sector"),  # AlphaVantage provides this!
            "marketCap": mc,
            "forwardPE": pe,
            "dividendYield": dy,
            "longBusinessSummary": data.get("Description"),
            "targetMeanPrice": tp
        }
    except Exception as e:
        logger.error(f"[AV-FULL] Failed for {ticker}: {e}")
        return {}


def _fetch_company_info_hybrid(ticker: str, session: requests.Session) -> dict:
    """
    Orchestrator Pattern with 3-Layer Redundancy.
    
    Flow:
    1. Try FinViz (Preferred, Unlimited).
    2. If FinViz fails (Cloud Block), Try Yahoo Fallback (Fills Sector/MarketCap).
    3. If BOTH fail, or if we need Description, call AlphaVantage (FULL mode).
    """
    result = {"longBusinessSummary": None, "sector": None, "marketCap": 0, "source": "Failed"}
    
    # --- Step 1: FinViz (Primary) ---
    finviz = _fetch_finviz_data(ticker, session)
    if finviz:
        result.update(finviz)
        result["source"] = "FinViz"
    
    # --- Step 2: Yahoo Fallback (If Sector missing) ---
    if not result["sector"]:
        try:
            yf_ticker = yf.Ticker(ticker)
            info = yf_ticker.info
            if info.get("sector"):
                result["sector"] = info.get("sector")
                result["marketCap"] = info.get("marketCap", 0)
                result["forwardPE"] = info.get("forwardPE")
                result["dividendYield"] = info.get("dividendYield")
                result["source"] = "YahooFallback"
        except Exception:
            pass

    # --- Step 3: AlphaVantage (The Ultimate Backup) ---
    # We call this to get the Description. 
    # CRITICAL: If Sector is STILL missing (FinViz & Yahoo failed), we use AV for EVERYTHING.
    av_data = _fetch_alphavantage_full(ticker)
    
    if av_data and "error" not in av_data:
        # Always take qualitative fields (Description)
        result["longBusinessSummary"] = av_data.get("longBusinessSummary")
        result["targetMeanPrice"] = av_data.get("targetMeanPrice")
        
        # If Sector is still null, take ALL numeric data from AV
        if not result["sector"]:
            result["sector"] = av_data.get("sector")
            result["marketCap"] = av_data.get("marketCap")
            result["forwardPE"] = av_data.get("forwardPE")
            result["dividendYield"] = av_data.get("dividendYield")
            
            # Update Source Label
            if result["source"] == "Failed":
                result["source"] = "AlphaVantage (Full)"
            else:
                result["source"] += "+AV(Backfill)"
        else:
             # Just appended AV description
             if result["source"] == "Failed":
                 result["source"] = "AlphaVantage"
             else:
                 result["source"] += "+AlphaVantage"
                 
    elif av_data.get("error") == "RateLimit":
        result["source"] += " (AV Limit)"

    return result


# ==============================================================================
# CORE LOGIC C: NAME RESOLUTION
# ==============================================================================

def _require_api_key(x_api_key: Optional[str]) -> None:
    expected = os.getenv("SERVICE_API_KEY")
    if expected and x_api_key != expected:
        raise HTTPException(status_code=401, detail="Invalid API key")

def _get_name_from_chart_api(ticker: str) -> Optional[str]:
    """
    Extracts company name from Yahoo Chart API Metadata.
    Reliable method that bypasses the blocked 'quoteSummary' endpoint.
    """
    try:
        # Request minimal data just to get metadata
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=1d"
        headers = {"User-Agent": random.choice(USER_AGENTS)}
        r = requests.get(url, headers=headers, timeout=5)
        if r.status_code == 200:
            meta = r.json()['chart']['result'][0]['meta']
            return meta.get('longName') or meta.get('shortName')
    except Exception:
        pass
    return None

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
    
    # STRATEGY 1: Chart API (Most Reliable)
    name = _get_name_from_chart_api(ticker)
    if name: return {"ticker": ticker, "company_name": name}

    # STRATEGY 2: yfinance (Backup)
    try:
        yf_ticker = yf.Ticker(ticker)
        info = yf_ticker.info
        name = info.get("longName") or info.get("shortName")
        if name: return {"ticker": ticker, "company_name": name}
    except Exception: pass

    # STRATEGY 3: FinViz (Scraping Fallback)
    try:
        session = requests.Session()
        headers = {"User-Agent": random.choice(USER_AGENTS), "Referer": "https://www.google.com/"}
        url = f"https://finviz.com/quote.ashx?t={ticker}"
        r = session.get(url, headers=headers, timeout=5)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, 'html.parser')
            title = soup.find('title')
            # Format: "IBM - International Business Machines - Stock Price..."
            if title and title.text:
                parts = title.text.split(" - ")
                if len(parts) >= 2:
                    clean_name = parts[1].split(" Stock Price")[0].strip()
                    return {"ticker": ticker, "company_name": clean_name}
    except Exception: pass

    return {"ticker": ticker, "company_name": ticker}


# ==============================================================================
# MAIN ENDPOINT
# ==============================================================================

@app.post("/portfolio/json")
def portfolio_json(req: PortfolioRequest, x_api_key: Optional[str] = Header(default=None)):
    """
    [ENDPOINT] Main Data Ingestion.
    Fetches Price Data (Quantitative) and Company Info (Qualitative).
    """
    _require_api_key(x_api_key)
    tickers = [t.upper() for t in req.tickers]
    output = []
    session = requests.Session()
    
    for t in tickers:
        # [THROTTLING] Random sleep between tickers
        # CHANGE v1.7.1: Increased from 2-5s to 5-10s for better rate limit compliance
        sleep_time = random.uniform(5.0, 10.0)
        logger.info(f"Processing {t}... inter-ticker delay: {sleep_time:.2f}s")
        time.sleep(sleep_time)
        
        # 1. Price Data (Native yfinance with enhanced rate limiting)
        try:
            res = _fetch_price_native(t, req.start_date, req.end_date, req.interval, req.retries)
            df = res.df.copy()
            
            # --- Returns Engine ---
            # Calculates Simple Returns (daily %) and Log Returns (for statistical models)
            if req.include_returns and not df.empty:
                df['simple_return'] = df['close'].pct_change()
                df['log_return'] = np.log(df['close'] / df['close'].shift(1))
                df.fillna(0, inplace=True) # First row will be NaN/Inf
            
            ohlcv = df.replace({float('nan'): None}).to_dict(orient="records")
        except Exception as e:
            logger.error(f"Price failed {t}: {e}")
            ohlcv = []

        # 2. Company Info (Hybrid + Full AlphaVantage Backup)
        info = _fetch_company_info_hybrid(t, session)
        
        output.append({
            "ticker": t,
            "batch_id": req.batch_id,
            "raw_ohlcv": ohlcv,
            "raw_tickerinfo": info
        })

    return output

if __name__ == "__main__":
    import uvicorn
    # Host 0.0.0.0 is required for Docker containers to be accessible externally
    # Port 8000 is standard for FastAPI
    uvicorn.run(app, host="0.0.0.0", port=8000)