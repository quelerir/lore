from __future__ import annotations

from dataclasses import InitVar, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from lore_splitter.contracts import (
    InputClassification,
    InputKind,
    ManifestDiagnostic,
    SourceFile,
    classify_source_file,
)
from lore_splitter.manifest import ManifestLoadResult


@dataclass(frozen=True)
class ResolvedInput:
    source_file: SourceFile
    local_path: Path
    classification: InitVar[InputClassification | None] = None
    input_kind: str = field(init=False)
    normalized_extension: str = field(init=False)
    mime_family: str = field(init=False)

    def __post_init__(self, classification: InputClassification | None) -> None:
        resolved_classification = classification or classify_source_file(self.source_file)
        object.__setattr__(self, "input_kind", resolved_classification.input_kind.value)
        object.__setattr__(
            self,
            "normalized_extension",
            resolved_classification.normalized_extension,
        )
        object.__setattr__(self, "mime_family", resolved_classification.mime_family)

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.source_file.to_dict(),
            "local_path": str(self.local_path),
            "input_kind": self.input_kind,
            "normalized_extension": self.normalized_extension,
            "mime_family": self.mime_family,
        }


ResolvedFile = ResolvedInput


@dataclass(frozen=True)
class ResolverResult:
    processable: list[ResolvedInput]
    diagnostics: list[ManifestDiagnostic]


def resolve_manifest(manifest: ManifestLoadResult, input_root: str | Path) -> ResolverResult:
    root = Path(input_root)
    processable: list[ResolvedInput] = []
    diagnostics: list[ManifestDiagnostic] = []

    for source_file in manifest.records:
        classification = classify_source_file(source_file)
        if classification.input_kind is InputKind.UNSUPPORTED:
            diagnostics.append(
                ManifestDiagnostic.for_source(
                    "unsupported_type",
                    f"Unsupported extension: {classification.normalized_extension or '<none>'}",
                    source_file,
                )
            )
            continue

        local_path = resolve_local_path(root, source_file.object_path)
        if not local_path.is_file():
            diagnostics.append(
                ManifestDiagnostic.for_source(
                    "missing_local_file",
                    f"File is not present under input root: {local_path}",
                    source_file,
                )
            )
            continue

        processable.append(
            ResolvedInput(
                source_file=source_file,
                local_path=local_path,
                classification=classification,
            )
        )

    return ResolverResult(processable=processable, diagnostics=diagnostics)


def resolve_local_path(input_root: Path, object_path: str) -> Path:
    posix_path = PurePosixPath(object_path)
    relative = PurePosixPath(*posix_path.parts[1:]) if posix_path.is_absolute() else posix_path
    if ".." in relative.parts:
        raise ValueError(f"Manifest object path escapes input root: {object_path}")
    root = input_root.resolve()
    candidate = root.joinpath(*relative.parts).resolve(strict=False)
    if candidate != root and root not in candidate.parents:
        raise ValueError(f"Manifest object path escapes input root: {object_path}")
    return candidate
