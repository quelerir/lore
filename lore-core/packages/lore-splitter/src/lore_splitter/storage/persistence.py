"""Payload-first persistence coordinator."""
from collections.abc import Mapping
from typing import Any

from lore_audit.registration import build_payload_registration
from lore_audit.validation import canonicalize_safe_json, safe_json_to_dict
from lore_splitter.chunks import Chunk, validate_chunk
from lore_splitter.per_file import Diagnostic, RunStatus


class PersistenceCoordinator:
    def __init__(
        self, repository: Any, *, table_store: Any = None, object_store: Any = None
    ) -> None:
        self.repository = repository
        self.table_store = table_store
        self.object_store = object_store

    def persist(
        self,
        run_id: str,
        chunks: list[Chunk],
        payloads: list[dict[str, Any]],
        *,
        logical_file_key: str,
        diagnostics: list[Diagnostic] | None = None,
        status: RunStatus = RunStatus.SUCCESS,
    ) -> Any:
        if status is not RunStatus.SUCCESS and (chunks or payloads):
            raise ValueError("non-success terminal outcome cannot contain durable data")
        terminal_diagnostics = list(diagnostics or [])
        for chunk in chunks:
            validate_chunk(chunk)
        verified: list[dict[str, Any]] = []
        for payload in payloads:
            store = self.table_store if payload.get("kind") == "table" else self.object_store
            if store is None:
                raise ValueError("required payload store is missing")
            method = store.store_table if payload.get("kind") == "table" else store.store_object
            result = method(payload["plan"])
            if getattr(result, "action", "failed") in {"failed", "collision"}:
                raise ValueError("payload storage failed")
            registration = build_payload_registration(payload, result)
            original_metadata = payload.get("metadata", {})
            if not isinstance(original_metadata, Mapping):
                raise ValueError("invalid payload audit registration")
            try:
                bounded_metadata = safe_json_to_dict(
                    canonicalize_safe_json(original_metadata)
                )
                bounded_coordinates = safe_json_to_dict(
                    canonicalize_safe_json(payload.get("coordinates", {}))
                )
            except (TypeError, ValueError):
                raise ValueError("invalid payload audit registration") from None
            verified.append(
                {
                    "verified": True,
                    "payload_id": payload["payload_id"],
                    "occurrence_ordinal": payload["occurrence_ordinal"],
                    "kind": payload["kind"],
                    "storage_identity": payload.get("storage_identity", payload["payload_id"]),
                    "content_hash": payload.get("content_hash", ""),
                    "coordinates": bounded_coordinates,
                    "occurrence_metadata": bounded_metadata,
                    "metadata": {
                        **bounded_metadata,
                        "audit_registration": registration,
                    },
                }
            )
        rows = [chunk.to_dict() for chunk in chunks]
        return self.repository.finalize_persisted(
            run_id,
            logical_file_key=logical_file_key,
            chunks=rows,
            payloads=verified,
            diagnostics=terminal_diagnostics,
            counts={
                "chunk_count": len(chunks),
                "payload_count": len(verified),
                "warning_count": sum(
                    item.level == "warning" for item in terminal_diagnostics
                ),
                "error_count": sum(
                    item.level == "error" for item in terminal_diagnostics
                ),
            },
            status=status,
        )
