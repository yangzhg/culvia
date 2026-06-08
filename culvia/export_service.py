from __future__ import annotations

import shutil
import tempfile
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from culvia.curation import PhotoMark, curation_export_dataframe, load_photo_marks
from culvia.curation_context import DisplayDataframeBuilder, build_curation_display_context
from culvia.curation_targets import frame_file_ids


EXPORT_PAYLOAD_VERSION = 1

SKIPPED_REASON_LABELS = {
    "missing": "源文件缺失",
    "copy_failed": "复制失败",
}


class ExportServiceError(Exception):
    def __init__(
        self,
        error_code: str,
        message: str,
        *,
        status_code: int = 400,
        params: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.status_code = status_code
        self.params = dict(params or {})


@dataclass(frozen=True)
class ExportSkippedFile:
    path: Path
    reason: str
    message: str = ""

    @property
    def label(self) -> str:
        return SKIPPED_REASON_LABELS.get(self.reason, "未复制")

    def to_payload(self) -> dict[str, str]:
        return {
            "path": str(self.path),
            "reason": self.reason,
            "label": self.label,
            "message": self.message,
        }


@dataclass(frozen=True)
class ExportCopyResult:
    destination: Path
    copied_paths: list[Path]
    skipped_paths: list[Path]
    skipped_details: list[ExportSkippedFile] | None = None

    @property
    def copied(self) -> int:
        return len(self.copied_paths)

    @property
    def skipped(self) -> int:
        return len(self.skipped_paths)

    def resolved_skipped_details(self) -> list[ExportSkippedFile]:
        if self.skipped_details is not None:
            return self.skipped_details
        return [ExportSkippedFile(path, "copy_failed", "未复制") for path in self.skipped_paths]

    def skipped_reason_summary(self) -> list[dict[str, object]]:
        counts: dict[str, int] = {}
        labels: dict[str, str] = {}
        for item in self.resolved_skipped_details():
            counts[item.reason] = counts.get(item.reason, 0) + 1
            labels[item.reason] = item.label
        return [
            {
                "reason": reason,
                "label": labels.get(reason, "未复制"),
                "count": count,
            }
            for reason, count in counts.items()
        ]

    def to_payload(self) -> dict[str, object]:
        copied_files = [str(path) for path in self.copied_paths[:20]]
        skipped_details = [item.to_payload() for item in self.resolved_skipped_details()[:20]]
        return {
            "ok": True,
            "schemaVersion": EXPORT_PAYLOAD_VERSION,
            "destination": str(self.destination),
            "copied": self.copied,
            "skipped": self.skipped,
            "copiedFiles": copied_files,
            "skippedDetails": skipped_details,
            "skippedReasonSummary": self.skipped_reason_summary(),
        }


@dataclass(frozen=True)
class ExportPreflightResult:
    destination: Path
    total: int
    ready_paths: list[Path]
    missing_paths: list[Path]
    renamed_paths: list[tuple[Path, Path]]
    destination_issue: str = ""

    @property
    def destination_writable(self) -> bool:
        return not self.destination_issue

    @property
    def ready(self) -> int:
        return len(self.ready_paths)

    @property
    def missing(self) -> int:
        return len(self.missing_paths)

    @property
    def renamed(self) -> int:
        return len(self.renamed_paths)

    def to_payload(self) -> dict[str, object]:
        return {
            "schemaVersion": EXPORT_PAYLOAD_VERSION,
            "destination": str(self.destination),
            "total": self.total,
            "ready": self.ready,
            "missing": self.missing,
            "renamed": self.renamed,
            "destinationWritable": self.destination_writable,
            "destinationIssue": self.destination_issue,
            "missingFiles": [str(path) for path in self.missing_paths[:20]],
            "renamedFiles": [
                {
                    "source": str(source),
                    "target": str(target),
                }
                for source, target in self.renamed_paths[:20]
            ],
        }


@dataclass(frozen=True)
class SelectedExportContext:
    marks: dict[str, PhotoMark]
    selected_df: pd.DataFrame


def export_csv_bytes(
    df: pd.DataFrame,
    marks: Mapping[str, PhotoMark],
    *,
    normalize_dataframe: Callable[[pd.DataFrame], pd.DataFrame],
) -> bytes:
    export_df = curation_export_dataframe(df, marks, normalize_dataframe=normalize_dataframe)
    return export_df.to_csv(index=False).encode("utf-8-sig")


def selected_curation_dataframe(source_df: pd.DataFrame, marks: Mapping[str, PhotoMark]) -> pd.DataFrame:
    if source_df.empty or "file_id" not in source_df:
        return source_df.iloc[0:0].copy()
    selected_ids = {file_id for file_id, mark in marks.items() if mark.status == "pick"}
    return source_df[source_df["file_id"].astype(str).isin(selected_ids)].copy()


def selected_export_csv_bytes(
    source_df: pd.DataFrame,
    marks: Mapping[str, PhotoMark],
    *,
    normalize_dataframe: Callable[[pd.DataFrame], pd.DataFrame],
) -> bytes:
    return export_csv_bytes(
        selected_curation_dataframe(source_df, marks), marks, normalize_dataframe=normalize_dataframe
    )


def filtered_export_csv_action(
    source_df: pd.DataFrame,
    filters: Mapping[str, Any],
    cache_path: str,
    dataframe_builder: DisplayDataframeBuilder,
    *,
    normalize_dataframe: Callable[[pd.DataFrame], pd.DataFrame],
) -> bytes:
    context = build_curation_display_context(source_df, filters, cache_path, dataframe_builder)
    return export_csv_bytes(context.filtered, context.mark_by_file_id, normalize_dataframe=normalize_dataframe)


def selected_export_csv_action(
    source_df: pd.DataFrame,
    cache_path: str,
    *,
    normalize_dataframe: Callable[[pd.DataFrame], pd.DataFrame],
) -> bytes:
    context = selected_export_context(source_df, cache_path)
    return export_csv_bytes(context.selected_df, context.marks, normalize_dataframe=normalize_dataframe)


def selected_export_context(source_df: pd.DataFrame, cache_path: str) -> SelectedExportContext:
    marks = load_photo_marks(cache_path, frame_file_ids(source_df))
    return SelectedExportContext(
        marks=marks,
        selected_df=selected_curation_dataframe(source_df, marks),
    )


def selected_export_dataframe_action(source_df: pd.DataFrame, cache_path: str) -> pd.DataFrame:
    return selected_export_context(source_df, cache_path).selected_df


def unique_destination_path(destination: Path, filename: str, *, reserved_names: Collection[str] | None = None) -> Path:
    reserved = set(reserved_names or [])
    target = destination / filename
    if not target.exists() and target.name not in reserved:
        return target
    stem = target.stem
    suffix = target.suffix
    for index in range(2, 10000):
        candidate = destination / f"{stem}-{index}{suffix}"
        if not candidate.exists() and candidate.name not in reserved:
            return candidate
    raise RuntimeError(f"无法生成唯一文件名: {filename}")


def destination_write_issue(destination: Path) -> str:
    try:
        with tempfile.NamedTemporaryFile(prefix=".culvia-preflight-", dir=destination, delete=True) as handle:
            handle.write(b"")
    except Exception as exc:
        return f"导出目录不可写：{exc}"
    return ""


def preflight_selected_export(
    selected_df: pd.DataFrame,
    destination: Path,
    *,
    destination_issue: str | None = None,
) -> ExportPreflightResult:
    ready_paths: list[Path] = []
    missing_paths: list[Path] = []
    renamed_paths: list[tuple[Path, Path]] = []
    reserved_names: set[str] = set()
    resolved_destination_issue = (
        destination_write_issue(destination) if destination_issue is None else destination_issue
    )

    for _, row in selected_df.iterrows():
        source_path = Path(str(row.get("path") or "")).expanduser()
        if not source_path.exists() or not source_path.is_file():
            missing_paths.append(source_path)
            continue
        target = unique_destination_path(destination, source_path.name, reserved_names=reserved_names)
        reserved_names.add(target.name)
        ready_paths.append(target)
        if target.name != source_path.name:
            renamed_paths.append((source_path, target))

    return ExportPreflightResult(
        destination=destination,
        total=len(selected_df),
        ready_paths=ready_paths,
        missing_paths=missing_paths,
        renamed_paths=renamed_paths,
        destination_issue=resolved_destination_issue,
    )


def export_preflight_action(source_df: pd.DataFrame, cache_path: str, destination_text: str) -> ExportPreflightResult:
    destination_text = str(destination_text or "").strip()
    if not destination_text:
        raise ExportServiceError("exportDestinationRequired", "请选择导出目录。", status_code=400)
    destination = Path(destination_text).expanduser()
    if not destination.exists() or not destination.is_dir():
        raise ExportServiceError(
            "exportDestinationUnavailable",
            "导出目录不可用。",
            status_code=400,
            params={"path": destination_text},
        )
    context = selected_export_context(source_df, cache_path)
    return preflight_selected_export(context.selected_df, destination)


def copy_selected_photo_files(selected_df: pd.DataFrame, destination: Path) -> ExportCopyResult:
    copied: list[Path] = []
    skipped: list[Path] = []
    skipped_details: list[ExportSkippedFile] = []
    for _, row in selected_df.iterrows():
        source_path = Path(str(row.get("path") or "")).expanduser()
        if not source_path.exists() or not source_path.is_file():
            skipped.append(source_path)
            skipped_details.append(ExportSkippedFile(source_path, "missing", "源文件不存在或不是文件"))
            continue
        try:
            target = unique_destination_path(destination, source_path.name)
            shutil.copy2(source_path, target)
            copied.append(target)
        except Exception as exc:
            skipped.append(source_path)
            skipped_details.append(ExportSkippedFile(source_path, "copy_failed", f"复制失败：{exc}"))
    return ExportCopyResult(
        destination=destination,
        copied_paths=copied,
        skipped_paths=skipped,
        skipped_details=skipped_details,
    )


def export_selected_files_action(source_df: pd.DataFrame, cache_path: str, destination_text: str) -> ExportCopyResult:
    destination_text = str(destination_text or "").strip()
    if not destination_text:
        raise ExportServiceError("exportDestinationRequired", "请选择导出目录。", status_code=400)
    destination = Path(destination_text).expanduser()
    try:
        destination.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        raise ExportServiceError(
            "exportDestinationCreateFailed",
            f"导出目录不可用：{exc}",
            status_code=400,
            params={"reason": str(exc)},
        ) from exc
    destination_issue = destination_write_issue(destination)
    if destination_issue:
        raise ExportServiceError(
            "exportDestinationNotWritable",
            destination_issue,
            status_code=400,
            params={"reason": destination_issue},
        )

    context = selected_export_context(source_df, cache_path)
    if context.selected_df.empty:
        raise ExportServiceError("exportNoPicks", "还没有入选照片。", status_code=400)
    return copy_selected_photo_files(context.selected_df, destination)
