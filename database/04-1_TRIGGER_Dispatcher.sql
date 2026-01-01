-- A. DISPATCHER TRIGGER (Portfolios -> Dispatcher Workflow)
CREATE OR REPLACE FUNCTION notify_dispatcher() RETURNS TRIGGER AS $$
BEGIN
    PERFORM net.http_post(
        url := 'https://unisaarland.app.n8n.cloud/webhook/c1181c25-0e1c-4b40-8163-e26039648638',
        body := jsonb_build_object('type', 'INSERT', 'record', row_to_json(NEW))
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_01_dispatcher
AFTER INSERT ON public.portfolios
FOR EACH ROW
EXECUTE FUNCTION notify_dispatcher();

-- B. FDI TRIGGER (Track Requests -> Financial Workflow)
CREATE OR REPLACE FUNCTION notify_fdi() RETURNS TRIGGER AS $$
BEGIN
    PERFORM net.http_post(
        url := 'https://unisaarland.app.n8n.cloud/webhook/e3220644-3d11-4f22-ac3d-fc06bddc44bd',
        body := jsonb_build_object('type', 'INSERT', 'record', row_to_json(NEW))
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_02_fdi
AFTER INSERT ON public.track_requests
FOR EACH ROW
EXECUTE FUNCTION notify_fdi();