-- To be replaced by check_ticker_completion() Trigger

CREATE OR REPLACE FUNCTION check_request_completion()
RETURNS TRIGGER AS $$
BEGIN
  -- MODIFIED: Mark ticker_status as 'complete' purely based on FDI status.
  -- We are temporarily ignoring patent_analysis_status and backtest_status.
  
  IF NEW.financial_analysis_status = 'complete' THEN
     
     NEW.ticker_status := 'complete';
     NEW.completed_at := NOW();
     
  END IF;
  
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;