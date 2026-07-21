from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from lore_splitter.contracts import RunSummary
from lore_splitter.manifest import ManifestError, load_manifest
from lore_splitter.resolver import resolve_manifest
from lore_splitter.xlsx import extract_workbooks


def _manifest_summary(args: argparse.Namespace) -> int:
    try:
        manifest = load_manifest(args.manifest)
    except ManifestError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    resolved = resolve_manifest(manifest, args.input_root)
    diagnostics = [*manifest.diagnostics, *resolved.diagnostics]
    summary = RunSummary.from_results(
        [item.source_file for item in resolved.processable],
        diagnostics,
        declared_size_bytes=manifest.declared_size_bytes,
    )
    payload = summary.to_dict()
    payload["workbook_count"] = sum(
        1 for item in resolved.processable if item.input_kind == "workbook"
    )
    payload["document_count"] = sum(
        1 for item in resolved.processable if item.input_kind == "document"
    )
    payload["diagnostics"] = [diagnostic.to_dict() for diagnostic in diagnostics]
    payload["processed"] = [item.to_dict() for item in resolved.processable]

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(
            "records={total_records} processed={processed_files} skipped={skipped_files} "
            "missing={missing_files} invalid={invalid_records} bytes={declared_size_bytes}".format(
                **payload
            )
        )
    return 0


def _xlsx_summary(args: argparse.Namespace) -> int:
    try:
        manifest = load_manifest(args.manifest)
    except ManifestError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    resolved = resolve_manifest(manifest, args.input_root)
    workbook_inputs = tuple(
        item for item in resolved.processable if item.input_kind == "workbook"
    )
    extraction = extract_workbooks(workbook_inputs)
    diagnostics = [*manifest.diagnostics, *resolved.diagnostics, *extraction.diagnostics]
    payload = {
        "workbook_count": len(extraction.workbooks),
        "sheet_count": sum(len(workbook.sheets) for workbook in extraction.workbooks),
        "candidate_table_count": sum(
            len(sheet.table_candidates)
            for workbook in extraction.workbooks
            for sheet in workbook.sheets
        ),
        "workbooks": [workbook.to_dict() for workbook in extraction.workbooks],
        "diagnostics": [diagnostic.to_dict() for diagnostic in diagnostics],
        "warnings": _xlsx_warnings(extraction.workbooks),
    }

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(
            "workbooks={workbook_count} sheets={sheet_count} "
            "candidate_tables={candidate_table_count} diagnostics={diagnostic_count}".format(
                diagnostic_count=len(diagnostics),
                **payload,
            )
        )
    return 0 if extraction.workbooks else 1


def _xlsx_warnings(workbooks) -> list[str]:
    warnings = {
        warning
        for workbook in workbooks
        for sheet in workbook.sheets
        for candidate in sheet.table_candidates
        for warning in candidate.warnings
    }
    return sorted(warnings)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="splitter")
    subparsers = parser.add_subparsers(dest="command", required=True)

    summary = subparsers.add_parser(
        "manifest-summary",
        help="Load an Airbyte-style file manifest and summarize local processing status.",
    )
    summary.add_argument("--manifest", required=True, type=Path)
    summary.add_argument("--input-root", required=True, type=Path)
    summary.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    summary.set_defaults(func=_manifest_summary)

    xlsx_summary = subparsers.add_parser(
        "xlsx-summary",
        help="Load an Airbyte-style manifest and summarize XLSX workbook extraction metadata.",
    )
    xlsx_summary.add_argument("--manifest", required=True, type=Path)
    xlsx_summary.add_argument("--input-root", required=True, type=Path)
    xlsx_summary.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    xlsx_summary.set_defaults(func=_xlsx_summary)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
