# P0 — Neo4j Foundations & Spike Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** De-risk the one new retrieval backend by proving Neo4j vector + Lucene fulltext + hybrid retrieval work on real Russian `lore_core` data, choosing the embedding model and analyzer with evidence, and designing derived identity + one-ready-version activation — so P1 can build the real projection on settled decisions.

**Architecture:** A new durable package `lore-core/packages/lore-retrieval/` holds the reusable primitives seeded here (derived-identity helpers, an `EmbeddingBackend` behind which bge-m3 runs via Ollama, a read-only `lore_core` Postgres source adapter, and thin Neo4j projection/retrieval wrappers over `neo4j` + `neo4j-graphrag-python`). Throwaway measurement harnesses live under `lore-core/packages/lore-retrieval/spikes/` and emit findings into decision docs under `docs/architecture/`. Neo4j is an external, DSN-addressed stateful backend; `lore_core` is read-only.

**Tech Stack:** Python 3.13, `neo4j` driver, `neo4j-graphrag-python`, `langchain-ollama` (bge-m3 embeddings), `asyncpg` (read-only lore_core), `pydantic` / `pydantic-settings`, `pytest`.

## Global Constraints

Copied verbatim from the roadmap invariants and the resolved P0 decisions. Every task's requirements implicitly include this section.

- `lore_core` remains canonical; this phase reads it **read-only** and never writes to it.
- Neo4j is a **rebuildable projection**, never the only copy of canonical content or SQL lineage.
- Existing chunking and canonical `chunk_id` are retained; **no re-chunking** — consume prepared chunks.
- Exactly **one ready index version** is visible at query time; inactive versions must not consume native `top_k` recall.
- Search and expansion use **fixed, parameterized Cypher** only; user/LLM text never becomes a label, relationship type, index name, or Cypher fragment.
- Neo4j is **external, addressed by `NEO4J_URI` + credentials**; credentials come from env/secret-management, never source.
- Embeddings are computed from the canonical `vector_text` view; the embedding model for P0 is **bge-m3 via Ollama**, behind an `EmbeddingBackend` interface so it is swappable by config.
- Spike data is the real **`loreagent_test`** `lore_core` corpus (Russian), read-only.
- Every derived `Chunk` carries exactly one retrieval-lane label: `TextChunk` (ordinary) or `TableChunk` (canonical `chunk_type="table_payload"`). These are mutually exclusive and rebuildable from `chunk_type`.
- No bounded route may return unbounded nodes, relationships, chunks, or paths.

## File Structure

New durable package (seeds P1):

- `lore-core/packages/lore-retrieval/pyproject.toml` — package + pinned deps.
- `lore-core/packages/lore-retrieval/src/lore_retrieval/__init__.py`
- `lore-core/packages/lore-retrieval/src/lore_retrieval/config.py` — spike/runtime settings from env.
- `lore-core/packages/lore-retrieval/src/lore_retrieval/identity.py` — `projection_id`, `section_id`, `section_prefixes`.
- `lore-core/packages/lore-retrieval/src/lore_retrieval/embeddings.py` — `EmbeddingBackend` protocol + `OllamaEmbeddingBackend` + `Neo4jGraphRagEmbedder` adapter.
- `lore-core/packages/lore-retrieval/src/lore_retrieval/source.py` — read-only `lore_core` Postgres adapter + `SourceChunk`.
- `lore-core/packages/lore-retrieval/src/lore_retrieval/neo4j_spike.py` — projection + index creation + vector/fulltext/hybrid queries.
- `lore-core/packages/lore-retrieval/src/lore_retrieval/ledger.py` — typed `DerivedIndexRecord` model (persistence deferred to P1).
- `lore-core/packages/lore-retrieval/spikes/probe_capabilities.py` — Neo4j edition/version/index capability probe.
- `lore-core/packages/lore-retrieval/spikes/cases_ru.yaml` — curated Russian retrieval cases (prose morphology + exact codes).
- `lore-core/packages/lore-retrieval/spikes/run_analyzer_eval.py` — analyzer comparison harness.
- `lore-core/packages/lore-retrieval/spikes/run_latency.py` — latency-at-scale harness.
- `lore-core/packages/lore-retrieval/tests/test_identity.py`
- `lore-core/packages/lore-retrieval/tests/test_embeddings.py`
- `lore-core/packages/lore-retrieval/tests/test_source.py`

Decision/design docs (durable P0 output):

- `docs/architecture/neo4j-identity-and-activation.md` — identity + one-ready-version activation design.
- `docs/architecture/neo4j-p0-decisions.md` — consolidated decision record answering the promotion questions.

---

### Task 1: Scaffold `lore-retrieval` package + pinned config

**Files:**
- Create: `lore-core/packages/lore-retrieval/pyproject.toml`
- Create: `lore-core/packages/lore-retrieval/src/lore_retrieval/__init__.py`
- Create: `lore-core/packages/lore-retrieval/src/lore_retrieval/config.py`
- Test: `lore-core/packages/lore-retrieval/tests/test_config.py`

**Interfaces:**
- Produces: `Settings` (pydantic-settings) with `neo4j_uri: str`, `neo4j_user: str`, `neo4j_password: str`, `neo4j_database: str = "neo4j"`, `lore_core_dsn: str`, `ollama_base_url: str`, `embedding_model: str = "bge-m3"`, `embedding_dim: int = 1024`; `get_settings() -> Settings`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
import os
from lore_retrieval.config import get_settings


def test_settings_read_from_env(monkeypatch):
    monkeypatch.setenv("RETRIEVAL_NEO4J_URI", "neo4j+s://example:7687")
    monkeypatch.setenv("RETRIEVAL_NEO4J_USER", "neo4j")
    monkeypatch.setenv("RETRIEVAL_NEO4J_PASSWORD", "secret")
    monkeypatch.setenv("RETRIEVAL_LORE_CORE_DSN", "postgresql://ro@db/loreagent_test")
    get_settings.cache_clear()
    s = get_settings()
    assert s.neo4j_uri == "neo4j+s://example:7687"
    assert s.embedding_model == "bge-m3"
    assert s.embedding_dim == 1024
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd lore-core/packages/lore-retrieval && uv run pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lore_retrieval.config'`

- [ ] **Step 3: Write `pyproject.toml`**

```toml
[project]
name = "lore-retrieval"
version = "0.0.1"
description = "Lore hybrid graph-RAG retrieval (Neo4j projection + LangGraph orchestration)"
requires-python = ">=3.13"
dependencies = [
    "neo4j>=5.28,<6",
    "neo4j-graphrag>=1.3,<2",
    "langchain-ollama>=0.2",
    "asyncpg>=0.30",
    "pydantic>=2.9",
    "pydantic-settings>=2.6",
    "pyyaml>=6.0",
]

[dependency-groups]
dev = ["pytest>=8.0", "pytest-asyncio>=0.24", "ruff>=0.15"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
asyncio_mode = "auto"

[tool.setuptools.packages.find]
where = ["src"]
```

> Note: pin exact resolved versions into `docs/architecture/neo4j-p0-decisions.md` in Task 11. The floors above are starting bounds; `uv lock` records the exact set.

- [ ] **Step 4: Write `config.py`**

```python
# src/lore_retrieval/config.py
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RETRIEVAL_", extra="ignore")

    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""
    neo4j_database: str = "neo4j"

    lore_core_dsn: str = ""

    ollama_base_url: str = "http://localhost:11434"
    embedding_model: str = "bge-m3"
    embedding_dim: int = 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 5: Create empty `__init__.py`**

```python
# src/lore_retrieval/__init__.py
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd lore-core/packages/lore-retrieval && uv run pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add lore-core/packages/lore-retrieval
git commit -m "feat(retrieval): scaffold lore-retrieval package with pinned deps and settings"
```

---

### Task 2: Derived-identity helpers

**Files:**
- Create: `lore-core/packages/lore-retrieval/src/lore_retrieval/identity.py`
- Test: `lore-core/packages/lore-retrieval/tests/test_identity.py`

**Interfaces:**
- Produces:
  - `projection_id(index_version: str, canonical_id: str) -> str` → `f"{index_version}:{canonical_id}"`.
  - `section_id(document_id: str, heading_path: tuple[str, ...]) -> str` — deterministic SHA256-based id, stable for a given `(document_id, heading_path)`.
  - `section_prefixes(heading_path: tuple[str, ...]) -> list[tuple[str, ...]]` — every non-empty path prefix, shallowest first.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_identity.py
from lore_retrieval.identity import projection_id, section_id, section_prefixes


def test_projection_id_joins_version_and_canonical():
    assert projection_id("v3", "chunk_abc") == "v3:chunk_abc"


def test_section_prefixes_lists_every_prefix_shallowest_first():
    assert section_prefixes(("Root", "Child", "Sub")) == [
        ("Root",),
        ("Root", "Child"),
        ("Root", "Child", "Sub"),
    ]


def test_section_prefixes_empty_path_is_empty():
    assert section_prefixes(()) == []


def test_section_id_is_deterministic_and_path_sensitive():
    a = section_id("doc1", ("Root", "Child"))
    b = section_id("doc1", ("Root", "Child"))
    c = section_id("doc1", ("Root",))
    d = section_id("doc2", ("Root", "Child"))
    assert a == b
    assert a != c
    assert a != d
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd lore-core/packages/lore-retrieval && uv run pytest tests/test_identity.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lore_retrieval.identity'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/lore_retrieval/identity.py
import hashlib


def projection_id(index_version: str, canonical_id: str) -> str:
    return f"{index_version}:{canonical_id}"


def section_prefixes(heading_path: tuple[str, ...]) -> list[tuple[str, ...]]:
    return [tuple(heading_path[: i + 1]) for i in range(len(heading_path))]


def section_id(document_id: str, heading_path: tuple[str, ...]) -> str:
    # Deterministic, collision-resistant, stable per (document, path).
    # \x1f (unit separator) cannot appear in heading text, so it is an
    # unambiguous delimiter between path segments and the document id.
    payload = document_id + "\x1e" + "\x1f".join(heading_path)
    return "sec_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd lore-core/packages/lore-retrieval && uv run pytest tests/test_identity.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add lore-core/packages/lore-retrieval/src/lore_retrieval/identity.py lore-core/packages/lore-retrieval/tests/test_identity.py
git commit -m "feat(retrieval): add derived identity helpers (projection_id, section_id, prefixes)"
```

---

### Task 3: Embedding backend (bge-m3 via Ollama) + graphrag adapter

**Files:**
- Create: `lore-core/packages/lore-retrieval/src/lore_retrieval/embeddings.py`
- Test: `lore-core/packages/lore-retrieval/tests/test_embeddings.py`

**Interfaces:**
- Produces:
  - `EmbeddingBackend` (Protocol): `embed_documents(texts: list[str]) -> list[list[float]]`, `embed_query(text: str) -> list[float]`, property `dim: int`.
  - `OllamaEmbeddingBackend(model: str, base_url: str, dim: int)` implementing it via `langchain_ollama.OllamaEmbeddings`.
  - `Neo4jGraphRagEmbedder(backend: EmbeddingBackend)` implementing `neo4j_graphrag.embeddings.base.Embedder` (`embed_query(text) -> list[float]`) so the pinned library can consume our backend.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_embeddings.py
from lore_retrieval.embeddings import EmbeddingBackend, Neo4jGraphRagEmbedder


class FakeBackend:
    dim = 3

    def embed_documents(self, texts):
        return [[float(len(t)), 0.0, 1.0] for t in texts]

    def embed_query(self, text):
        return [float(len(text)), 0.0, 1.0]


def test_backend_satisfies_protocol():
    b = FakeBackend()
    assert isinstance(b, EmbeddingBackend)


def test_graphrag_embedder_delegates_query():
    embedder = Neo4jGraphRagEmbedder(FakeBackend())
    assert embedder.embed_query("abcd") == [4.0, 0.0, 1.0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd lore-core/packages/lore-retrieval && uv run pytest tests/test_embeddings.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lore_retrieval.embeddings'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/lore_retrieval/embeddings.py
from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbeddingBackend(Protocol):
    dim: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...


class OllamaEmbeddingBackend:
    def __init__(self, model: str, base_url: str, dim: int) -> None:
        from langchain_ollama import OllamaEmbeddings

        self.dim = dim
        self._model = model
        self._client = OllamaEmbeddings(model=model, base_url=base_url)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._client.embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._client.embed_query(text)


class Neo4jGraphRagEmbedder:
    """Adapts an EmbeddingBackend to neo4j_graphrag's Embedder interface."""

    def __init__(self, backend: EmbeddingBackend) -> None:
        self._backend = backend

    def embed_query(self, text: str) -> list[float]:
        return self._backend.embed_query(text)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd lore-core/packages/lore-retrieval && uv run pytest tests/test_embeddings.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Integration smoke check (manual, non-CI)**

Run (requires Ollama with bge-m3 pulled: `ollama pull bge-m3`):
```bash
cd lore-core/packages/lore-retrieval && uv run python -c "
from lore_retrieval.config import get_settings
from lore_retrieval.embeddings import OllamaEmbeddingBackend
s = get_settings()
b = OllamaEmbeddingBackend(s.embedding_model, s.ollama_base_url, s.embedding_dim)
v = b.embed_query('пример запроса на русском')
print('dim=', len(v))
"
```
Expected: `dim= 1024`. Record the observed dimension in Task 11 (confirms `embedding_dim`).

- [ ] **Step 6: Commit**

```bash
git add lore-core/packages/lore-retrieval/src/lore_retrieval/embeddings.py lore-core/packages/lore-retrieval/tests/test_embeddings.py
git commit -m "feat(retrieval): add EmbeddingBackend with Ollama bge-m3 and graphrag adapter"
```

---

### Task 4: Read-only `lore_core` source adapter

**Files:**
- Create: `lore-core/packages/lore-retrieval/src/lore_retrieval/source.py`
- Test: `lore-core/packages/lore-retrieval/tests/test_source.py`

**Interfaces:**
- Produces:
  - `SourceChunk` (pydantic model): `chunk_id: str`, `document_id: str`, `run_id: str`, `chunk_type: str`, `position: int`, `heading_path: tuple[str, ...]`, `vector_text: str`, `fulltext: str`, `vector_text_hash: str`, `fulltext_hash: str`, `is_table: bool` (property: `chunk_type == "table_payload"`).
  - `row_to_source_chunk(row: dict) -> SourceChunk` — maps a `lore_core.chunks` row (with jsonb `coordinates`) into a `SourceChunk`.
  - `async fetch_chunks(dsn: str, *, run_id: str | None = None, limit: int = 500) -> list[SourceChunk]` — read-only asyncpg query against `lore_core.chunks`, ordered by `(document_id, position)`.

**Notes:** The read is `SELECT ... FROM lore_core.chunks` in a `READ ONLY` transaction. Column names follow the merged read side (`display_text`/`full_text`/`vector_text`, `coordinates` jsonb with `heading_path`). Confirm exact column names against `lore-core/services/lore-chat/audit/read_cursor.py` before running; adjust the SELECT if the audit read side names differ.

- [ ] **Step 1: Write the failing test (pure mapping, no DB)**

```python
# tests/test_source.py
from lore_retrieval.source import row_to_source_chunk


def _row(**over):
    base = {
        "chunk_id": "c1",
        "document_id": "d1",
        "run_id": "r1",
        "chunk_type": "text",
        "position": 0,
        "coordinates": {"heading_path": ["Root", "Child"]},
        "vector_text": "векторный текст",
        "full_text": "полный текст с кодом ABC-123",
        "vector_text_hash": "vh",
        "fulltext_hash": "fh",
    }
    base.update(over)
    return base


def test_mapping_reads_nested_heading_path():
    sc = row_to_source_chunk(_row())
    assert sc.heading_path == ("Root", "Child")
    assert sc.fulltext == "полный текст с кодом ABC-123"
    assert sc.is_table is False


def test_table_payload_flagged_as_table():
    sc = row_to_source_chunk(_row(chunk_type="table_payload"))
    assert sc.is_table is True


def test_missing_heading_path_defaults_empty():
    sc = row_to_source_chunk(_row(coordinates={}))
    assert sc.heading_path == ()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd lore-core/packages/lore-retrieval && uv run pytest tests/test_source.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lore_retrieval.source'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/lore_retrieval/source.py
from pydantic import BaseModel


class SourceChunk(BaseModel):
    chunk_id: str
    document_id: str
    run_id: str
    chunk_type: str
    position: int
    heading_path: tuple[str, ...]
    vector_text: str
    fulltext: str
    vector_text_hash: str
    fulltext_hash: str

    @property
    def is_table(self) -> bool:
        return self.chunk_type == "table_payload"


def row_to_source_chunk(row: dict) -> SourceChunk:
    coords = row.get("coordinates") or {}
    heading = tuple(coords.get("heading_path") or ())
    return SourceChunk(
        chunk_id=row["chunk_id"],
        document_id=row["document_id"],
        run_id=row["run_id"],
        chunk_type=row["chunk_type"],
        position=row["position"],
        heading_path=heading,
        vector_text=row["vector_text"],
        fulltext=row["full_text"],
        vector_text_hash=row["vector_text_hash"],
        fulltext_hash=row["fulltext_hash"],
    )


async def fetch_chunks(
    dsn: str, *, run_id: str | None = None, limit: int = 500
) -> list[SourceChunk]:
    import asyncpg

    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute("BEGIN TRANSACTION READ ONLY")
        where = "WHERE run_id = $1" if run_id else ""
        args = ([run_id, limit] if run_id else [limit])
        limit_pos = "$2" if run_id else "$1"
        rows = await conn.fetch(
            f"""
            SELECT chunk_id, document_id, run_id, chunk_type, position,
                   coordinates, vector_text, full_text,
                   vector_text_hash, fulltext_hash
            FROM lore_core.chunks
            {where}
            ORDER BY document_id, position
            LIMIT {limit_pos}
            """,
            *args,
        )
        await conn.execute("COMMIT")
    finally:
        await conn.close()

    import json

    result = []
    for r in rows:
        d = dict(r)
        if isinstance(d.get("coordinates"), str):
            d["coordinates"] = json.loads(d["coordinates"])
        result.append(row_to_source_chunk(d))
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd lore-core/packages/lore-retrieval && uv run pytest tests/test_source.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Integration smoke check (manual, requires loreagent_test DSN)**

Run:
```bash
cd lore-core/packages/lore-retrieval && RETRIEVAL_LORE_CORE_DSN="<ro dsn to loreagent_test>" uv run python -c "
import asyncio
from lore_retrieval.config import get_settings
from lore_retrieval.source import fetch_chunks
rows = asyncio.run(fetch_chunks(get_settings().lore_core_dsn, limit=20))
print('fetched', len(rows), 'sample heading:', rows[0].heading_path if rows else None)
print('tables:', sum(c.is_table for c in rows))
"
```
Expected: prints a non-zero count and a Russian heading path. If column names error, reconcile against `audit/read_cursor.py` and fix the SELECT, then re-run.

- [ ] **Step 6: Commit**

```bash
git add lore-core/packages/lore-retrieval/src/lore_retrieval/source.py lore-core/packages/lore-retrieval/tests/test_source.py
git commit -m "feat(retrieval): add read-only lore_core source adapter and SourceChunk"
```

---

### Task 5: Neo4j capability probe (answers promotion Q1)

**Files:**
- Create: `lore-core/packages/lore-retrieval/spikes/probe_capabilities.py`
- Modify: `docs/architecture/neo4j-p0-decisions.md` (create in this task; append later)

**Interfaces:**
- Consumes: `Settings` (Task 1).
- Produces: a printed + doc-recorded capability report: edition, version, whether native vector index and fulltext index are supported, and whether multi-database is available (drives the activation-isolation choice).

- [ ] **Step 1: Write the probe script**

```python
# spikes/probe_capabilities.py
"""Throwaway: probe the external Neo4j instance for edition/version/capabilities."""
from neo4j import GraphDatabase
from lore_retrieval.config import get_settings


def main() -> None:
    s = get_settings()
    driver = GraphDatabase.driver(s.neo4j_uri, auth=(s.neo4j_user, s.neo4j_password))
    with driver.session(database=s.neo4j_database) as sess:
        comp = sess.run(
            "CALL dbms.components() YIELD name, versions, edition "
            "RETURN name, versions, edition"
        ).data()
        print("components:", comp)

        # Vector + fulltext index procedures available?
        procs = sess.run(
            "SHOW PROCEDURES YIELD name "
            "WHERE name IN ['db.index.vector.queryNodes', 'db.index.fulltext.queryNodes'] "
            "RETURN collect(name) AS available"
        ).single()["available"]
        print("index procs available:", procs)

        # Multi-database (Enterprise) => separate-DB activation is possible.
        try:
            dbs = sess.run("SHOW DATABASES YIELD name RETURN collect(name) AS names").single()["names"]
            print("databases visible:", dbs)
        except Exception as e:  # Community may restrict SHOW DATABASES
            print("SHOW DATABASES not available:", e)
    driver.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the probe**

Run:
```bash
cd lore-core/packages/lore-retrieval && uv run python spikes/probe_capabilities.py
```
Expected: prints edition (`community` or `enterprise`), a 5.x version, both index procedures available, and the visible databases.

- [ ] **Step 3: Record findings**

Create `docs/architecture/neo4j-p0-decisions.md` with a `## 1. Neo4j capabilities` section capturing: edition, exact version, vector/fulltext support (yes/no), and multi-database availability. Add one line: **activation isolation baseline** = version-labeled indexes (portable); **separate-DB activation** = available only if edition is Enterprise.

- [ ] **Step 4: Commit**

```bash
git add lore-core/packages/lore-retrieval/spikes/probe_capabilities.py docs/architecture/neo4j-p0-decisions.md
git commit -m "spike(retrieval): probe Neo4j capabilities and record edition/version/index support"
```

---

### Task 6: Spike projection — load a batch into Neo4j with vector + fulltext indexes

**Files:**
- Create: `lore-core/packages/lore-retrieval/src/lore_retrieval/neo4j_spike.py`

**Interfaces:**
- Consumes: `SourceChunk` (Task 4), `EmbeddingBackend` (Task 3), `projection_id`/`section_id` (Task 2), `Settings` (Task 1).
- Produces:
  - `async project_batch(driver, database, index_version, chunks, backend, embed_batch=64) -> int` — MERGEs `Chunk` nodes with label `TextChunk`/`TableChunk` (version-labeled for isolation), sets `projection_id`, `chunk_id`, `document_id`, `section_id`, `chunk_type`, `position`, `fulltext`, `fulltext_hash`, `embedding`. Returns node count.
  - `ensure_indexes(driver, database, index_version, dim)` — creates version-scoped vector + fulltext indexes for `TextChunk` and `TableChunk` via `neo4j_graphrag.indexes`.

**Notes:** version-scoped index/label naming (e.g. label `TextChunk_v3`, index `text_vec_v3`) is the Community-portable one-ready-version mechanism; only the active version's indexes exist/serve queries. All writes are parameterized; no query text is interpolated from user/LLM input (index names come from the trusted `index_version`, which is an internal identifier, not user text).

- [ ] **Step 1: Write the implementation**

```python
# src/lore_retrieval/neo4j_spike.py
from neo4j import AsyncDriver
from neo4j_graphrag.indexes import create_vector_index, create_fulltext_index
from lore_retrieval.identity import projection_id, section_id
from lore_retrieval.source import SourceChunk


def _labels(index_version: str) -> tuple[str, str]:
    v = index_version.replace("-", "_")
    return f"TextChunk_{v}", f"TableChunk_{v}"


async def ensure_indexes(driver: AsyncDriver, database: str, index_version: str, dim: int) -> None:
    text_label, table_label = _labels(index_version)
    v = index_version.replace("-", "_")
    for label in (text_label, table_label):
        create_vector_index(
            driver, name=f"vec_{label}", label=label, embedding_property="embedding",
            dimensions=dim, similarity_fn="cosine", neo4j_database=database,
        )
        create_fulltext_index(
            driver, name=f"ft_{label}", label=label, node_properties=["fulltext"],
            neo4j_database=database,
        )


async def project_batch(
    driver: AsyncDriver, database: str, index_version: str,
    chunks: list[SourceChunk], backend, embed_batch: int = 64,
) -> int:
    text_label, table_label = _labels(index_version)
    total = 0
    async with driver.session(database=database) as sess:
        for i in range(0, len(chunks), embed_batch):
            window = chunks[i : i + embed_batch]
            vectors = backend.embed_documents([c.vector_text for c in window])
            rows = [
                {
                    "projection_id": projection_id(index_version, c.chunk_id),
                    "chunk_id": c.chunk_id,
                    "document_id": c.document_id,
                    "section_id": section_id(c.document_id, c.heading_path),
                    "chunk_type": c.chunk_type,
                    "position": c.position,
                    "fulltext": c.fulltext,
                    "fulltext_hash": c.fulltext_hash,
                    "embedding": vec,
                    "label": table_label if c.is_table else text_label,
                }
                for c, vec in zip(window, vectors)
            ]
            # One MERGE per lane label; APOC-free, parameterized.
            for label in (text_label, table_label):
                sub = [r for r in rows if r["label"] == label]
                if not sub:
                    continue
                await sess.run(
                    f"""
                    UNWIND $rows AS r
                    MERGE (c:{label} {{projection_id: r.projection_id}})
                    SET c.chunk_id = r.chunk_id, c.document_id = r.document_id,
                        c.section_id = r.section_id, c.chunk_type = r.chunk_type,
                        c.position = r.position, c.fulltext = r.fulltext,
                        c.fulltext_hash = r.fulltext_hash, c.embedding = r.embedding
                    """,
                    rows=sub,
                )
                total += len(sub)
    return total
```

- [ ] **Step 2: Run a projection smoke test (manual, requires Neo4j + Ollama + loreagent_test)**

Run:
```bash
cd lore-core/packages/lore-retrieval && uv run python -c "
import asyncio
from neo4j import AsyncGraphDatabase
from lore_retrieval.config import get_settings
from lore_retrieval.embeddings import OllamaEmbeddingBackend
from lore_retrieval.source import fetch_chunks
from lore_retrieval.neo4j_spike import ensure_indexes, project_batch

async def main():
    s = get_settings()
    backend = OllamaEmbeddingBackend(s.embedding_model, s.ollama_base_url, s.embedding_dim)
    chunks = await fetch_chunks(s.lore_core_dsn, limit=200)
    driver = AsyncGraphDatabase.driver(s.neo4j_uri, auth=(s.neo4j_user, s.neo4j_password))
    await ensure_indexes(driver, s.neo4j_database, 'spike1', s.embedding_dim)
    n = await project_batch(driver, s.neo4j_database, 'spike1', chunks, backend)
    print('projected', n, 'nodes')
    await driver.close()

asyncio.run(main())
"
```
Expected: `projected 200 nodes` (or fewer if the corpus is smaller). Confirms embeddings + indexes + parameterized MERGE work end-to-end.

- [ ] **Step 3: Commit**

```bash
git add lore-core/packages/lore-retrieval/src/lore_retrieval/neo4j_spike.py
git commit -m "spike(retrieval): project lore_core batch into Neo4j with vector+fulltext indexes"
```

---

### Task 7: Spike retrieval — vector, fulltext, hybrid query functions

**Files:**
- Modify: `lore-core/packages/lore-retrieval/src/lore_retrieval/neo4j_spike.py`

**Interfaces:**
- Consumes: the version-scoped labels/indexes from Task 6, `Neo4jGraphRagEmbedder` (Task 3).
- Produces (all return `list[tuple[str, float]]` = `(chunk_id, score)`, bounded by `top_k`):
  - `async vector_search(driver, database, index_version, query, embedder, top_k=50)`
  - `async fulltext_search(driver, database, index_version, query, top_k=50)`
  - `def rrf_fuse(routes: list[list[tuple[str, float]]], rrf_k: int = 60) -> list[tuple[str, float]]` — RRF over ranked routes, deduped by `chunk_id`.

- [ ] **Step 1: Write a unit test for RRF fusion (pure, no DB)**

```python
# tests/test_rrf.py
from lore_retrieval.neo4j_spike import rrf_fuse


def test_rrf_dedups_and_rewards_agreement():
    vector = [("a", 0.9), ("b", 0.8), ("c", 0.7)]
    fulltext = [("b", 5.0), ("a", 4.0), ("d", 3.0)]
    fused = rrf_fuse([vector, fulltext])
    ids = [cid for cid, _ in fused]
    assert set(ids) == {"a", "b", "c", "d"}          # deduped union
    assert ids[0] in {"a", "b"}                       # agreed items rank first
    assert ids.index("a") < ids.index("c")            # a (in both) beats c (in one)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd lore-core/packages/lore-retrieval && uv run pytest tests/test_rrf.py -v`
Expected: FAIL with `ImportError: cannot import name 'rrf_fuse'`

- [ ] **Step 3: Append the implementation to `neo4j_spike.py`**

```python
# append to src/lore_retrieval/neo4j_spike.py

async def vector_search(driver, database, index_version, query, embedder, top_k=50):
    text_label, _ = _labels(index_version)
    qvec = embedder.embed_query(query)
    async with driver.session(database=database) as sess:
        res = await sess.run(
            f"""
            CALL db.index.vector.queryNodes($index, $k, $qvec)
            YIELD node, score
            RETURN node.chunk_id AS chunk_id, score
            """,
            index=f"vec_{text_label}", k=top_k, qvec=qvec,
        )
        return [(r["chunk_id"], r["score"]) async for r in res]


async def fulltext_search(driver, database, index_version, query, top_k=50):
    text_label, _ = _labels(index_version)
    async with driver.session(database=database) as sess:
        res = await sess.run(
            f"""
            CALL db.index.fulltext.queryNodes($index, $q, {{limit: $k}})
            YIELD node, score
            RETURN node.chunk_id AS chunk_id, score
            """,
            index=f"ft_{text_label}", q=query, k=top_k,
        )
        return [(r["chunk_id"], r["score"]) async for r in res]


def rrf_fuse(routes: list[list[tuple[str, float]]], rrf_k: int = 60) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}
    for route in routes:
        for rank, (chunk_id, _) in enumerate(route):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (rrf_k + rank)
    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
```

> Note: `q` for fulltext is passed as a bound parameter — user text never becomes a Cypher fragment. Escaping Lucene special characters for exact-code queries is evaluated in Task 8.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd lore-core/packages/lore-retrieval && uv run pytest tests/test_rrf.py -v`
Expected: PASS

- [ ] **Step 5: Retrieval smoke check (manual)**

Run (after Task 6 projection):
```bash
cd lore-core/packages/lore-retrieval && uv run python -c "
import asyncio
from neo4j import AsyncGraphDatabase
from lore_retrieval.config import get_settings
from lore_retrieval.embeddings import OllamaEmbeddingBackend, Neo4jGraphRagEmbedder
from lore_retrieval.neo4j_spike import vector_search, fulltext_search, rrf_fuse

async def main():
    s = get_settings()
    emb = Neo4jGraphRagEmbedder(OllamaEmbeddingBackend(s.embedding_model, s.ollama_base_url, s.embedding_dim))
    d = AsyncGraphDatabase.driver(s.neo4j_uri, auth=(s.neo4j_user, s.neo4j_password))
    q = 'пример вопроса из корпуса'
    v = await vector_search(d, s.neo4j_database, 'spike1', q, emb, top_k=10)
    f = await fulltext_search(d, s.neo4j_database, 'spike1', q, top_k=10)
    print('vector top:', v[:3]); print('fulltext top:', f[:3])
    print('fused top:', rrf_fuse([v, f])[:5])
    await d.close()

asyncio.run(main())
"
```
Expected: three non-empty ranked lists; fused list dedups by chunk_id.

- [ ] **Step 6: Commit**

```bash
git add lore-core/packages/lore-retrieval/src/lore_retrieval/neo4j_spike.py lore-core/packages/lore-retrieval/tests/test_rrf.py
git commit -m "spike(retrieval): add vector/fulltext search and RRF fusion"
```

---

### Task 8: Russian analyzer evaluation (answers analyzer promotion question)

**Files:**
- Create: `lore-core/packages/lore-retrieval/spikes/cases_ru.yaml`
- Create: `lore-core/packages/lore-retrieval/spikes/run_analyzer_eval.py`
- Modify: `docs/architecture/neo4j-p0-decisions.md`

**Interfaces:**
- Consumes: projection + fulltext search primitives (Tasks 6–7). This task re-creates the fulltext index under different analyzers and measures recall.
- Produces: a recorded analyzer decision (prose-morphology recall vs exact-code recall) in the decisions doc.

- [ ] **Step 1: Curate the case set from real data**

Create `spikes/cases_ru.yaml` with 10–20 hand-labeled cases pulled from the projected corpus. Two required buckets:

```yaml
# spikes/cases_ru.yaml
prose:      # morphology matters: query in one grammatical form, answer text in another
  - query: "как рассчитывается премия сотрудника"
    expect_chunk_ids: ["<fill from corpus>"]
exact:      # codes/identifiers must match verbatim; stemming/stopwords can hurt
  - query: "ABC-123"
    expect_chunk_ids: ["<fill from corpus>"]
  - query: "табельный номер 4021"
    expect_chunk_ids: ["<fill from corpus>"]
```

Fill `expect_chunk_ids` by inspecting `fetch_chunks` output for chunks whose `fulltext` contains the target. This is manual labeling — keep it small but real.

- [ ] **Step 2: Write the analyzer harness**

```python
# spikes/run_analyzer_eval.py
"""Throwaway: compare Lucene analyzers on Russian prose vs exact-code recall.

For each analyzer, drop+recreate the TextChunk fulltext index with that analyzer,
run every case, and report recall@10 per bucket.
"""
import asyncio
import yaml
from pathlib import Path
from neo4j import AsyncGraphDatabase
from lore_retrieval.config import get_settings
from lore_retrieval.neo4j_spike import fulltext_search, _labels

ANALYZERS = ["standard", "standard-no-stop-words", "russian", "whitespace"]


async def recreate_ft_index(driver, database, index_version, analyzer):
    text_label, _ = _labels(index_version)
    name = f"ft_{text_label}"
    async with driver.session(database=database) as sess:
        await sess.run(f"DROP INDEX {name} IF EXISTS")
        await sess.run(
            f"""
            CREATE FULLTEXT INDEX {name} FOR (n:{text_label}) ON EACH [n.fulltext]
            OPTIONS {{ indexConfig: {{ `fulltext.analyzer`: $analyzer }} }}
            """,
            analyzer=analyzer,
        )
        # wait for the index to come online
        await sess.run(f"CALL db.awaitIndex($name, 120)", name=name)


def recall_at_k(hits: list[str], expected: list[str]) -> float:
    if not expected:
        return 0.0
    return len(set(hits) & set(expected)) / len(set(expected))


async def main():
    s = get_settings()
    cases = yaml.safe_load(Path(__file__).parent.joinpath("cases_ru.yaml").read_text())
    driver = AsyncGraphDatabase.driver(s.neo4j_uri, auth=(s.neo4j_user, s.neo4j_password))
    for analyzer in ANALYZERS:
        await recreate_ft_index(driver, s.neo4j_database, "spike1", analyzer)
        report = {}
        for bucket, items in cases.items():
            recalls = []
            for c in items:
                hits = [cid for cid, _ in await fulltext_search(
                    driver, s.neo4j_database, "spike1", c["query"], top_k=10)]
                recalls.append(recall_at_k(hits, c["expect_chunk_ids"]))
            report[bucket] = sum(recalls) / len(recalls) if recalls else 0.0
        print(f"analyzer={analyzer:24s} " + " ".join(f"{b}={r:.2f}" for b, r in report.items()))
    await driver.close()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 3: Run the harness**

Run:
```bash
cd lore-core/packages/lore-retrieval && uv run python spikes/run_analyzer_eval.py
```
Expected: one line per analyzer with `prose=` and `exact=` recall. Typical shape: `russian` wins prose, `whitespace`/`standard-no-stop-words` wins exact codes.

- [ ] **Step 4: Record the analyzer decision**

Append `## 2. Analyzer` to `docs/architecture/neo4j-p0-decisions.md`: the recall table, the chosen analyzer (or the decision to run a second exact-match sub-index if no single analyzer wins both), and any Lucene escaping needed for exact-code queries.

- [ ] **Step 5: Commit**

```bash
git add lore-core/packages/lore-retrieval/spikes/cases_ru.yaml lore-core/packages/lore-retrieval/spikes/run_analyzer_eval.py docs/architecture/neo4j-p0-decisions.md
git commit -m "spike(retrieval): evaluate Russian Lucene analyzers and record decision"
```

---

### Task 9: Latency at expected scale

**Files:**
- Create: `lore-core/packages/lore-retrieval/spikes/run_latency.py`
- Modify: `docs/architecture/neo4j-p0-decisions.md`

**Interfaces:**
- Consumes: projection + retrieval primitives (Tasks 6–7).
- Produces: recorded p50/p90 latency for vector, fulltext, and fused retrieval at a target corpus size.

- [ ] **Step 1: Write the latency harness**

```python
# spikes/run_latency.py
"""Throwaway: measure vector/fulltext/hybrid latency at scale."""
import asyncio
import time
import statistics
from neo4j import AsyncGraphDatabase
from lore_retrieval.config import get_settings
from lore_retrieval.embeddings import OllamaEmbeddingBackend, Neo4jGraphRagEmbedder
from lore_retrieval.neo4j_spike import vector_search, fulltext_search, rrf_fuse

QUERIES = [
    "как рассчитывается премия", "табельный номер сотрудника",
    "матрица грейдов", "отпускные выплаты", "структура подразделения",
]


async def timed(coro_factory, runs=20):
    lat = []
    for _ in range(runs):
        for q in QUERIES:
            t0 = time.perf_counter()
            await coro_factory(q)
            lat.append((time.perf_counter() - t0) * 1000)
    lat.sort()
    p50 = statistics.median(lat)
    p90 = lat[int(len(lat) * 0.9)]
    return p50, p90


async def main():
    s = get_settings()
    emb = Neo4jGraphRagEmbedder(OllamaEmbeddingBackend(s.embedding_model, s.ollama_base_url, s.embedding_dim))
    d = AsyncGraphDatabase.driver(s.neo4j_uri, auth=(s.neo4j_user, s.neo4j_password))

    async def vec(q): return await vector_search(d, s.neo4j_database, "spike1", q, emb, 50)
    async def ft(q): return await fulltext_search(d, s.neo4j_database, "spike1", q, 50)
    async def hybrid(q):
        v = await vec(q); f = await ft(q); return rrf_fuse([v, f])

    for name, fac in [("vector", vec), ("fulltext", ft), ("hybrid", hybrid)]:
        p50, p90 = await timed(fac)
        print(f"{name:9s} p50={p50:.1f}ms p90={p90:.1f}ms")
    await d.close()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Project a scale batch, then run latency**

Run (raise the `limit` in the Task 6 smoke to the largest available corpus first, e.g. `limit=5000`), then:
```bash
cd lore-core/packages/lore-retrieval && uv run python spikes/run_latency.py
```
Expected: three lines with p50/p90 in ms. Note whether the embedding call dominates hybrid latency (it queries Ollama per turn).

- [ ] **Step 3: Record latency findings**

Append `## 3. Latency` to `docs/architecture/neo4j-p0-decisions.md`: corpus size, p50/p90 per route, and whether latency is acceptable for an interactive turn (and whether query-embedding should be cached/warmed).

- [ ] **Step 4: Commit**

```bash
git add lore-core/packages/lore-retrieval/spikes/run_latency.py docs/architecture/neo4j-p0-decisions.md
git commit -m "spike(retrieval): measure vector/fulltext/hybrid latency at scale"
```

---

### Task 10: Identity & one-ready-version activation design doc

**Files:**
- Create: `docs/architecture/neo4j-identity-and-activation.md`
- Create: `lore-core/packages/lore-retrieval/src/lore_retrieval/ledger.py`
- Test: `lore-core/packages/lore-retrieval/tests/test_ledger.py`

**Interfaces:**
- Produces: `DerivedIndexRecord` (pydantic model) with the ledger fields from the spec; `LedgerStatus` enum (`pending|indexing|ready|failed|superseded`). Persistence is deferred to P1 — this task delivers the typed shape + the written activation design.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ledger.py
from lore_retrieval.ledger import DerivedIndexRecord, LedgerStatus


def test_record_defaults_to_pending():
    r = DerivedIndexRecord(
        run_id="r1", index_version="v3", chunk_schema_version="cs1",
        section_projection_version="sp1", embedding_model_version="bge-m3",
        fulltext_analyzer_version="russian", graph_schema_version="g1",
        neo4j_server_version="5.26", neo4j_graphrag_version="1.3",
        reranker_version="none",
    )
    assert r.status is LedgerStatus.pending


def test_status_accepts_terminal_values():
    assert LedgerStatus("ready") is LedgerStatus.ready
    assert LedgerStatus("superseded") is LedgerStatus.superseded
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd lore-core/packages/lore-retrieval && uv run pytest tests/test_ledger.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lore_retrieval.ledger'`

- [ ] **Step 3: Write the ledger model**

```python
# src/lore_retrieval/ledger.py
from enum import Enum
from pydantic import BaseModel


class LedgerStatus(str, Enum):
    pending = "pending"
    indexing = "indexing"
    ready = "ready"
    failed = "failed"
    superseded = "superseded"


class DerivedIndexRecord(BaseModel):
    run_id: str
    index_version: str
    chunk_schema_version: str
    section_projection_version: str
    embedding_model_version: str
    fulltext_analyzer_version: str
    graph_schema_version: str
    neo4j_server_version: str
    neo4j_graphrag_version: str
    reranker_version: str
    status: LedgerStatus = LedgerStatus.pending
    started_at: str | None = None
    completed_at: str | None = None
    error_summary: str | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd lore-core/packages/lore-retrieval && uv run pytest tests/test_ledger.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Write the activation design doc**

Create `docs/architecture/neo4j-identity-and-activation.md` covering, informed by the Task 5 probe result:
- **Derived identity:** `projection_id = index_version + ":" + canonical_id`; why `projection_id` filtering after native `top_k` is insufficient (inactive versions consume recall).
- **One-ready-version activation:** the chosen isolation shape — version-labeled indexes for Community (baseline) and/or separate databases for Enterprise; queries always target exactly one ready version.
- **Ledger:** the `DerivedIndexRecord` fields and lifecycle (`pending → indexing → ready`, previous stays `ready` until the new one passes, then `superseded`).
- **Rebuild / rollback / backup / restore:** build a complete projection before activation; keep the previous ready projection; atomic switch; restore path if Neo4j is lost (rebuild from `lore_core`).

- [ ] **Step 6: Commit**

```bash
git add lore-core/packages/lore-retrieval/src/lore_retrieval/ledger.py lore-core/packages/lore-retrieval/tests/test_ledger.py docs/architecture/neo4j-identity-and-activation.md
git commit -m "feat(retrieval): add derived-index ledger model and activation design doc"
```

---

### Task 11: P0 decision record & exit gate

**Files:**
- Modify: `docs/architecture/neo4j-p0-decisions.md`
- Modify: `docs/superpowers/specs/2026-07-21-neo4j-hybrid-rag-roadmap-design.md` (mark P0 done + link)

**Interfaces:**
- Consumes: findings from Tasks 5, 8, 9; observed dims from Task 3; capability from Task 5.
- Produces: the consolidated decision record that answers the P0 promotion questions and gates P1.

- [ ] **Step 1: Pin the exact dependency set**

Run:
```bash
cd lore-core/packages/lore-retrieval && uv lock && grep -E "^name = \"(neo4j|neo4j-graphrag|langchain-ollama)\"" -A1 uv.lock
```
Expected: exact resolved versions printed. Copy them into the decisions doc.

- [ ] **Step 2: Complete the decision record**

Ensure `docs/architecture/neo4j-p0-decisions.md` has all sections filled:
- `## 1. Neo4j capabilities` — edition, version, index support, multi-db (Task 5).
- `## 2. Analyzer` — recall table + chosen analyzer/strategy (Task 8).
- `## 3. Latency` — p50/p90 verdict (Task 9).
- `## 4. Pinned versions` — Neo4j server, driver, `neo4j-graphrag`, embedding model + observed dimension, reranker (deferred to P2 — record "none in P0").
- `## 5. Embedding model` — bge-m3 via Ollama, dimension confirmed from Task 3 Step 5, similarity = cosine.
- `## 6. Activation shape` — pointer to `neo4j-identity-and-activation.md`.
- `## 7. Promotion-question status` — a checklist mapping each P0-relevant promotion question from the roadmap to its answer or an explicit "deferred to P<n>".

- [ ] **Step 3: Mark P0 complete in the roadmap**

Edit `docs/superpowers/specs/2026-07-21-neo4j-hybrid-rag-roadmap-design.md`: in the P0 row/section, add `Status: DONE — see docs/architecture/neo4j-p0-decisions.md`.

- [ ] **Step 4: Run the full package test suite**

Run: `cd lore-core/packages/lore-retrieval && uv run pytest -v`
Expected: all unit tests pass (config, identity, embeddings, source, rrf, ledger).

- [ ] **Step 5: Commit**

```bash
git add docs/architecture/neo4j-p0-decisions.md docs/superpowers/specs/2026-07-21-neo4j-hybrid-rag-roadmap-design.md
git commit -m "docs(retrieval): consolidate P0 decision record and mark P0 complete"
```

---

## Self-Review

**Spec coverage (P0 scope of the roadmap):**
- Pin Neo4j/driver/graphrag/embedding/reranker versions → Tasks 1, 11 (reranker recorded as deferred to P2).
- Embedding model + batching decision → Tasks 3, 6 (batched embed), 11.
- Russian/multilingual analyzer decision → Task 8.
- Prove vector + fulltext + hybrid retrieval + latency at scale → Tasks 6, 7, 9.
- Derived identity (`projection_id`), ledger, one-ready-version activation/rebuild/rollback/backup/restore design → Tasks 2, 10.
- Neo4j capabilities / edition / activation isolation → Task 5, 10.
- Read-only `lore_core` access → Task 4.
- Answer the promotion questions → Task 11.

Deferred by design (not P0): the deterministic full Section/NEXT projection and its 8 invariants (P1), reranking (P2), auto-merging (P3), table lane/SQL (P4), Langfuse (P2), full eval matrix (P5). The spike uses a minimal `section_id` only; it does not build the Section graph.

**Placeholder scan:** `cases_ru.yaml` intentionally contains `<fill from corpus>` — this is a manual labeling step (Task 8 Step 1), not a code placeholder; the harness code and every implementation step are complete.

**Type consistency:** `SourceChunk`/`is_table` (Task 4) is consumed unchanged in Task 6; `_labels()`/`index_version` naming is identical across Tasks 6–9; `EmbeddingBackend.embed_documents`/`embed_query` (Task 3) match their call sites in Tasks 6–9; `DerivedIndexRecord` fields (Task 10) mirror the roadmap ledger list.
