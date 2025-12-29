-- Step 1: Update existing rows to valid values
UPDATE public.portfolios 
SET status = CASE 
  WHEN status = 'PENDING' THEN 'pending'
  WHEN status = 'PROCESSING' THEN 'processing'
  WHEN status = 'COMPLETED' THEN 'completed'
  WHEN status = 'FAILED' THEN 'failed'
  ELSE 'pending'
END;

-- Step 2: Drop the old constraint
ALTER TABLE public.portfolios 
  DROP CONSTRAINT IF EXISTS portfolios_status_check;

-- Step 3: Rename column
ALTER TABLE public.portfolios 
  RENAME COLUMN status TO portfolio_status;

-- Step 4: Add new constraint
ALTER TABLE public.portfolios 
  ADD CONSTRAINT portfolios_portfolio_status_check 
  CHECK (portfolio_status IN ('pending', 'processing', 'completed', 'failed'));

-- Step 5: Add new tracking columns
ALTER TABLE public.portfolios 
  ADD COLUMN IF NOT EXISTS tickers_financial_complete integer DEFAULT 0,
  ADD COLUMN IF NOT EXISTS tickers_patent_complete integer DEFAULT 0,
  ADD COLUMN IF NOT EXISTS backtesting_status text DEFAULT 'pending' 
    CHECK (backtesting_status IN ('pending', 'running', 'complete', 'finished', 'failed')),
  ADD COLUMN IF NOT EXISTS FDI_status text DEFAULT 'pending' 
    CHECK (FDI_status IN ('pending', 'running', 'complete', 'finished', 'failed')),
  ADD COLUMN IF NOT EXISTS PDI_status text DEFAULT 'pending' 
    CHECK (PDI_status IN ('pending', 'running', 'complete', 'finished', 'failed'));

-- Step 6: Make input_tickers nullable
ALTER TABLE public.portfolios 
  ALTER COLUMN input_tickers DROP NOT NULL;