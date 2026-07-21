# Phase 3 — Airflow Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the real-Airflow-SDK edge (2 operators + 3 hook-wrappers + provider metadata + config loader + example DAG) into a standalone `apache-airflow-providers-lore` package, completing the lore↔agent-lore merge while keeping `lore_splitter`/`lore_audit` 100% Airflow-free.

**Architecture:** Verbatim cross-repo port of each source file with a mechanical namespace rewrite plus a small set of *named* remaps. All Airflow-importing code lives ONLY in the provider. The provider is a standalone uv project (own `pyproject.toml`, excluded from the app workspace); `apache-airflow` is an OPTIONAL extra so the test env installs airflow-free and tests fake the SDK via `install_airflow_stubs()`.

**Tech Stack:** Python ≥3.10 (Airflow's floor), uv, pytest, hatchling. Depends on sibling packages `lore-splitter` + `lore-audit-core` via path sources.

## Global Constraints

- **Source repo root:** `/Users/stamplevskiyd/adventum/agent-lore/lore-core/`
  - Provider source: `airflow-providers/apache-airflow-providers-lore/` → modules under `airflow/providers/lore/`, tests under `tests/`
  - Example DAG source: `dags/lore_splitter.py`
- **Target provider root:** `/Users/stamplevskiyd/development/lore/lore-core/airflow-providers/apache-airflow-providers-lore/`
  - Keep the `airflow/providers/lore/` package dir (Airflow provider-discovery namespace). NEW subpackage `airflow/providers/lore/adapters/` holds the 3 hook-wrappers.
- **Namespace rewrite (every ported provider file), applied to imports only:**
  - `airflow.providers.lore.splitter.storage.airflow_postgres` → `airflow.providers.lore.adapters.airflow_postgres`
  - `airflow.providers.lore.splitter.storage.airflow_s3` → `airflow.providers.lore.adapters.airflow_s3`
  - `airflow.providers.lore.audit.airflow_adapters` → `airflow.providers.lore.adapters.airflow_audit_adapters`
  - `airflow.providers.lore.audit.repository` → `lore_audit.snapshot_repository`  *(honors the 2b rename)*
  - `airflow.providers.lore.audit.<other>` → `lore_audit.<other>`
  - `airflow.providers.lore.splitter.<other>` → `lore_splitter.<other>`
  - `airflow.providers.lore.splitter.storage.contracts` → `lore_splitter.storage`  *(storage/contracts.py was dropped in 2c; symbols re-exported from the storage package root)*
  - **Untouched:** the provider's own namespace `airflow.providers.lore.{operators,config,adapters,get_provider_info}`, and ALL real Airflow SDK imports (`airflow.models`, `airflow.exceptions`, `airflow.utils.context`, `airflow.sdk`, `airflow.utils.trigger_rule`, `airflow.hooks.*`, `airflow.providers.{amazon,postgres}.*`).
- **Moves are verbatim** apart from the rewrite + named remaps. No reformatting/reordering/logic changes.
- **`apache-airflow` is an optional extra**, never a base dependency — the test env must resolve WITHOUT it. Airflow must NEVER enter the app uv-workspace env.
- **Test command** (run from the provider root): `uv run pytest tests -q` (uv builds the provider's own env from its `pyproject.toml`: siblings + PyYAML + pytest, NO airflow).
- Sibling package suites must stay green and untouched except the one debt-stub removal in Task 6: lore-splitter 284/1, lore-audit-core 156, audit-api 96/1, chat 121/1.
- Stage ONLY the files each task names. Never `git add -A`. Never stage `lore-core/.chainlit/`.
- The provider's `__init__.py` files that are pure namespace packages stay minimal; do NOT add package-root re-exports beyond what the source declares (`operators/__init__.py` keeps its `__all__`).

---

### Task 1: Provider skeleton + packaging

Stand up the package so it resolves standalone and is importable, before any Airflow code lands.

**Files:**
- Create: `airflow-providers/apache-airflow-providers-lore/pyproject.toml`
- Create: `airflow-providers/apache-airflow-providers-lore/README.md` (copy source verbatim)
- Create: `airflow-providers/apache-airflow-providers-lore/airflow/providers/lore/__init__.py` (empty)
- Create: `airflow-providers/apache-airflow-providers-lore/airflow/providers/lore/get_provider_info.py` (copy source verbatim — pure dict, no imports to rewrite)
- Create: `airflow-providers/apache-airflow-providers-lore/tests/test_provider_metadata.py` (new smoke test)
- Modify: `lore-core/pyproject.toml` (add workspace `exclude`)

**Interfaces:**
- Produces: an installable `apache-airflow-providers-lore` project whose env has `lore_splitter` + `lore_audit` importable and NO `airflow` installed. `get_provider_info()` returns the provider-info dict.

- [ ] **Step 1: Exclude the provider from the app workspace**

Edit `lore-core/pyproject.toml` — add an `exclude` to the workspace table so uv treats the nested provider as its own project, not a member:

```toml
[tool.uv.workspace]
members = ["packages/*", "services/*"]
exclude = ["airflow-providers/*"]
```

- [ ] **Step 2: Write the provider `pyproject.toml`**

Create `airflow-providers/apache-airflow-providers-lore/pyproject.toml`. `apache-airflow` is an OPTIONAL extra; base deps are only what the provider imports directly (`PyYAML`) plus the two sibling packages via path sources (they transitively pull markitdown/openpyxl/Pillow/pymupdf/python-docx/python-pptx/defusedxml/psycopg). Static version avoids a git-tag dependency.

```toml
[build-system]
requires = ["hatchling>=1.18"]
build-backend = "hatchling.build"

[project]
name = "apache-airflow-providers-lore"
version = "0.1.0"
description = "Apache Airflow provider for Lore Splitter operators"
readme = "README.md"
requires-python = ">=3.10"
authors = [{ name = "Adventum", email = "n.sushchenko@adventum.ru" }]
classifiers = [
    "Programming Language :: Python :: 3",
    "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
    "Operating System :: OS Independent",
]
dependencies = [
    "PyYAML==6.0.3",
    "lore-splitter",
    "lore-audit-core",
]

[project.optional-dependencies]
airflow = ["apache-airflow>=3.1.7,<4.0.0"]
postgres = ["psycopg==3.3.4"]

[project.entry-points.apache_airflow_provider]
provider_info = "airflow.providers.lore.get_provider_info:get_provider_info"

[project.urls]
Homepage = "https://github.com/adventum/agent-lore"

[dependency-groups]
dev = ["pytest>=8.0", "ruff>=0.4"]

[tool.uv.sources]
lore-splitter = { path = "../../packages/lore-splitter", editable = true }
lore-audit-core = { path = "../../packages/lore-audit-core", editable = true }

[tool.hatch.build.targets.wheel]
packages = ["airflow"]
```

- [ ] **Step 3: Copy `README.md` and `get_provider_info.py` verbatim**

```bash
SRC=/Users/stamplevskiyd/adventum/agent-lore/lore-core/airflow-providers/apache-airflow-providers-lore
DST=/Users/stamplevskiyd/development/lore/lore-core/airflow-providers/apache-airflow-providers-lore
cp "$SRC/README.md" "$DST/README.md"
mkdir -p "$DST/airflow/providers/lore"
: > "$DST/airflow/providers/lore/__init__.py"
cp "$SRC/airflow/providers/lore/get_provider_info.py" "$DST/airflow/providers/lore/get_provider_info.py"
```
`get_provider_info.py` is a pure dict returning module paths as strings — confirm it has no `import` to rewrite: `grep -n import "$DST/airflow/providers/lore/get_provider_info.py"` → expect no output.

- [ ] **Step 4: Write the metadata smoke test**

Create `tests/test_provider_metadata.py`:

```python
from __future__ import annotations


def test_get_provider_info_declares_both_operators():
    from airflow.providers.lore.get_provider_info import get_provider_info

    info = get_provider_info()
    assert info["package-name"] == "apache-airflow-providers-lore"
    modules = info["operators"][0]["python-modules"]
    assert "airflow.providers.lore.operators.lore_splitter_operator" in modules
    assert "airflow.providers.lore.operators.lore_splitter_audit_operator" in modules


def test_sibling_packages_importable_without_airflow():
    import sys

    import lore_splitter  # noqa: F401
    import lore_audit  # noqa: F401

    # The provider test env must resolve airflow-free.
    assert "airflow" not in sys.modules
```

- [ ] **Step 5: Verify the env resolves airflow-free and tests pass**

Run from the provider root:
```bash
cd /Users/stamplevskiyd/development/lore/lore-core/airflow-providers/apache-airflow-providers-lore
uv run pytest tests -q
```
Expected: 2 passed. If uv complains the package is part of the workspace, re-check Step 1's `exclude`. If `apache-airflow` gets installed, re-check that it's under `[project.optional-dependencies].airflow`, not base `dependencies`. Confirm airflow absent: `uv run python -c "import importlib.util,sys; print('airflow' , importlib.util.find_spec('airflow'))"` → expect `airflow None`.

- [ ] **Step 6: Commit**

```bash
cd /Users/stamplevskiyd/development/lore
git add lore-core/pyproject.toml \
        lore-core/airflow-providers/apache-airflow-providers-lore/pyproject.toml \
        lore-core/airflow-providers/apache-airflow-providers-lore/README.md \
        lore-core/airflow-providers/apache-airflow-providers-lore/airflow/providers/lore/__init__.py \
        lore-core/airflow-providers/apache-airflow-providers-lore/airflow/providers/lore/get_provider_info.py \
        lore-core/airflow-providers/apache-airflow-providers-lore/tests/test_provider_metadata.py
git commit -m "feat(provider): standalone apache-airflow-providers-lore skeleton"
```

---

### Task 2: Storage hook-adapters + shared stub helper

Port the two splitter storage hook-wrappers into `adapters/`, plus the shared Airflow-stub test helper and the storage-hook test.

**Files:**
- Create: `airflow/providers/lore/adapters/__init__.py` (empty)
- Create: `airflow/providers/lore/adapters/airflow_postgres.py` (from source `airflow/providers/lore/splitter/storage/airflow_postgres.py`)
- Create: `airflow/providers/lore/adapters/airflow_s3.py` (from source `.../splitter/storage/airflow_s3.py`)
- Create: `tests/_airflow_stubs.py` (extract `install_airflow_stubs()` from source `tests/test_lore_splitter_operator.py`)
- Create: `tests/test_storage_airflow_hooks.py` (from source `tests/test_storage_airflow_hooks.py`)

**Interfaces:**
- Produces: `PostgresHookTableToastStoreFactory` (in `adapters/airflow_postgres.py`), `S3HookObjectToastStore` + `AirflowS3StorageError` (in `adapters/airflow_s3.py`), and `install_airflow_stubs()` (in `tests/_airflow_stubs.py`).
- `airflow_postgres.py` remap: `from airflow.providers.lore.splitter.storage.postgres import PostgresTableToastStore` → `from lore_splitter.storage.postgres import PostgresTableToastStore`.
- `airflow_s3.py` remaps: `from airflow.providers.lore.splitter.storage.contracts import (ImageToastStoragePlan, ImageToastStorageResult)` → `from lore_splitter.storage import (ImageToastStoragePlan, ImageToastStorageResult)`; `from airflow.providers.lore.splitter.storage.object_schema import validate_image_storage_plan` → `from lore_splitter.storage.object_schema import validate_image_storage_plan`.

- [ ] **Step 1: Copy the two adapters + rewrite imports**

```bash
SRC=/Users/stamplevskiyd/adventum/agent-lore/lore-core/airflow-providers/apache-airflow-providers-lore/airflow/providers/lore
DST=/Users/stamplevskiyd/development/lore/lore-core/airflow-providers/apache-airflow-providers-lore/airflow/providers/lore
mkdir -p "$DST/adapters"
: > "$DST/adapters/__init__.py"
cp "$SRC/splitter/storage/airflow_postgres.py" "$DST/adapters/airflow_postgres.py"
cp "$SRC/splitter/storage/airflow_s3.py" "$DST/adapters/airflow_s3.py"
```
Apply the remaps above (Edit). The lazy `importlib.import_module("airflow.providers.postgres...")` / `"airflow.providers.amazon...")` strings are REAL SDK hook paths — leave them. Confirm no stale internal namespace remains:
```bash
grep -n "airflow.providers.lore" "$DST/adapters/airflow_postgres.py" "$DST/adapters/airflow_s3.py"
```
Expected: no output (they should now import `lore_splitter.*`).

- [ ] **Step 2: Extract the shared stub helper**

Create `tests/_airflow_stubs.py` containing the `install_airflow_stubs()` function from source `tests/test_lore_splitter_operator.py` (the full definition registering fake `airflow`, `airflow.models.BaseOperator`, `airflow.exceptions.{AirflowException,AirflowFailException}`, `airflow.utils.context.Context`, `airflow.hooks.base.BaseHook`, and the fake `airflow.providers.{amazon.aws.hooks.s3.S3Hook, postgres.hooks.postgres.PostgresHook}`). Preserve its `PROVIDER_ROOT` computation but anchor it to the provider package root in the new layout:

```python
from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import Mock

# tests/ -> provider root; the fake `airflow` package __path__ points at the
# real provider `airflow/` dir so `airflow.providers.lore.*` resolves to real code.
PROVIDER_ROOT = Path(__file__).resolve().parent.parent


def install_airflow_stubs():
    ...  # verbatim body from source test_lore_splitter_operator.py (uses PROVIDER_ROOT / "airflow")
```
Copy the body verbatim from source; only the `PROVIDER_ROOT` definition is adapted as above.

- [ ] **Step 3: Copy the storage-hook test + repoint the stub import**

```bash
cp "$SRC_TESTS/test_storage_airflow_hooks.py" "$DST_ROOT/tests/test_storage_airflow_hooks.py"
```
(where `SRC_TESTS=/Users/stamplevskiyd/adventum/agent-lore/lore-core/airflow-providers/apache-airflow-providers-lore/tests`, `DST_ROOT=/Users/stamplevskiyd/development/lore/lore-core/airflow-providers/apache-airflow-providers-lore`.)

Rewrites in the test:
- `from tests.test_lore_splitter_operator import install_airflow_stubs` → `from _airflow_stubs import install_airflow_stubs`
- Any `airflow.providers.lore.splitter.storage.airflow_postgres` / `...airflow_s3` module-name strings used in `importlib.import_module(...)` → `airflow.providers.lore.adapters.airflow_postgres` / `airflow.providers.lore.adapters.airflow_s3`.
Confirm: `grep -n "test_lore_splitter_operator\|splitter.storage.airflow" tests/test_storage_airflow_hooks.py` → no output.

- [ ] **Step 4: Run the test**

```bash
cd /Users/stamplevskiyd/development/lore/lore-core/airflow-providers/apache-airflow-providers-lore
uv run pytest tests/test_storage_airflow_hooks.py -q
```
Expected: all pass (source had ~storage-hook cases). If an `ImportError` on `lore_splitter.storage` symbols appears, re-check the `airflow_s3.py` remap (Step 1).

- [ ] **Step 5: Commit**

```bash
cd /Users/stamplevskiyd/development/lore
git add lore-core/airflow-providers/apache-airflow-providers-lore/airflow/providers/lore/adapters/ \
        lore-core/airflow-providers/apache-airflow-providers-lore/tests/_airflow_stubs.py \
        lore-core/airflow-providers/apache-airflow-providers-lore/tests/test_storage_airflow_hooks.py
git commit -m "feat(provider): splitter storage hook-adapters + stub helper"
```

---

### Task 3: Audit hook-adapter

Port the audit adapter (the one with the `snapshot_repository` remap) and its integration test.

**Files:**
- Create: `airflow/providers/lore/adapters/airflow_audit_adapters.py` (from source `airflow/providers/lore/audit/airflow_adapters.py`)
- Create: `tests/test_audit_airflow_adapters.py` (from source `tests/test_audit_airflow_adapters.py`)

**Interfaces:**
- Produces: `AirflowAuditAdapters` (frozen dataclass with `.reader`, `.writer`, `.payload_resolver`, `.bounds`), `build_airflow_audit_adapters(...)`, `_S3CapabilityResolver`.
- Remaps: `from .engine_contracts import PayloadResolutionFact, PhysicalResolution` → `from lore_audit.engine_contracts import PayloadResolutionFact, PhysicalResolution`; `from .persistence import PostgresAuditResultWriter` → `from lore_audit.persistence import PostgresAuditResultWriter`; `from .repository import AuditReadBounds, PostgresAuditSnapshotRepository` → `from lore_audit.snapshot_repository import AuditReadBounds, PostgresAuditSnapshotRepository`.
- Lazy `importlib.import_module("airflow.providers.postgres.hooks.postgres")` / `"...amazon.aws.hooks.s3"` — real SDK paths, leave them.

- [ ] **Step 1: Copy the adapter + rewrite imports**

```bash
SRC=/Users/stamplevskiyd/adventum/agent-lore/lore-core/airflow-providers/apache-airflow-providers-lore/airflow/providers/lore
DST=/Users/stamplevskiyd/development/lore/lore-core/airflow-providers/apache-airflow-providers-lore/airflow/providers/lore
cp "$SRC/audit/airflow_adapters.py" "$DST/adapters/airflow_audit_adapters.py"
```
Apply the three remaps above. Confirm:
```bash
grep -n "airflow.providers.lore\|^from \.\| \.engine_contracts\| \.persistence\| \.repository" "$DST/adapters/airflow_audit_adapters.py"
```
Expected: no output (all internal imports now point at `lore_audit.*`).

- [ ] **Step 2: Copy the integration test + rewrite**

```bash
SRC_TESTS=/Users/stamplevskiyd/adventum/agent-lore/lore-core/airflow-providers/apache-airflow-providers-lore/tests
DST_ROOT=/Users/stamplevskiyd/development/lore/lore-core/airflow-providers/apache-airflow-providers-lore
cp "$SRC_TESTS/test_audit_airflow_adapters.py" "$DST_ROOT/tests/test_audit_airflow_adapters.py"
```
Rewrite in the test: `from airflow.providers.lore.audit.airflow_adapters import ...` → `from airflow.providers.lore.adapters.airflow_audit_adapters import ...`; any `airflow.providers.lore.audit.repository` → `lore_audit.snapshot_repository`; other `airflow.providers.lore.audit.<x>` → `lore_audit.<x>`. If it imports `install_airflow_stubs`, repoint to `from _airflow_stubs import install_airflow_stubs`. Confirm: `grep -n "airflow.providers.lore.audit\|test_lore_splitter_operator" tests/test_audit_airflow_adapters.py` → no output.

- [ ] **Step 3: Run the test**

```bash
cd /Users/stamplevskiyd/development/lore/lore-core/airflow-providers/apache-airflow-providers-lore
uv run pytest tests/test_audit_airflow_adapters.py -q
```
Expected: all pass (~adapter cases). An `ImportError` on `AuditReadBounds`/`PostgresAuditSnapshotRepository` means the `snapshot_repository` remap (Step 1) is wrong — both live in `lore_audit.snapshot_repository`.

- [ ] **Step 4: Commit**

```bash
cd /Users/stamplevskiyd/development/lore
git add lore-core/airflow-providers/apache-airflow-providers-lore/airflow/providers/lore/adapters/airflow_audit_adapters.py \
        lore-core/airflow-providers/apache-airflow-providers-lore/tests/test_audit_airflow_adapters.py
git commit -m "feat(provider): audit hook-adapter (snapshot_repository wired)"
```

---

### Task 4: Operators + config

Port both operators and the config loader (the operator-visible surface), with their stub-based tests.

**Files:**
- Create: `airflow/providers/lore/operators/__init__.py` (from source — keeps `__all__`)
- Create: `airflow/providers/lore/operators/lore_splitter_operator.py` (from source)
- Create: `airflow/providers/lore/operators/lore_splitter_audit_operator.py` (from source)
- Create: `airflow/providers/lore/config/__init__.py` (from source)
- Create: `airflow/providers/lore/config/runtime.py` (from source)
- Create: `tests/test_lore_splitter_operator.py` (from source; repoint stub helper)
- Create: `tests/test_lore_splitter_audit_operator.py` (from source)

**Interfaces:**
- Consumes: `adapters.airflow_postgres.PostgresHookTableToastStoreFactory`, `adapters.airflow_s3.S3HookObjectToastStore` (Task 2), `adapters.airflow_audit_adapters.{AirflowAuditAdapters, build_airflow_audit_adapters}` (Task 3), `install_airflow_stubs` (Task 2).
- Produces: `LoreSplitterOperator`, `LoreSplitterAuditOperator`, and the runtime-config surface (`load_runtime_config`, `SplitterRuntimeConfig`, `AuditRuntimeConfig`, `ViewerRuntimeConfig`, `LoreRuntimeConfig`, `RuntimeConfigError`).

**Remaps — `lore_splitter_operator.py`:**
- `from airflow.providers.lore.splitter.airflow_item import AirbyteItemError, normalize_airbyte_item` → `from lore_splitter.airflow_item import ...`
- `from airflow.providers.lore.splitter.per_file import ProcessingAlreadyActive, redact_text` → `from lore_splitter.per_file import ...`
- `from airflow.providers.lore.splitter.per_file_execution import (build_v12_dispatcher, ...)` → `from lore_splitter.per_file_execution import (...)`
- lazy in-function: `from airflow.providers.lore.splitter.storage.airflow_postgres import PostgresHookTableToastStoreFactory` → `from airflow.providers.lore.adapters.airflow_postgres import PostgresHookTableToastStoreFactory`
- lazy: `from airflow.providers.lore.splitter.storage.airflow_s3 import S3HookObjectToastStore` → `from airflow.providers.lore.adapters.airflow_s3 import S3HookObjectToastStore`
- lazy: `from airflow.providers.lore.splitter.storage.core_repository import CoreRepository` → `from lore_splitter.storage.core_repository import CoreRepository`
- lazy: `from airflow.providers.lore.splitter.storage.persistence import PersistenceCoordinator` → `from lore_splitter.storage.persistence import PersistenceCoordinator`
- KEEP real SDK: `airflow.exceptions`, `airflow.models`, `airflow.utils.context`, and the lazy `importlib.import_module("airflow.providers.{amazon,postgres}...")` hook strings.

**Remaps — `lore_splitter_audit_operator.py`:**
- `from airflow.providers.lore.audit.airflow_adapters import (AirflowAuditAdapters, build_airflow_audit_adapters)` → `from airflow.providers.lore.adapters.airflow_audit_adapters import (...)`
- `from airflow.providers.lore.audit.repository import AuditReadBounds` → `from lore_audit.snapshot_repository import AuditReadBounds`
- `from airflow.providers.lore.audit.service import (...)` → `from lore_audit.service import (...)`
- KEEP real SDK: `airflow.exceptions.AirflowFailException`, `airflow.models.BaseOperator`, `airflow.utils.context.Context`.

**Remaps — `config/runtime.py`:**
- `from airflow.providers.lore.splitter.config import (SplitterConfigError, validate_splitter_config)` → `from lore_splitter.config import (...)`
- `config/__init__.py` imports `from airflow.providers.lore.config.runtime import (...)` — provider-internal namespace, leave unchanged.

- [ ] **Step 1: Copy operators + config + rewrite**

```bash
SRC=/Users/stamplevskiyd/adventum/agent-lore/lore-core/airflow-providers/apache-airflow-providers-lore/airflow/providers/lore
DST=/Users/stamplevskiyd/development/lore/lore-core/airflow-providers/apache-airflow-providers-lore/airflow/providers/lore
mkdir -p "$DST/operators" "$DST/config"
cp "$SRC/operators/__init__.py" "$DST/operators/__init__.py"
cp "$SRC/operators/lore_splitter_operator.py" "$DST/operators/lore_splitter_operator.py"
cp "$SRC/operators/lore_splitter_audit_operator.py" "$DST/operators/lore_splitter_audit_operator.py"
cp "$SRC/config/__init__.py" "$DST/config/__init__.py"
cp "$SRC/config/runtime.py" "$DST/config/runtime.py"
```
Apply every remap above. `operators/__init__.py` imports the two operator classes from `airflow.providers.lore.operators.*` (provider namespace) — leave unchanged. Confirm no stale splitter/audit internal namespaces:
```bash
grep -rn "airflow.providers.lore.splitter\|airflow.providers.lore.audit" "$DST/operators" "$DST/config"
```
Expected: no output.

- [ ] **Step 2: Copy the operator tests + repoint stubs**

```bash
SRC_TESTS=/Users/stamplevskiyd/adventum/agent-lore/lore-core/airflow-providers/apache-airflow-providers-lore/tests
DST_ROOT=/Users/stamplevskiyd/development/lore/lore-core/airflow-providers/apache-airflow-providers-lore
cp "$SRC_TESTS/test_lore_splitter_operator.py" "$DST_ROOT/tests/test_lore_splitter_operator.py"
cp "$SRC_TESTS/test_lore_splitter_audit_operator.py" "$DST_ROOT/tests/test_lore_splitter_audit_operator.py"
```
In `test_lore_splitter_operator.py`: it DEFINES `install_airflow_stubs()` inline — replace that definition with `from _airflow_stubs import install_airflow_stubs` (the helper now lives in `tests/_airflow_stubs.py`; do not keep a divergent copy). Keep `import_operator_module()` and everything else. In BOTH tests, rewrite any `airflow.providers.lore.splitter.*` / `airflow.providers.lore.audit.*` module-name strings the same way as the source modules (e.g. audit adapter strings → `airflow.providers.lore.adapters.airflow_audit_adapters`). `test_lore_splitter_audit_operator.py` builds minimal inline stubs — leave its inline stubs, but repoint any module-name strings for the moved adapters. Confirm:
```bash
grep -n "def install_airflow_stubs\|airflow.providers.lore.audit.airflow_adapters\|splitter.storage.airflow" tests/test_lore_splitter_operator.py tests/test_lore_splitter_audit_operator.py
```
Expected: no output.

- [ ] **Step 3: Run both operator tests**

```bash
cd /Users/stamplevskiyd/development/lore/lore-core/airflow-providers/apache-airflow-providers-lore
uv run pytest tests/test_lore_splitter_operator.py tests/test_lore_splitter_audit_operator.py -q
```
Expected: all pass (source: 697 + 340 lines of cases). A `KeyError`/`ImportError` on an adapter module string points to a missed module-name rewrite in Step 2.

- [ ] **Step 4: Run the whole provider suite so far**

```bash
uv run pytest tests -q
```
Expected: everything green (metadata + storage hooks + audit adapter + both operators).

- [ ] **Step 5: Commit**

```bash
cd /Users/stamplevskiyd/development/lore
git add lore-core/airflow-providers/apache-airflow-providers-lore/airflow/providers/lore/operators/ \
        lore-core/airflow-providers/apache-airflow-providers-lore/airflow/providers/lore/config/ \
        lore-core/airflow-providers/apache-airflow-providers-lore/tests/test_lore_splitter_operator.py \
        lore-core/airflow-providers/apache-airflow-providers-lore/tests/test_lore_splitter_audit_operator.py
git commit -m "feat(provider): operators + runtime config loader"
```

---

### Task 5: Example DAG + DAG/UAT tests

Bring the example DAG and its structure tests. The real-DagBag/UAT assertions skip cleanly when Airflow is absent.

**Files:**
- Create: `example_dags/lore_splitter.py` (from source `dags/lore_splitter.py`)
- Create: `tests/test_lore_dag.py` (from source)
- Create: `tests/test_phase26_uat.py` (from source; add a module-level Airflow guard)

**Interfaces:**
- Consumes: `airflow.providers.lore.operators.{LoreSplitterOperator, LoreSplitterAuditOperator}`, `airflow.providers.lore.config.load_runtime_config` (Task 4).
- The DAG imports real SDK `from airflow.sdk import dag, get_current_context, task` and `from airflow.utils.trigger_rule import TriggerRule` — these are provided by the stub loader in `test_lore_dag.py` or skipped in `test_phase26_uat.py`; the DAG file itself is unchanged apart from operator/config namespace (already provider-namespaced, so NO rewrite needed).

- [ ] **Step 1: Copy the example DAG**

```bash
cp /Users/stamplevskiyd/adventum/agent-lore/lore-core/dags/lore_splitter.py \
   /Users/stamplevskiyd/development/lore/lore-core/airflow-providers/apache-airflow-providers-lore/example_dags/lore_splitter.py
```
Its imports (`airflow.providers.lore.config`, `airflow.providers.lore.operators`, `airflow.sdk`, `airflow.utils.trigger_rule`) are all provider-namespace or real SDK — NO rewrite. Confirm: `grep -n "airflow.providers.lore.splitter\|airflow.providers.lore.audit" example_dags/lore_splitter.py` → no output.

- [ ] **Step 2: Copy `test_lore_dag.py` + repoint the DAG path**

```bash
SRC_TESTS=/Users/stamplevskiyd/adventum/agent-lore/lore-core/airflow-providers/apache-airflow-providers-lore/tests
DST_ROOT=/Users/stamplevskiyd/development/lore/lore-core/airflow-providers/apache-airflow-providers-lore
cp "$SRC_TESTS/test_lore_dag.py" "$DST_ROOT/tests/test_lore_dag.py"
```
The test loads the DAG file by path (`importlib.util.spec_from_file_location`). Update its DAG-path constant to point at the new `example_dags/lore_splitter.py`. Find it: `grep -n "dags/lore_splitter\|lore_splitter.py\|DAG_PATH\|spec_from_file_location\|Path(" tests/test_lore_dag.py`; set the path to `Path(__file__).resolve().parent.parent / "example_dags" / "lore_splitter.py"`. Its `test_real_dagbag_import_when_scheduler_is_available` already `pytest.skip`s on `ModuleNotFoundError` — leave that.

- [ ] **Step 3: Copy `test_phase26_uat.py` + add an Airflow guard**

```bash
cp "$SRC_TESTS/test_phase26_uat.py" "$DST_ROOT/tests/test_phase26_uat.py"
```
The source imports `from airflow.models.dagbag import DagBag` UNGUARDED at module top and also needs a real Postgres (`ephemeral_postgres`), so it would error at collection in the airflow-free env. Add, at the very top of the module (after `from __future__ import annotations`), a hard skip guard so the whole module is skipped cleanly:
```python
import pytest

pytest.importorskip("airflow.models.dagbag", reason="Phase-3 UAT needs a real Airflow install")
```
Repoint its DAG-path constant to `example_dags/lore_splitter.py` the same way as Step 2. Leave the rest verbatim.

- [ ] **Step 4: Run the DAG/UAT tests**

```bash
cd /Users/stamplevskiyd/development/lore/lore-core/airflow-providers/apache-airflow-providers-lore
uv run pytest tests/test_lore_dag.py tests/test_phase26_uat.py -q
```
Expected: `test_lore_dag` structural cases pass; its real-dagbag case SKIPS; `test_phase26_uat` SKIPS as a module (no airflow). Output shows passed + skipped, zero failures/errors.

- [ ] **Step 5: Full provider suite green**

```bash
uv run pytest tests -q
```
Expected: all pass or skip; zero failures. Note the skip count in the commit is expected.

- [ ] **Step 6: Commit**

```bash
cd /Users/stamplevskiyd/development/lore
git add lore-core/airflow-providers/apache-airflow-providers-lore/example_dags/lore_splitter.py \
        lore-core/airflow-providers/apache-airflow-providers-lore/tests/test_lore_dag.py \
        lore-core/airflow-providers/apache-airflow-providers-lore/tests/test_phase26_uat.py
git commit -m "feat(provider): example DAG + DAG/UAT structure tests"
```

---

### Task 6: Reinstate deferred debts

Close the cross-phase debts recorded in 2b/2d, now that the adapters exist.

**Files:**
- Create: `tests/test_audit_service_catalog_rollback.py` (port the excised adapter-using catalog test from source `tests/test_audit_service.py`)
- Modify: `packages/lore-splitter/tests/test_audit_persistence.py` (remove the obsolete `pass` stub)

**Background (the three debts):**
1. **Excised 2b `__all__`-surface test** (`test_audit_engine.py::test_public_audit_surface_retains_all_pure_phase_20_values`) asserted the source's aggregating `audit/__init__.py` `__all__`. The merge deliberately adopted **empty `__init__.py` + direct-submodule imports** across all packages (`lore_audit/__init__.py` is empty). That surface no longer exists → the test is **obsolete**; do NOT reinstate it (it would contradict the architecture). Recorded here as resolved-obsolete.
2. **Excised 2b adapter-integration test** — the airflow-adapter catalog-rollback test removed from `test_audit_service.py`. Reinstate in the provider (it needs `build_airflow_audit_adapters`).
3. **Skip-marked 2d stub** `test_real_postgres_catalog_error_does_not_poison_failure_write` in `packages/lore-splitter/tests/test_audit_persistence.py` — a bare `pass` placeholder whose intent (catalog error must not poison the failure-write) is the same concern as debt #2 and is now covered in the provider. Remove the placeholder.

- [ ] **Step 1: Port the excised adapter catalog-rollback test**

From source `tests/test_audit_service.py`, extract `test_catalog_failure_rolls_back_before_service_persists_resolution_failure` (and any small in-file helpers/mock hook classes it needs — e.g. mock `PostgresHook`/cursor and `build_airflow_audit_adapters` usage) into a NEW file `tests/test_audit_service_catalog_rollback.py` in the provider. Rewrite imports: `build_airflow_audit_adapters` from `airflow.providers.lore.adapters.airflow_audit_adapters`; `lore_audit.service` for `AuditService`; `lore_audit.snapshot_repository` for `AuditReadBounds` if used; repoint any stub helper to `from _airflow_stubs import install_airflow_stubs`. Keep the test body's assertions verbatim.

- [ ] **Step 2: Run it**

```bash
cd /Users/stamplevskiyd/development/lore/lore-core/airflow-providers/apache-airflow-providers-lore
uv run pytest tests/test_audit_service_catalog_rollback.py -q
```
Expected: pass. If it genuinely needs a real Postgres (`ephemeral_postgres`) rather than mock hooks, gate it with `pytest.importorskip`/Docker-skip mirroring the source's own guard and note it in the report.

- [ ] **Step 3: Remove the obsolete lore-splitter stub**

In `packages/lore-splitter/tests/test_audit_persistence.py`, delete the `@pytest.mark.skip(...)`-decorated `test_real_postgres_catalog_error_does_not_poison_failure_write` function (the bare `pass` placeholder). Verify no other reference:
```bash
grep -rn "test_real_postgres_catalog_error_does_not_poison_failure_write" /Users/stamplevskiyd/development/lore/lore-core/packages/lore-splitter
```
Expected: no output after deletion.

- [ ] **Step 4: Confirm lore-splitter suite still green (one fewer skip)**

```bash
cd /Users/stamplevskiyd/development/lore/lore-core
uv run --package lore-splitter pytest packages/lore-splitter/tests -q
```
Expected: 284 passed / 0 skipped (was 284/1 — the removed stub was the lone skip). If a different skip existed, expect the skip count to drop by exactly one.

- [ ] **Step 5: Commit**

```bash
cd /Users/stamplevskiyd/development/lore
git add lore-core/airflow-providers/apache-airflow-providers-lore/tests/test_audit_service_catalog_rollback.py \
        lore-core/packages/lore-splitter/tests/test_audit_persistence.py
git commit -m "test(provider): reinstate audit catalog-rollback; drop obsolete 2d stub"
```

---

## Post-phase

The merge is code-complete: every module lives in its canonical home; the provider is the sole Airflow-importing package and builds/tests standalone airflow-free. What remains is **Phase 4** (final cleanup: any lingering re-export shims, scripts, docs sweep) — a separate plan. Update `.superpowers/sdd/progress.md` and the memory file `lore-agent-merge.md` on completion.

## Self-Review

- **Spec coverage:** all four approved decisions implemented — (1) all Airflow code in the provider `adapters/`+`operators/` (Tasks 2–5); (2) standalone pkg excluded from workspace + `apache-airflow` optional + stub tests (Task 1 + all test steps); (3) `config/runtime.py` faithful port (Task 4); (4) example DAG + structure tests (Task 5). The 3 debts are resolved in Task 6 (one as obsolete-by-design, with rationale). Every source test that runs airflow-free is ported; the two that need a real Airflow (`test_lore_dag`'s dagbag case, `test_phase26_uat`) skip cleanly.
- **Placeholder scan:** no TBD/"handle errors" — every step is a concrete `cp`/`grep`/`uv run`/`git` command or an explicit named remap with before/after text. The two "if it genuinely needs real Postgres / note it" clauses (Task 6 Step 2) are deliberate reviewer-surfacing instructions with a concrete fallback (mirror the source guard), not open-ended placeholders.
- **Type/name consistency:** adapter class/factory names are used identically across producer and consumer tasks — `PostgresHookTableToastStoreFactory`, `S3HookObjectToastStore`, `AirflowAuditAdapters`, `build_airflow_audit_adapters`, `AuditReadBounds` (from `lore_audit.snapshot_repository`), `load_runtime_config`. The `airflow.providers.lore.adapters.*` new-home namespace is used consistently in every operator/test remap.
