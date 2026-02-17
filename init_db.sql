-- init_db.sql
-- Baseline schema for Global Trade Analysis (GTA).
--
-- Design principles:
-- 1) Frontend must NOT call any external APIs directly.
-- 2) All external data fetching must be done by scheduled jobs.
-- 3) Jobs persist results (data + metadata) into DB; web APIs are DB readers only.
--
-- Keep this file as the single source of truth for schema/index creation.

-- User account table for authentication
CREATE TABLE IF NOT EXISTS public.app_user (
    id BIGSERIAL PRIMARY KEY,
    username VARCHAR(320) NOT NULL,
    email VARCHAR(320) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    display_name VARCHAR(64),
    is_active BOOLEAN NOT NULL DEFAULT FALSE,
    is_superuser BOOLEAN NOT NULL DEFAULT FALSE,
    last_login_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Constraints: username must equal email, both lowercase
    CONSTRAINT ck_app_user_username_eq_email CHECK (username = email),
    CONSTRAINT ck_app_user_email_lowercase CHECK (email = lower(email)),
    CONSTRAINT ck_app_user_username_lowercase CHECK (username = lower(username)),
    CONSTRAINT ck_app_user_email_format CHECK (
        email ~ '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$'
    ),

    CONSTRAINT uq_app_user_username UNIQUE (username),
    CONSTRAINT uq_app_user_email UNIQUE (email)
);

COMMENT ON TABLE public.app_user IS 'User accounts for accessing protected pages (e.g., /jobs). Registration requires admin activation.';
COMMENT ON COLUMN public.app_user.username IS 'Username (must be same as email).';
COMMENT ON COLUMN public.app_user.email IS 'User email address (lowercase, unique).';
COMMENT ON COLUMN public.app_user.password_hash IS 'BCrypt hashed password.';
COMMENT ON COLUMN public.app_user.display_name IS 'Optional display name for UI.';
COMMENT ON COLUMN public.app_user.is_active IS 'Whether account is activated (admin approval required).';
COMMENT ON COLUMN public.app_user.is_superuser IS 'Whether user has admin privileges.';
COMMENT ON COLUMN public.app_user.last_login_at IS 'Timestamp of last successful login.';

CREATE INDEX IF NOT EXISTS idx_app_user_email ON public.app_user(email);

-- Trigger to auto-update updated_at
DROP TRIGGER IF EXISTS trg_app_user_updated_at ON public.app_user;
CREATE TRIGGER trg_app_user_updated_at
BEFORE UPDATE ON public.app_user
FOR EACH ROW
EXECUTE FUNCTION public.set_updated_at();

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

CREATE TABLE IF NOT EXISTS public.widget_snapshots (
    id BIGSERIAL PRIMARY KEY,
    widget_key VARCHAR(100) NOT NULL,
    scope VARCHAR(80) NOT NULL DEFAULT 'Global',
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- legacy plain-text attribution (prefer payload.source for UI going forward)
    source TEXT NOT NULL DEFAULT '',

    -- when the job fetched & materialized this snapshot (job time)
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- source-declared or reasonably inferred timestamp of the data itself (NOT job time)
    source_updated_at TIMESTAMPTZ NULL,
    source_updated_at_note TEXT NOT NULL DEFAULT '',

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
COMMENT ON COLUMN public.widget_snapshots.source_updated_at IS 'Source-declared or inferred timestamp of the data itself (NOT job run time).';
COMMENT ON COLUMN public.widget_snapshots.source_updated_at_note IS 'Explanation of how source_updated_at is derived (declared vs inferred).';
COMMENT ON COLUMN public.widget_snapshots.is_stale IS 'Whether snapshot is marked stale (e.g., fetch failed, data too old).';
COMMENT ON COLUMN public.widget_snapshots.job_run_id IS 'FK to job_runs for provenance/traceability.';
COMMENT ON COLUMN public.widget_snapshots.created_at IS 'Row creation time.';

-- Online migration for existing DBs (safe on redeploy)
ALTER TABLE IF EXISTS public.widget_snapshots
  ADD COLUMN IF NOT EXISTS source_updated_at TIMESTAMPTZ NULL;
ALTER TABLE IF EXISTS public.widget_snapshots
  ADD COLUMN IF NOT EXISTS source_updated_at_note TEXT NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_job_runs_job_started_at
    ON public.job_runs(job_id, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_job_runs_status_started_at
    ON public.job_runs(status, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_widget_snapshots_lookup
    ON public.widget_snapshots(widget_key, scope, fetched_at DESC);

CREATE INDEX IF NOT EXISTS idx_widget_snapshots_fetched_at
    ON public.widget_snapshots(fetched_at);

-- Geo dictionary: DB-driven list of geos used by jobs and dashboard.
CREATE TABLE IF NOT EXISTS public.geo_dictionary (
    geo_name VARCHAR(80) PRIMARY KEY,
    iso_alpha2 VARCHAR(4) NOT NULL DEFAULT '',
    iso_alpha3 VARCHAR(4) NOT NULL DEFAULT '',
    wdi_code VARCHAR(10) NOT NULL DEFAULT '',
    display_name VARCHAR(160) NOT NULL DEFAULT '',
    region VARCHAR(80) NOT NULL DEFAULT '',
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order INTEGER NOT NULL DEFAULT 100,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE public.geo_dictionary IS 'Master dictionary of geographic scopes used by jobs, dashboard, and APIs. Replaces hardcoded ALLOWED_GEOS.';
COMMENT ON COLUMN public.geo_dictionary.geo_name IS 'Canonical geo name (primary key, used in widget_snapshots.scope and job params).';
COMMENT ON COLUMN public.geo_dictionary.iso_alpha2 IS 'ISO 3166-1 alpha-2 code (empty for aggregates like Global).';
COMMENT ON COLUMN public.geo_dictionary.iso_alpha3 IS 'ISO 3166-1 alpha-3 code (empty for aggregates).';
COMMENT ON COLUMN public.geo_dictionary.wdi_code IS 'World Bank WDI country/aggregate code (e.g. WLD, IND, CHN).';
COMMENT ON COLUMN public.geo_dictionary.display_name IS 'Human-readable display name for UI.';
COMMENT ON COLUMN public.geo_dictionary.region IS 'Geographic region grouping (e.g. Asia, Europe, Americas, Middle East).';
COMMENT ON COLUMN public.geo_dictionary.enabled IS 'Whether this geo is active for job scheduling and dashboard display.';
COMMENT ON COLUMN public.geo_dictionary.sort_order IS 'Display ordering (lower = first). Global should be 0.';
COMMENT ON COLUMN public.geo_dictionary.created_at IS 'Row creation time.';
COMMENT ON COLUMN public.geo_dictionary.updated_at IS 'Row update time (maintained by trigger).';

DROP TRIGGER IF EXISTS trg_geo_dictionary_updated_at ON public.geo_dictionary;
CREATE TRIGGER trg_geo_dictionary_updated_at
BEFORE UPDATE ON public.geo_dictionary
FOR EACH ROW
EXECUTE FUNCTION public.set_updated_at();

-- Seed geo_dictionary with default geos (idempotent via ON CONFLICT).
INSERT INTO public.geo_dictionary (geo_name, iso_alpha2, iso_alpha3, wdi_code, display_name, region, enabled, sort_order) VALUES
    ('Global',         '',   '',    'WLD', 'Global',              '',              TRUE,  0),
    ('China',          'CN', 'CHN', 'CHN', 'China',               'Asia',          TRUE, 10),
    ('United States',  'US', 'USA', 'USA', 'United States',       'Americas',      TRUE, 11),
    ('Japan',          'JP', 'JPN', 'JPN', 'Japan',               'Asia',          TRUE, 12),
    ('Germany',        'DE', 'DEU', 'DEU', 'Germany',             'Europe',        TRUE, 13),
    ('United Kingdom', 'GB', 'GBR', 'GBR', 'United Kingdom',      'Europe',        TRUE, 14),
    ('India',          'IN', 'IND', 'IND', 'India',               'Asia',          TRUE, 20),
    ('Mexico',         'MX', 'MEX', 'MEX', 'Mexico',              'Americas',      TRUE, 21),
    ('Singapore',      'SG', 'SGP', 'SGP', 'Singapore',           'Asia',          TRUE, 22),
    ('Hong Kong',      'HK', 'HKG', 'HKG', 'Hong Kong',           'Asia',          TRUE, 23),
    ('Middle East',    '',   '',    'MEA', 'Middle East & North Africa', 'Middle East', TRUE, 30),
    ('Taiwan',         'TW', 'TWN', 'TWN', 'Taiwan',              'Asia',          TRUE, 24)
ON CONFLICT (geo_name) DO NOTHING;

-- Optional v2 tables (additive; safe to ignore if not used by app yet)

-- Public context cache (used for Insight research prompts)
CREATE TABLE IF NOT EXISTS public.public_contexts (
    id BIGSERIAL PRIMARY KEY,
    url TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    excerpt TEXT NOT NULL DEFAULT '',
    ok BOOLEAN NOT NULL DEFAULT TRUE,
    error TEXT NOT NULL DEFAULT '',
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE public.public_contexts IS 'Cached public web excerpts for LLM Insight research (job-only fetch).';
COMMENT ON COLUMN public.public_contexts.url IS 'Source URL.';
COMMENT ON COLUMN public.public_contexts.title IS 'HTML <title> best-effort.';
COMMENT ON COLUMN public.public_contexts.excerpt IS 'Plain-text excerpt used in prompts.';
COMMENT ON COLUMN public.public_contexts.ok IS 'Whether fetch succeeded.';
COMMENT ON COLUMN public.public_contexts.error IS 'Error message if fetch failed.';
COMMENT ON COLUMN public.public_contexts.fetched_at IS 'When this excerpt was fetched.';

CREATE INDEX IF NOT EXISTS idx_public_contexts_url_fetched_at
    ON public.public_contexts(url, fetched_at DESC);


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
    default_scope VARCHAR(80) NOT NULL DEFAULT 'Global',
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
    scope VARCHAR(80) NOT NULL DEFAULT 'Global',
    lang VARCHAR(16) NOT NULL DEFAULT 'en',
    content TEXT NOT NULL,
    reference_list JSONB NOT NULL DEFAULT '[]'::jsonb,
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
COMMENT ON COLUMN public.widget_commentaries.reference_list IS 'Citations list (JSON array of {title,url,publisher,date}).';
COMMENT ON COLUMN public.widget_commentaries.generated_by IS 'Generator tag (template/llm/human).';
COMMENT ON COLUMN public.widget_commentaries.job_run_id IS 'FK to job_runs for provenance.';
COMMENT ON COLUMN public.widget_commentaries.created_at IS 'Row creation time.';

-- Insights stored per homepage card + tab; generated by scheduled job.
-- Insight job state (cursor for batching within time budget)
CREATE TABLE IF NOT EXISTS public.widget_insight_job_state (
    id BIGSERIAL PRIMARY KEY,
    key VARCHAR(80) NOT NULL UNIQUE,
    value JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE public.widget_insight_job_state IS 'State/cursor storage for insight generation job batching.';
CREATE INDEX IF NOT EXISTS idx_widget_insight_job_state_key ON public.widget_insight_job_state(key);

CREATE TABLE IF NOT EXISTS public.widget_insights (
    id BIGSERIAL PRIMARY KEY,
    card_key VARCHAR(80) NOT NULL,
    tab_key VARCHAR(80) NOT NULL,
    scope VARCHAR(80) NOT NULL DEFAULT 'Global',
    lang VARCHAR(16) NOT NULL DEFAULT 'en',
    content TEXT NOT NULL,
    reference_list JSONB NOT NULL DEFAULT '[]'::jsonb,
    source_updated_at TIMESTAMPTZ NULL,

    -- de-dup / traceability
    data_digest VARCHAR(64) NOT NULL DEFAULT '',
    input_snapshot_keys JSONB NOT NULL DEFAULT '[]'::jsonb,

    -- llm provenance (optional)
    llm_provider VARCHAR(40) NOT NULL DEFAULT '',
    llm_model VARCHAR(80) NOT NULL DEFAULT '',
    llm_prompt TEXT NOT NULL DEFAULT '',
    llm_error TEXT NOT NULL DEFAULT '',

    generated_by VARCHAR(80) NOT NULL DEFAULT 'job',
    job_run_id BIGINT NULL REFERENCES public.job_runs(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Online migration for existing DBs
ALTER TABLE IF EXISTS public.widget_insights ADD COLUMN IF NOT EXISTS data_digest VARCHAR(64) NOT NULL DEFAULT '';
ALTER TABLE IF EXISTS public.widget_insights ADD COLUMN IF NOT EXISTS input_snapshot_keys JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE IF EXISTS public.widget_insights ADD COLUMN IF NOT EXISTS llm_provider VARCHAR(40) NOT NULL DEFAULT '';
ALTER TABLE IF EXISTS public.widget_insights ADD COLUMN IF NOT EXISTS llm_model VARCHAR(80) NOT NULL DEFAULT '';
ALTER TABLE IF EXISTS public.widget_insights ADD COLUMN IF NOT EXISTS llm_prompt TEXT NOT NULL DEFAULT '';
ALTER TABLE IF EXISTS public.widget_insights ADD COLUMN IF NOT EXISTS llm_error TEXT NOT NULL DEFAULT '';
ALTER TABLE IF EXISTS public.widget_insights ALTER COLUMN content TYPE TEXT;
ALTER TABLE IF EXISTS public.widget_insights ALTER COLUMN llm_prompt TYPE TEXT;
ALTER TABLE IF EXISTS public.widget_insights ALTER COLUMN llm_error TYPE TEXT;

CREATE INDEX IF NOT EXISTS idx_widget_insights_lookup
    ON public.widget_insights(card_key, tab_key, scope, lang, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_widget_insights_digest
    ON public.widget_insights(card_key, tab_key, scope, lang, data_digest);

-- Detailed per-attempt logs for LLM Insight generation.
CREATE TABLE IF NOT EXISTS public.insight_generate_logs (
    id BIGSERIAL PRIMARY KEY,
    job_run_id BIGINT NULL REFERENCES public.job_runs(id) ON DELETE SET NULL,
    card_key VARCHAR(80) NOT NULL,
    tab_key VARCHAR(80) NOT NULL,
    scope VARCHAR(80) NOT NULL DEFAULT 'Global',
    lang VARCHAR(16) NOT NULL DEFAULT 'en',

    llm_provider VARCHAR(40) NOT NULL DEFAULT '',
    llm_model VARCHAR(80) NOT NULL DEFAULT '',
    endpoint TEXT NOT NULL DEFAULT '',

    request_system TEXT NOT NULL DEFAULT '',
    request_user TEXT NOT NULL DEFAULT '',
    request_payload JSONB NOT NULL DEFAULT '{}'::jsonb,

    response_status INTEGER NULL,
    response_raw TEXT NOT NULL DEFAULT '',
    parsed_content TEXT NOT NULL DEFAULT '',
    parsed_references JSONB NOT NULL DEFAULT '[]'::jsonb,

    ok BOOLEAN NOT NULL DEFAULT FALSE,
    error TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE public.insight_generate_logs IS 'Per-attempt logs for LLM Insight generation, including full prompt payload and full raw response.';
CREATE INDEX IF NOT EXISTS idx_insight_generate_logs_job_created
    ON public.insight_generate_logs(job_run_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_insight_generate_logs_lookup
    ON public.insight_generate_logs(card_key, tab_key, scope, lang, created_at DESC);
ALTER TABLE IF EXISTS public.insight_generate_logs ALTER COLUMN endpoint TYPE TEXT;
ALTER TABLE IF EXISTS public.insight_generate_logs ALTER COLUMN request_system TYPE TEXT;
ALTER TABLE IF EXISTS public.insight_generate_logs ALTER COLUMN request_user TYPE TEXT;
ALTER TABLE IF EXISTS public.insight_generate_logs ALTER COLUMN request_payload TYPE JSONB USING request_payload::jsonb;
ALTER TABLE IF EXISTS public.insight_generate_logs ALTER COLUMN response_raw TYPE TEXT;
ALTER TABLE IF EXISTS public.insight_generate_logs ALTER COLUMN parsed_content TYPE TEXT;
ALTER TABLE IF EXISTS public.insight_generate_logs ALTER COLUMN parsed_references TYPE JSONB USING parsed_references::jsonb;
ALTER TABLE IF EXISTS public.insight_generate_logs ALTER COLUMN error TYPE TEXT;

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
