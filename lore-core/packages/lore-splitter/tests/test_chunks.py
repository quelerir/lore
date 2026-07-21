from dataclasses import FrozenInstanceError

import pytest
from lore_splitter.chunks import (
    ChunkBudget,
    ChunkCoordinates,
    ChunkValidationError,
    PayloadRef,
    build_chunk,
    normalize_text,
    validate_chunk,
)


def test_chunk_identity_is_run_scoped_but_content_signature_is_not():
    coordinates = ChunkCoordinates(heading_path=("Policy",), page=2)
    ref = PayloadRef("payload-1", "table", 0)
    display = f"# Policy\nBody {ref.compact()}\n"
    first = build_chunk(
        run_id="run-a",
        file_id="file-a",
        ordinal=0,
        pipeline_type="markdown",
        chunk_type="text",
        display_text=display,
        vector_text="# Policy\nBody\n",
        fulltext="# Policy\nBody\n",
        coordinates=coordinates,
        payload_refs=(ref,),
    )
    second = build_chunk(
        run_id="run-b",
        file_id="file-b",
        ordinal=0,
        pipeline_type="markdown",
        chunk_type="text",
        display_text=display,
        vector_text="# Policy\nBody\n",
        fulltext="# Policy\nBody\n",
        coordinates=coordinates,
        payload_refs=(ref,),
    )
    assert first.chunk_id != second.chunk_id
    assert first.content_signature == second.content_signature
    assert first.vector_hash == second.vector_hash
    assert first.fulltext_hash == second.fulltext_hash


def test_normalization_preserves_meaningful_whitespace():
    assert normalize_text("e\u0301  x\r\ny") == "é  x\ny\n"


def test_payload_refs_are_compact_and_chunk_is_frozen():
    ref = PayloadRef("p1", "image", 3)
    assert ref.to_dict() == {"payload_id": "p1", "kind": "image", "occurrence_ordinal": 3}
    with pytest.raises(FrozenInstanceError):
        ref.payload_id = "other"


def test_builder_splits_and_repeats_heading_context():
    chunks = build_chunk(
        run_id="run-a",
        file_id="file-a",
        ordinal=0,
        pipeline_type="markdown",
        chunk_type="text",
        display_text="# Heading\n\nFirst sentence. Second sentence.\n\nThird paragraph.",
        vector_text="# Heading\n\nFirst sentence. Second sentence.\n\nThird paragraph.",
        fulltext="# Heading\n\nFirst sentence. Second sentence.\n\nThird paragraph.",
        coordinates=ChunkCoordinates(heading_path=("Heading",)),
        budget=ChunkBudget(max_vector_chars=35, max_fulltext_chars=35),
    )
    assert len(chunks) > 1
    assert all(chunk.vector_text.startswith("# Heading\n") for chunk in chunks)
    assert all(chunk.fulltext.startswith("# Heading\n") for chunk in chunks)


def test_validator_rejects_invalid_boundaries_without_mutating_candidate():
    chunk = build_chunk(
        run_id="run-a",
        file_id="file-a",
        ordinal=0,
        pipeline_type="markdown",
        chunk_type="text",
        display_text="Body",
        vector_text="Body",
        fulltext="Body",
    )
    original = chunk.to_dict()
    with pytest.raises(ChunkValidationError, match="invalid_ordinal"):
        validate_chunk(chunk, ordinal=-1)
    assert chunk.to_dict() == original
