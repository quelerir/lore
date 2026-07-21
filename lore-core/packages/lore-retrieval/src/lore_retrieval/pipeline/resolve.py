"""Canonical evidence resolution stage.

Batch-resolves final canonical envelopes for the selected chunk ids and drops
any that fail verification (missing / wrong-version / superseded / hash
mismatch). Rejected chunks cannot contribute evidence downstream.
"""
from lore_retrieval.contracts import ResolutionResult
from lore_retrieval.interfaces import CanonicalEvidenceResolver


async def resolve_evidence(
    resolver: CanonicalEvidenceResolver,
    chunk_ids: list[str],
    *,
    index_version: str = "spike1",
) -> ResolutionResult:
    return await resolver.resolve(chunk_ids, index_version=index_version)
