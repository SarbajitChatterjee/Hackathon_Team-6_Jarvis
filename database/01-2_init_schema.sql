-- 1. 'track_requests' (The Controller)
-- Tracks the lifecycle. Every analysis starts here.
CREATE TABLE IF NOT EXISTS public.track_requests (
    request_id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    ticker TEXT NOT NULL,
    status TEXT DEFAULT 'PENDING', -- PENDING, PROCESSING, COMPLETED, FAILED
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL,
    completed_at TIMESTAMP WITH TIME ZONE,
    error_log TEXT
);

-- 2. 'ticker_data' (The Financial Foundation)
-- Stores cleaned price history/calculations so we don't re-fetch from API every time.
CREATE TABLE IF NOT EXISTS public.ticker_data (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    request_id UUID REFERENCES public.track_requests(request_id),
    ticker TEXT NOT NULL,
    period_start DATE,
    period_end DATE,
    raw_ohlcv JSONB, -- Stores the daily price data structure
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- 3. 'patent_data' (The IP Asset)
-- Stores the output from the Patent Agent.
CREATE TABLE IF NOT EXISTS public.patent_data (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    request_id UUID REFERENCES public.track_requests(request_id),
    ticker TEXT NOT NULL,
    summary_payload JSONB, -- The AI summary of patents
    patent_count INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- 4. 'backtest_results' (The Quant & AI Vault)
-- This is your hybrid table. 
-- 'Backtesting/FFM' inserts the metrics. 'Modal 2' updates the ai_analysis_payload.
CREATE TABLE IF NOT EXISTS public.backtest_results (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    request_id UUID REFERENCES public.track_requests(request_id),
    ticker TEXT NOT NULL,
    
    -- QUANTITATIVE FIELDS (Inserted by Python Node)
    alpha NUMERIC,
    beta_market NUMERIC,
    beta_smb NUMERIC, -- Small Minus Big
    beta_hml NUMERIC, -- High Minus Low
    sharpe_ratio NUMERIC,
    max_drawdown NUMERIC,
    plot_data JSONB, -- X/Y coordinates for frontend charts
    
    -- QUALITATIVE FIELD (Updated by Modal 2)
    -- This is nullable so the Quant engine can save first without error.
    ai_analysis_payload JSONB DEFAULT NULL,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- 5. Create a View for Frontend Fetching
-- Joins everything into one easy API call for your dashboard.
CREATE OR REPLACE VIEW public.dashboard_view AS
SELECT 
    tr.request_id,
    tr.ticker,
    tr.status,
    br.sharpe_ratio,
    br.alpha,
    br.plot_data,
    br.ai_analysis_payload,
    pd.summary_payload as patent_summary
FROM track_requests tr
LEFT JOIN backtest_results br ON tr.request_id = br.request_id
LEFT JOIN patent_data pd ON tr.request_id = pd.request_id;