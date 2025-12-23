import os
import io
import uuid
from datetime import datetime
from typing import List, Optional

import pandas as pd
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from yahoo_fin import stock_info as si

app = FastAPI(title="Jarvis YahooFin Service")

ALLOWED_INTERVALS = {"1d", "1wk", "1mo"}

DEFAULT_COLUMNS = ["open", "high", "low", "close", "adjclose", "volume"]


def _to_mmddyyyy(date_str: Optional[str]) -> Optional[str]:
    """
    yahoo_fin's get_data commonly expects mm/dd/yyyy for start_date/end_date.
    We accept ISO yyyy-mm-dd and convert for safety.
    """
    if not date_str:
        return None
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.strftime("%m/%d/%Y")
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid date format '{date_str}'. Use YYYY-MM-DD."
        ) from e


def _require_api_key(x_api_key: Optional[str]) -> None:
    expected = os.getenv("SERVICE_API_KEY")
    if expected and x_api_key != expected:
        raise HTTPException(status_code=401, detail="Invalid API key")


class PortfolioCsvRequest(BaseModel):
    portfolio_id: str = Field(..., min_length=1)
    batch_id: Optional[str] = None
    tickers: List[str] = Field(..., min_length=1)
    start_date: Optional[str] = None  # YYYY-MM-DD
    end_date: Optional[str] = None    # YYYY-MM-DD
    interval: str = "1d"
    columns: Optional[List[str]] = None  # e.g. ["close","volume"]


@app.post("/portfolio/csv")
def portfolio_csv(req: PortfolioCsvRequest, x_api_key: Optional[str] = Header(default=None)):
    _require_api_key(x_api_key)

    interval = req.interval.strip()
    if interval not in ALLOWED_INTERVALS:
        raise HTTPException(status_code=400, detail=f"interval must be one of {sorted(ALLOWED_INTERVALS)}")

    batch_id = (req.batch_id or str(uuid.uuid4())).strip()
    portfolio_id = req.portfolio_id.strip()

    # Normalise tickers
    tickers = [t.strip() for t in req.tickers if t and t.strip()]
    if not tickers:
        raise HTTPException(status_code=400, detail="tickers must contain at least 1 non-empty ticker")

    # Columns
    wanted_cols = req.columns or DEFAULT_COLUMNS
    wanted_cols = [c.strip().lower() for c in wanted_cols if c and c.strip()]
    if not wanted_cols:
        raise HTTPException(status_code=400, detail="columns must contain at least 1 column name")

    start_mmdd = _to_mmddyyyy(req.start_date)
    end_mmdd = _to_mmddyyyy(req.end_date)

    frames = []
    for t in tickers:
        try:
            df = si.get_data(
                t,
                start_date=start_mmdd,
                end_date=end_mmdd,
                index_as_date=True,
                interval=interval,
            )
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Failed fetching ticker '{t}': {str(e)}") from e

        if df is None or df.empty:
            raise HTTPException(status_code=502, detail=f"No data returned for ticker '{t}'")

        # Make sure we have a 'date' column
        df = df.reset_index()
        if "index" in df.columns and "date" not in df.columns:
            df = df.rename(columns={"index": "date"})

        # Add ticker column so rows can be merged safely
        df["ticker"] = t

        # Select only requested columns that actually exist
        available = set(df.columns.str.lower())
        # Map lower -> actual for safe selection
        lower_to_actual = {c.lower(): c for c in df.columns}

        keep = ["date", "ticker"]
        for c in wanted_cols:
            if c in available:
                keep.append(lower_to_actual[c])

        out = df[keep].copy()
        frames.append(out)

    merged = pd.concat(frames, ignore_index=True)

    # Sort for readability (date then ticker)
    if "date" in merged.columns:
        merged = merged.sort_values(by=["date", "ticker"], kind="mergesort")

    # Output CSV (single file for whole portfolio run)
    buf = io.StringIO()
    merged.to_csv(buf, index=False)
    buf.seek(0)

    filename = f"portfolio_{portfolio_id}_batch_{batch_id}.csv"
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "X-Batch-Id": batch_id,
        "X-Portfolio-Id": portfolio_id,
    }

    return StreamingResponse(buf, media_type="text/csv", headers=headers)