# ==============================================================================
# JARVIS MARKET DATA SERVICE - ALPHAVANTAGE ONLY
# ==============================================================================
# Version: 1.0.0 (AlphaVantage API)
# Maintainer: Jarvis DevOps Team
# Context: Strict API-only version. No web scraping.
#
# ARCHITECTURAL DECISIONS:
# 1. Price Data: Yahoo Finance Chart API (v8).
# 2. Company Info: AlphaVantage 'OVERVIEW' endpoint (All 6 fields).
#    - PRO: Reliable, clean JSON, no scraping risks.
#    - CON: Strict 25 requests/day limit on free tier.
# 3. Name Resolution: yfinance Ticker.info.
# ==============================================================================

from __future__ import annotations

import os
import time
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Literal, Optional

import pandas as pd
import requests
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

import yfinance as yf

# --- Optional Import (Legacy Support) ---
try:
    from yahoo_fin.stock_info import get_data as yahoo_fin_get_data
except ImportError:
    yahoo_fin_get_data = None


# --- Configuration & Constants ---
APP_TITLE = "Jarvis Market Data Service - AlphaVantage"
APP_VERSION = "1.0.0"
DEFAULT_UA = "Mozilla/5.0"
ALLOWED_INTERVALS = {"1d", "1wk", "1mo"}


app = FastAPI(title=APP_TITLE, version=APP_VERSION)


# ==============================================================================
# DATA MODELS (Pydantic)
# ==============================================================================

class PortfolioRequest(BaseModel):
    """Payload for batch fetching market data."""
    batch_id: Optional[str] = Field(default=None, description="If omitted, server generates a UUID.")
    portfolio_id: Optional[str] = Field(default=None, description="Optional portfolio identifier.")
    tickers: List[str] = Field(..., min_length=1, description="e.g. ['AAPL','MSFT']; any length allowed.")
    start_date: str = Field(..., description="YYYY-MM-DD or MM/DD/YYYY")
    end_date: str = Field(..., description="YYYY-MM-DD or MM/DD/YYYY")
    interval: Literal["1d", "1wk", "1mo"] = "1d"
    fetch_mode: Literal["chart", "yahoo_fin", "auto"] = "chart"
    
    # Configuration flags
    use_adjclose_as_close: bool = True
    include_adjclose_column: bool = True
    include_returns: bool = True
    strict: bool = True
    
    # Retry/Throttling policies
    max_tickers: int = 50
    sleep_seconds: float = 0.2
    retries: int = 3
    backoff_base_seconds: float = 0.5


class ResolveRequest(BaseModel):
    ticker: str


class CompanyNameResponse(BaseModel):
    ticker: str
    company_name: str


# ==============================================================================
# UTILITY FUNCTIONS
# ==============================================================================

def _require_api_key(x_api_key: Optional[str]) -> None:
    expected = os.getenv("SERVICE_API_KEY")
    if expected and x_api_key != expected:
        raise HTTPException(status_code=401, detail="Invalid API key")

def _to_mmddyyyy(s: str) -> str:
    s = s.strip()
    if "/" in s:
        return s
    dt = datetime.fromisoformat(s)
    return dt.strftime("%m/%d/%Y")

def _to_unix_utc_midnight(s: str) -> int:
    s = s.strip()
    if "/" in s:
        dt = datetime.strptime(s, "%m/%d/%Y")
    else:
        dt = datetime.strptime(s, "%Y-%m-%d")
    dt_utc = datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)
    return int(dt_utc.timestamp())

@dataclass
class FetchResult:
    df: pd.DataFrame
    source: str


# ==============================================================================
# PART A: PRICE DATA FETCHING (Quantitative)
# ==============================================================================

def _fetch_chart(
    ticker: str,
    start_date: str,
    end_date: str,
    interval: str,
    retries: int,
    backoff_base_seconds: float,
) -> FetchResult:
    """Fetch OHLCV from Yahoo v8 chart endpoint"""
    period1 = _to_unix_utc_midnight(start_date)
    period2 = _to_unix_utc_midnight(end_date) + 24 * 60 * 60

    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    params = {
        "period1": period1,
        "period2": period2,
        "interval": interval,
        "events": "div,splits",
        "includeAdjustedClose": "true",
    }
    headers = {
        "User-Agent": DEFAULT_UA,
        "Accept": "application/json,text/plain,*/*",
        "Referer": f"https://finance.yahoo.com/quote/{ticker}",
    }

    last_err: Optional[str] = None
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=20)
            if r.status_code != 200:
                last_err = f"HTTP {r.status_code}"
                raise ValueError(last_err)

            payload = r.json()
            result = (payload.get("chart", {}).get("result") or [None])[0]
            if not result:
                raise ValueError("No result in chart response")

            ts = result.get("timestamp") or []
            quote = (result.get("indicators", {}).get("quote") or [None])[0] or {}

            if not ts:
                raise ValueError("No timestamps returned")
            
            dates = pd.to_datetime(ts, unit="s", utc=True)
            df = pd.DataFrame({
                "datetime": dates.strftime("%Y-%m-%d"),
                "close": quote.get("close"),
            })

            df = df.dropna(subset=["close"]).copy()
            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            df = df.dropna(subset=["close"]).copy()

            return FetchResult(df=df, source="chart")

        except Exception as e:
            last_err = str(e)
            if attempt < retries - 1:
                time.sleep(backoff_base_seconds * (2**attempt))
                continue
            raise ValueError(f"chart fetch failed: {last_err}") from e

    raise ValueError(f"chart fetch failed: {last_err}")


def _fetch_yahoo_fin(
    ticker: str,
    start_date: str,
    end_date: str,
    interval: str,
) -> FetchResult:
    """Fetch using yahoo_fin.get_data (Fallback)."""
    if yahoo_fin_get_data is None:
        raise ValueError("yahoo_fin is not available")

    start_mmdd = _to_mmddyyyy(start_date)
    end_mmdd = _to_mmddyyyy(end_date)

    df = yahoo_fin_get_data(
        ticker,
        start_date=start_mmdd,
        end_date=end_mmdd,
        index_as_date=True,
        interval=interval,
    )

    if df is None or df.empty:
        raise ValueError("No data returned from yahoo_fin.get_data")

    df = df.reset_index().rename(columns={"index": "datetime"})
    if "date" in df.columns and "datetime" not in df.columns:
        df = df.rename(columns={"date": "datetime"})

    df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce").dt.strftime("%Y-%m-%d")
    df["ticker"] = ticker.upper()
    df["openinterest"] = 0
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype("int64")
    
    return FetchResult(df=df, source="yahoo_fin")


# ============================================================================
# ALPHAVANTAGE-ONLY COMPANY INFO SYSTEM
# ============================================================================

def _fetch_alphavantage_data(ticker: str) -> dict:
    """
    Fetch company info from AlphaVantage API.
    
    Returns ALL 6 fields:
        - longBusinessSummary (Description)
        - sector
        - marketCap
        - forwardPE
        - dividendYield
        - targetMeanPrice
    
    Requires: ALPHA_VANTAGE_API_KEY environment variable.
    Warning: Free tier limit is 25 requests/day.
    """
    api_key = os.getenv("ALPHA_VANTAGE_API_KEY", "")
    if not api_key:
        raise ValueError("ALPHA_VANTAGE_API_KEY environment variable not set")
    
    url = "https://www.alphavantage.co/query"
    params = {
        "function": "OVERVIEW",
        "symbol": ticker,
        "apikey": api_key
    }
    
    try:
        print(f"[ALPHAVANTAGE] Fetching data for {ticker}...")
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        # Check validity
        if not data or "Symbol" not in data:
            if "Note" in data and "API call frequency" in data["Note"]:
                raise ValueError(f"Rate limit exceeded: {data['Note']}")
            raise ValueError(f"No data returned for {ticker}")
        
        # Parse Fields safely
        market_cap = 0
        try:
            market_cap_str = data.get("MarketCapitalization", "0")
            if market_cap_str and market_cap_str not in [None, "None", "-", "0"]:
                market_cap = int(float(market_cap_str))
        except (ValueError, TypeError):
            pass
        
        div_yield = 0.0
        try:
            div_str = data.get("DividendYield", "0")
            if div_str and div_str not in [None, "None", "-"]:
                div_yield = float(div_str)
        except (ValueError, TypeError):
            pass
        
        forward_pe = None
        try:
            pe_str = data.get("ForwardPE", None)
            if pe_str and pe_str not in [None, "None", "-"]:
                forward_pe = float(pe_str)
        except (ValueError, TypeError):
            pass
        
        target_price = None
        try:
            target_str = data.get("AnalystTargetPrice", None)
            if target_str and target_str not in [None, "None", "-"]:
                target_price = float(target_str)
        except (ValueError, TypeError):
            pass
        
        result = {
            "longBusinessSummary": data.get("Description", None),
            "sector": data.get("Sector", None),
            "marketCap": market_cap,
            "forwardPE": forward_pe,
            "dividendYield": div_yield,
            "targetMeanPrice": target_price,
            "source": "AlphaVantage"
        }
        
        print(f"[ALPHAVANTAGE] ✓ Successfully fetched all 6 fields for {ticker}")
        return result
        
    except Exception as e:
        print(f"[ALPHAVANTAGE] ✗ Failed for {ticker}: {e}")
        raise Exception(f"AlphaVantage API failed: {e}")


@app.get("/health")
def health():
    return {"status": "ok", "version": APP_VERSION}


@app.post("/portfolio/json")
def portfolio_json(req: PortfolioRequest, x_api_key: Optional[str] = Header(default=None)):
    """
    Main endpoint for Data Ingestion.
    Accepts list of tickers, returns OHLCV + Fundamental Data.
    
    STRATEGY:
    - Price Data: Yahoo Finance Chart API.
    - Fundamentals: AlphaVantage ONLY.
    
    NOTE: High throttling (13-15s sleep) applied to respect free tier limits.
    """
    _require_api_key(x_api_key)

    tickers = [t.strip().upper() for t in req.tickers if t and t.strip()]
    output_list = []

    for t in tickers:
        # Aggressive throttling for AlphaVantage free tier
        sleep_time = random.uniform(13.0, 15.0)
        print(f"[THROTTLE] Sleeping {sleep_time:.2f}s before fetching {t}...")
        time.sleep(sleep_time)

        ticker_result = {
            "ticker": t,
            "batch_id": req.batch_id,
            "raw_ohlcv": [],
            "raw_tickerinfo": {}
        }

        # 1. Fetch Price Data
        try:
            if req.fetch_mode == "chart":
                res = _fetch_chart(t, req.start_date, req.end_date, req.interval, req.retries, req.backoff_base_seconds)
            else: 
                try:
                    res = _fetch_yahoo_fin(t, req.start_date, req.end_date, req.interval)
                except:
                    res = _fetch_chart(t, req.start_date, req.end_date, req.interval, req.retries, req.backoff_base_seconds)
            
            df = res.df.copy()
            df = df.replace([float('inf'), float('-inf')], float('nan'))
            df = df.where(pd.notnull(df), None)
            ticker_result["raw_ohlcv"] = df[["datetime", "close"]].to_dict(orient="records")
            
        except Exception as e:
            print(f"[ERROR] Price data fetch failed for {t}: {e}")

        # 2. Fetch Fundamentals (AlphaVantage Only)
        try:
            company_info = _fetch_alphavantage_data(t)
            ticker_result["raw_tickerinfo"] = company_info
        except Exception as e:
            print(f"[ERROR] AlphaVantage fetch failed for {t}: {e}")
            ticker_result["raw_tickerinfo"] = {
                "error": "AlphaVantage fetch failed",
                "details": str(e),
                "note": "Check API Key and 25/day limit"
            }

        output_list.append(ticker_result)

    if not output_list:
        raise HTTPException(status_code=502, detail="All tickers failed.")

    return output_list


@app.post("/company/name", response_model=CompanyNameResponse)
def resolve_company_profile(req: ResolveRequest, x_api_key: Optional[str] = Header(default=None)):
    """
    Resolves a ticker symbol to its official Legal Entity Name.
    Critical for Patent Search matching.
    
    STRATEGY:
    1. Primary: yfinance Ticker.info (No search API).
    2. Fallback: Return Ticker as name.
    """
    _require_api_key(x_api_key)
    
    ticker = req.ticker.strip().upper()
    
    # --- STRATEGY 1: YFINANCE ---
    try:
        print(f"[YFINANCE] Attempting to resolve {ticker}...")
        yf_ticker = yf.Ticker(ticker)
        info = yf_ticker.info
        
        company_name = (
            info.get("longName") or 
            info.get("shortName") or 
            info.get("name") or
            ticker
        )
        
        print(f"[YFINANCE] ✓ Resolved {ticker} -> {company_name}")
        return {"ticker": ticker, "company_name": company_name}
        
    except Exception as e:
        print(f"[YFINANCE] ✗ Failed for {ticker}: {e}")
    
    # --- STRATEGY 2: FALLBACK ---
    print(f"[FALLBACK] Could not resolve {ticker}, returning ticker as company_name")
    return {"ticker": ticker, "company_name": ticker}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)