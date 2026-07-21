ALTER TABLE lore_core.processing_runs
    ADD COLUMN IF NOT EXISTS orchestration_claim_key text;

CREATE UNIQUE INDEX IF NOT EXISTS processing_runs_orchestration_claim_key_uidx
    ON lore_core.processing_runs (orchestration_claim_key)
    WHERE orchestration_claim_key IS NOT NULL;

INSERT INTO lore_core.schema_versions(version)
VALUES ('003_orchestration_claim_key')
ON CONFLICT (version) DO NOTHING;
