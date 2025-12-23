from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Literal, Optional, Tuple

import pandas as pd
import requests
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

# Optional (kept for future / fallback)
try:
    from yahoo_fin.stock_info import get_data as yahoo_fin_get_data
except Exception:
    yahoo_fin_get_data = None


app = FastAPI(title="Jarvis Market Data Service", version="0.2")

ALLOWED_INTERVALS = {"1d", "1wk", "1mo"}  # matches common Yahoo chart intervals
DEFAULT_UA = "Mozilla/5.0"


class PortfolioRequest(BaseModel):
    # Identifiers
    batch_id: Optional[str] = Field(default=None, description="If omitted, server generates a UUID.")
    portfolio_id: Optional[str] = Field(default=None, description="Optional portfolio identifier.")

    # Portfolio constituents (any length)
    tickers: List[str] = Field(..., min_length=1, description="e.g. ['AAPL','MSFT']; any length allowed.")

    # Date range (accept ISO or mm/dd/yyyy)
    start_date: str = Field(..., description="YYYY-MM-DD or MM/DD/YYYY")
    end_date: str = Field(..., description="YYYY-MM-DD or MM/DD/YYYY")

    # Sampling
    interval: Literal["1d", "1wk", "1mo"] = "1d"

    # Fetch strategy
    fetch_mode: Literal["chart", "yahoo_fin", "auto"] = "chart"
    # chart    -> always use Yahoo v8 chart JSON endpoint
    # yahoo_fin -> always use yahoo_fin.get_data (may be brittle)
    # auto     -> try yahoo_fin, fallback to chart

    # Output behaviour
    use_adjclose_as_close: bool = True
    include_adjclose_column: bool = True
    include_returns: bool = True

    # Failure behaviour
    strict: bool = True  # True: fail entire request if ANY ticker fails

    # Safety / throttling
    max_tickers: int = 50
    sleep_seconds: float = 0.2
    retries: int = 3
    backoff_base_seconds: float = 0.5


def _require_api_key(x_api_key: Optional[str]) -> None:
    """
    Optional API key check (only enforced if SERVICE_API_KEY env is set).
    """
    import os

    expected = os.getenv("SERVICE_API_KEY")
    if expected and x_api_key != expected:
        raise HTTPException(status_code=401, detail="Invalid API key")


def _to_mmddyyyy(s: str) -> str:
    """
    yahoo_fin commonly expects MM/DD/YYYY for start_date/end_date.
    We accept ISO too and convert.
    """
    s = s.strip()
    if "/" in s:
        return s
    dt = datetime.fromisoformat(s)
    return dt.strftime("%m/%d/%Y")


def _to_unix_utc_midnight(s: str) -> int:
    """
    Accepts YYYY-MM-DD or MM/DD/YYYY and returns unix timestamp at UTC midnight.
    """
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
    source: str  # "chart" or "yahoo_fin"


def _fetch_chart(
    ticker: str,
    start_date: str,
    end_date: str,
    interval: str,
    retries: int,
    backoff_base_seconds: float,
) -> FetchResult:
    """
    Fetch OHLCV from Yahoo v8 chart endpoint and shape to a clean DataFrame.
    """
    period1 = _to_unix_utc_midnight(start_date)
    # Add 1 day to include end_date rows reliably
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
            adjc = (result.get("indicators", {}).get("adjclose") or [None])[0] or {}

            if not ts:
                raise ValueError("No timestamps returned")
            
            # when ts is a list/array) returns a DatetimeIndex, and .dt is a Series accessor, not for DatetimeIndex. 
            # Pandas docs explicitly note .dt is for Series with datetimelike values, while a datetime index has its own date/time methods
            dates = pd.to_datetime(ts, unit="s", utc=True)
            df = pd.DataFrame(
                {
                    "datetime": dates.strftime("%Y-%m-%d"),
                    "open": quote.get("open"),
                    "high": quote.get("high"),
                    "low": quote.get("low"),
                    "close": quote.get("close"),
                    "volume": quote.get("volume"),
                    "adjclose": adjc.get("adjclose"),
                }
            )

            df["ticker"] = ticker.upper()
            df["openinterest"] = 0

            # Drop rows with missing close
            df = df.dropna(subset=["close"]).copy()

            # Cast numeric columns safely
            for col in ["open", "high", "low", "close", "adjclose"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")

            df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype("int64")

            # Some rows may still have NaNs in OHLC; keep if close exists, user can decide later
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
    """
    Fetch using yahoo_fin.get_data (kept as optional mode / fallback).
    """
    if yahoo_fin_get_data is None:
        raise ValueError("yahoo_fin is not available in this container")

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

    # yahoo_fin df index is date; normalize to columns
    df = df.reset_index().rename(columns={"index": "datetime"})
    if "date" in df.columns and "datetime" not in df.columns:
        df = df.rename(columns={"date": "datetime"})

    # Ensure expected columns exist
    expected = {"open", "high", "low", "close", "adjclose", "volume"}
    missing = expected - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns from yahoo_fin: {sorted(missing)}")

    df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce").dt.strftime("%Y-%m-%d")
    df["ticker"] = ticker.upper()
    df["openinterest"] = 0

    df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype("int64")
    return FetchResult(df=df, source="yahoo_fin")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/portfolio/ohlcv.csv")
def portfolio_ohlcv_csv(req: PortfolioRequest, x_api_key: Optional[str] = Header(default=None)):
    _require_api_key(x_api_key)

    interval = req.interval.strip()
    if interval not in ALLOWED_INTERVALS:
        raise HTTPException(status_code=400, detail=f"interval must be one of {sorted(ALLOWED_INTERVALS)}")

    tickers = [t.strip().upper() for t in req.tickers if t and t.strip()]
    if not tickers:
        raise HTTPException(status_code=400, detail="tickers must contain at least 1 valid symbol")
    if len(tickers) > req.max_tickers:
        raise HTTPException(status_code=400, detail=f"Too many tickers. Max allowed = {req.max_tickers}")

    batch_id = (req.batch_id or str(uuid.uuid4())).strip()
    portfolio_id = (req.portfolio_id or "").strip() or None

    frames: List[pd.DataFrame] = []
    failed: List[Tuple[str, str]] = []
    sources_used: List[str] = []

    for t in tickers:
        try:
            if req.fetch_mode == "chart":
                res = _fetch_chart(
                    t,
                    req.start_date,
                    req.end_date,
                    interval,
                    retries=req.retries,
                    backoff_base_seconds=req.backoff_base_seconds,
                )
            elif req.fetch_mode == "yahoo_fin":
                res = _fetch_yahoo_fin(t, req.start_date, req.end_date, interval)
            else:  # auto
                try:
                    res = _fetch_yahoo_fin(t, req.start_date, req.end_date, interval)
                except Exception:
                    res = _fetch_chart(
                        t,
                        req.start_date,
                        req.end_date,
                        interval,
                        retries=req.retries,
                        backoff_base_seconds=req.backoff_base_seconds,
                    )

            df = res.df.copy()

            # Use adjusted close as close if requested and available
            if req.use_adjclose_as_close and "adjclose" in df.columns:
                df["close"] = df["adjclose"]

            # Returns (per ticker)
            if req.include_returns:
                df = df.sort_values(["datetime"]).copy()
                df["ret"] = df["close"].pct_change()

            frames.append(df)
            sources_used.append(res.source)

        except Exception as e:
            failed.append((t, str(e)))
            if req.strict:
                raise HTTPException(status_code=502, detail=f"Failed to fetch {t}: {e}") from e

        finally:
            if req.sleep_seconds and req.sleep_seconds > 0:
                time.sleep(req.sleep_seconds)

    if not frames:
        raise HTTPException(status_code=502, detail=f"All tickers failed. Failures: {failed}")

    merged = pd.concat(frames, ignore_index=True)

    # Build output columns:
    # Backtrader-standard lines + ticker; optionally adjclose and ret
    base_cols = ["datetime", "ticker", "open", "high", "low", "close", "volume", "openinterest"]
    out_cols = base_cols.copy()

    if req.include_adjclose_column and "adjclose" in merged.columns:
        # Put adjclose right after close for readability
        idx = out_cols.index("close") + 1
        out_cols.insert(idx, "adjclose")

    if req.include_returns and "ret" in merged.columns:
        out_cols.append("ret")

    # Add batch/portfolio columns at the front (useful as an input to your DB)
    if batch_id:
        merged.insert(0, "batch_id", batch_id)
        out_cols = ["batch_id"] + out_cols

    if portfolio_id:
        insert_at = 1 if batch_id else 0
        merged.insert(insert_at, "portfolio_id", portfolio_id)

        # IMPORTANT: keep datetime in the output columns
        out_cols = (["batch_id"] if batch_id else []) + ["portfolio_id"] + base_cols

        # Re-add optional columns
        if req.include_adjclose_column and "adjclose" in merged.columns:
            out_cols.insert(out_cols.index("close") + 1, "adjclose")
        if req.include_returns and "ret" in merged.columns:
            out_cols.append("ret")

    # Ensure all columns exist before selection
    out_cols = [c for c in out_cols if c in merged.columns]

    merged = merged[out_cols].sort_values(["ticker", "datetime"], kind="mergesort")

    csv_bytes = merged.to_csv(index=False).encode("utf-8")

    filename = f"portfolio_{portfolio_id or 'no_portfolio'}_{batch_id}_{interval}.csv"
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "X-Batch-Id": batch_id,
    }
    if portfolio_id:
        headers["X-Portfolio-Id"] = portfolio_id
    if failed:
        headers["X-Failed-Tickers"] = ",".join([t for t, _ in failed])

    # Helpful diagnostic: what source(s) were used
    if sources_used:
        headers["X-Data-Sources"] = ",".join(sorted(set(sources_used)))

    return Response(content=csv_bytes, media_type="text/csv", headers=headers)