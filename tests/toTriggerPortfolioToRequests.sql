-- Create a demo portfolio that will trigger your Database Webhook (INSERT)
insert into public.portfolios (name, input_tickers, thesis, portfolio_status)
values (
  'Demo Portfolio-1',
  array['TST1','MST2','IST3'],
  'Testing n8n webhook + ticker fan-out',
  'processing'
)
returning id, created_at, input_tickers;