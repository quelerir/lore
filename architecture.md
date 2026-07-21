# Lore Audit Package Boundaries Design

## Goal

Move the v1.3 audit backend out of the Airflow provider namespace so repository
layout reflects actual ownership. Preserve the existing `/api/v1/audit` HTTP
contract and the working internal2 testing deployment while leaving only
Airflow-specific adapters and composition code in the Lore Airflow provider.

## Audit finding

The current implementation is physically located below
`airflow.providers.lore.audit`, but most of it does not implement an Airflow
provider extension. The rule engine, contracts, validation, registration,
read-side services, cursor handling, persistence abstractions, and FastAPI
surface are ordinary Lore backend code.

The genuine Airflow boundary is limited to code that resolves Airflow
Connections or constructs AWS/Postgres hooks. The current HTTP runtime also
uses those facilities to compose the testing service, but its routes,
middleware, schemas, limits, and error handling are independent of Airflow.

Some audit modules currently import reusable Splitter primitives through the
`airflow.providers.lore` namespace, including `RunStatus`, text normalization,
redaction, and storage registration contracts. These imports are a placement
dependency, not evidence that the audit domain belongs to Airflow. The split
must move or replace those audit-facing primitives so the new core package has
no imports from the Airflow namespace.

## Target ownership

```text
lore-core/
├── packages/
│   └── lore-audit-core/
│       ├── pyproject.toml
│       ├── src/lore_audit/
│       │   ├── contracts and shared primitives
│       │   ├── rules/
│       │   ├── registration.py
│       │   ├── validation.py
│       │   ├── persistence.py
│       │   ├── read contracts/repositories/adapters
│       │   └── services
│       └── tests/
├── services/
│   └── lore-audit-api/
│       ├── pyproject.toml
│       ├── src/lore_audit_api/
│       │   ├── contracts.py
│       │   ├── errors.py
│       │   ├── limits.py
│       │   ├── middleware.py
│       │   ├── routes.py
│       │   ├── factory.py
│       │   └── server.py
│       └── tests/
└── airflow-providers/
    └── apache-airflow-providers-lore/
        └── airflow/providers/lore/
            ├── audit integration adapters
            ├── operators/
            └── splitter Airflow integration
```

The physical package names are `lore_audit` and `lore_audit_api`. The API
package is the frontend-facing backend service. The Airflow provider is an
integration consumer, not the owner of either package.

## Dependency direction

The permanent dependency graph is:

```text
lore_audit_api ───────────────> lore_audit
airflow.providers.lore ───────> lore_audit
Airflow deployment composition ─> lore_audit_api + lore_audit
```

`lore_audit` must not import Airflow, FastAPI, or Uvicorn. `lore_audit_api`
must not import the `airflow.providers.lore` namespace. Airflow connection and
hook objects are supplied through explicit adapters during application
composition.

The testing deployment may continue to run beside Airflow and reuse Airflow
Connections. Its composition entry point belongs to the Airflow integration
edge and injects concrete Postgres/S3 adapters into the standalone API app.
This keeps the current operational topology without making the HTTP service an
Airflow provider feature.

## Compatibility and migration

Existing imports under `airflow.providers.lore.audit` are kept temporarily as
thin re-export shims. They contain no business logic and delegate to
`lore_audit` or `lore_audit_api`. Existing DAGs, operators, Phase 26 evidence,
and downstream imports therefore continue to work during the migration.

New code and updated tests import the canonical package names directly. A
follow-up release can remove the compatibility shims after repository-wide
search and runtime evidence show there are no remaining consumers.

The move must preserve:

- all 19 existing `/api/v1/audit` operations;
- request, response, cursor, error, and OpenAPI contracts;
- bounds, redaction, registration allowlists, and read-only behavior;
- the current testing database and S3 object resolution behavior;
- existing operator behavior and serialized audit results.

No database migration or destructive data rewrite is part of this change.

## Packaging

Each new component gets its own `pyproject.toml` and test boundary.
`lore-audit-core` owns only its domain/runtime dependencies.
`lore-audit-api` owns FastAPI and Pydantic and exposes the ASGI application
factory. Uvicorn is a service/deployment dependency, not an Airflow provider
dependency.

The provider removes FastAPI, Pydantic, and Uvicorn from its direct optional
dependency set except where a temporary compatibility extra is necessary for
one release. The deployment installs or mounts all three local packages
explicitly rather than relying on `PYTHONPATH` pointing only at the provider
source tree.

## Testing deployment

Only the testing environment is in scope:

- API host: `control-airflow-internal2` (`10.32.1.70`), sidecar port `8340`;
- frontend/API URL: `https://lore-test.adventum.ru`;
- Lore testing host: `control-loreagent-test-internal2` (`10.32.1.87`);
- database: `loreagent_test`.

Deploycraft keeps the existing sidecar and ingress topology but updates mounts,
installation paths, and the Uvicorn entry point to use the standalone service
plus the Airflow composition adapter. The service name may remain
`airflow-lore-audit-api` for a compatibility release, even though source
ownership changes.

Production `control-loreagent-internal2`, `https://lore.adventum.ru`, and the
`loreagent` production database are explicitly out of scope. Production is
checked only through non-mutating health/state verification before and after
the testing deployment.

## Verification and rollback

Local verification includes package-specific unit tests, compatibility import
tests, the complete provider suite, Phase 26 API contract tests, Ruff, and the
focused Deploycraft compose/nginx tests. A repository search must prove that
canonical implementation code no longer lives under the provider audit
namespace.

Live testing verification includes:

- healthy API sidecar on port `8340`;
- exactly 19 OpenAPI operations below `/api/v1/audit`;
- successful real-data file, run, chunk, diagnostics, table profile, query,
  and sample requests;
- HTTP 200 for testing Chainlit and same-origin API routes;
- no restart or configuration mutation of the production Lore service.

Deployment changes remain rollback-safe because the public contract and data
schema do not change. Rollback restores the previous Compose command and
provider-only mount while retaining the same database and S3 registrations.

## Repository and delivery boundaries

The canonical implementation and compatibility shims are committed in
`agent-lore`. Deployment wiring is committed separately in `deploycraft`.
`project-internal2` changes are made only if inventory or host-path wiring is
actually required. Unrelated dirty files in those repositories are preserved.

After local and live verification, all task commits are pushed normally to the
existing Gitea branches without force-pushing.
