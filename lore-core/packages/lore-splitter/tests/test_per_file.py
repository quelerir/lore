from datetime import UTC, datetime, timedelta

import pytest
from lore_splitter.contracts import SourceFile
from lore_splitter.per_file import (
    ClaimAction,
    ProcessingAlreadyActive,
    RunSnapshot,
    RunStatus,
    build_processing_identity,
    decide_claim,
    logical_file_key,
    sanitize_metadata,
)


def source(**overrides):
    values = dict(
        source_id="drive",
        stream="files",
        file_id="42",
        source_path="docs/a.md",
        object_path="docs/a.md",
        mime_type="text/markdown",
        size_bytes=10,
        metadata={"secret": "do-not-store", "owner": "alice"},
    )
    values.update(overrides)
    return SourceFile(**values)


def identity(**overrides):
    item = source(**overrides)
    return build_processing_identity(
        item, "content-hash", {"limit": 10}, operator_version="op/1", chunk_schema_version="chunk/1"
    )


def test_logical_key_is_composite_and_metadata_is_allowlisted():
    item = source()
    safe, dropped = sanitize_metadata(item)
    assert logical_file_key(item) == "drive:files:42"
    assert "owner" in dropped and "secret" in dropped
    assert "secret" not in safe


def test_identity_is_deterministic_and_content_sensitive():
    assert identity().identity_hash == identity().identity_hash
    assert identity().identity_hash != identity(file_id="43").identity_hash


def test_cache_hit_does_not_create_new_run():
    current = RunSnapshot(
        "run-1",
        identity(),
        RunStatus.SUCCESS,
        datetime.now(UTC),
        datetime.now(UTC),
    )
    decision = decide_claim(current.identity, current)
    assert decision.action is ClaimAction.CACHE_HIT
    assert decision.run_id == "run-1" and decision.reused


def test_active_duplicate_fails_fast_with_safe_identifiers():
    now = datetime.now(UTC)
    current = RunSnapshot("run-1", identity(), RunStatus.ACTIVE, now, now + timedelta(minutes=5))
    with pytest.raises(ProcessingAlreadyActive, match="drive:files:42") as exc:
        decide_claim(current.identity, current, now=now)
    assert "secret" not in str(exc.value)


def test_expired_claim_gets_new_run_and_marks_stale():
    now = datetime.now(UTC)
    current = RunSnapshot(
        "run-1",
        identity(),
        RunStatus.ACTIVE,
        now - timedelta(hours=1),
        now - timedelta(minutes=1),
        current_success_run_id="run-0",
    )
    decision = decide_claim(current.identity, current, now=now)
    assert decision.action is ClaimAction.STALE_RECOVERY
    assert decision.run_id != "run-1" and decision.stale_run_id == "run-1"


def test_overwrite_supersedes_prior_success():
    now = datetime.now(UTC)
    current = RunSnapshot(
        "run-1", identity(), RunStatus.SUCCESS, now, now, current_success_run_id="run-1"
    )
    decision = decide_claim(current.identity, current, overwrite=True, now=now)
    assert decision.action is ClaimAction.OVERWRITE
    assert decision.supersedes_run_id == "run-1"
