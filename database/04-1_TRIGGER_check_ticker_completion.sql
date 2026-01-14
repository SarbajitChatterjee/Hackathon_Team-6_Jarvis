-- 1. Create (or Update) the function to check sub-statuses
CREATE OR REPLACE FUNCTION check_ticker_completion()
RETURNS TRIGGER AS $$
BEGIN
    -- Check if all 3 sub-processes are marked 'complete'
    -- Note: We use IS NOT DISTINCT FROM to handle potential NULLs safely
    IF NEW.financial_analysis_status = 'complete' AND 
       NEW.patent_analysis_status = 'complete' AND 
       NEW.ffm_status = 'complete' AND              -- new addition wrt to new column added
       NEW.backtest_status = 'complete' THEN
       
       -- Update the main status automatically
       NEW.ticker_status = 'complete';
       
       -- Optional: Update the completed_at timestamp if it's not already set
       IF NEW.completed_at IS NULL THEN
           NEW.completed_at = NOW();
       END IF;
    END IF;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 2. Create (or Replace) the Trigger
CREATE OR REPLACE TRIGGER update_main_ticker_status
BEFORE UPDATE ON track_requests
FOR EACH ROW
EXECUTE FUNCTION check_ticker_completion();