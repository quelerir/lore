CREATE TABLE IF NOT EXISTS lore_core.payload_occurrences (
    run_id uuid NOT NULL REFERENCES lore_core.processing_runs(run_id),
    payload_id text NOT NULL,
    occurrence_ordinal integer NOT NULL CHECK (occurrence_ordinal >= 0),
    kind text NOT NULL,
    storage_identity text NOT NULL,
    content_hash text NOT NULL,
    coordinates jsonb NOT NULL DEFAULT '{}'::jsonb,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (run_id, payload_id, occurrence_ordinal)
);
CREATE INDEX IF NOT EXISTS payload_occurrences_payload_idx ON lore_core.payload_occurrences (payload_id);
INSERT INTO lore_core.schema_versions(version) VALUES ('002_chunk_payload_foundation') ON CONFLICT (version) DO NOTHING;
