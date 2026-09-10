"""Export verified result cards as CSV files readable by SciDAVis."""

from __future__ import annotations

import csv
import os
import shutil
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from stem_sci.statistics.models import StatisticalResultCard
from stem_sci.utils.hash_utils import sha256_text


class SciDAVisAvailability(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available: bool
    reason: str | None = None


class SciDAVisExport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=1)
    result_id: str = Field(min_length=1)
    filename: str = Field(min_length=1)
    file_path: str = Field(min_length=1)
    row_count: int = Field(ge=1)
    format: str = "csv"


class SciDAVisAdapter:
    """Detect SciDAVis and export Controller-owned result values."""

    def __init__(self, root: Path, executable: str | None = None) -> None:
        self.root = root
        self.executable = executable or os.getenv("STEM_SCI_SCIDAVIS_EXECUTABLE")

    def resolve_executable(self) -> str | None:
        if self.executable:
            return self.executable if Path(self.executable).is_file() else None
        resolved = shutil.which("scidavis") or shutil.which("SciDAVis")
        if resolved:
            return resolved
        candidates = (
            Path(os.environ.get("ProgramFiles(x86)", "")) / "SciDAVis" / "scidavis.exe",
            Path(os.environ.get("ProgramFiles", "")) / "SciDAVis" / "scidavis.exe",
        )
        return next((str(path) for path in candidates if path.is_file()), None)

    def detect(self) -> SciDAVisAvailability:
        resolved = self.resolve_executable()
        return SciDAVisAvailability(
            available=resolved is not None,
            reason=None if resolved is not None else "SCIDAVIS_EXECUTABLE_NOT_FOUND",
        )

    def export_result(self, project_id: str, result: StatisticalResultCard) -> SciDAVisExport:
        if result.project_id != project_id:
            raise ValueError("result project does not match export project")
        if not result.values:
            raise ValueError("statistical result card has no values to export")
        directory = self.root / "scidavis-exports" / sha256_text(project_id)[:16]
        directory.mkdir(parents=True, exist_ok=True)
        filename = f"{result.result_id}.csv"
        path = directory / filename
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(("result_key", "value"))
            writer.writerows((key, value) for key, value in sorted(result.values.items()))
        return SciDAVisExport(
            project_id=project_id,
            result_id=result.result_id,
            filename=filename,
            file_path=str(path),
            row_count=len(result.values),
        )
