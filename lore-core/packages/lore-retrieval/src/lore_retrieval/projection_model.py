"""Deterministic, Neo4j-independent structural projection.

Given the canonical chunks of one or more documents, derive the Section
hierarchy and NEXT adjacency as pure in-memory structures. This is the
algorithmic core of P1: it computes exactly what will be written to Neo4j
(Document/Section/Chunk + HAS_SECTION/HAS_SUBSECTION/HAS_CHUNK/NEXT) without
touching Neo4j, so the spec's projection invariants can be proven offline.

A chunk attaches to its deepest applicable section (the section whose
heading_path equals the chunk's full heading_path). Every heading-path prefix
becomes a Section; chunks with an empty heading_path attach to a synthetic
document-root section (heading_path == ()).
"""
from collections import defaultdict

from pydantic import BaseModel

from lore_retrieval.identity import section_id, section_prefixes
from lore_retrieval.source import SourceChunk


class Section(BaseModel):
    section_id: str
    document_id: str
    heading_path: tuple[str, ...]
    depth: int
    parent_section_id: str | None  # None => attaches to the Document (top-level or synthetic root)
    position: int  # deterministic order within the document
    chunk_ids: list[str]

    @property
    def is_synthetic_root(self) -> bool:
        return self.heading_path == ()


class StructuralProjection(BaseModel):
    sections: list[Section]
    chunk_section: dict[str, str]  # chunk_id -> section_id
    next_edges: list[tuple[str, str]]  # (from_chunk_id, to_chunk_id), consecutive within one document


def _section_paths(doc_chunks: list[SourceChunk]) -> set[tuple[str, ...]]:
    paths: set[tuple[str, ...]] = set()
    for c in doc_chunks:
        if c.heading_path:
            paths.update(section_prefixes(c.heading_path))
        else:
            paths.add(())  # synthetic document-root
    return paths


def _parent_of(path: tuple[str, ...], paths: set[tuple[str, ...]], doc_id: str) -> str | None:
    if not path:  # synthetic root -> Document
        return None
    parent_path = path[:-1]
    if parent_path == ():
        # depth-1 section: parent is the synthetic root only if one exists,
        # otherwise it is a top-level section attached to the Document.
        return section_id(doc_id, ()) if () in paths else None
    return section_id(doc_id, parent_path)


def build_structural_projection(chunks: list[SourceChunk]) -> StructuralProjection:
    by_doc: dict[str, list[SourceChunk]] = defaultdict(list)
    for c in chunks:
        by_doc[c.document_id].append(c)

    all_sections: list[Section] = []
    chunk_section: dict[str, str] = {}
    next_edges: list[tuple[str, str]] = []

    for doc_id, dchunks in by_doc.items():
        ordered = sorted(dchunks, key=lambda c: c.position)

        # NEXT: consecutive chunks within this document only.
        for a, b in zip(ordered, ordered[1:]):
            next_edges.append((a.chunk_id, b.chunk_id))

        paths = _section_paths(ordered)

        # Subtree-minimum position drives deterministic section ordering: a
        # section sorts by the earliest chunk anywhere beneath it.
        def subtree_min(path: tuple[str, ...]) -> int:
            depth = len(path)
            positions = [
                c.position
                for c in ordered
                if (c.heading_path[:depth] == path if depth else True)
            ]
            return min(positions) if positions else 1 << 30

        ordered_paths = sorted(paths, key=lambda p: (subtree_min(p), len(p), p))
        position_of = {p: i for i, p in enumerate(ordered_paths)}

        sections: dict[tuple[str, ...], Section] = {}
        for p in ordered_paths:
            sections[p] = Section(
                section_id=section_id(doc_id, p),
                document_id=doc_id,
                heading_path=p,
                depth=len(p),
                parent_section_id=_parent_of(p, paths, doc_id),
                position=position_of[p],
                chunk_ids=[],
            )

        # Attach each chunk to its deepest section (its full heading_path, or root).
        for c in ordered:
            key = c.heading_path if c.heading_path else ()
            sections[key].chunk_ids.append(c.chunk_id)
            chunk_section[c.chunk_id] = sections[key].section_id

        all_sections.extend(sections.values())

    return StructuralProjection(
        sections=all_sections, chunk_section=chunk_section, next_edges=next_edges
    )


def validate_projection(projection: StructuralProjection, chunks: list[SourceChunk]) -> bool:
    """Assert the spec's structural-projection invariants. Raises ValueError on violation."""
    chunk_by_id = {c.chunk_id: c for c in chunks}
    sections_by_id = {s.section_id: s for s in projection.sections}

    # Invariant 7: positions unique within a document.
    per_doc_positions: dict[str, set[int]] = defaultdict(set)
    for c in chunks:
        if c.position in per_doc_positions[c.document_id]:
            raise ValueError(f"positions must be unique within document {c.document_id}")
        per_doc_positions[c.document_id].add(c.position)

    # Invariant 2 + 6: exactly one section per (document, heading_path).
    seen: set[tuple[str, tuple[str, ...]]] = set()
    for s in projection.sections:
        key = (s.document_id, s.heading_path)
        if key in seen:
            raise ValueError(f"duplicate section for {key}")
        seen.add(key)

    for s in projection.sections:
        # Invariant 3: parent is the section one heading-prefix shorter.
        if s.parent_section_id is not None:
            parent = sections_by_id.get(s.parent_section_id)
            if parent is None:
                raise ValueError(f"section {s.section_id} references unknown parent")
            if parent.document_id != s.document_id:
                raise ValueError("parent/child edge crosses a document boundary")
            if parent.heading_path != s.heading_path[:-1]:
                raise ValueError("parent edge does not reproduce heading-prefix order")

        # Invariant 1 + 4: members belong to this document and this exact section path.
        for cid in s.chunk_ids:
            c = chunk_by_id[cid]
            if c.document_id != s.document_id:
                raise ValueError("chunk assigned across a document boundary")
            expected = c.heading_path if c.heading_path else ()
            if expected != s.heading_path:
                raise ValueError("section contains a structurally incompatible chunk")

    # Invariant 1 + 7: NEXT edges stay within one document and follow order.
    for a, b in projection.next_edges:
        if chunk_by_id[a].document_id != chunk_by_id[b].document_id:
            raise ValueError("NEXT edge crosses a document boundary")
        if chunk_by_id[a].position >= chunk_by_id[b].position:
            raise ValueError("NEXT edge is not forward-ordered by position")

    # Invariant 8: every table_payload chunk is retained as its own member.
    for c in chunks:
        if c.is_table and projection.chunk_section.get(c.chunk_id) is None:
            raise ValueError(f"table anchor {c.chunk_id} was dropped from the projection")

    return True
