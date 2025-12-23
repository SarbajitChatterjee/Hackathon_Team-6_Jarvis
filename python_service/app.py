from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import List, Optional, Literal
from datetime import datetime
import pandas as pd
import time

from yahoo_fin.stock_info import get_data  # yahoo_fin

app = FastAPI(title="Market Data Service", version="0.1")


class PortfolioRequest(BaseModel):
    batch_id: Optional[str] = Field(default=None, description="Same batch_id used across the portfolio run")
    portfolio_id: Optional[str] = Field(default=None, description="Optional portfolio identifier")
    tickers: List[str] = Field(..., min_length=1, description="Variable length: 5, 10, 15... all allowed")
    start_date: str = Field(..., description="ISO (YYYY-MM-DD) or mm/dd/yyyy")
    end_date: str = Field(..., description="ISO (YYYY-MM-DD) or mm/dd/yyyy")
    interval: Literal["1d", "1wk", "1mo"] = "1d"

    # Output controls
    use_adjclose_as_close: bool = True
    include_adjclose_column: bool = True
    include_returns: bool = True

    # Safety controls
    max_tickers: int = 50
    sleep_seconds: float = 0.2  # gentle throttling
    strict: bool = True         # if True: fail request when any ticker fails


def _to_mmddyyyy(s: str) -> str:
    """
    yahoo_fin examples commonly use mm/dd/yyyy for start_date/end_date. :contentReference[oaicite:2]{index=2}
    Accept ISO too, and convert.
    """
    s = s.strip()
    if "/" in s:
        return s  # assume mm/dd/yyyy already
    # assume ISO
    dt = datetime.fromisoformat(s)
    return dt.strftime("%m/%d/%Y")


def _fetch_one(ticker: str, start_mmddyyyy: str, end_mmddyyyy: str, interval: str) -> pd.DataFrame:
    # yahoo_fin returns OHLC + adjclose + volume columns internally :contentReference[oaicite:3]{index=3}
    df = get_data(
        ticker,
        start_date=start_mmddyyyy,
        end_date=end_mmddyyyy,
        index_as_date=True,
        interval=interval,
    )

    if df is None or df.empty:
        raise ValueError("No data returned")

    # Ensure we have the expected columns
    expected = {"open", "high", "low", "close", "adjclose", "volume"}
    missing = expected - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns: {sorted(missing)}")

    df = df.reset_index().rename(columns={"index": "datetime"})
    df["ticker"] = ticker.upper()

    # Backtrader standard lines: datetime, open, high, low, close, volume, openinterest :contentReference[oaicite:4]{index=4}
    if df["datetime"].dtype != "datetime64[ns]":
        df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")

    df["datetime"] = df["datetime"].dt.strftime("%Y-%m-%d")
    df["openinterest"] = 0

    return df


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/portfolio/ohlcv.csv")
def portfolio_ohlcv(req: PortfolioRequest):
    # ---- Where “5 vs 10 vs 15 tickers” is handled ----
    tickers = [t.strip().upper() for t in req.tickers if t and t.strip()]
    if not tickers:
        raise HTTPException(status_code=400, detail="tickers must contain at least 1 valid symbol")

    if len(tickers) > req.max_tickers:
        raise HTTPException(status_code=400, detail=f"Too many tickers. Max allowed = {req.max_tickers}")

    start_mmddyyyy = _to_mmddyyyy(req.start_date)
    end_mmddyyyy = _to_mmddyyyy(req.end_date)

    frames = []
    failed = []

    for ticker in tickers:
        try:
            frames.append(_fetch_one(ticker, start_mmddyyyy, end_mmddyyyy, req.interval))
        except Exception as e:
            failed.append((ticker, str(e)))
            if req.strict:
                raise HTTPException(status_code=502, detail=f"Failed to fetch {ticker}: {e}")
        finally:
            if req.sleep_seconds and req.sleep_seconds > 0:
                time.sleep(req.sleep_seconds)

    if not frames:
        raise HTTPException(status_code=502, detail=f"All tickers failed: {failed}")

    df = pd.concat(frames, ignore_index=True)

    # Choose close series
    if req.use_adjclose_as_close:
        df["close"] = df["adjclose"]

    # Optional returns (per ticker)
    if req.include_returns:
        df["ret"] = df.groupby("ticker")["close"].pct_change()

    # Column set for MVP: Backtrader + ticker (+ optional extras)
    cols = ["datetime", "ticker", "open", "high", "low", "close", "volume", "openinterest"]
    if req.include_adjclose_column:
        cols.insert(cols.index("close") + 1, "adjclose")
    if req.include_returns:
        cols.append("ret")

    df = df[cols].sort_values(["ticker", "datetime"])

    # Add batch/portfolio fields if you want them inside the CSV (handy for DB traceability)
    if req.batch_id:
        df.insert(0, "batch_id", req.batch_id)
    if req.portfolio_id:
        df.insert(1 if req.batch_id else 0, "portfolio_id", req.portfolio_id)

    csv_bytes = df.to_csv(index=False).encode("utf-8")

    filename = f"portfolio_{req.batch_id or 'no_batch'}_{req.interval}.csv"
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"'
    }
    # (Optional) expose failures as header (useful if strict=False)
    if failed:
        headers["X-Failed-Tickers"] = ",".join([t for t, _ in failed])

    return Response(content=csv_bytes, media_type="text/csv", headers=headers)