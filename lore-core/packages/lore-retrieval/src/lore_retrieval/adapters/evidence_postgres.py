"""CanonicalEvidenceResolver over the lore_core Postgres read side.

``rows_to_resolution`` is the pure verification/mapping core (unit-tested);
``PostgresEvidenceResolver`` is the thin asyncpg wrapper (live-verified once a
loreagent_test DSN is available). Physical/version checks that depend on the
derived-index ledger (active run set, expected hashes) are optional inputs so
this works before the ledger is wired.
"""
from lore_retrieval.contracts import EvidenceEnvelope, ResolutionResult
from lore_retrieval.source import _as_json


def rows_to_resolution(
    rows_by_id: dict[str, dict],
    requested_ids: list[str],
    index_version: str,
    *,
    active_run_ids: set[str] | None = None,
    expected_hash: dict[str, str] | None = None,
) -> ResolutionResult:
    resolved: list[EvidenceEnvelope] = []
    rejected: list[tuple[str, str]] = []
    for cid in requested_ids:
        row = rows_by_id.get(cid)
        if row is None:
            rejected.append((cid, "missing"))
            continue
        if active_run_ids is not None and row["run_id"] not in active_run_ids:
            rejected.append((cid, "wrong_version"))
            continue
        if expected_hash and cid in expected_hash and expected_hash[cid] != row["fulltext_hash"]:
            rejected.append((cid, "hash_mismatch"))
            continue
        resolved.append(
            EvidenceEnvelope(
                chunk_id=cid,
                fulltext=row["fulltext"],
                display_text=row.get("display_text") or row["fulltext"],
                coordinates=_as_json(row.get("coordinates"), {}),
                payload_refs=_as_json(row.get("payload_refs"), []),
                run_id=row["run_id"],
                index_version=index_version,
                fulltext_hash=row["fulltext_hash"],
            )
        )
    return ResolutionResult(resolved=resolved, rejected=rejected)


class PostgresEvidenceResolver:
    # NOTE: the real version gate is ``active_run_ids`` (from the derived-index
    # ledger, wired in P1). ``index_version`` is only stamped onto the envelope
    # here — unlike ``InMemoryEvidenceResolver`` it does not by itself reject a
    # stale version. Callers must pass the active run set to enforce versioning.
    def __init__(
        self,
        dsn: str,
        *,
        active_run_ids: set[str] | None = None,
        expected_hash: dict[str, str] | None = None,
    ) -> None:
        self._dsn = dsn
        self._active_run_ids = active_run_ids
        self._expected_hash = expected_hash

    async def resolve(self, chunk_ids: list[str], *, index_version: str) -> ResolutionResult:
        import asyncpg

        conn = await asyncpg.connect(self._dsn, statement_cache_size=0)  # pgbouncer-safe
        try:
            async with conn.transaction(readonly=True):
                rows = await conn.fetch(
                    """
                    SELECT chunk_id, run_id::text AS run_id, fulltext, display_text,
                           coordinates, payload_refs, fulltext_hash
                    FROM lore_core.chunks
                    WHERE chunk_id = ANY($1::text[])
                    """,
                    chunk_ids,
                )
        finally:
            await conn.close()

        rows_by_id = {r["chunk_id"]: dict(r) for r in rows}
        return rows_to_resolution(
            rows_by_id,
            chunk_ids,
            index_version,
            active_run_ids=self._active_run_ids,
            expected_hash=self._expected_hash,
        )
