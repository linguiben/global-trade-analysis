-- init_db.sql
-- Baseline schema for Global Trade Analysis.
-- Keep this file as the source of truth for table/index creation.

CREATE TABLE IF NOT EXISTS public.user_visit_log (
    id BIGSERIAL PRIMARY KEY,
    ip VARCHAR(64) NOT NULL,
    user_agent VARCHAR(512) NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.job_definitions (
    job_id VARCHAR(100) PRIMARY KEY,
    name VARCHAR(160) NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    cron_expr VARCHAR(64) NOT NULL,
    timezone VARCHAR(64) NOT NULL DEFAULT 'UTC',
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    default_params JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_scheduled_at TIMESTAMPTZ NULL,
    last_success_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.job_runs (
    id BIGSERIAL PRIMARY KEY,
    job_id VARCHAR(100) NOT NULL REFERENCES public.job_definitions(job_id) ON DELETE CASCADE,
    status VARCHAR(24) NOT NULL,
    triggered_by VARCHAR(32) NOT NULL DEFAULT 'scheduler',
    params JSONB NOT NULL DEFAULT '{}'::jsonb,
    message TEXT NOT NULL DEFAULT '',
    error TEXT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ NULL,
    duration_ms INTEGER NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.widget_snapshots (
    id BIGSERIAL PRIMARY KEY,
    widget_key VARCHAR(100) NOT NULL,
    scope VARCHAR(80) NOT NULL DEFAULT 'global',
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    source TEXT NOT NULL DEFAULT '',
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    is_stale BOOLEAN NOT NULL DEFAULT FALSE,
    job_run_id BIGINT NULL REFERENCES public.job_runs(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_job_runs_job_started_at
    ON public.job_runs(job_id, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_job_runs_status_started_at
    ON public.job_runs(status, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_widget_snapshots_lookup
    ON public.widget_snapshots(widget_key, scope, fetched_at DESC);

CREATE INDEX IF NOT EXISTS idx_widget_snapshots_fetched_at
    ON public.widget_snapshots(fetched_at);

-- Optional v2 tables (additive; safe to ignore if not used by app yet)

CREATE TABLE IF NOT EXISTS public.data_sources (
    source_key VARCHAR(80) PRIMARY KEY,
    name VARCHAR(160) NOT NULL,
    link TEXT NOT NULL DEFAULT '',
    license_note TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.widget_definitions (
    widget_key VARCHAR(100) PRIMARY KEY,
    module VARCHAR(80) NOT NULL DEFAULT '',
    name VARCHAR(160) NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    default_scope VARCHAR(80) NOT NULL DEFAULT 'global',
    frequency VARCHAR(24) NOT NULL DEFAULT '',
    unit VARCHAR(32) NOT NULL DEFAULT '',
    source_key VARCHAR(80) NULL REFERENCES public.data_sources(source_key) ON DELETE SET NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.widget_commentaries (
    id BIGSERIAL PRIMARY KEY,
    widget_key VARCHAR(100) NOT NULL,
    scope VARCHAR(80) NOT NULL DEFAULT 'global',
    lang VARCHAR(16) NOT NULL DEFAULT 'en',
    content TEXT NOT NULL,
    reference_list JSONB NOT NULL DEFAULT '[]'::jsonb,
    generated_by VARCHAR(80) NOT NULL DEFAULT '',
    job_run_id BIGINT NULL REFERENCES public.job_runs(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_widget_commentaries_lookup
    ON public.widget_commentaries(widget_key, scope, lang, created_at DESC);

CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_job_definitions_updated_at ON public.job_definitions;
CREATE TRIGGER trg_job_definitions_updated_at
BEFORE UPDATE ON public.job_definitions
FOR EACH ROW
EXECUTE FUNCTION public.set_updated_at();

DROP TRIGGER IF EXISTS trg_data_sources_updated_at ON public.data_sources;
CREATE TRIGGER trg_data_sources_updated_at
BEFORE UPDATE ON public.data_sources
FOR EACH ROW
EXECUTE FUNCTION public.set_updated_at();

DROP TRIGGER IF EXISTS trg_widget_definitions_updated_at ON public.widget_definitions;
CREATE TRIGGER trg_widget_definitions_updated_at
BEFORE UPDATE ON public.widget_definitions
FOR EACH ROW
EXECUTE FUNCTION public.set_updated_at();
