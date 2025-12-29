-- 1. Create the Function that checks for completion
CREATE OR REPLACE FUNCTION check_portfolio_completion()
RETURNS TRIGGER AS $$
BEGIN
  -- Check if there are ANY pending/processing requests left for this portfolio
  IF NOT EXISTS (
    SELECT 1 
    FROM track_requests 
    WHERE portfolio_id = NEW.portfolio_id 
      AND status IN ('PENDING', 'PROCESSING')
  ) THEN
    -- If NONE are pending, the whole Portfolio is done!
    UPDATE portfolios
    SET status = 'COMPLETED'
    WHERE id = NEW.portfolio_id;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 2. Create the Trigger to run it automatically
CREATE TRIGGER on_track_request_update
AFTER UPDATE OF status ON track_requests
FOR EACH ROW
WHEN (NEW.status = 'COMPLETED') -- Only run when a task finishes
EXECUTE FUNCTION check_portfolio_completion();