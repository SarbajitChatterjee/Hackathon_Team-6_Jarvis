CREATE OR REPLACE FUNCTION check_portfolio_completion()
RETURNS TRIGGER AS $$
BEGIN
  -- Check if both ACTIVE sub-processes are marked as 'finished'
  IF NEW.fdi_status = 'finished' 
     AND NEW.pdi_status = 'finished'
     AND NEW.backtesting_status = 'finished' 
     AND NEW.modal2_synthesis_status = 'finished'       -- new addition due to modifcation in the table
     THEN
     
     NEW.portfolio_status := 'finished';
     
  END IF;
  
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create the trigger
DROP TRIGGER IF EXISTS update_main_portfolio_status ON public.portfolios;
CREATE TRIGGER update_main_portfolio_status
BEFORE UPDATE ON public.portfolios
FOR EACH ROW
EXECUTE FUNCTION check_portfolio_completion();