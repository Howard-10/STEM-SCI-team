from pathlib import Path

from stem_sci.statistics.models import ExecutionStatus, StatisticalResultCard
from stem_sci.statistics.scidavis import SciDAVisAdapter


def _result(project_id: str) -> StatisticalResultCard:
    return StatisticalResultCard(
        result_id="result-1",
        project_id=project_id,
        execution_run_ref="run://1",
        analysis_plan_ref="plan://1",
        validation_report_ref="validation://1",
        execution_status=ExecutionStatus.EXECUTION_VERIFIED,
        deterministic_parser_version="test-v1",
        values={"group_1_mean": 60.0, "group_2_mean": 72.5},
    )


def test_scidavis_export_is_tidy_and_project_scoped(tmp_path: Path) -> None:
    adapter = SciDAVisAdapter(tmp_path, executable=str(tmp_path / "scidavis.exe"))
    exported = adapter.export_result("project-1", _result("project-1"))

    assert exported.row_count == 2
    assert Path(exported.file_path).read_text(encoding="utf-8") == (
        "result_key,value\n"
        "group_1_mean,60.0\n"
        "group_2_mean,72.5\n"
    )


def test_scidavis_export_rejects_cross_project_result(tmp_path: Path) -> None:
    adapter = SciDAVisAdapter(tmp_path)
    try:
        adapter.export_result("project-2", _result("project-1"))
    except ValueError as error:
        assert "project" in str(error)
    else:
        raise AssertionError("cross-project result was exported")
