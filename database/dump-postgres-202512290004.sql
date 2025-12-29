--
-- PostgreSQL database dump
--

-- Dumped from database version 17.6
-- Dumped by pg_dump version 17.0

-- Started on 2025-12-29 00:04:08

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- TOC entry 34 (class 2615 OID 2200)
-- Name: public; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA public;


--
-- TOC entry 3912 (class 0 OID 0)
-- Dependencies: 34
-- Name: SCHEMA public; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON SCHEMA public IS 'standard public schema';


--
-- TOC entry 40 (class 2615 OID 18727)
-- Name: supabase_functions; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA supabase_functions;


--
-- TOC entry 27 (class 2615 OID 16653)
-- Name: vault; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA vault;


--
-- TOC entry 1261 (class 1247 OID 17498)
-- Name: agent_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.agent_status AS ENUM (
    'PROCESSING',
    'FINISHED',
    'FAILED'
);


--
-- TOC entry 535 (class 1255 OID 33442)
-- Name: check_portfolio_completion(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.check_portfolio_completion() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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
$$;


--
-- TOC entry 533 (class 1255 OID 18751)
-- Name: http_request(); Type: FUNCTION; Schema: supabase_functions; Owner: -
--

CREATE FUNCTION supabase_functions.http_request() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'supabase_functions'
    AS $$
    DECLARE
      request_id bigint;
      payload jsonb;
      url text := TG_ARGV[0]::text;
      method text := TG_ARGV[1]::text;
      headers jsonb DEFAULT '{}'::jsonb;
      params jsonb DEFAULT '{}'::jsonb;
      timeout_ms integer DEFAULT 1000;
    BEGIN
      IF url IS NULL OR url = 'null' THEN
        RAISE EXCEPTION 'url argument is missing';
      END IF;

      IF method IS NULL OR method = 'null' THEN
        RAISE EXCEPTION 'method argument is missing';
      END IF;

      IF TG_ARGV[2] IS NULL OR TG_ARGV[2] = 'null' THEN
        headers = '{"Content-Type": "application/json"}'::jsonb;
      ELSE
        headers = TG_ARGV[2]::jsonb;
      END IF;

      IF TG_ARGV[3] IS NULL OR TG_ARGV[3] = 'null' THEN
        params = '{}'::jsonb;
      ELSE
        params = TG_ARGV[3]::jsonb;
      END IF;

      IF TG_ARGV[4] IS NULL OR TG_ARGV[4] = 'null' THEN
        timeout_ms = 1000;
      ELSE
        timeout_ms = TG_ARGV[4]::integer;
      END IF;

      CASE
        WHEN method = 'GET' THEN
          SELECT http_get INTO request_id FROM net.http_get(
            url,
            params,
            headers,
            timeout_ms
          );
        WHEN method = 'POST' THEN
          payload = jsonb_build_object(
            'old_record', OLD,
            'record', NEW,
            'type', TG_OP,
            'table', TG_TABLE_NAME,
            'schema', TG_TABLE_SCHEMA
          );

          SELECT http_post INTO request_id FROM net.http_post(
            url,
            payload,
            params,
            headers,
            timeout_ms
          );
        ELSE
          RAISE EXCEPTION 'method argument % is invalid', method;
      END CASE;

      INSERT INTO supabase_functions.hooks
        (hook_table_id, hook_name, request_id)
      VALUES
        (TG_RELID, TG_NAME, request_id);

      RETURN NEW;
    END
  $$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- TOC entry 400 (class 1259 OID 28882)
-- Name: backtest_results; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.backtest_results (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
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
    created_at timestamp with time zone DEFAULT timezone('utc'::text, now()) NOT NULL
);


--
-- TOC entry 399 (class 1259 OID 28868)
-- Name: patent_data; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.patent_data (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    request_id uuid,
    ticker text NOT NULL,
    summary_payload jsonb,
    patent_count integer,
    created_at timestamp with time zone DEFAULT timezone('utc'::text, now()) NOT NULL
);


--
-- TOC entry 397 (class 1259 OID 28844)
-- Name: track_requests; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.track_requests (
    request_id uuid DEFAULT gen_random_uuid() NOT NULL,
    ticker text NOT NULL,
    status text DEFAULT 'PENDING'::text,
    created_at timestamp with time zone DEFAULT timezone('utc'::text, now()) NOT NULL,
    completed_at timestamp with time zone,
    error_log text,
    portfolio_id uuid
);


--
-- TOC entry 401 (class 1259 OID 28896)
-- Name: dashboard_view; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.dashboard_view AS
 SELECT tr.request_id,
    tr.ticker,
    tr.status,
    br.sharpe_ratio,
    br.alpha,
    br.plot_data,
    br.ai_analysis_payload,
    pd.summary_payload AS patent_summary
   FROM ((public.track_requests tr
     LEFT JOIN public.backtest_results br ON ((tr.request_id = br.request_id)))
     LEFT JOIN public.patent_data pd ON ((tr.request_id = pd.request_id)));


--
-- TOC entry 402 (class 1259 OID 33427)
-- Name: portfolios; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.portfolios (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name text NOT NULL,
    input_tickers text[],
    portfolio_status text DEFAULT 'PENDING'::text,
    created_at timestamp with time zone DEFAULT now(),
    user_id uuid DEFAULT auth.uid(),
    thesis text,
    ticker_count integer DEFAULT 0 NOT NULL,
    backtesting_status text DEFAULT 'pending'::text,
    fdi_status text DEFAULT 'pending'::text,
    pdi_status text DEFAULT 'pending'::text,
    CONSTRAINT portfolios_backtesting_status_check CHECK ((backtesting_status = ANY (ARRAY['pending'::text, 'running'::text, 'complete'::text, 'finished'::text, 'failed'::text]))),
    CONSTRAINT portfolios_fdi_status_check CHECK ((fdi_status = ANY (ARRAY['pending'::text, 'running'::text, 'complete'::text, 'finished'::text, 'failed'::text]))),
    CONSTRAINT portfolios_pdi_status_check CHECK ((pdi_status = ANY (ARRAY['pending'::text, 'running'::text, 'complete'::text, 'finished'::text, 'failed'::text]))),
    CONSTRAINT portfolios_portfolio_status_check CHECK ((portfolio_status = ANY (ARRAY['pending'::text, 'processing'::text, 'completed'::text, 'failed'::text])))
);


--
-- TOC entry 398 (class 1259 OID 28854)
-- Name: ticker_data; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ticker_data (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    request_id uuid,
    ticker text NOT NULL,
    period_start date,
    period_end date,
    raw_ohlcv jsonb,
    created_at timestamp with time zone DEFAULT timezone('utc'::text, now()) NOT NULL
);


--
-- TOC entry 396 (class 1259 OID 18740)
-- Name: hooks; Type: TABLE; Schema: supabase_functions; Owner: -
--

CREATE TABLE supabase_functions.hooks (
    id bigint NOT NULL,
    hook_table_id integer NOT NULL,
    hook_name text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    request_id bigint
);


--
-- TOC entry 3913 (class 0 OID 0)
-- Dependencies: 396
-- Name: TABLE hooks; Type: COMMENT; Schema: supabase_functions; Owner: -
--

COMMENT ON TABLE supabase_functions.hooks IS 'Supabase Functions Hooks: Audit trail for triggered hooks.';


--
-- TOC entry 395 (class 1259 OID 18739)
-- Name: hooks_id_seq; Type: SEQUENCE; Schema: supabase_functions; Owner: -
--

CREATE SEQUENCE supabase_functions.hooks_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- TOC entry 3914 (class 0 OID 0)
-- Dependencies: 395
-- Name: hooks_id_seq; Type: SEQUENCE OWNED BY; Schema: supabase_functions; Owner: -
--

ALTER SEQUENCE supabase_functions.hooks_id_seq OWNED BY supabase_functions.hooks.id;


--
-- TOC entry 394 (class 1259 OID 18731)
-- Name: migrations; Type: TABLE; Schema: supabase_functions; Owner: -
--

CREATE TABLE supabase_functions.migrations (
    version text NOT NULL,
    inserted_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- TOC entry 3702 (class 2604 OID 18743)
-- Name: hooks id; Type: DEFAULT; Schema: supabase_functions; Owner: -
--

ALTER TABLE ONLY supabase_functions.hooks ALTER COLUMN id SET DEFAULT nextval('supabase_functions.hooks_id_seq'::regclass);


--
-- TOC entry 3742 (class 2606 OID 28890)
-- Name: backtest_results backtest_results_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.backtest_results
    ADD CONSTRAINT backtest_results_pkey PRIMARY KEY (id);


--
-- TOC entry 3740 (class 2606 OID 28876)
-- Name: patent_data patent_data_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.patent_data
    ADD CONSTRAINT patent_data_pkey PRIMARY KEY (id);


--
-- TOC entry 3744 (class 2606 OID 33438)
-- Name: portfolios portfolios_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.portfolios
    ADD CONSTRAINT portfolios_pkey PRIMARY KEY (id);


--
-- TOC entry 3738 (class 2606 OID 28862)
-- Name: ticker_data ticker_data_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ticker_data
    ADD CONSTRAINT ticker_data_pkey PRIMARY KEY (id);


--
-- TOC entry 3736 (class 2606 OID 28853)
-- Name: track_requests track_requests_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.track_requests
    ADD CONSTRAINT track_requests_pkey PRIMARY KEY (request_id);


--
-- TOC entry 3731 (class 2606 OID 18748)
-- Name: hooks hooks_pkey; Type: CONSTRAINT; Schema: supabase_functions; Owner: -
--

ALTER TABLE ONLY supabase_functions.hooks
    ADD CONSTRAINT hooks_pkey PRIMARY KEY (id);


--
-- TOC entry 3729 (class 2606 OID 18738)
-- Name: migrations migrations_pkey; Type: CONSTRAINT; Schema: supabase_functions; Owner: -
--

ALTER TABLE ONLY supabase_functions.migrations
    ADD CONSTRAINT migrations_pkey PRIMARY KEY (version);


--
-- TOC entry 3734 (class 1259 OID 33450)
-- Name: idx_track_requests_portfolio_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_track_requests_portfolio_id ON public.track_requests USING btree (portfolio_id);


--
-- TOC entry 3732 (class 1259 OID 18750)
-- Name: supabase_functions_hooks_h_table_id_h_name_idx; Type: INDEX; Schema: supabase_functions; Owner: -
--

CREATE INDEX supabase_functions_hooks_h_table_id_h_name_idx ON supabase_functions.hooks USING btree (hook_table_id, hook_name);


--
-- TOC entry 3733 (class 1259 OID 18749)
-- Name: supabase_functions_hooks_request_id_idx; Type: INDEX; Schema: supabase_functions; Owner: -
--

CREATE INDEX supabase_functions_hooks_request_id_idx ON supabase_functions.hooks USING btree (request_id);


--
-- TOC entry 3749 (class 2620 OID 33443)
-- Name: track_requests on_track_request_update; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER on_track_request_update AFTER UPDATE OF status ON public.track_requests FOR EACH ROW WHEN ((new.status = 'COMPLETED'::text)) EXECUTE FUNCTION public.check_portfolio_completion();


--
-- TOC entry 3752 (class 2620 OID 35787)
-- Name: portfolios test-trigger-dispatcher; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER "test-trigger-dispatcher" AFTER INSERT ON public.portfolios FOR EACH ROW EXECUTE FUNCTION supabase_functions.http_request('https://unisaarland.app.n8n.cloud/webhook-test/c1181c25-0e1c-4b40-8163-e26039648638', 'POST', '{"Content-type":"application/json"}', '{}', '5000');


--
-- TOC entry 3750 (class 2620 OID 35857)
-- Name: track_requests test_track_requests_processing_webhook; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER test_track_requests_processing_webhook AFTER UPDATE ON public.track_requests FOR EACH ROW WHEN (((new.status = 'processing'::text) AND (old.status IS DISTINCT FROM 'PROCESSING'::text))) EXECUTE FUNCTION supabase_functions.http_request('https://unisaarland.app.n8n.cloud/webhook-test/e3220644-3d11-4f22-ac3d-fc06bddc44bd', 'POST', '{"Content-Type":"application/json"}', '{}', '5000');


--
-- TOC entry 3751 (class 2620 OID 35931)
-- Name: track_requests track_requests_processing_webhook; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER track_requests_processing_webhook AFTER INSERT OR UPDATE ON public.track_requests FOR EACH ROW WHEN ((new.status = 'processing'::text)) EXECUTE FUNCTION supabase_functions.http_request('https://unisaarland.app.n8n.cloud/webhook/e3220644-3d11-4f22-ac3d-fc06bddc44bd', 'POST', '{"Content-Type":"application/json"}', '{}', '5000');


--
-- TOC entry 3753 (class 2620 OID 34643)
-- Name: portfolios trigger-dispatcher; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER "trigger-dispatcher" AFTER INSERT ON public.portfolios FOR EACH ROW EXECUTE FUNCTION supabase_functions.http_request('https://unisaarland.app.n8n.cloud/webhook/c1181c25-0e1c-4b40-8163-e26039648638', 'POST', '{"Content-type":"application/json"}', '{}', '5000');


--
-- TOC entry 3748 (class 2606 OID 28891)
-- Name: backtest_results backtest_results_request_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.backtest_results
    ADD CONSTRAINT backtest_results_request_id_fkey FOREIGN KEY (request_id) REFERENCES public.track_requests(request_id);


--
-- TOC entry 3747 (class 2606 OID 28877)
-- Name: patent_data patent_data_request_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.patent_data
    ADD CONSTRAINT patent_data_request_id_fkey FOREIGN KEY (request_id) REFERENCES public.track_requests(request_id);


--
-- TOC entry 3746 (class 2606 OID 28863)
-- Name: ticker_data ticker_data_request_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ticker_data
    ADD CONSTRAINT ticker_data_request_id_fkey FOREIGN KEY (request_id) REFERENCES public.track_requests(request_id);


--
-- TOC entry 3745 (class 2606 OID 33445)
-- Name: track_requests track_requests_portfolio_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.track_requests
    ADD CONSTRAINT track_requests_portfolio_id_fkey FOREIGN KEY (portfolio_id) REFERENCES public.portfolios(id) ON DELETE CASCADE;


--
-- TOC entry 3905 (class 3256 OID 33440)
-- Name: portfolios Users can insert own portfolios; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Users can insert own portfolios" ON public.portfolios FOR INSERT WITH CHECK ((auth.uid() = user_id));


--
-- TOC entry 3904 (class 3256 OID 33439)
-- Name: portfolios Users can view own portfolios; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Users can view own portfolios" ON public.portfolios FOR SELECT USING ((auth.uid() = user_id));


--
-- TOC entry 3903 (class 0 OID 33427)
-- Dependencies: 402
-- Name: portfolios; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.portfolios ENABLE ROW LEVEL SECURITY;

-- Completed on 2025-12-29 00:04:10

--
-- PostgreSQL database dump complete
--

