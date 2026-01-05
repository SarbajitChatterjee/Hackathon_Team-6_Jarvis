import os
import sys
import json
import pandas as pd
import numpy as np
import backtrader as bt
import statsmodels.api as sm
import pandas_datareader.data as web
from supabase import create_client, Client
from datetime import datetime

# ==========================================
# 1. SETUP & CREDENTIALS
# ==========================================
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
REQUEST_ID = os.environ.get("REQUEST_ID") # Passed from n8n

if not all([SUPABASE_URL, SUPABASE_KEY, REQUEST_ID]):
    print("CRITICAL ERROR: Missing Env Vars (SUPABASE_URL, SUPABASE_KEY, or REQUEST_ID)")
    sys.exit(1)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ==========================================
# 2. DATABASE UTILS
# ==========================================
def update_status(status_text):
    """Updates the track_requests table status"""
    try:
        supabase.table('track_requests').update({'backtest_status': status_text}).eq('request_id', REQUEST_ID).execute()
        print(f"--- Status updated to: {status_text} ---")
    except Exception as e:
        print(f"Error updating status: {e}")

def fetch_ticker_data():
    """
    Fetches the raw OHLCV JSON from ticker_data table using REQUEST_ID.
    Returns: (DataFrame, Ticker_Name)
    """
    print(f"--- Fetching Data for Request: {REQUEST_ID} ---")
    
    # 1. Get the Ticker Name from track_requests (for context)
    req_response = supabase.table('track_requests').select('ticker').eq('request_id', REQUEST_ID).execute()
    if not req_response.data:
        raise ValueError("Invalid Request ID")
    ticker = req_response.data[0]['ticker']

    # 2. Get the Raw Data from ticker_data
    data_response = supabase.table('ticker_data').select('raw_ohlcv').eq('request_id', REQUEST_ID).execute()
    if not data_response.data or not data_response.data[0]['raw_ohlcv']:
        raise ValueError(f"No OHLCV data found in ticker_data for request {REQUEST_ID}")
    
    raw_json = data_response.data[0]['raw_ohlcv']
    
    # 3. Parse JSONB to DataFrame
    # Assumption: raw_ohlcv is a list of dicts: [{'Date': '...', 'Open': 100, ...}, ...]
    df = pd.DataFrame(raw_json)
    
    # Handle Date parsing (crucial!)
    # Check common date column names
    date_col = None
    for col in ['Date', 'date', 'datetime', 'Timestamp']:
        if col in df.columns:
            date_col = col
            break
            
    if not date_col:
        raise ValueError("Could not detect Date column in raw_ohlcv JSON")

    df[date_col] = pd.to_datetime(df[date_col])
    df.set_index(date_col, inplace=True)
    df.sort_index(inplace=True)
    
    # Normalize columns for Backtrader (Capitalized)
    col_map = {c: c.capitalize() for c in df.columns}
    df.rename(columns=col_map, inplace=True)
    
    return df, ticker

# ==========================================
# 3. ANALYSIS ENGINES
# ==========================================
def run_fama_french(df, ticker):
    print("--- Running Fama-French Regression ---")
    try:
        # Resample to Monthly for stability
        monthly_ret = df['Close'].resample('ME').last().pct_change().dropna()
        monthly_ret.name = "Portfolio"

        if len(monthly_ret) < 6:
            return None # Not enough data

        # Fetch Factors (Requires Internet)
        start = monthly_ret.index[0]
        end = monthly_ret.index[-1]
        ff_factors = web.DataReader('F-F_Research_Data_Factors', 'famafrench', start, end)[0]
        ff_factors = ff_factors / 100.0
        
        combined = pd.merge(monthly_ret, ff_factors, left_index=True, right_index=True)
        combined['XsRet'] = combined['Portfolio'] - combined['RF']
        
        y = combined['XsRet']
        X = sm.add_constant(combined[['Mkt-RF', 'SMB', 'HML']])
        
        model = sm.OLS(y, X).fit()
        
        return {
            "alpha": float(model.params.get('const', 0)),
            "beta_market": float(model.params.get('Mkt-RF', 0)),
            "beta_smb": float(model.params.get('SMB', 0)),
            "beta_hml": float(model.params.get('HML', 0))
        }
    except Exception as e:
        print(f"FFM Error: {e}")
        return None

class SimpleStrategy(bt.Strategy):
    params = (('fast', 10), ('slow', 30),)
    def __init__(self):
        self.fast_ma = bt.indicators.SMA(period=self.params.fast)
        self.slow_ma = bt.indicators.SMA(period=self.params.slow)
        self.crossover = bt.indicators.CrossOver(self.fast_ma, self.slow_ma)
    def next(self):
        if not self.position:
            if self.crossover > 0: self.buy()
        elif self.crossover < 0: self.close()

def run_backtest(df):
    print("--- Running Backtest ---")
    cerebro = bt.Cerebro()
    cerebro.adddata(bt.feeds.PandasData(dataname=df))
    cerebro.addstrategy(SimpleStrategy)
    cerebro.broker.setcash(10000.0)
    
    # Analyzers for Schema Requirements
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', riskfreerate=0.0)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    
    # Run
    results = cerebro.run()
    strat = results[0]
    
    # Extract Metrics
    sharpe = strat.analyzers.sharpe.get_analysis().get('sharperatio', 0.0)
    if sharpe is None: sharpe = 0.0
    
    max_dd = strat.analyzers.drawdown.get_analysis().get('max', {}).get('drawdown', 0.0)
    
    # Extract Plot Data (Equity Curve)
    # We reconstruct this from the broker observers
    equity_curve = []
    # Note: Backtrader's internal data extraction can be tricky. 
    # A simpler way is to just assume daily close * position or track it in the strategy.
    # For robust plotting, we usually add an observer or logger.
    # Here is a simplified approximation using the broker value at the end:
    final_value = cerebro.broker.getvalue()

    return {
        "sharpe_ratio": float(sharpe),
        "max_drawdown": float(max_dd),
        "final_value": float(final_value),
        # In a real production app, you would log daily values in the strategy
        # to build the 'plot_data' JSON array.
        "plot_data": [{"status": "placeholder_for_equity_curve"}] 
    }

# ==========================================
# 4. MAIN WORKFLOW
# ==========================================
if __name__ == "__main__":
    update_status('processing')
    
    try:
        # 1. Get Data
        df, ticker = fetch_ticker_data()
        
        # 2. Run Analysis
        ff_res = run_fama_french(df, ticker)
        bt_res = run_backtest(df)
        
        # 3. Prepare Payloads
        # AI Payload: A clean summary for the LLM to read later
        ai_payload = {
            "summary": f"Backtest for {ticker} resulted in Sharpe {bt_res['sharpe_ratio']:.2f}.",
            "metrics": {
                "alpha": ff_res['alpha'] if ff_res else 0,
                "beta": ff_res['beta_market'] if ff_res else 0,
                "max_drawdown": bt_res['max_drawdown']
            }
        }

        # 4. Save to DB
        insert_payload = {
            "request_id": REQUEST_ID,
            "ticker": ticker,
            "alpha": ff_res['alpha'] if ff_res else None,
            "beta_market": ff_res['beta_market'] if ff_res else None,
            "beta_smb": ff_res['beta_smb'] if ff_res else None,
            "beta_hml": ff_res['beta_hml'] if ff_res else None,
            "sharpe_ratio": bt_res['sharpe_ratio'],
            "max_drawdown": bt_res['max_drawdown'],
            "plot_data": bt_res['plot_data'],
            "ai_analysis_payload": ai_payload
        }

        print("--- Saving Results to DB ---")
        supabase.table('backtest_results').insert(insert_payload).execute()
        
        # 5. Mark Complete
        # Also update track_requests to 'complete' for the backtest column
        supabase.table('track_requests').update({
            'backtest_status': 'complete',
            'ticker_status': 'processing' # Still processing other things? or complete?
        }).eq('request_id', REQUEST_ID).execute()
        
        print("--- SUCCESS ---")

    except Exception as e:
        print(f"--- FAILURE: {e} ---")
        # Log error to DB
        supabase.table('track_requests').update({
            'backtest_status': 'failed', 
            'error_log': str(e)
        }).eq('request_id', REQUEST_ID).execute()
        sys.exit(1)