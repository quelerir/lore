from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from lore_core_domain.redaction import redact_text, redact_value
from lore_core_domain.run_status import RunStatus
from lore_splitter.contracts import SourceFile

PROCESSING_SCHEMA_VERSION = "processing/v1"
DEFAULT_LEASE_SECONDS = 900
SAFE_METADATA_KEYS = frozenset(
    {
        "source_id",
        "stream",
        "file_id",
        "source_path",
        "object_path",
        "mime_type",
        "size_bytes",
        "created_at",
        "updated_at",
        "input_kind",
        "normalized_extension",
        "mime_family",
    }
)


class ClaimAction(StrEnum):
    NEW = "new"
    CACHE_HIT = "cache_hit"
    OVERWRITE = "overwrite"
    STALE_RECOVERY = "stale_recovery"


class ProcessingAlreadyActive(RuntimeError):
    retryable = True

    def __init__(self, file_key: str, run_id: str) -> None:
        self.file_key = file_key
        self.run_id = run_id
        super().__init__(f"processing already active: file={file_key} run={run_id}")


def _canonical(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str
    )


def sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def logical_file_key(source: SourceFile) -> str:
    return ":".join((source.source_id, source.stream, source.file_id))


def sanitize_metadata(source: SourceFile) -> tuple[dict[str, Any], tuple[str, ...]]:
    candidate = {**source.to_dict(), **source.metadata}
    safe = {key: value for key, value in candidate.items() if key in SAFE_METADATA_KEYS}
    dropped = tuple(sorted(set(candidate) - set(safe)))
    return redact_value(safe), dropped


@dataclass(frozen=True)
class ProcessingIdentity:
    logical_key: str
    source_content_hash: str
    config_hash: str
    operator_version: str
    chunk_schema_version: str

    @property
    def identity_hash(self) -> str:
        return sha256_json(self.to_dict())

    def to_dict(self) -> dict[str, str]:
        return {
            "logical_key": self.logical_key,
            "source_content_hash": self.source_content_hash,
            "config_hash": self.config_hash,
            "operator_version": self.operator_version,
            "chunk_schema_version": self.chunk_schema_version,
        }


def build_processing_identity(
    source: SourceFile,
    content_hash: str,
    config: dict[str, Any],
    *,
    operator_version: str,
    chunk_schema_version: str,
) -> ProcessingIdentity:
    return ProcessingIdentity(
        logical_file_key(source),
        content_hash,
        sha256_json(config),
        operator_version,
        chunk_schema_version,
    )


@dataclass(frozen=True)
class RunSnapshot:
    run_id: str
    identity: ProcessingIdentity
    status: RunStatus
    claimed_at: datetime
    lease_until: datetime
    current_success_run_id: str | None = None
    supersedes_run_id: str | None = None

    @property
    def lease_expired(self) -> bool:
        return self.lease_until <= datetime.now(UTC)


@dataclass(frozen=True)
class ClaimDecision:
    action: ClaimAction
    run_id: str | None
    supersedes_run_id: str | None = None
    stale_run_id: str | None = None
    reused: bool = False


def decide_claim(
    identity: ProcessingIdentity,
    existing: RunSnapshot | None,
    *,
    overwrite: bool = False,
    now: datetime | None = None,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
) -> ClaimDecision:
    now = now or datetime.now(UTC)
    if existing is None:
        return ClaimDecision(ClaimAction.NEW, str(uuid.uuid4()))
    if existing.identity.identity_hash != identity.identity_hash:
        return ClaimDecision(ClaimAction.NEW, str(uuid.uuid4()))
    if existing.status is RunStatus.SUCCESS and not overwrite:
        return ClaimDecision(ClaimAction.CACHE_HIT, existing.run_id, reused=True)
    if existing.status is RunStatus.ACTIVE and existing.lease_until > now:
        raise ProcessingAlreadyActive(identity.logical_key, existing.run_id)
    action = (
        ClaimAction.STALE_RECOVERY
        if existing.status is RunStatus.ACTIVE
        else ClaimAction.OVERWRITE
    )
    return ClaimDecision(
        action,
        str(uuid.uuid4()),
        supersedes_run_id=existing.current_success_run_id,
        stale_run_id=existing.run_id if action is ClaimAction.STALE_RECOVERY else None,
    )


@dataclass(frozen=True)
class Diagnostic:
    level: str
    code: str
    message: str
    stage: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "code": self.code,
            "message": redact_text(self.message),
            "stage": self.stage,
            "details": redact_value(self.details),
        }


@dataclass(frozen=True)
class RunResult:
    run_id: str
    status: RunStatus
    reused: bool = False
    supersedes_run_id: str | None = None
    chunk_count: int = 0
    payload_count: int = 0
    warning_count: int = 0
    error_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return redact_value(
            {
                "run_id": self.run_id,
                "status": self.status.value,
                "reused": self.reused,
                "supersedes_run_id": self.supersedes_run_id,
                "chunk_count": self.chunk_count,
                "payload_count": self.payload_count,
                "warning_count": self.warning_count,
                "error_count": self.error_count,
            }
        )
