# lore-core

Root of the Lore Python monorepo. Merge in progress (branch `lore-agent-merge`);
see `docs/superpowers/specs/2026-07-20-lore-agent-merge-design.md`.

Layout:
- `services/lore-chat/` — Chainlit chat backend (product).
- `services/lore-audit-api/` — standalone audit read API (ASGI factory; Phase 1).
- `packages/lore-audit-core/` — audit rule engine + read domain (Phase 1).
- `packages/lore-splitter/` — document ingestion / chunking pipeline (Phase 2).
- `airflow-providers/apache-airflow-providers-lore/` — Airflow operators, DAGs,
  hooks; thin adapters over the packages (Phase 3). External Airflow only.
