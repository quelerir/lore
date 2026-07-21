from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from lore_splitter.contracts import ManifestDiagnostic
from lore_splitter.documents import (
    DocumentImageExtractionResult,
    DocumentInputArtifact,
    DocumentMarkdownResult,
    ImageSkip,
    ImageToastCandidate,
    ImageToastOccurrence,
    build_image_storage_plans,
    convert_document_inputs,
    extract_document_images,
    route_document_inputs,
)
from lore_splitter.manifest import ManifestError, load_manifest
from lore_splitter.markdown.contracts import (
    TableData,
    TableProfile,
    ToastDecision,
    WorkbookOutputBundle,
)
from lore_splitter.markdown.output import (
    MetadataConfig,
    write_document_outputs,
    write_run_manifest,
    write_workbook_outputs,
)
from lore_splitter.markdown.profile import profile_table
from lore_splitter.markdown.table_data import extract_table_data
from lore_splitter.markdown.table_markdown import (
    MarkdownTableExtractionResult,
    extract_markdown_document_tables,
)
from lore_splitter.markdown.toast import ToastThresholds, classify_table
from lore_splitter.resolver import resolve_manifest
from lore_core_domain.storage_contracts import (
    ImageToastStorageResult,
    TableToastStorageResult,
)
from lore_splitter.storage.fake import FakeObjectToastStore, FakeTableToastStore
from lore_splitter.storage.object_schema import image_object_key
from lore_splitter.storage.schema import (
    DEFAULT_TOAST_SCHEMA,
    build_table_storage_plan,
)
from lore_splitter.xlsx import extract_workbooks


class PipelineRunError(RuntimeError):
    """Raised when the end-to-end Splitter runner cannot complete."""

    def __init__(
        self,
        message: str,
        *,
        result: PipelineResult | None = None,
        diagnostics: tuple[ManifestDiagnostic, ...] = (),
    ) -> None:
        super().__init__(message)
        self.result = result
        self.diagnostics = diagnostics


@dataclass(frozen=True)
class PipelineConfig:
    manifest_path: Path
    input_root: Path
    output_dir: Path
    storage_mode: str = "dry_run"
    embedding_byte_budget: int = 4096
    max_embedding_unique_values: int = 3
    toast_min_rows: int = 40
    toast_min_columns: int = 8
    toast_min_cells: int = 240
    storage_schema: str = DEFAULT_TOAST_SCHEMA
    image_toast_bucket: str = "splitter-image-toast"
    image_toast_prefix: str = "image-toast"
    table_store: Any | None = field(default=None, repr=False, compare=False)
    object_store: Any | None = field(default=None, repr=False, compare=False)


@dataclass(frozen=True)
class PipelineResult:
    processed_files: int
    skipped_files: int
    workbook_count: int
    document_count: int
    extracted_table_count: int
    toast_table_count: int
    inline_table_count: int
    warning_count: int
    error_count: int
    artifact_paths: dict[str, Any]
    bundles: tuple[WorkbookOutputBundle, ...]
    diagnostics: tuple[ManifestDiagnostic, ...]
    storage_results: tuple[TableToastStorageResult, ...] = ()
    storage_result_count: int = 0
    failed_storage_result_count: int = 0
    image_candidate_count: int = 0
    image_toast_count: int = 0
    skipped_image_count: int = 0
    image_storage_result_count: int = 0
    failed_image_storage_result_count: int = 0
    image_extraction_result: DocumentImageExtractionResult | None = None
    image_storage_results: tuple[ImageToastStorageResult, ...] = ()

    def to_summary_dict(self) -> dict[str, Any]:
        return {
            "processed_files": self.processed_files,
            "skipped_files": self.skipped_files,
            "workbook_count": self.workbook_count,
            "document_count": self.document_count,
            "extracted_table_count": self.extracted_table_count,
            "toast_table_count": self.toast_table_count,
            "inline_table_count": self.inline_table_count,
            "warning_count": self.warning_count,
            "error_count": self.error_count,
            "storage_result_count": self.storage_result_count,
            "failed_storage_result_count": self.failed_storage_result_count,
            "image_candidate_count": self.image_candidate_count,
            "image_toast_count": self.image_toast_count,
            "skipped_image_count": self.skipped_image_count,
            "image_storage_result_count": self.image_storage_result_count,
            "failed_image_storage_result_count": self.failed_image_storage_result_count,
            "artifact_paths": self.artifact_paths,
        }


def run(config_or_kwargs: PipelineConfig | None = None, **kwargs: Any) -> PipelineResult:
    config = _coerce_config(config_or_kwargs, kwargs)
    if config.storage_mode not in {"dry_run", "postgres"}:
        raise PipelineRunError("storage_mode must be 'dry_run' or 'postgres'")
    if config.storage_mode == "postgres" and config.table_store is None:
        raise PipelineRunError("postgres storage mode requires a table_store")

    try:
        manifest = load_manifest(config.manifest_path)
        resolved = resolve_manifest(manifest, config.input_root)
        workbook_inputs = tuple(
            resolved_input
            for resolved_input in resolved.processable
            if resolved_input.input_kind == "workbook"
        )
        document_inputs = tuple(
            resolved_input
            for resolved_input in resolved.processable
            if resolved_input.input_kind == "document"
        )
        document_routing = route_document_inputs(document_inputs)
        document_artifact_path = _write_document_inputs_artifact(
            config.output_dir,
            document_routing.documents,
        )
        thresholds = ToastThresholds(
            max_inline_rows=config.toast_min_rows,
            max_inline_columns=config.toast_min_columns,
            max_inline_cells=config.toast_min_cells,
        )
        document_conversion = convert_document_inputs(document_routing.documents)
        image_extraction = extract_document_images(document_conversion.documents)
        markdown_table_extraction = extract_markdown_document_tables(
            document_conversion.documents,
            thresholds=thresholds,
        )
        extraction = extract_workbooks(workbook_inputs)
        table_extraction = extract_table_data(extraction.workbooks)
        tables_by_workbook = _tables_by_workbook(table_extraction.tables)
        profiles: list[TableProfile] = []
        decisions: list[ToastDecision] = []

        for table in table_extraction.tables:
            profile = profile_table(table)
            profiles.append(profile)
            decisions.append(classify_table(table, profile, thresholds=thresholds))

        storage_results = _store_toast_tables(
            config,
            (*table_extraction.tables, *markdown_table_extraction.unique_tables),
            (*tuple(profiles), *_unique_markdown_profiles(markdown_table_extraction)),
            (*tuple(decisions), *_unique_markdown_decisions(markdown_table_extraction)),
        )
        image_storage_results = _store_toast_images(config, image_extraction)
        storage_results_by_key = _storage_result_lookup(storage_results)
        profile_groups = _profiles_by_workbook(table_extraction.tables, tuple(profiles))
        decision_groups = _decisions_by_workbook(table_extraction.tables, tuple(decisions))
        metadata_config = MetadataConfig(
            embedding_byte_budget=config.embedding_byte_budget,
            max_embedding_unique_values=config.max_embedding_unique_values,
        )
        bundles = tuple(
            write_workbook_outputs(
                config.output_dir,
                workbook,
                tables_by_workbook.get(workbook.workbook_checksum, ()),
                profile_groups.get(workbook.workbook_checksum, ()),
                decision_groups.get(workbook.workbook_checksum, ()),
                metadata_config=metadata_config,
            )
            for workbook in extraction.workbooks
        )
        document_bundles = tuple(
            write_document_outputs(
                config.output_dir,
                document,
                tables=_markdown_tables_for_document(markdown_table_extraction, document),
                profiles=_markdown_profiles_for_document(markdown_table_extraction, document),
                decisions=_markdown_decisions_for_document(markdown_table_extraction, document),
                occurrences=_markdown_occurrences_for_document(markdown_table_extraction, document),
                image_extraction=_image_extraction_for_document(image_extraction, document),
                image_storage_results=image_storage_results,
            )
            for document in markdown_table_extraction.documents
        )
        run_manifest = write_run_manifest(
            config.output_dir,
            (*bundles, *document_bundles),
            storage_results_by_toast_id=storage_results_by_key,
            image_storage_results=image_storage_results,
        )
    except ManifestError as exc:
        raise PipelineRunError(str(exc)) from exc
    except OSError as exc:
        raise PipelineRunError(f"Could not write pipeline artifacts: {exc}") from exc
    except ValueError as exc:
        raise PipelineRunError(str(exc)) from exc

    diagnostics = (
        *manifest.diagnostics,
        *resolved.diagnostics,
        *document_routing.diagnostics,
        *document_conversion.diagnostics,
        *image_extraction.diagnostics,
        *markdown_table_extraction.diagnostics,
        *extraction.diagnostics,
        *table_extraction.diagnostics,
    )
    all_decisions = (*tuple(decisions), *markdown_table_extraction.decisions)
    classification_counts = Counter(decision.classification for decision in all_decisions)
    result = PipelineResult(
        processed_files=len(extraction.workbooks),
        skipped_files=sum(1 for item in diagnostics if item.reason == "unsupported_type"),
        workbook_count=len(extraction.workbooks),
        document_count=len(markdown_table_extraction.documents),
        extracted_table_count=len(table_extraction.tables) + len(markdown_table_extraction.tables),
        toast_table_count=classification_counts["toast"],
        inline_table_count=classification_counts["inline"],
        warning_count=_warning_count(all_decisions, storage_results, image_storage_results),
        error_count=_error_count(diagnostics, storage_results, image_storage_results),
        artifact_paths={
            "run_manifest": str(run_manifest.manifest_path),
            "workbooks": [bundle.to_dict()["paths"] for bundle in bundles],
            "documents": [bundle.to_dict()["paths"] for bundle in document_bundles],
            **(
                {"document_inputs": str(document_artifact_path)}
                if document_artifact_path is not None
                else {}
            ),
        },
        bundles=bundles,
        diagnostics=tuple(diagnostics),
        storage_results=storage_results,
        storage_result_count=len(storage_results),
        failed_storage_result_count=sum(
            1 for storage_result in storage_results if storage_result.action == "failed"
        ),
        image_candidate_count=len(image_extraction.candidates),
        image_toast_count=len(image_extraction.unique_candidates),
        skipped_image_count=len(image_extraction.skips),
        image_storage_result_count=len(image_storage_results),
        failed_image_storage_result_count=sum(
            1 for storage_result in image_storage_results if storage_result.action == "failed"
        ),
        image_extraction_result=image_extraction,
        image_storage_results=image_storage_results,
    )
    if result.failed_storage_result_count:
        raise PipelineRunError(
            f"storage failed for {result.failed_storage_result_count} table TOAST(s)",
            result=result,
            diagnostics=result.diagnostics,
        )
    if result.failed_image_storage_result_count:
        raise PipelineRunError(
            f"image storage failed for {result.failed_image_storage_result_count} image TOAST(s)",
            result=result,
            diagnostics=result.diagnostics,
        )
    fatal_input_diagnostics = _fatal_input_diagnostics(result.diagnostics)
    if result.workbook_count + result.document_count == 0 and fatal_input_diagnostics:
        raise PipelineRunError(
            _fatal_input_message(fatal_input_diagnostics),
            result=result,
            diagnostics=result.diagnostics,
        )
    return result


def _write_document_inputs_artifact(
    output_dir: Path,
    documents: tuple[DocumentInputArtifact, ...],
) -> Path | None:
    if not documents:
        return None
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    artifact_path = output_path / "document_inputs.json"
    payload = {"documents": [document.to_dict() for document in documents]}
    artifact_path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return artifact_path


def _coerce_config(
    config_or_kwargs: PipelineConfig | None,
    kwargs: dict[str, Any],
) -> PipelineConfig:
    if config_or_kwargs is None:
        return PipelineConfig(**kwargs)
    if kwargs:
        raise TypeError("pass either a PipelineConfig or keyword arguments, not both")
    return config_or_kwargs


def _tables_by_workbook(tables: tuple[TableData, ...]) -> dict[str, tuple[TableData, ...]]:
    grouped: dict[str, list[TableData]] = {}
    for table in tables:
        grouped.setdefault(table.workbook_checksum, []).append(table)
    return {checksum: tuple(items) for checksum, items in grouped.items()}


def _profiles_by_workbook(
    tables: tuple[TableData, ...],
    profiles: tuple[TableProfile, ...],
) -> dict[str, tuple[TableProfile, ...]]:
    grouped: dict[str, list[TableProfile]] = {}
    for table, profile in zip(tables, profiles, strict=True):
        grouped.setdefault(table.workbook_checksum, []).append(profile)
    return {checksum: tuple(items) for checksum, items in grouped.items()}


def _decisions_by_workbook(
    tables: tuple[TableData, ...],
    decisions: tuple[ToastDecision, ...],
) -> dict[str, tuple[ToastDecision, ...]]:
    grouped: dict[str, list[ToastDecision]] = {}
    for table, decision in zip(tables, decisions, strict=True):
        grouped.setdefault(table.workbook_checksum, []).append(decision)
    return {checksum: tuple(items) for checksum, items in grouped.items()}


def _markdown_occurrences_for_document(
    extraction: MarkdownTableExtractionResult,
    document: DocumentMarkdownResult,
) -> tuple[Any, ...]:
    return tuple(
        occurrence
        for occurrence in extraction.occurrences
        if occurrence.source.source_identity == document.source_identity
    )


def _markdown_tables_for_document(
    extraction: MarkdownTableExtractionResult,
    document: DocumentMarkdownResult,
) -> tuple[TableData, ...]:
    occurrences = _markdown_occurrences_for_document(extraction, document)
    return tuple(occurrence.table for occurrence in occurrences if occurrence.table is not None)


def _markdown_profiles_for_document(
    extraction: MarkdownTableExtractionResult,
    document: DocumentMarkdownResult,
) -> tuple[TableProfile, ...]:
    occurrences = _markdown_occurrences_for_document(extraction, document)
    return tuple(occurrence.profile for occurrence in occurrences if occurrence.profile is not None)


def _markdown_decisions_for_document(
    extraction: MarkdownTableExtractionResult,
    document: DocumentMarkdownResult,
) -> tuple[ToastDecision, ...]:
    occurrences = _markdown_occurrences_for_document(extraction, document)
    return tuple(
        occurrence.decision for occurrence in occurrences if occurrence.decision is not None
    )


def _unique_markdown_profiles(
    extraction: MarkdownTableExtractionResult,
) -> tuple[TableProfile, ...]:
    seen: set[str] = set()
    profiles: list[TableProfile] = []
    for profile, decision in zip(extraction.profiles, extraction.decisions, strict=True):
        if decision.content_signature in seen:
            continue
        seen.add(decision.content_signature)
        profiles.append(profile)
    return tuple(profiles)


def _unique_markdown_decisions(
    extraction: MarkdownTableExtractionResult,
) -> tuple[ToastDecision, ...]:
    seen: set[str] = set()
    decisions: list[ToastDecision] = []
    for decision in extraction.decisions:
        if decision.content_signature in seen:
            continue
        seen.add(decision.content_signature)
        decisions.append(decision)
    return tuple(decisions)


def _image_extraction_for_document(
    extraction: DocumentImageExtractionResult,
    document: DocumentMarkdownResult,
) -> DocumentImageExtractionResult:
    document_identity = document.source_identity

    candidates = tuple(
        candidate
        for candidate in extraction.candidates
        if candidate.source_identity == document_identity
        or any(
            occurrence.source_identity == document_identity
            for occurrence in candidate.occurrences
        )
    )
    unique_candidates: list[ImageToastCandidate] = []
    occurrences: list[ImageToastOccurrence] = []
    for candidate in extraction.unique_candidates:
        document_occurrences = tuple(
            occurrence
            for occurrence in candidate.occurrences
            if occurrence.source_identity == document_identity
        )
        if not document_occurrences and candidate.source_identity != document_identity:
            continue
        filtered_candidate = replace(
            candidate,
            occurrences=document_occurrences or candidate.occurrences,
        )
        unique_candidates.append(filtered_candidate)
        occurrences.extend(filtered_candidate.occurrences)

    skips: list[ImageSkip] = []
    for skip in extraction.skips:
        candidate = skip.candidate
        if candidate.source_identity == document_identity or any(
            occurrence.source_identity == document_identity
            for occurrence in candidate.occurrences
        ):
            skips.append(skip)

    diagnostics = tuple(
        diagnostic
        for diagnostic in extraction.diagnostics
        if diagnostic.file_id == document.source.file_id
    )
    return DocumentImageExtractionResult(
        candidates=candidates,
        unique_candidates=tuple(unique_candidates),
        occurrences=tuple(occurrences),
        skips=tuple(skips),
        diagnostics=diagnostics,
        warnings=extraction.warnings,
    )


def _store_toast_tables(
    config: PipelineConfig,
    tables: tuple[TableData, ...],
    profiles: tuple[TableProfile, ...],
    decisions: tuple[ToastDecision, ...],
) -> tuple[TableToastStorageResult, ...]:
    store = config.table_store
    if store is None and config.storage_mode == "dry_run":
        store = FakeTableToastStore()
    if store is None:
        return ()

    results: list[TableToastStorageResult] = []
    for table, profile, decision in zip(tables, profiles, decisions, strict=True):
        if decision.classification != "toast":
            continue
        plan = build_table_storage_plan(
            table,
            profile,
            decision,
            schema_name=config.storage_schema,
        )
        results.append(store.store_table(plan))
    return tuple(results)


def _store_toast_images(
    config: PipelineConfig,
    image_extraction: DocumentImageExtractionResult,
) -> tuple[ImageToastStorageResult, ...]:
    plans = tuple(
        replace(
            plan,
            bucket=config.image_toast_bucket,
            object_key=image_object_key(
                plan.toast_id,
                plan.extension,
                prefix=config.image_toast_prefix,
            ),
        )
        for plan in build_image_storage_plans(
            image_extraction,
            bucket=config.image_toast_bucket,
        )
    )
    if not plans:
        return ()
    store = config.object_store
    if store is None and config.storage_mode == "dry_run":
        store = FakeObjectToastStore()
    if store is None:
        return ()
    return tuple(store.store_object(plan) for plan in plans)


def _storage_result_lookup(
    storage_results: tuple[TableToastStorageResult, ...],
) -> dict[tuple[str, str | None, int | None, str | None] | str, TableToastStorageResult]:
    lookup: dict[tuple[str, str | None, int | None, str | None] | str, TableToastStorageResult] = {}
    for result in storage_results:
        key = (
            result.toast_id,
            result.source_checksum or result.workbook_checksum,
            result.sheet.get("index"),
            result.range.get("a1_range") or _markdown_storage_location_key(result),
        )
        lookup[key] = result
        lookup[result.toast_id] = result
    return lookup


def _markdown_storage_location_key(result: TableToastStorageResult) -> str | None:
    markdown = (result.source_location or {}).get("markdown")
    if not markdown:
        return None
    return f"L{markdown['line_start']}:L{markdown['line_end']}"


def _warning_count(
    decisions: tuple[ToastDecision, ...],
    storage_results: tuple[TableToastStorageResult, ...],
    image_storage_results: tuple[ImageToastStorageResult, ...] = (),
) -> int:
    return len(
        {
            warning
            for decision in decisions
            for warning in decision.warnings
        }
        | {warning for result in storage_results for warning in result.warnings}
        | {warning for result in image_storage_results for warning in result.warnings}
    )


def _error_count(
    diagnostics: tuple[ManifestDiagnostic, ...],
    storage_results: tuple[TableToastStorageResult, ...],
    image_storage_results: tuple[ImageToastStorageResult, ...] = (),
) -> int:
    diagnostic_errors = sum(
        1
        for diagnostic in diagnostics
        if diagnostic.reason not in {"unsupported_type"}
    )
    storage_errors = sum(1 for result in storage_results if result.action == "failed")
    image_storage_errors = sum(
        1 for result in image_storage_results if result.action == "failed"
    )
    return diagnostic_errors + storage_errors + image_storage_errors


def _fatal_input_diagnostics(
    diagnostics: tuple[ManifestDiagnostic, ...],
) -> tuple[ManifestDiagnostic, ...]:
    return tuple(
        diagnostic
        for diagnostic in diagnostics
        if diagnostic.reason
        in {
            "document_conversion_failed",
            "missing_local_file",
            "no_extractable_text",
            "unreadable_workbook",
        }
    )


def _fatal_input_message(diagnostics: tuple[ManifestDiagnostic, ...]) -> str:
    counts = Counter(diagnostic.reason for diagnostic in diagnostics)
    details = ", ".join(f"{reason}={count}" for reason, count in sorted(counts.items()))
    return f"unreadable required input file(s): {details}"
