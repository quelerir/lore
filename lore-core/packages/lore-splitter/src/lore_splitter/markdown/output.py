from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from lore_splitter.documents.contracts import (
    DocumentImageExtractionResult,
    DocumentMarkdownResult,
    ImageToastCandidate,
    ImageToastOccurrence,
)
from lore_splitter.markdown.contracts import (
    DocumentOutputBundle,
    RunOutputManifest,
    TableData,
    TableProfile,
    ToastDecision,
    WorkbookOutputBundle,
)
from lore_splitter.markdown.render import render_workbook_markdown
from lore_splitter.markdown.table_markdown import MarkdownTableOccurrence
from lore_splitter.markdown.toast import CLASSIFICATION_SKIPPED
from lore_core_domain.storage_contracts import (
    ImageToastStorageResult,
    TableToastStorageResult,
)
from lore_splitter.xlsx.contracts import WorkbookExtraction

StorageResultKey = tuple[str, str | None, int | None, str | None]
OutputBundle = WorkbookOutputBundle | DocumentOutputBundle


@dataclass(frozen=True)
class MetadataConfig:
    embedding_byte_budget: int = 4096
    max_embedding_unique_values: int = 3


def build_workbook_output_bundle(
    output_dir: Path,
    workbook: WorkbookExtraction,
    tables: tuple[TableData, ...],
    profiles: tuple[TableProfile, ...],
    decisions: tuple[ToastDecision, ...],
    *,
    sheet_scalar_text: Mapping[str, Sequence[str]] | None = None,
    metadata_config: MetadataConfig | None = None,
) -> WorkbookOutputBundle:
    bundle_id = _workbook_bundle_id(workbook)
    base_path = Path(output_dir) / bundle_id
    markdown = render_workbook_markdown(
        workbook,
        tables,
        profiles,
        decisions,
        sheet_scalar_text=sheet_scalar_text,
    )
    embedding_metadata = build_embedding_metadata(
        workbook,
        tables,
        profiles,
        decisions,
        config=metadata_config,
    )
    full_metadata = build_full_metadata(workbook, tables, profiles, decisions)
    return WorkbookOutputBundle(
        bundle_id=bundle_id,
        markdown_path=base_path.with_suffix(".md"),
        embedding_metadata_path=Path(f"{base_path}.embedding.json"),
        full_metadata_path=Path(f"{base_path}.full.json"),
        markdown=markdown,
        embedding_metadata=embedding_metadata,
        full_metadata=full_metadata,
    )


def write_workbook_outputs(
    output_dir: Path,
    workbook: WorkbookExtraction,
    tables: tuple[TableData, ...],
    profiles: tuple[TableProfile, ...],
    decisions: tuple[ToastDecision, ...],
    *,
    sheet_scalar_text: Mapping[str, Sequence[str]] | None = None,
    metadata_config: MetadataConfig | None = None,
) -> WorkbookOutputBundle:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    bundle = build_workbook_output_bundle(
        output_path,
        workbook,
        tables,
        profiles,
        decisions,
        sheet_scalar_text=sheet_scalar_text,
        metadata_config=metadata_config,
    )
    bundle.markdown_path.write_text(bundle.markdown, encoding="utf-8")
    _write_json(bundle.embedding_metadata_path, bundle.embedding_metadata)
    _write_json(bundle.full_metadata_path, bundle.full_metadata)
    return bundle


def build_document_output_bundle(
    output_dir: Path,
    document: DocumentMarkdownResult,
    *,
    tables: tuple[TableData, ...] = (),
    profiles: tuple[TableProfile, ...] = (),
    decisions: tuple[ToastDecision, ...] = (),
    occurrences: tuple[MarkdownTableOccurrence, ...] = (),
    image_extraction: DocumentImageExtractionResult | None = None,
    image_storage_results: tuple[ImageToastStorageResult, ...] = (),
) -> DocumentOutputBundle:
    bundle_id = _document_bundle_id(document)
    base_path = Path(output_dir) / bundle_id
    markdown = _insert_image_toast_markers(document.markdown, image_extraction)
    output_document = replace(document, markdown=markdown)
    embedding_metadata = build_document_embedding_metadata(
        output_document,
        tables=tables,
        profiles=profiles,
        decisions=decisions,
        occurrences=occurrences,
        image_extraction=image_extraction,
    )
    full_metadata = build_document_full_metadata(
        output_document,
        tables=tables,
        profiles=profiles,
        decisions=decisions,
        occurrences=occurrences,
        image_extraction=image_extraction,
        image_storage_results=image_storage_results,
    )
    return DocumentOutputBundle(
        bundle_id=bundle_id,
        markdown_path=base_path.with_suffix(".md"),
        embedding_metadata_path=Path(f"{base_path}.embedding.json"),
        full_metadata_path=Path(f"{base_path}.full.json"),
        markdown=markdown,
        embedding_metadata=embedding_metadata,
        full_metadata=full_metadata,
    )


def write_document_outputs(
    output_dir: Path,
    document: DocumentMarkdownResult,
    *,
    tables: tuple[TableData, ...] = (),
    profiles: tuple[TableProfile, ...] = (),
    decisions: tuple[ToastDecision, ...] = (),
    occurrences: tuple[MarkdownTableOccurrence, ...] = (),
    image_extraction: DocumentImageExtractionResult | None = None,
    image_storage_results: tuple[ImageToastStorageResult, ...] = (),
) -> DocumentOutputBundle:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    bundle = build_document_output_bundle(
        output_path,
        document,
        tables=tables,
        profiles=profiles,
        decisions=decisions,
        occurrences=occurrences,
        image_extraction=image_extraction,
        image_storage_results=image_storage_results,
    )
    bundle.markdown_path.write_text(bundle.markdown, encoding="utf-8")
    _write_json(bundle.embedding_metadata_path, bundle.embedding_metadata)
    _write_json(bundle.full_metadata_path, bundle.full_metadata)
    return bundle


def write_run_manifest(
    output_dir: Path,
    bundles: tuple[OutputBundle, ...],
    *,
    storage_results_by_toast_id: Mapping[str | StorageResultKey, TableToastStorageResult]
    | None = None,
    image_storage_results: tuple[ImageToastStorageResult, ...] = (),
) -> RunOutputManifest:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    manifest_path = output_path / "run_manifest.json"
    manifest = RunOutputManifest(
        manifest_path=manifest_path,
        bundles=tuple(
            _manifest_bundle_entry(
                bundle,
                storage_results_by_toast_id=storage_results_by_toast_id,
                image_storage_results=image_storage_results,
            )
            for bundle in bundles
        ),
    )
    _write_json(manifest_path, manifest.to_dict())
    return manifest


def build_document_embedding_metadata(
    document: DocumentMarkdownResult,
    *,
    tables: tuple[TableData, ...] = (),
    profiles: tuple[TableProfile, ...] = (),
    decisions: tuple[ToastDecision, ...] = (),
    occurrences: tuple[MarkdownTableOccurrence, ...] = (),
    image_extraction: DocumentImageExtractionResult | None = None,
) -> dict[str, Any]:
    structure_signals = dict(document.structure_signals or {})
    document_entry: dict[str, Any] = {
        "source": document.source_identity,
        "document_format": document.document_format,
        "document_checksum": document.document_checksum,
        "warnings": list(document.warnings),
        "text_stats": _document_text_stats(document.markdown),
    }
    title = structure_signals.get("title")
    if title:
        document_entry["title"] = title
    headings = structure_signals.get("headings")
    if headings:
        document_entry["headings"] = list(headings)
    metadata: dict[str, Any] = {"document": document_entry}
    table_entries = [
        _document_embedding_table_entry(group)
        for group in _document_table_groups(tables, profiles, decisions, occurrences)
    ]
    if table_entries:
        metadata["tables"] = table_entries
    image_entries = _document_embedding_image_entries(document, image_extraction)
    if image_entries:
        metadata["images"] = image_entries
    return metadata


def build_document_full_metadata(
    document: DocumentMarkdownResult,
    *,
    tables: tuple[TableData, ...] = (),
    profiles: tuple[TableProfile, ...] = (),
    decisions: tuple[ToastDecision, ...] = (),
    occurrences: tuple[MarkdownTableOccurrence, ...] = (),
    image_extraction: DocumentImageExtractionResult | None = None,
    image_storage_results: tuple[ImageToastStorageResult, ...] = (),
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "document": {
            "source": document.source.to_dict(),
            "source_identity": document.source_identity,
            "local_path": document.local_path,
            "normalized_extension": document.normalized_extension,
            "document_format": document.document_format,
            "document_checksum": document.document_checksum,
            "warnings": list(document.warnings),
            "diagnostics": [diagnostic.to_dict() for diagnostic in document.diagnostics],
            "structure_signals": dict(document.structure_signals or {}),
            "text_stats": _document_text_stats(document.markdown),
        }
    }
    table_entries = [
        _document_full_table_entry(group)
        for group in _document_table_groups(tables, profiles, decisions, occurrences)
    ]
    if table_entries:
        metadata["tables"] = table_entries
    image_entries = _document_full_image_entries(
        document,
        image_extraction,
        image_storage_results=image_storage_results,
    )
    if image_entries:
        metadata["images"] = image_entries
    skipped_images = _document_skipped_image_entries(image_extraction)
    if skipped_images:
        metadata["skipped_images"] = skipped_images
    if image_extraction is not None:
        if image_extraction.warnings:
            metadata["image_warnings"] = sorted(image_extraction.warnings)
        if image_extraction.diagnostics:
            metadata["image_diagnostics"] = [
                diagnostic.to_dict() for diagnostic in image_extraction.diagnostics
            ]
    return metadata


def build_embedding_metadata(
    workbook: WorkbookExtraction,
    tables: tuple[TableData, ...],
    profiles: tuple[TableProfile, ...],
    decisions: tuple[ToastDecision, ...],
    *,
    config: MetadataConfig | None = None,
) -> dict[str, Any]:
    active_config = config or MetadataConfig()
    metadata: dict[str, Any] = {
        "workbook": _workbook_core(workbook),
        "tables": [
            _embedding_table_core(table, profile, decision)
            for table, profile, decision in zip(tables, profiles, decisions, strict=True)
        ],
    }

    optional_steps = (
        lambda payload: _add_inferred_types(payload, profiles),
        lambda payload: _add_aggregates(payload, profiles),
        lambda payload: _add_unique_values(payload, profiles, active_config),
        lambda payload: _add_semantic_hints(payload, profiles),
        lambda payload: _add_content_signatures(payload, decisions),
        lambda payload: _add_decision_reasons(payload, decisions),
    )
    for step in optional_steps:
        candidate = _copy_metadata(metadata)
        step(candidate)
        if len(metadata_json_bytes(candidate)) <= active_config.embedding_byte_budget:
            metadata = candidate
    return metadata


def build_full_metadata(
    workbook: WorkbookExtraction,
    tables: tuple[TableData, ...],
    profiles: tuple[TableProfile, ...],
    decisions: tuple[ToastDecision, ...],
) -> dict[str, Any]:
    table_entries = [
        _full_table_entry(table, profile, decision)
        for table, profile, decision in zip(tables, profiles, decisions, strict=True)
    ]
    skipped_fragments = [
        _skipped_fragment(entry)
        for entry in table_entries
        if entry["classification"] == CLASSIFICATION_SKIPPED
    ]
    return {
        "workbook": workbook.to_dict(),
        "tables": table_entries,
        "skipped_fragments": skipped_fragments,
        "diagnostics": [
            {
                "reason": "skipped_fragment",
                "message": (
                    f"Skipped decorative fragment on {fragment['sheet']['name']} "
                    f"{fragment['range']['a1_range']}"
                ),
                "source": fragment["source"],
                "sheet": fragment["sheet"],
                "range": fragment["range"],
                "warnings": fragment["warnings"],
            }
            for fragment in skipped_fragments
        ],
    }


def metadata_json_bytes(metadata: dict[str, Any]) -> bytes:
    return json.dumps(
        metadata,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _workbook_bundle_id(workbook: WorkbookExtraction) -> str:
    payload = {
        "source": workbook.source_file.identity_dict(),
        "workbook_checksum": workbook.workbook_checksum,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"wb_{hashlib.sha256(encoded).hexdigest()[:20]}"


def _document_bundle_id(document: DocumentMarkdownResult) -> str:
    payload = {
        "source": document.source_identity,
        "document_checksum": document.document_checksum,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"doc_{hashlib.sha256(encoded).hexdigest()[:20]}"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(metadata_json_bytes(payload).decode("utf-8") + "\n", encoding="utf-8")


def _manifest_bundle_entry(
    bundle: OutputBundle,
    *,
    storage_results_by_toast_id: Mapping[str | StorageResultKey, TableToastStorageResult]
    | None = None,
    image_storage_results: tuple[ImageToastStorageResult, ...] = (),
) -> dict[str, Any]:
    if isinstance(bundle, DocumentOutputBundle):
        return _document_manifest_bundle_entry(
            bundle,
            storage_results_by_toast_id=storage_results_by_toast_id,
            image_storage_results=image_storage_results,
        )
    return _workbook_manifest_bundle_entry(
        bundle,
        storage_results_by_toast_id=storage_results_by_toast_id,
    )


def _workbook_manifest_bundle_entry(
    bundle: WorkbookOutputBundle,
    *,
    storage_results_by_toast_id: Mapping[str | StorageResultKey, TableToastStorageResult]
    | None = None,
) -> dict[str, Any]:
    full_metadata = bundle.full_metadata
    tables = full_metadata["tables"]
    classification_counts = Counter(table["classification"] for table in tables)
    warnings = sorted({warning for table in tables for warning in table.get("warnings", [])})
    toast_ids = [table["toast_id"] for table in tables if table.get("toast_id") is not None]
    entry = {
        "kind": "workbook",
        "bundle_id": bundle.bundle_id,
        "paths": {
            "markdown": str(bundle.markdown_path),
            "embedding_metadata": str(bundle.embedding_metadata_path),
            "full_metadata": str(bundle.full_metadata_path),
        },
        "source": full_metadata["workbook"]["source_file"]
        if "source_file" in full_metadata["workbook"]
        else bundle.embedding_metadata["workbook"]["source"],
        "workbook_checksum": full_metadata["workbook"]["workbook_checksum"],
        "toast_ids": toast_ids,
        "classification_counts": dict(sorted(classification_counts.items())),
        "warnings": warnings,
        "diagnostics": full_metadata["diagnostics"],
        "metadata_paths": {
            "embedding": str(bundle.embedding_metadata_path),
            "full": str(bundle.full_metadata_path),
        },
        "content_signatures": [table["content_signature"] for table in tables],
    }
    storage_entries = _storage_entries(tables, storage_results_by_toast_id)
    if storage_entries:
        entry["storage"] = storage_entries
    return entry


def _document_manifest_bundle_entry(
    bundle: DocumentOutputBundle,
    *,
    storage_results_by_toast_id: Mapping[str | StorageResultKey, TableToastStorageResult]
    | None = None,
    image_storage_results: tuple[ImageToastStorageResult, ...] = (),
) -> dict[str, Any]:
    document = bundle.full_metadata["document"]
    tables = bundle.full_metadata.get("tables", [])
    images = bundle.full_metadata.get("images", [])
    skipped_images = bundle.full_metadata.get("skipped_images", [])
    classification_counts = Counter(table["classification"] for table in tables)
    warnings = sorted(
        {
            warning
            for warning in document["warnings"]
            for warning in (warning,)
        }
        | {warning for table in tables for warning in table.get("warnings", [])}
    )
    toast_ids = [table["toast_id"] for table in tables if table.get("toast_id") is not None]
    image_toast_ids = [image["toast_id"] for image in images if image.get("toast_id")]
    entry = {
        "kind": "document",
        "bundle_id": bundle.bundle_id,
        "paths": {
            "markdown": str(bundle.markdown_path),
            "embedding_metadata": str(bundle.embedding_metadata_path),
            "full_metadata": str(bundle.full_metadata_path),
        },
        "source": document["source_identity"],
        "document_checksum": document["document_checksum"],
        "document_format": document["document_format"],
        "warnings": warnings,
        "diagnostics": document["diagnostics"],
        "metadata_paths": {
            "embedding": str(bundle.embedding_metadata_path),
            "full": str(bundle.full_metadata_path),
        },
    }
    if tables:
        entry["toast_ids"] = toast_ids
        entry["table_toast_ids"] = toast_ids
        entry["classification_counts"] = dict(sorted(classification_counts.items()))
        entry["table_counts"] = dict(sorted(classification_counts.items()))
        entry["content_signatures"] = [table["content_signature"] for table in tables]
        storage_entries = _storage_entries(tables, storage_results_by_toast_id)
        if storage_entries:
            entry["storage"] = storage_entries
    if images or skipped_images:
        entry["image_toast_ids"] = image_toast_ids
        entry["image_counts"] = _manifest_image_counts(
            images,
            skipped_images,
            image_storage_results,
        )
        skipped_reasons = Counter(image["reason"] for image in skipped_images)
        entry["skipped_image_reasons"] = dict(sorted(skipped_reasons.items()))
    return entry


def _document_text_stats(markdown: str) -> dict[str, int]:
    text = markdown.rstrip("\n")
    return {
        "characters": len(text),
        "lines": len(text.splitlines()) if text else 0,
    }


def _insert_image_toast_markers(
    markdown: str,
    image_extraction: DocumentImageExtractionResult | None,
) -> str:
    if image_extraction is None or not image_extraction.unique_candidates:
        return markdown

    lines = markdown.rstrip("\n").splitlines()
    if not lines:
        return markdown

    insertions: dict[int, list[str]] = {}
    for candidate in sorted(image_extraction.unique_candidates, key=lambda item: item.toast_id):
        for occurrence in candidate.occurrences:
            line_index = _image_marker_line_index(lines, occurrence)
            insertions.setdefault(line_index, []).append(f"[TOAST: {candidate.toast_id}]")

    output_lines: list[str] = []
    for index, line in enumerate(lines):
        output_lines.append(line)
        markers = insertions.get(index, [])
        if markers and line.strip():
            output_lines.append("")
        output_lines.extend(markers)
    return "\n".join(output_lines) + ("\n" if markdown.endswith("\n") else "")


def _image_marker_line_index(lines: list[str], occurrence: ImageToastOccurrence) -> int:
    location = occurrence.source_location
    metadata = dict(location.metadata or {})
    anchor = metadata.get("inline_anchor")
    if isinstance(anchor, str) and anchor:
        for index, line in enumerate(lines):
            if anchor in line:
                return index

    heading = metadata.get("heading")
    if isinstance(heading, str) and heading:
        normalized_heading = heading.strip()
        for index, line in enumerate(lines):
            stripped = line.strip()
            if stripped.lstrip("#").strip() == normalized_heading:
                return index

    line_start = metadata.get("line_start")
    if isinstance(line_start, int) and line_start > 0:
        return min(line_start - 1, len(lines) - 1)

    return len(lines) - 1


def _document_table_groups(
    tables: tuple[TableData, ...],
    profiles: tuple[TableProfile, ...],
    decisions: tuple[ToastDecision, ...],
    occurrences: tuple[MarkdownTableOccurrence, ...],
) -> list[dict[str, Any]]:
    if not tables:
        return []

    grouped: dict[str, dict[str, Any]] = {}
    for table, profile, decision in zip(tables, profiles, decisions, strict=True):
        key = decision.content_signature
        grouped.setdefault(
            key,
            {
                "table": table,
                "profile": profile,
                "decision": decision,
                "locations": [],
                "formats": [],
            },
        )

    if occurrences:
        for occurrence in occurrences:
            if occurrence.decision is None or occurrence.table is None:
                continue
            key = occurrence.decision.content_signature
            group = grouped.get(key)
            if group is None:
                continue
            group["locations"].append(occurrence.location.to_dict())
            group["formats"].append(occurrence.table_format)
    else:
        for table, decision in zip(tables, decisions, strict=True):
            if table.markdown is not None:
                group = grouped[decision.content_signature]
                group["locations"].append(table.markdown.to_dict())

    for group in grouped.values():
        group["locations"] = _dedupe_dicts(group["locations"])
        group["formats"] = tuple(dict.fromkeys(group["formats"]))
    return list(grouped.values())


def _document_image_groups(
    image_extraction: DocumentImageExtractionResult | None,
) -> list[dict[str, Any]]:
    if image_extraction is None:
        return []

    groups: dict[str, dict[str, Any]] = {}
    for candidate in image_extraction.unique_candidates:
        group = groups.setdefault(
            candidate.toast_id,
            {
                "candidate": candidate,
                "locations": [],
            },
        )
        group["locations"].extend(occurrence.to_dict() for occurrence in candidate.occurrences)

    for group in groups.values():
        group["locations"] = _dedupe_dicts(group["locations"])
    return [groups[key] for key in sorted(groups)]


def _dedupe_dicts(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        key = json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _document_embedding_image_entries(
    document: DocumentMarkdownResult,
    image_extraction: DocumentImageExtractionResult | None,
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for group in _document_image_groups(image_extraction):
        candidate: ImageToastCandidate = group["candidate"]
        locations: list[dict[str, Any]] = group["locations"]
        entry = {
            "toast_id": candidate.toast_id,
            "source_kind": "document",
            "source_checksum": document.document_checksum,
            "first_location": locations[0]["source_location"]
            if locations
            else candidate.source_location.to_dict(),
            "occurrence_count": len(locations) or 1,
            "dimensions": {
                "width_px": candidate.width_px,
                "height_px": candidate.height_px,
            },
            "content_type": candidate.content_type,
            "warnings": list(candidate.warnings),
        }
        entries.append(entry)
    return entries


def _document_full_image_entries(
    document: DocumentMarkdownResult,
    image_extraction: DocumentImageExtractionResult | None,
    *,
    image_storage_results: tuple[ImageToastStorageResult, ...],
) -> list[dict[str, Any]]:
    storage_by_toast_id = {
        result.toast_id: result
        for result in sorted(image_storage_results, key=lambda item: item.toast_id)
    }
    entries: list[dict[str, Any]] = []
    for group in _document_image_groups(image_extraction):
        candidate: ImageToastCandidate = group["candidate"]
        entry = {
            "toast_id": candidate.toast_id,
            "content_type": candidate.content_type,
            "extension": candidate.extension,
            "byte_size": candidate.byte_size,
            "checksum_sha256": candidate.checksum_sha256,
            "source": dict(candidate.source_identity),
            "source_kind": "document",
            "source_checksum": document.document_checksum,
            "source_location": candidate.source_location.to_dict(),
            "dimensions": {
                "width_px": candidate.width_px,
                "height_px": candidate.height_px,
            },
            "warnings": list(candidate.warnings),
            "diagnostics": list(candidate.diagnostics),
            "locations": group["locations"],
        }
        storage_result = storage_by_toast_id.get(candidate.toast_id)
        if storage_result is not None:
            entry["storage"] = storage_result.to_dict()
        entries.append(entry)
    return entries


def _document_skipped_image_entries(
    image_extraction: DocumentImageExtractionResult | None,
) -> list[dict[str, Any]]:
    if image_extraction is None:
        return []
    entries: list[dict[str, Any]] = []
    for skip in image_extraction.skips:
        candidate = skip.candidate
        entries.append(
            {
                "toast_id": candidate.toast_id,
                "reason": skip.reason,
                "diagnostics": list(skip.diagnostics),
                "content_type": candidate.content_type,
                "extension": candidate.extension,
                "byte_size": candidate.byte_size,
                "checksum_sha256": candidate.checksum_sha256,
                "dimensions": {
                    "width_px": candidate.width_px,
                    "height_px": candidate.height_px,
                },
                "source": dict(candidate.source_identity),
                "source_location": candidate.source_location.to_dict(),
                "warnings": list(candidate.warnings),
            }
        )
    return sorted(entries, key=lambda item: (item["reason"], item["toast_id"]))


def _manifest_image_counts(
    images: list[dict[str, Any]],
    skipped_images: list[dict[str, Any]],
    image_storage_results: tuple[ImageToastStorageResult, ...],
) -> dict[str, int]:
    image_toast_ids = {image["toast_id"] for image in images if image.get("toast_id")}
    matching_storage = [
        result for result in image_storage_results if result.toast_id in image_toast_ids
    ]
    return {
        "stored": sum(1 for result in matching_storage if result.action != "failed"),
        "failed_storage": sum(1 for result in matching_storage if result.action == "failed"),
        "skipped": len(skipped_images),
        "unique": len(image_toast_ids),
        "occurrences": sum(len(image.get("locations", ())) or 1 for image in images),
    }


def _document_embedding_table_entry(group: dict[str, Any]) -> dict[str, Any]:
    table: TableData = group["table"]
    profile: TableProfile = group["profile"]
    decision: ToastDecision = group["decision"]
    locations: list[dict[str, Any]] = group["locations"]
    entry = {
        "classification": decision.classification,
        "toast_id": decision.toast_id,
        "source": table.source_file.identity_dict(),
        "source_kind": table.source_kind,
        "source_checksum": table.source_checksum,
        "dimensions": {
            "rows": profile.row_count,
            "columns": profile.column_count,
            "cells": profile.cell_count,
        },
        "columns": list(table.columns),
        "warnings": list(_combined_warnings(profile, decision)),
        "content_signature": decision.content_signature,
        "occurrence_count": len(locations) or 1,
    }
    if locations:
        entry["first_location"] = locations[0]
    if group["formats"]:
        entry["table_formats"] = list(group["formats"])
    return entry


def _document_full_table_entry(group: dict[str, Any]) -> dict[str, Any]:
    table: TableData = group["table"]
    profile: TableProfile = group["profile"]
    decision: ToastDecision = group["decision"]
    locations: list[dict[str, Any]] = group["locations"]
    entry = {
        "classification": decision.classification,
        "toast_id": decision.toast_id,
        "source": table.source_file.identity_dict(),
        "local_path": str(table.local_path),
        "source_kind": table.source_kind,
        "source_checksum": table.source_checksum,
        "table_index": table.table_index,
        "columns": list(table.columns),
        "profile": profile.to_dict(),
        "decision": decision.to_dict(),
        "content_signature": decision.content_signature,
        "warnings": list(_combined_warnings(profile, decision)),
        "locations": locations,
    }
    if locations:
        entry["first_location"] = locations[0]
    if group["formats"]:
        entry["table_formats"] = list(group["formats"])
    return entry


def _storage_entries(
    tables: list[dict[str, Any]],
    storage_results_by_toast_id: Mapping[str | StorageResultKey, TableToastStorageResult] | None,
) -> list[dict[str, Any]]:
    if not storage_results_by_toast_id:
        return []
    entries: list[dict[str, Any]] = []
    for table in tables:
        result = _storage_result_for_table(table, storage_results_by_toast_id)
        if result is not None:
            entries.append(result.to_manifest_entry())
    return entries


def _storage_result_for_table(
    table: dict[str, Any],
    storage_results: Mapping[str | StorageResultKey, TableToastStorageResult],
) -> TableToastStorageResult | None:
    toast_id = table.get("toast_id")
    if toast_id is None:
        return None
    key = _storage_result_key(table)
    result = storage_results.get(key)
    if result is None:
        result = storage_results.get(toast_id)
    if result is None or not _storage_result_matches_table(result, table):
        return None
    return result


def _storage_result_key(table: dict[str, Any]) -> StorageResultKey:
    return (
        table["toast_id"],
        table.get("source_checksum") or table.get("workbook_checksum"),
        table.get("sheet", {}).get("index") or table.get("first_location", {}).get("table_index"),
        table.get("range", {}).get("a1_range")
        or _markdown_location_key(table.get("first_location")),
    )


def _storage_result_matches_table(
    result: TableToastStorageResult,
    table: dict[str, Any],
) -> bool:
    if table.get("source_kind") == "document":
        return (
            result.toast_id == table.get("toast_id")
            and (result.source_kind in {None, "document"})
            and result.source_checksum in {None, table.get("source_checksum")}
        )
    return (
        result.toast_id == table.get("toast_id")
        and result.workbook_checksum == table.get("workbook_checksum")
        and result.sheet == table.get("sheet")
        and result.range == table.get("range")
    )


def _markdown_location_key(location: dict[str, Any] | None) -> str | None:
    if not location:
        return None
    return f"L{location['line_start']}:L{location['line_end']}"


def _workbook_core(workbook: WorkbookExtraction) -> dict[str, Any]:
    return {
        "source": workbook.source_file.identity_dict(),
        "workbook_checksum": workbook.workbook_checksum,
    }


def _embedding_table_core(
    table: TableData,
    profile: TableProfile,
    decision: ToastDecision,
) -> dict[str, Any]:
    return {
        "classification": decision.classification,
        "toast_id": decision.toast_id,
        "source": table.source_file.identity_dict(),
        "workbook_checksum": table.workbook_checksum,
        "sheet": {"name": table.sheet_name, "index": table.sheet_index},
        "range": table.range.to_dict(),
        "dimensions": {
            "rows": profile.row_count,
            "columns": profile.column_count,
            "cells": profile.cell_count,
        },
        "columns": list(table.columns),
        "warnings": list(_combined_warnings(profile, decision)),
    }


def _full_table_entry(
    table: TableData,
    profile: TableProfile,
    decision: ToastDecision,
) -> dict[str, Any]:
    return {
        "classification": decision.classification,
        "toast_id": decision.toast_id,
        "source": table.source_file.identity_dict(),
        "local_path": str(table.local_path),
        "workbook_checksum": table.workbook_checksum,
        "sheet": {"name": table.sheet_name, "index": table.sheet_index},
        "range": table.range.to_dict(),
        "columns": list(table.columns),
        "profile": profile.to_dict(),
        "decision": decision.to_dict(),
        "content_signature": decision.content_signature,
        "warnings": list(_combined_warnings(profile, decision)),
    }


def _skipped_fragment(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": entry["source"],
        "sheet": entry["sheet"],
        "range": entry["range"],
        "columns": entry["columns"],
        "content_signature": entry["content_signature"],
        "reasons": entry["decision"]["reasons"],
        "warnings": entry["warnings"],
    }


def _combined_warnings(
    profile: TableProfile,
    decision: ToastDecision,
) -> tuple[str, ...]:
    return tuple(dict.fromkeys((*profile.warnings, *decision.warnings)))


def _add_inferred_types(metadata: dict[str, Any], profiles: tuple[TableProfile, ...]) -> None:
    for table_entry, profile in zip(metadata["tables"], profiles, strict=True):
        table_entry["inferred_types"] = {
            column.name: column.inferred_type for column in profile.column_profiles
        }


def _add_aggregates(metadata: dict[str, Any], profiles: tuple[TableProfile, ...]) -> None:
    for table_entry, profile in zip(metadata["tables"], profiles, strict=True):
        aggregates = {}
        for column in profile.column_profiles:
            if column.min_value is not None or column.max_value is not None:
                aggregates[column.name] = {"min": column.min_value, "max": column.max_value}
        if aggregates:
            table_entry["aggregates"] = aggregates


def _add_unique_values(
    metadata: dict[str, Any],
    profiles: tuple[TableProfile, ...],
    config: MetadataConfig,
) -> None:
    for table_entry, profile in zip(metadata["tables"], profiles, strict=True):
        uniques = {
            column.name: list(column.unique_values[: config.max_embedding_unique_values])
            for column in profile.column_profiles
            if column.unique_values
        }
        if uniques:
            table_entry["unique_values"] = uniques


def _add_semantic_hints(metadata: dict[str, Any], profiles: tuple[TableProfile, ...]) -> None:
    for table_entry, profile in zip(metadata["tables"], profiles, strict=True):
        hints = {
            column.name: list(column.semantic_hints)
            for column in profile.column_profiles
            if column.semantic_hints
        }
        if hints:
            table_entry["semantic_hints"] = hints


def _add_content_signatures(
    metadata: dict[str, Any],
    decisions: tuple[ToastDecision, ...],
) -> None:
    for table_entry, decision in zip(metadata["tables"], decisions, strict=True):
        table_entry["content_signature"] = decision.content_signature


def _add_decision_reasons(
    metadata: dict[str, Any],
    decisions: tuple[ToastDecision, ...],
) -> None:
    for table_entry, decision in zip(metadata["tables"], decisions, strict=True):
        if decision.reasons:
            table_entry["decision_reasons"] = list(decision.reasons)


def _copy_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return json.loads(metadata_json_bytes(metadata).decode("utf-8"))
