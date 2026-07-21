"""Immutable bounded values accepted and returned by the pure audit engine."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from lore_audit.contracts import AuditLifecycleResult, AuditSnapshot, LifecycleOutcome, RuleResult
from lore_audit.validation import canonicalize_safe_json, safe_json_to_dict, validate_target_id

AUDIT_V1 = "audit/v1"
EMPTY_DOMAIN_TARGET_ID = "__audit_empty_domain__"
MAX_BOUNDED_STRING = 256

_SHA256 = re.compile(r"[0-9a-f]{64}", re.ASCII)
_PHYSICAL_IDENTITY_KEYS = {
    "postgres": frozenset({"schema_name", "table_name"}),
    "s3": frozenset({"bucket", "object_key"}),
}
_REGISTRATION_KEYS = {
    "table": frozenset(
        {
            "schema_name",
            "table_name",
            "row_count",
            "column_count",
            "columns",
            "source_kind",
            "source_checksum",
            "source_location",
            "profile_signature",
        }
    ),
    "image": frozenset(
        {
            "bucket",
            "object_key",
            "content_type",
            "extension",
            "byte_size",
            "checksum_sha256",
            "source_kind",
            "source_checksum",
            "source_location",
            "width",
            "height",
            "dimensions",
        }
    ),
}
_METADATA_KEYS = frozenset(
    {
        "columns",
        "row_count",
        "column_count",
        "source_kind",
        "source_checksum",
        "source_location",
        "sheet",
        "range",
        "content_type",
        "extension",
        "byte_size",
        "checksum_sha256",
        "width",
        "height",
        "dimensions",
    }
)
_SUMMARY_KEYS = frozenset(
    {"profile_signature", "row_count", "column_count", "columns", "warnings", "statistics"}
)


def _non_empty_string(value: Any, name: str, *, max_length: int = MAX_BOUNDED_STRING) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if not value or len(value) > max_length:
        raise ValueError(f"{name} length is outside the allowed range")


def _non_negative(value: Any, name: str, *, positive: bool = False) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an integer")
    if value < (1 if positive else 0):
        qualifier = "positive" if positive else "non-negative"
        raise ValueError(f"{name} must be {qualifier}")


def _allowlisted_mapping(
    value: Any,
    allowed: frozenset[str],
    name: str,
    *,
    preserved_sha256_fields: frozenset[str] = frozenset(),
) -> Any:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a mapping")
    unsupported = sorted(set(value) - allowed)
    if unsupported:
        raise ValueError(f"{name} contains unsupported fields: {', '.join(unsupported)}")
    generic_values = dict(value)
    preserved = {}
    for field_name in preserved_sha256_fields:
        if field_name not in generic_values:
            continue
        field_value = generic_values.pop(field_name)
        if not isinstance(field_value, str):
            raise TypeError(f"{field_name} must be a string")
        if _SHA256.fullmatch(field_value) is None:
            raise ValueError(f"{field_name} must be a lowercase 64-hex SHA-256")
        preserved[field_name] = field_value
    canonical = canonicalize_safe_json(generic_values)
    if not preserved:
        return canonical
    return type(canonical)(sorted((*canonical, *preserved.items())))


def _optional_sha256(value: Any, name: str) -> None:
    if value is not None and (not isinstance(value, str) or _SHA256.fullmatch(value) is None):
        raise ValueError(f"{name} must be a lowercase 64-hex SHA-256")


@dataclass(frozen=True)
class ChunkTokenFact:
    chunk_id: str
    tokenizer_id: str
    vector_token_count: int
    vector_hard_limit: int

    def __post_init__(self) -> None:
        validate_target_id(self.chunk_id)
        _non_empty_string(self.tokenizer_id, "tokenizer_id")
        _non_negative(self.vector_token_count, "vector_token_count")
        _non_negative(self.vector_hard_limit, "vector_hard_limit", positive=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "tokenizer_id": self.tokenizer_id,
            "vector_token_count": self.vector_token_count,
            "vector_hard_limit": self.vector_hard_limit,
        }


@dataclass(frozen=True)
class PhysicalResolution:
    storage_kind: str
    resolved: bool
    identity: Any = field(default_factory=dict)
    checksum_sha256: str | None = None
    byte_size: int | None = None
    content_type: str | None = None

    def __post_init__(self) -> None:
        if self.storage_kind not in _PHYSICAL_IDENTITY_KEYS:
            raise ValueError("storage_kind must be postgres or s3")
        if not isinstance(self.resolved, bool):
            raise TypeError("resolved must be a boolean")
        identity = _allowlisted_mapping(
            self.identity, _PHYSICAL_IDENTITY_KEYS[self.storage_kind], "physical identity"
        )
        _optional_sha256(self.checksum_sha256, "checksum_sha256")
        if self.byte_size is not None:
            _non_negative(self.byte_size, "byte_size")
        if self.content_type is not None:
            _non_empty_string(self.content_type, "content_type")
        object.__setattr__(self, "identity", identity)

    def to_dict(self) -> dict[str, Any]:
        return {
            "storage_kind": self.storage_kind,
            "resolved": self.resolved,
            "identity": safe_json_to_dict(self.identity),
            "checksum_sha256": self.checksum_sha256,
            "byte_size": self.byte_size,
            "content_type": self.content_type,
        }


@dataclass(frozen=True)
class PayloadResolutionFact:
    payload_id: str
    kind: str
    registered: bool
    occurrence_count: int
    registration_identity: Any = field(default_factory=dict)
    physical: PhysicalResolution | None = None
    metadata: Any = field(default_factory=dict)
    summary: Any = field(default_factory=dict)

    def __post_init__(self) -> None:
        validate_target_id(self.payload_id)
        if self.kind not in _REGISTRATION_KEYS:
            raise ValueError("payload kind must be table or image")
        if not isinstance(self.registered, bool):
            raise TypeError("registered must be a boolean")
        _non_negative(self.occurrence_count, "occurrence_count")
        registration = _allowlisted_mapping(
            self.registration_identity,
            _REGISTRATION_KEYS[self.kind],
            "registration_identity",
            preserved_sha256_fields=(
                frozenset({"profile_signature"})
                if self.kind == "table"
                else frozenset()
            ),
        )
        metadata = _allowlisted_mapping(self.metadata, _METADATA_KEYS, "metadata")
        summary = _allowlisted_mapping(
            self.summary,
            _SUMMARY_KEYS,
            "summary",
            preserved_sha256_fields=(
                frozenset({"profile_signature"})
                if self.kind == "table"
                else frozenset()
            ),
        )
        if self.physical is not None:
            if not isinstance(self.physical, PhysicalResolution):
                raise TypeError("physical must be a PhysicalResolution")
            expected_storage = "postgres" if self.kind == "table" else "s3"
            if self.physical.storage_kind != expected_storage:
                raise ValueError("payload kind is incompatible with physical storage")
        # Occurrences may exist before registration, but registration-derived
        # identities and physical resolution cannot be trusted in that state.
        if not self.registered and (registration or self.physical is not None):
            raise ValueError(
                "unregistered payload must not contain registration or physical evidence"
            )
        object.__setattr__(self, "registration_identity", registration)
        object.__setattr__(self, "metadata", metadata)
        object.__setattr__(self, "summary", summary)

    def to_dict(self) -> dict[str, Any]:
        return {
            "payload_id": self.payload_id,
            "kind": self.kind,
            "registered": self.registered,
            "occurrence_count": self.occurrence_count,
            "registration_identity": safe_json_to_dict(self.registration_identity),
            "physical": self.physical.to_dict() if self.physical is not None else None,
            "metadata": safe_json_to_dict(self.metadata),
            "summary": safe_json_to_dict(self.summary),
        }


@dataclass(frozen=True)
class AuditEngineInput:
    snapshot: AuditSnapshot
    ruleset_version: str
    token_facts: tuple[ChunkTokenFact, ...] = ()
    payload_facts: tuple[PayloadResolutionFact, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot, AuditSnapshot):
            raise TypeError("snapshot must be an AuditSnapshot")
        if self.ruleset_version != AUDIT_V1 or self.snapshot.ruleset_version != AUDIT_V1:
            raise ValueError("engine input supports exact audit/v1 only")
        tokens = self._typed_tuple(self.token_facts, ChunkTokenFact, "token_facts")
        payloads = self._typed_tuple(
            self.payload_facts, PayloadResolutionFact, "payload_facts"
        )
        self._reject_duplicates((item.chunk_id for item in tokens), "token fact identity")
        self._reject_duplicates(
            ((item.kind, item.payload_id) for item in payloads), "payload fact identity"
        )
        actual_ids = (
            self.snapshot.run.run_id,
            *(item.chunk_id for item in self.snapshot.chunks),
            *(item.payload_id for item in self.snapshot.payload_occurrences),
            *(item.payload_id for item in payloads),
        )
        for target_id in actual_ids:
            validate_target_id(target_id)
            if target_id == EMPTY_DOMAIN_TARGET_ID:
                raise ValueError("actual target identity collides with reserved empty-domain id")
        object.__setattr__(self, "token_facts", tuple(sorted(tokens, key=lambda item: item.chunk_id)))
        object.__setattr__(
            self, "payload_facts", tuple(sorted(payloads, key=lambda item: (item.kind, item.payload_id)))
        )

    @staticmethod
    def _typed_tuple(values: Any, item_type: type, name: str) -> tuple[Any, ...]:
        try:
            items = tuple(values)
        except TypeError as exc:
            raise TypeError(f"{name} must be iterable") from exc
        if any(not isinstance(item, item_type) for item in items):
            raise TypeError(f"{name} contains an invalid value")
        return items

    @staticmethod
    def _reject_duplicates(values: Any, name: str) -> None:
        items = tuple(values)
        if len(items) != len(set(items)):
            raise ValueError(f"duplicate {name}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot": self.snapshot.to_dict(),
            "ruleset_version": self.ruleset_version,
            "token_facts": [item.to_dict() for item in self.token_facts],
            "payload_facts": [item.to_dict() for item in self.payload_facts],
        }


@dataclass(frozen=True)
class AuditEngineResult:
    results: tuple[RuleResult, ...]
    lifecycle: AuditLifecycleResult

    def __post_init__(self) -> None:
        try:
            results = tuple(self.results)
        except TypeError as exc:
            raise TypeError("results must be iterable") from exc
        if any(not isinstance(item, RuleResult) for item in results):
            raise TypeError("results must contain RuleResult values")
        if not isinstance(self.lifecycle, AuditLifecycleResult):
            raise TypeError("lifecycle must be an AuditLifecycleResult")
        identities = tuple(
            (item.rule_id, item.target.kind, item.target.target_id) for item in results
        )
        if len(identities) != len(set(identities)):
            raise ValueError("duplicate rule result identity")
        if any(item.ruleset_version != self.lifecycle.ruleset_version for item in results):
            raise ValueError("result ruleset does not match lifecycle ruleset")
        if self.lifecycle.outcome is LifecycleOutcome.COMPLETED:
            if self.lifecycle.checked_rule_count != len(results):
                raise ValueError("completed lifecycle count does not match results")
        elif results:
            raise ValueError("non-completed lifecycle cannot carry rule results")
        object.__setattr__(self, "results", results)

    def to_dict(self) -> dict[str, Any]:
        return {
            "results": [item.to_dict() for item in self.results],
            "lifecycle": self.lifecycle.to_dict(),
        }


__all__ = [
    "AuditEngineInput",
    "AuditEngineResult",
    "ChunkTokenFact",
    "PayloadResolutionFact",
    "PhysicalResolution",
]
