-- WARNING: This schema is for context only and is not meant to be run.
-- Table order and constraints may not be valid for execution.

CREATE TABLE public.backtest_results (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  request_id uuid,
  ticker text NOT NULL,
  alpha numeric,
  beta_market numeric,
  beta_smb numeric,
  beta_hml numeric,
  sharpe_ratio numeric,
  max_drawdown numeric,
  plot_data jsonb,
  ai_analysis_payload jsonb,
  created_at timestamp with time zone NOT NULL DEFAULT timezone('utc'::text, now()),
  CONSTRAINT backtest_results_pkey PRIMARY KEY (id),
  CONSTRAINT backtest_results_request_id_fkey FOREIGN KEY (request_id) REFERENCES public.track_requests(request_id)
);
CREATE TABLE public.patent_data (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  request_id uuid,
  ticker text NOT NULL,
  summary_payload jsonb,
  patent_count integer,
  created_at timestamp with time zone NOT NULL DEFAULT timezone('utc'::text, now()),
  CONSTRAINT patent_data_pkey PRIMARY KEY (id),
  CONSTRAINT patent_data_request_id_fkey FOREIGN KEY (request_id) REFERENCES public.track_requests(request_id)
);
CREATE TABLE public.portfolios (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  name text NOT NULL,
  input_tickers ARRAY NOT NULL,
  status text DEFAULT 'PENDING'::text CHECK (status = ANY (ARRAY['PENDING'::text, 'PROCESSING'::text, 'COMPLETED'::text, 'FAILED'::text])),
  created_at timestamp with time zone DEFAULT now(),
  user_id uuid DEFAULT auth.uid(),
  thesis text,
  CONSTRAINT portfolios_pkey PRIMARY KEY (id)
);
CREATE TABLE public.ticker_data (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  request_id uuid,
  ticker text NOT NULL,
  period_start date,
  period_end date,
  raw_ohlcv jsonb,
  created_at timestamp with time zone NOT NULL DEFAULT timezone('utc'::text, now()),
  CONSTRAINT ticker_data_pkey PRIMARY KEY (id),
  CONSTRAINT ticker_data_request_id_fkey FOREIGN KEY (request_id) REFERENCES public.track_requests(request_id)
);
CREATE TABLE public.track_requests (
  request_id uuid NOT NULL DEFAULT gen_random_uuid(),
  ticker text NOT NULL,
  status text DEFAULT 'PENDING'::text,
  created_at timestamp with time zone NOT NULL DEFAULT timezone('utc'::text, now()),
  completed_at timestamp with time zone,
  error_log text,
  portfolio_id uuid,
  CONSTRAINT track_requests_pkey PRIMARY KEY (request_id),
  CONSTRAINT track_requests_portfolio_id_fkey FOREIGN KEY (portfolio_id) REFERENCES public.portfolios(id)
);