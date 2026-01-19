import os
from typing import Optional, Dict, Any, List
from datetime import datetime
from uuid import UUID
from abc import ABC, abstractmethod

import pandas as pd
import numpy as np
import backtrader as bt
import statsmodels.api as sm
import pandas_datareader.data as web

from fastapi import FastAPI, HTTPException, BackgroundTasks, status
from fastapi.responses import JSONResponse 
from pydantic import BaseModel, Field

# ==========================================
# FASTAPI APP INITIALIZATION
# ==========================================
app = FastAPI(
    title="FFM Backtesting API",
    description="API for Fama-French Model analysis and strategy backtesting",
    version="1.0.0"
)

# ==========================================
# DATA PROVIDER INTERFACE (Adapter Pattern)
# ==========================================
class DataProvider(ABC):
    """Abstract interface for data operations - can be implemented by n8n, Supabase, etc."""
    
    @abstractmethod
    def get_ticker_data(self, request_id: UUID) -> tuple[pd.DataFrame, str]:
        """Fetch OHLCV data and ticker symbol"""
        pass
    
    @abstractmethod
    def update_status(self, request_id: UUID, status_text: str, field: str = 'backtest_status'):
        """Update request status"""
        pass
    
    @abstractmethod
    def save_ffm_results(self, request_id: UUID, ticker: str, results: Dict[str, Any]):
        """Save Fama-French results"""
        pass
    
    @abstractmethod
    def save_backtest_results(self, request_id: UUID, ticker: str, results: Dict[str, Any]):
        """Save backtest results"""
        pass

# ==========================================
# IN-MEMORY DATA PROVIDER (Default)
# ==========================================
class InMemoryDataProvider(DataProvider):
    """
    In-memory data provider for testing or when using external workflow (n8n).
    Data is passed via API and results are returned via API responses.
    """
    
    def __init__(self):
        self.data_store: Dict[UUID, Dict[str, Any]] = {}
        self.status_store: Dict[UUID, Dict[str, str]] = {}
        self.ffm_results: Dict[UUID, Dict[str, Any]] = {}
        self.backtest_results: Dict[UUID, Dict[str, Any]] = {}
    
    def store_data(self, request_id: UUID, ticker: str, ohlcv_data: List[Dict]):
        """Store data for processing (called by n8n via API)"""
        self.data_store[request_id] = {
            'ticker': ticker,
            'ohlcv': ohlcv_data
        }
    
    def get_ticker_data(self, request_id: UUID) -> tuple[pd.DataFrame, str]:
        if request_id not in self.data_store:
            raise ValueError(f"No data found for request {request_id}")
    
        data = self.data_store[request_id]
        ticker = data['ticker']
        raw_json = data['ohlcv']
        
        # Parse to DataFrame
        df = pd.DataFrame(raw_json)
        
        print(f"Original columns: {df.columns.tolist()}")
        print(f"First row: {df.iloc[0].to_dict() if len(df) > 0 else 'No data'}")
        
        # Handle Date parsing - check multiple possible column names
        date_col = None
        for col in ['Date', 'date', 'datetime', 'Datetime', 'Timestamp', 'timestamp', 'time']:
            if col in df.columns:
                date_col = col
                break
        
        if not date_col:
            raise ValueError(f"Could not detect Date column. Available columns: {df.columns.tolist()}")
        
        print(f"Using date column: {date_col}")
        
        # Convert to datetime and set as index
        df[date_col] = pd.to_datetime(df[date_col])
        df.set_index(date_col, inplace=True)
        df.sort_index(inplace=True)
        
        print(f"Date range: {df.index.min()} to {df.index.max()}")
        print(f"Total rows: {len(df)}")
        
        # Normalize columns - handle both lowercase and mixed case
        # Map to expected capitalized format: Open, High, Low, Close, Volume
        column_mapping = {}
        for col in df.columns:
            col_lower = col.lower()
            if col_lower == 'open':
                column_mapping[col] = 'Open'
            elif col_lower == 'high':
                column_mapping[col] = 'High'
            elif col_lower == 'low':
                column_mapping[col] = 'Low'
            elif col_lower == 'close':
                column_mapping[col] = 'Close'
            elif col_lower == 'volume':
                column_mapping[col] = 'Volume'
            else:
                # For any other columns, capitalize first letter
                column_mapping[col] = col.capitalize()
        
        df.rename(columns=column_mapping, inplace=True)
        
        print(f"Normalized columns: {df.columns.tolist()}")
        
        # Verify we have the Close column (required for FFM)
        if 'Close' not in df.columns:
            raise ValueError(f"'Close' column missing after normalization. Available: {df.columns.tolist()}")
        
        return df, ticker
    
    def update_status(self, request_id: UUID, status_text: str, field: str = 'backtest_status'):
        if request_id not in self.status_store:
            self.status_store[request_id] = {}
        self.status_store[request_id][field] = status_text
        print(f"--- {field} status updated to: {status_text} ---")
    
    def get_status(self, request_id: UUID) -> Dict[str, str]:
        return self.status_store.get(request_id, {})
    
    def save_ffm_results(self, request_id: UUID, ticker: str, results: Dict[str, Any]):
        self.ffm_results[request_id] = {
            "request_id": str(request_id),
            "ticker": ticker,
            **results,
            "created_at": datetime.utcnow().isoformat()
        }
        print(f"--- FFM Results saved for {request_id} ---")
    
    def get_ffm_results(self, request_id: UUID) -> Optional[Dict[str, Any]]:
        return self.ffm_results.get(request_id)
    
    def save_backtest_results(self, request_id: UUID, ticker: str, results: Dict[str, Any]):
        self.backtest_results[request_id] = {
            "request_id": str(request_id),
            "ticker": ticker,
            **results,
            "created_at": datetime.utcnow().isoformat()
        }
        print(f"--- Backtest Results saved for {request_id} ---")
    
    def get_backtest_results(self, request_id: UUID) -> Optional[Dict[str, Any]]:
        return self.backtest_results.get(request_id)

# ==========================================
# GLOBAL DATA PROVIDER INSTANCE
# ==========================================
data_provider = InMemoryDataProvider()

# ==========================================
# PYDANTIC MODELS (Request/Response Schemas)
# ==========================================
class DataUploadRequest(BaseModel):
    """Request model for uploading OHLCV data"""
    request_id: UUID = Field(..., description="Unique request ID")
    ticker: str = Field(..., description="Stock ticker symbol")
    ohlcv_data: List[Dict[str, Any]] = Field(..., description="OHLCV data as list of dicts")
    
    class Config:
        json_schema_extra = {
            "example": {
                "request_id": "550e8400-e29b-41d4-a716-446655440000",
                "ticker": "AAPL",
                "ohlcv_data": [
                    {
                        "Date": "2024-01-01",
                        "Open": 100.0,
                        "High": 105.0,
                        "Low": 99.0,
                        "Close": 103.0,
                        "Volume": 1000000
                    }
                ]
            }
        }

class AnalysisRequest(BaseModel):
    """Request model for triggering analysis"""
    request_id: UUID = Field(..., description="Unique request ID")
    
    class Config:
        json_schema_extra = {
            "example": {
                "request_id": "550e8400-e29b-41d4-a716-446655440000"
            }
        }

class BacktestRequest(BaseModel):
    """Request model for backtesting"""
    request_id: UUID = Field(..., description="Unique request ID")
    fast_ma: int = Field(default=10, ge=1, description="Fast moving average period")
    slow_ma: int = Field(default=30, ge=1, description="Slow moving average period")
    initial_cash: float = Field(default=10000.0, gt=0, description="Initial portfolio value")
    
    class Config:
        json_schema_extra = {
            "example": {
                "request_id": "550e8400-e29b-41d4-a716-446655440000",
                "fast_ma": 10,
                "slow_ma": 30,
                "initial_cash": 10000.0
            }
        }

class StatusResponse(BaseModel):
    """Generic status response"""
    request_id: UUID
    message: str
    status: str

class StatusCheckResponse(BaseModel):
    """Status check response with details"""
    request_id: UUID
    statuses: Dict[str, str]
    has_ffm_results: bool
    has_backtest_results: bool

# ==========================================
# ANALYSIS ENGINES
# ==========================================
def run_fama_french(df: pd.DataFrame, ticker: str) -> Optional[Dict[str, float]]:
    """Run Fama-French 3-factor model regression"""
    print("--- Running Fama-French Regression ---")
    try:
        if 'Close' not in df.columns:
            print(f"ERROR: 'Close' column not found")
            return None
        
        # Resample to Monthly
        monthly_ret = df['Close'].resample('ME').last().pct_change().dropna()
        monthly_ret.name = "Portfolio"

        if len(monthly_ret) < 6:
            print(f"ERROR: Only {len(monthly_ret)} months of data")
            return None

        # Fetch Factors
        start = monthly_ret.index[0]
        end = monthly_ret.index[-1]
        
        print(f"Fetching FF factors from {start.date()} to {end.date()}...")
        
        ff_factors = web.DataReader(
            'F-F_Research_Data_Factors', 'famafrench', start, end
        )[0]
        ff_factors = ff_factors / 100.0
        
        print(f"Monthly returns: {len(monthly_ret)} months")
        print(f"FF factors: {len(ff_factors)} months")

        # Convert BOTH to PeriodIndex for matching
        monthly_ret.index = monthly_ret.index.to_period('M')
        # ff_factors already has PeriodIndex
        
        print(f"Monthly ret index type: {type(monthly_ret.index)}")
        print(f"FF factors index type: {type(ff_factors.index)}")
        print(f"Monthly ret sample: {monthly_ret.index[:3].tolist()}")
        print(f"FF factors sample: {ff_factors.index[:3].tolist()}")
        
        # Now merge will work because both are PeriodIndex
        combined = pd.merge(monthly_ret, ff_factors, left_index=True, right_index=True, how='inner')
        
        print(f"Combined: {len(combined)} months after merge")
        
        if len(combined) < 6:
            print(f"ERROR: Only {len(combined)} months after merge")
            return None
        
        combined['XsRet'] = combined['Portfolio'] - combined['RF']
        
        y = combined['XsRet']
        X = sm.add_constant(combined[['Mkt-RF', 'SMB', 'HML']])
        
        model = sm.OLS(y, X).fit()
        
        print("✅ Fama-French regression completed!")
        print(f"   Alpha: {model.params.get('const', 0):.6f}")
        print(f"   Beta: {model.params.get('Mkt-RF', 0):.4f}")
        print(f"   R²: {model.rsquared:.4f}")
        
        return {
            "alpha": float(model.params.get('const', 0)),
            "beta_market": float(model.params.get('Mkt-RF', 0)),
            "beta_smb": float(model.params.get('SMB', 0)),
            "beta_hml": float(model.params.get('HML', 0)),
            "r_squared": float(model.rsquared)
        }
    except Exception as e:
        print(f"FFM Error: {e}")
        import traceback
        traceback.print_exc()
        return None

class SimpleStrategy(bt.Strategy):
    """Moving Average Crossover Strategy"""
    params = (('fast', 10), ('slow', 30),)
    
    def __init__(self):
        self.fast_ma = bt.indicators.SMA(period=self.params.fast)
        self.slow_ma = bt.indicators.SMA(period=self.params.slow)
        self.crossover = bt.indicators.CrossOver(self.fast_ma, self.slow_ma)
    
    def next(self):
        if not self.position:
            if self.crossover > 0:
                self.buy()
        elif self.crossover < 0:
            self.close()

def run_backtest(df: pd.DataFrame, fast_ma: int = 10, 
                 slow_ma: int = 30, initial_cash: float = 10000.0) -> Dict[str, Any]:
    """Run backtest with configurable parameters"""
    print("--- Running Backtest ---")
    print(f"Original data: {len(df)} rows")
    
    # 🔥 OPTIMIZATION: Use only last 6 months for faster processing
    # 6 months ≈ 126 trading days (sufficient for MA strategy)
    if len(df) > 126:
        df = df.tail(126)
        print(f"Optimized to last 126 rows for speed")
    
    cerebro = bt.Cerebro()
    cerebro.adddata(bt.feeds.PandasData(dataname=df))
    cerebro.addstrategy(SimpleStrategy, fast=fast_ma, slow=slow_ma)
    cerebro.broker.setcash(initial_cash)
    
    # Only essential analyzers (faster)
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', riskfreerate=0.0)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    
    # Run
    starting_value = cerebro.broker.getvalue()
    results = cerebro.run()
    final_value = cerebro.broker.getvalue()
    strat = results[0]
    
    # Extract Metrics
    sharpe = strat.analyzers.sharpe.get_analysis().get('sharperatio', 0.0)
    if sharpe is None:
        sharpe = 0.0
    
    max_dd = strat.analyzers.drawdown.get_analysis().get('max', {}).get('drawdown', 0.0)
    total_return = ((final_value - starting_value) / starting_value) * 100
    
    print(f"Backtest completed in optimized mode")
    
    return {
        "sharpe_ratio": float(sharpe),
        "max_drawdown": float(max_dd),
        "final_value": float(final_value),
        "initial_value": float(starting_value),
        "total_return_pct": float(total_return),
        "strategy_params": {
            "fast_ma": fast_ma,
            "slow_ma": slow_ma,
            "initial_cash": initial_cash
        },
        "data_points_used": len(df)
    }

# ==========================================
# BACKGROUND TASK PROCESSORS
# ==========================================
async def process_ffm_analysis(request_id: UUID):
    """Background task for Fama-French analysis"""
    try:
        data_provider.update_status(request_id, 'processing', 'ffm_status')
        
        # Fetch data
        df, ticker = data_provider.get_ticker_data(request_id)
        
        # Run analysis
        ff_res = run_fama_french(df, ticker)
        
        if not ff_res:
            raise ValueError("Insufficient data for Fama-French analysis")
        
        # Save results
        data_provider.save_ffm_results(request_id, ticker, ff_res)
        data_provider.update_status(request_id, 'complete', 'ffm_status')
        
        print(f"--- FFM Analysis Complete for {request_id} ---")
        
    except Exception as e:
        print(f"--- FFM Analysis Failed: {e} ---")
        data_provider.update_status(request_id, 'failed', 'ffm_status')
        data_provider.update_status(request_id, str(e), 'error_log')

async def process_backtest(request_id: UUID, fast_ma: int, 
                          slow_ma: int, initial_cash: float):
    """Background task for backtesting"""
    try:
        data_provider.update_status(request_id, 'processing', 'backtest_status')
        
        # Fetch data
        df, ticker = data_provider.get_ticker_data(request_id)
        
        # Run backtest
        bt_res = run_backtest(df, fast_ma, slow_ma, initial_cash)
        
        # Save results
        data_provider.save_backtest_results(request_id, ticker, bt_res)
        data_provider.update_status(request_id, 'complete', 'backtest_status')
        
        print(f"--- Backtest Complete for {request_id} ---")
        
    except Exception as e:
        print(f"--- Backtest Failed: {e} ---")
        data_provider.update_status(request_id, 'failed', 'backtest_status')
        data_provider.update_status(request_id, str(e), 'error_log')

# ==========================================
# API ENDPOINTS
# ==========================================
@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "status": "online",
        "service": "FFM Backtesting API",
        "version": "1.0.0",
        "mode": "standalone (n8n integration ready)"
    }

@app.post("/api/v1/data/upload", response_model=StatusResponse)
async def upload_data(request: DataUploadRequest):
    """
    Upload OHLCV data for analysis (called by n8n)
    
    n8n should call this endpoint first to provide the data,
    then trigger analysis/backtest endpoints.
    """
    try:
        data_provider.store_data(
            request.request_id,
            request.ticker,
            request.ohlcv_data
        )
        
        return StatusResponse(
            request_id=request.request_id,
            message=f"Data uploaded successfully for {request.ticker}",
            status="ready"
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload data: {str(e)}"
        )

@app.post("/api/v1/analysis/fama-french", response_model=StatusResponse)
async def trigger_fama_french(
    request: AnalysisRequest,
    background_tasks: BackgroundTasks
):
    """
    Trigger Fama-French 3-factor model analysis
    
    Prerequisites: Data must be uploaded via /api/v1/data/upload first
    Returns immediately - analysis runs in background
    """
    try:
        # Verify data exists
        if request.request_id not in data_provider.data_store:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No data found for request {request.request_id}. Upload data first via /api/v1/data/upload"
            )
        
        # Add background task
        background_tasks.add_task(process_ffm_analysis, request.request_id)
        
        return StatusResponse(
            request_id=request.request_id,
            message="Fama-French analysis started",
            status="processing"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start analysis: {str(e)}"
        )

@app.post("/api/v1/backtest/run", response_model=StatusResponse)
async def trigger_backtest(
    request: BacktestRequest,
    background_tasks: BackgroundTasks
):
    """
    Trigger backtesting with moving average crossover strategy
    
    Prerequisites: Data must be uploaded via /api/v1/data/upload first
    Returns immediately - backtest runs in background
    """
    try:
        # Verify data exists
        if request.request_id not in data_provider.data_store:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No data found for request {request.request_id}. Upload data first via /api/v1/data/upload"
            )
        
        # Validate parameters
        if request.fast_ma >= request.slow_ma:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="fast_ma must be less than slow_ma"
            )
        
        # Add background task
        background_tasks.add_task(
            process_backtest,
            request.request_id,
            request.fast_ma,
            request.slow_ma,
            request.initial_cash
        )
        
        return StatusResponse(
            request_id=request.request_id,
            message="Backtest started",
            status="processing"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start backtest: {str(e)}"
        )

@app.get("/api/v1/status/{request_id}", response_model=StatusCheckResponse)
async def get_status(request_id: UUID):
    """
    Get the current status of analyses
    
    Returns status for both FFM and backtest, plus whether results are available
    """
    try:
        statuses = data_provider.get_status(request_id)
        
        if not statuses and request_id not in data_provider.data_store:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Request ID {request_id} not found"
            )
        
        return StatusCheckResponse(
            request_id=request_id,
            statuses=statuses,
            has_ffm_results=data_provider.get_ffm_results(request_id) is not None,
            has_backtest_results=data_provider.get_backtest_results(request_id) is not None
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch status: {str(e)}"
        )

@app.get("/api/v1/results/fama-french/{request_id}")
async def get_ffm_results(request_id: UUID):
    """
    Retrieve Fama-French analysis results
    
    n8n can poll this endpoint to get results when status is 'complete'
    """
    try:
        results = data_provider.get_ffm_results(request_id)
        
        if not results:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No FFM results found for request {request_id}"
            )
        
        return results
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch results: {str(e)}"
        )

@app.get("/api/v1/results/backtest/{request_id}")
async def get_backtest_results(request_id: UUID):
    """
    Retrieve backtest results
    
    n8n can poll this endpoint to get results when status is 'complete'
    """
    try:
        results = data_provider.get_backtest_results(request_id)
        
        if not results:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No backtest results found for request {request_id}"
            )
        
        return results
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch results: {str(e)}"
        )

@app.delete("/api/v1/data/{request_id}")
async def cleanup_data(request_id: UUID):
    """
    Clean up data and results for a request
    
    n8n can call this after retrieving results to free memory
    """
    try:
        removed_items = []
        
        if request_id in data_provider.data_store:
            del data_provider.data_store[request_id]
            removed_items.append("data")
        
        if request_id in data_provider.status_store:
            del data_provider.status_store[request_id]
            removed_items.append("status")
        
        if request_id in data_provider.ffm_results:
            del data_provider.ffm_results[request_id]
            removed_items.append("ffm_results")
        
        if request_id in data_provider.backtest_results:
            del data_provider.backtest_results[request_id]
            removed_items.append("backtest_results")
        
        if not removed_items:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No data found for request {request_id}"
            )
        
        return {
            "request_id": str(request_id),
            "message": "Data cleaned up successfully",
            "removed": removed_items
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to cleanup data: {str(e)}"
        )

# ==========================================
# RUN SERVER
# ==========================================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)