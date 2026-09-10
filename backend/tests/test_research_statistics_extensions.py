from stem_sci.controller.data_pipeline import DataPipelineBeginRequest
from stem_sci.statistics.meta_analysis import MetaAnalysisOperator
from stem_sci.statistics.multiple_comparisons import (
    MultipleComparisonOperator,
    MultiplicityMethod,
)


def test_holm_correction_is_auditable() -> None:
    report = MultipleComparisonOperator().run(
        report_id="multiplicity-1",
        p_values={"primary": 0.01, "secondary": 0.04, "exploratory": 0.8},
        method=MultiplicityMethod.HOLM,
    )
    assert report.method is MultiplicityMethod.HOLM
    assert report.results[0].adjusted_p_value == 0.03
    assert report.significant_count == 1


def test_random_effects_meta_analysis_reports_heterogeneity() -> None:
    report = MetaAnalysisOperator().run(
        report_id="meta-1",
        studies=[("s1", 0.2, 0.1), ("s2", 0.4, 0.1), ("s3", 0.3, 0.12)],
    )
    assert report.study_count == 3
    assert report.ci_lower < report.pooled_effect < report.ci_upper
    assert set(report.leave_one_out_effects) == {"s1", "s2", "s3"}


def test_pipeline_request_exposes_pre_specified_multiplicity_settings() -> None:
    fields = DataPipelineBeginRequest.model_fields
    assert fields["multiple_comparison_correction"].default is False
    assert fields["multiple_comparison_method"].default is MultiplicityMethod.HOLM
