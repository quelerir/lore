ALTER TABLE lore_core.diagnostics
    ADD COLUMN IF NOT EXISTS origin text NOT NULL DEFAULT 'splitter',
    ADD COLUMN IF NOT EXISTS diagnostic_key text;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'diagnostics_origin_check'
          AND conrelid = 'lore_core.diagnostics'::regclass
    ) THEN
        ALTER TABLE lore_core.diagnostics
            ADD CONSTRAINT diagnostics_origin_check
            CHECK (origin IN ('splitter', 'audit_rule'));
    END IF;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'diagnostics_audit_key_required_check'
          AND conrelid = 'lore_core.diagnostics'::regclass
    ) THEN
        ALTER TABLE lore_core.diagnostics
            ADD CONSTRAINT diagnostics_audit_key_required_check
            CHECK (
                origin <> 'audit_rule'
                OR (run_id IS NOT NULL AND diagnostic_key IS NOT NULL)
            );
    END IF;
END
$$;

CREATE UNIQUE INDEX IF NOT EXISTS diagnostics_audit_run_key_uidx
    ON lore_core.diagnostics (run_id, diagnostic_key)
    WHERE origin = 'audit_rule';

INSERT INTO lore_core.schema_versions(version)
VALUES ('004_audit_diagnostics')
ON CONFLICT (version) DO NOTHING;
