CREATE SCHEMA IF NOT EXISTS lore_core;
CREATE SCHEMA IF NOT EXISTS lore_toast;

CREATE TABLE IF NOT EXISTS lore_core.schema_versions (
    version text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS lore_core.processed_files (
    logical_file_key text PRIMARY KEY,
    source_id text NOT NULL,
    stream text NOT NULL,
    file_id text NOT NULL,
    source_path text,
    object_path text,
    mime_type text,
    pipeline_type text,
    source_content_hash text,
    config_hash text,
    operator_version text,
    chunk_schema_version text,
    status text NOT NULL,
    latest_run_id uuid,
    current_success_run_id uuid,
    sanitized_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    schema_drift_fields jsonb NOT NULL DEFAULT '[]'::jsonb,
    last_seen_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source_id, stream, file_id)
);

CREATE TABLE IF NOT EXISTS lore_core.processing_runs (
    run_id uuid PRIMARY KEY,
    logical_file_key text NOT NULL REFERENCES lore_core.processed_files(logical_file_key),
    source_content_hash text NOT NULL,
    config_hash text NOT NULL,
    operator_version text NOT NULL,
    chunk_schema_version text NOT NULL,
    status text NOT NULL,
    overwrite_reason text,
    supersedes_run_id uuid REFERENCES lore_core.processing_runs(run_id),
    claimed_at timestamptz NOT NULL DEFAULT now(),
    heartbeat_at timestamptz NOT NULL DEFAULT now(),
    lease_until timestamptz NOT NULL,
    finished_at timestamptz,
    chunk_count integer NOT NULL DEFAULT 0,
    payload_count integer NOT NULL DEFAULT 0,
    warning_count integer NOT NULL DEFAULT 0,
    error_count integer NOT NULL DEFAULT 0,
    error jsonb NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (logical_file_key, source_content_hash, config_hash, operator_version, chunk_schema_version, run_id)
);

CREATE INDEX IF NOT EXISTS processing_runs_identity_idx ON lore_core.processing_runs (logical_file_key, source_content_hash, config_hash, operator_version, chunk_schema_version, status);

CREATE TABLE IF NOT EXISTS lore_core.chunks (
    chunk_id text PRIMARY KEY,
    logical_file_key text NOT NULL,
    run_id uuid NOT NULL REFERENCES lore_core.processing_runs(run_id),
    ordinal integer NOT NULL,
    pipeline_type text NOT NULL,
    chunk_type text NOT NULL,
    vector_text text NOT NULL,
    fulltext text NOT NULL,
    display_text text NOT NULL,
    coordinates jsonb NOT NULL DEFAULT '{}'::jsonb,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    payload_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
    content_signature text NOT NULL,
    vector_text_hash text NOT NULL,
    fulltext_hash text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (run_id, ordinal)
);

CREATE TABLE IF NOT EXISTS lore_core.payloads (
    payload_id text PRIMARY KEY,
    logical_file_key text NOT NULL,
    run_id uuid NOT NULL REFERENCES lore_core.processing_runs(run_id),
    kind text NOT NULL,
    storage text NOT NULL,
    storage_uri text,
    toast_schema text,
    toast_table text,
    label text,
    coordinates jsonb NOT NULL DEFAULT '{}'::jsonb,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    content_hash text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS lore_core.diagnostics (
    diagnostic_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    logical_file_key text NOT NULL,
    run_id uuid REFERENCES lore_core.processing_runs(run_id),
    chunk_id text REFERENCES lore_core.chunks(chunk_id),
    payload_id text REFERENCES lore_core.payloads(payload_id),
    level text NOT NULL,
    code text NOT NULL,
    message text NOT NULL,
    stage text NOT NULL,
    details jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO lore_core.schema_versions(version) VALUES ('001_lore_core') ON CONFLICT (version) DO NOTHING;
