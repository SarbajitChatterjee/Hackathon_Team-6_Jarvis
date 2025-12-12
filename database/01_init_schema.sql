-- 1. Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- 2. Create the ENUM for agent status
-- Note: If this type already exists, this command will be skipped or throw a soft error depending on your tool.
-- You can run: DROP TYPE IF EXISTS agent_status CASCADE; if you need a clean slate.
DO $$ BEGIN
    CREATE TYPE agent_status AS ENUM ('PROCESSING', 'FINISHED', 'FAILED');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- 3. Create Table: raw_agent_outputs (Layer 1 Storage)
-- UPDATED: agent_type check constraint now includes specific AnnualStatement types.
CREATE TABLE IF NOT EXISTS raw_agent_outputs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id UUID NOT NULL,
    agent_type TEXT NOT NULL CHECK (
        agent_type IN ('patentData', 'Bloomberg', 'AnnualStatements_C', 'AnnualStatements_I')
    ),
    status agent_status DEFAULT 'PROCESSING',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    payload JSONB DEFAULT '{}'::jsonb
);

-- 4. Create Table: master_insights (Layer 2 Storage)
CREATE TABLE IF NOT EXISTS master_insights (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id UUID NOT NULL,
    insight_summary TEXT,
    structured_data JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 5. Performance Indexes
CREATE INDEX IF NOT EXISTS idx_raw_agent_batch_id ON raw_agent_outputs(batch_id);
CREATE INDEX IF NOT EXISTS idx_master_insights_batch_id ON master_insights(batch_id);
CREATE INDEX IF NOT EXISTS idx_raw_agent_composite ON raw_agent_outputs(batch_id, agent_type, status);

-- 6. Security (RLS)
ALTER TABLE raw_agent_outputs ENABLE ROW LEVEL SECURITY;
ALTER TABLE master_insights ENABLE ROW LEVEL SECURITY;

-- Dev Policy: Allow all access
DROP POLICY IF EXISTS "Enable all access for dev" ON raw_agent_outputs;
CREATE POLICY "Enable all access for dev" ON raw_agent_outputs FOR ALL USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "Enable all access for dev" ON master_insights;
CREATE POLICY "Enable all access for dev" ON master_insights FOR ALL USING (true) WITH CHECK (true);