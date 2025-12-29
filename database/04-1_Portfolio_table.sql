-- 1. Create the PORTFOLIOS table (The Hub)
CREATE TABLE IF NOT EXISTS portfolios (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  
  -- The user-friendly name. If they don't provide one, your code should auto-fill this with the ticker names.
  name TEXT NOT NULL, 
  
  -- CRITICAL: This is an array. It stores ['AAPL'] or ['AAPL', 'MSFT'].
  input_tickers TEXT[] NOT NULL, 
  
  -- Status tracks the "Brain" work (Friction 2).
  status TEXT CHECK (status IN ('PENDING', 'PROCESSING', 'COMPLETED', 'FAILED')) DEFAULT 'PENDING',
  
  created_at TIMESTAMPTZ DEFAULT NOW(),
  user_id UUID DEFAULT auth.uid()
);

-- 2. Security Policy (Row Level Security)
-- This ensures User A cannot see User B's portfolios.
ALTER TABLE portfolios ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own portfolios" 
ON portfolios FOR SELECT 
USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own portfolios" 
ON portfolios FOR INSERT 
WITH CHECK (auth.uid() = user_id);