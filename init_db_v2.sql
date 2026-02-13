-- init_db_v2.sql
-- Baseline schema v2 for Global Trade Analysis (GTA).
--
-- Design principles:
-- 1) Frontend must NOT call any external APIs directly.
-- 2) All external data fetching must be done by scheduled jobs.
-- 3) Jobs persist results (data + metadata) into DB; web APIs are DB readers only.
--
-- Notes:
-- - This file is intended to be the source of truth for initializing a fresh database.
-- - Existing code currently relies on: user_visit_log, job_definitions, job_runs, widget_snapshots.
-- - New tables in v2 (data_sources, widget_definitions, widget_commentaries) are additive and
--   can be adopted incrementally by jobs / APIs.

-- =========================
-- 0) Core: request logging
-- =========================

CREATE TABLE IF NOT EXISTS public.user_visit_log (
    id BIGSERIAL PRIMARY KEY,
    ip VARCHAR(64) NOT NULL,
    user_agent VARCHAR(512) NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE public.user_visit_log IS 'Web visit log for basic traffic/debugging (non-auth).';
COMMENT ON COLUMN public.user_visit_log.id IS 'Primary key.';
COMMENT ON COLUMN public.user_visit_log.ip IS 'Visitor IP address (as seen by server / proxy).';
COMMENT ON COLUMN public.user_visit_log.user_agent IS 'HTTP User-Agent string.';
COMMENT ON COLUMN public.user_visit_log.created_at IS 'Row creation time (server time, timestamptz).';

-- =============================
-- 1) Jobs: definitions and runs
-- =============================

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

COMMENT ON TABLE public.job_definitions IS 'Job scheduler definitions. Jobs are responsible for ALL external data fetching.';
COMMENT ON COLUMN public.job_definitions.job_id IS 'Stable job identifier used by scheduler and code.';
COMMENT ON COLUMN public.job_definitions.name IS 'Human-readable job name.';
COMMENT ON COLUMN public.job_definitions.description IS 'Job description and expected outputs.';
COMMENT ON COLUMN public.job_definitions.cron_expr IS 'Cron expression controlling schedule.';
COMMENT ON COLUMN public.job_definitions.timezone IS 'Timezone used to interpret cron_expr.';
COMMENT ON COLUMN public.job_definitions.enabled IS 'Whether scheduler should run this job.';
COMMENT ON COLUMN public.job_definitions.default_params IS 'Default job parameters (merged with runtime params).';
COMMENT ON COLUMN public.job_definitions.last_scheduled_at IS 'Last time the scheduler enqueued/triggered the job.';
COMMENT ON COLUMN public.job_definitions.last_success_at IS 'Last time the job finished successfully.';
COMMENT ON COLUMN public.job_definitions.created_at IS 'Row creation time.';
COMMENT ON COLUMN public.job_definitions.updated_at IS 'Row update time (maintained by trigger).';

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

COMMENT ON TABLE public.job_runs IS 'Execution history of job runs; used for observability and traceability.';
COMMENT ON COLUMN public.job_runs.id IS 'Primary key.';
COMMENT ON COLUMN public.job_runs.job_id IS 'Job identifier (FK to job_definitions.job_id).';
COMMENT ON COLUMN public.job_runs.status IS 'Run status (e.g., running/success/failed/skipped).';
COMMENT ON COLUMN public.job_runs.triggered_by IS 'Trigger source (scheduler/manual/api/etc.).';
COMMENT ON COLUMN public.job_runs.params IS 'Runtime parameters used in this run.';
COMMENT ON COLUMN public.job_runs.message IS 'Human-readable summary message.';
COMMENT ON COLUMN public.job_runs.error IS 'Error details if failed.';
COMMENT ON COLUMN public.job_runs.started_at IS 'Run start time.';
COMMENT ON COLUMN public.job_runs.finished_at IS 'Run end time (NULL if still running).';
COMMENT ON COLUMN public.job_runs.duration_ms IS 'Elapsed time in milliseconds.';
COMMENT ON COLUMN public.job_runs.created_at IS 'Row creation time.';

CREATE INDEX IF NOT EXISTS idx_job_runs_job_started_at
    ON public.job_runs(job_id, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_job_runs_status_started_at
    ON public.job_runs(status, started_at DESC);

-- ======================================
-- 2) Widget snapshots (DB-read-only APIs)
-- ======================================

CREATE TABLE IF NOT EXISTS public.widget_snapshots (
    id BIGSERIAL PRIMARY KEY,
    widget_key VARCHAR(100) NOT NULL,
    scope VARCHAR(80) NOT NULL DEFAULT 'global',

    -- payload should include BOTH data and metadata, e.g.
    -- period/unit/source/definitions/caveats/references/data
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- optional legacy/plain-text source (keep for backward compatibility)
    source TEXT NOT NULL DEFAULT '',

    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    is_stale BOOLEAN NOT NULL DEFAULT FALSE,
    job_run_id BIGINT NULL REFERENCES public.job_runs(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE public.widget_snapshots IS 'Materialized widget data generated by jobs. Web APIs MUST only read from this table (no external fetch on request).';
COMMENT ON COLUMN public.widget_snapshots.id IS 'Primary key.';
COMMENT ON COLUMN public.widget_snapshots.widget_key IS 'Widget identifier (stable key used by frontend/backend).';
COMMENT ON COLUMN public.widget_snapshots.scope IS 'Scope / geo / segment key (e.g., global, country ISO3, region code).';
COMMENT ON COLUMN public.widget_snapshots.payload IS 'Snapshot payload JSON (data + metadata contract: source/period/unit/definitions/caveats/references).';
COMMENT ON COLUMN public.widget_snapshots.source IS 'Legacy source string (prefer payload.source.* going forward).';
COMMENT ON COLUMN public.widget_snapshots.fetched_at IS 'When external data was fetched and snapshot produced.';
COMMENT ON COLUMN public.widget_snapshots.is_stale IS 'Whether snapshot is marked stale (e.g., fetch failed, data too old).';
COMMENT ON COLUMN public.widget_snapshots.job_run_id IS 'FK to job_runs for provenance/traceability.';
COMMENT ON COLUMN public.widget_snapshots.created_at IS 'Row creation time.';

CREATE INDEX IF NOT EXISTS idx_widget_snapshots_lookup
    ON public.widget_snapshots(widget_key, scope, fetched_at DESC);

CREATE INDEX IF NOT EXISTS idx_widget_snapshots_fetched_at
    ON public.widget_snapshots(fetched_at);

-- =====================================
-- 3) Optional v2 additions (additive)
-- =====================================

CREATE TABLE IF NOT EXISTS public.data_sources (
    source_key VARCHAR(80) PRIMARY KEY,
    name VARCHAR(160) NOT NULL,
    link TEXT NOT NULL DEFAULT '',
    license_note TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE public.data_sources IS 'Catalog of external data sources (World Bank WDI / IMF PortWatch / Drewry etc.). Jobs should reference this for consistent attribution.';
COMMENT ON COLUMN public.data_sources.source_key IS 'Stable identifier for the data source (e.g., wdi, imf_portwatch, drewry_wci).';
COMMENT ON COLUMN public.data_sources.name IS 'Display name shown in UI Source block.';
COMMENT ON COLUMN public.data_sources.link IS 'Landing page or API entry point for attribution.';
COMMENT ON COLUMN public.data_sources.license_note IS 'Short license / attribution note to show in UI or docs.';
COMMENT ON COLUMN public.data_sources.notes IS 'Internal notes (caveats, scraping risk, registration required, etc.).';
COMMENT ON COLUMN public.data_sources.created_at IS 'Row creation time.';
COMMENT ON COLUMN public.data_sources.updated_at IS 'Row update time (maintained by trigger).';

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

COMMENT ON TABLE public.widget_definitions IS 'Optional registry of widgets for consistent UI labeling, scheduling, and metadata defaults (additive; snapshots remain source of truth for data).';
COMMENT ON COLUMN public.widget_definitions.widget_key IS 'Stable widget identifier.';
COMMENT ON COLUMN public.widget_definitions.module IS 'High-level module/tab (e.g., trade_flow, wealth, financial_flow).';
COMMENT ON COLUMN public.widget_definitions.name IS 'Display name.';
COMMENT ON COLUMN public.widget_definitions.description IS 'Widget description and semantic definition.';
COMMENT ON COLUMN public.widget_definitions.default_scope IS 'Default scope for this widget (global / ISO3 etc.).';
COMMENT ON COLUMN public.widget_definitions.frequency IS 'Expected update frequency (daily/weekly/monthly/annual).';
COMMENT ON COLUMN public.widget_definitions.unit IS 'Primary unit displayed in UI.';
COMMENT ON COLUMN public.widget_definitions.source_key IS 'FK to data_sources for default attribution.';
COMMENT ON COLUMN public.widget_definitions.enabled IS 'Whether widget is enabled for display/update.';
COMMENT ON COLUMN public.widget_definitions.created_at IS 'Row creation time.';
COMMENT ON COLUMN public.widget_definitions.updated_at IS 'Row update time (maintained by trigger).';

CREATE TABLE IF NOT EXISTS public.widget_commentaries (
    id BIGSERIAL PRIMARY KEY,
    widget_key VARCHAR(100) NOT NULL,
    scope VARCHAR(80) NOT NULL DEFAULT 'global',
    lang VARCHAR(16) NOT NULL DEFAULT 'en',
    content TEXT NOT NULL,
    references JSONB NOT NULL DEFAULT '[]'::jsonb,
    generated_by VARCHAR(80) NOT NULL DEFAULT '',
    job_run_id BIGINT NULL REFERENCES public.job_runs(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE public.widget_commentaries IS 'Optional stored commentary text for widgets (with citations). Can be generated by jobs; frontend reads from DB only.';
COMMENT ON COLUMN public.widget_commentaries.id IS 'Primary key.';
COMMENT ON COLUMN public.widget_commentaries.widget_key IS 'Widget identifier this commentary belongs to.';
COMMENT ON COLUMN public.widget_commentaries.scope IS 'Scope / geo / segment key.';
COMMENT ON COLUMN public.widget_commentaries.lang IS 'Language code (e.g., en, zh).';
COMMENT ON COLUMN public.widget_commentaries.content IS 'Commentary content (markdown/plain text).';
COMMENT ON COLUMN public.widget_commentaries.references IS 'Citations list (JSON array of {title,url,publisher,date}).';
COMMENT ON COLUMN public.widget_commentaries.generated_by IS 'Generator tag (template/llm/human).';
COMMENT ON COLUMN public.widget_commentaries.job_run_id IS 'FK to job_runs for provenance.';
COMMENT ON COLUMN public.widget_commentaries.created_at IS 'Row creation time.';

CREATE INDEX IF NOT EXISTS idx_widget_commentaries_lookup
    ON public.widget_commentaries(widget_key, scope, lang, created_at DESC);

-- =================================
-- 4) Trigger for updated_at columns
-- =================================

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
