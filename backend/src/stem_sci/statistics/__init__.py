"""Statistical execution-plan and result contracts."""

from .conformal import MAPIEConformalAdapter, PredictionInterval
from .dual_validation import CrossEngineResultValidator, DualEngineValidationOutcome
from .meta_analysis import MetaAnalysisOperator, MetaAnalysisReport, PyMAREMetaAnalysisAdapter
from .models import (
    AnalysisModelSpecification,
    AnalysisPlan,
    AnalysisPlanAmendment,
    ExecutableAnalysisPlan,
    ExecutionStatus,
    HumanExecutionApproval,
    InterpretationStatus,
    ReproducibilityManifest,
    ResultConsistencyReport,
    ResultValidationReport,
    StatisticalResultCard,
    ValidationMode,
    VarianceBoundaryPolicy,
)
from .multiple_comparisons import (
    AdjustedPValue,
    MultipleComparisonOperator,
    MultipleComparisonReport,
    MultiplicityMethod,
)
from .outliers import OutlierFinding, OutlierReport, PyODOutlierAdapter
from .python_operator import (
    CsvPythonAnalysisOperator,
    PythonAnalysisRequest,
    PythonExecutionOutcome,
)
from .robustness import (
    RobustnessAnalysisOperator,
    RobustnessCheck,
    RobustnessReport,
    RobustnessStatus,
)
from .sensitivity import ConfoundingSensitivityReport, SensemakrAdapter
from .spss_adapter import SpssAdapter, SpssAnalysisRequest, SpssAvailability, SpssExecutionOutcome
from .validation import SingleEngineResultValidator

__all__ = [
    "AdjustedPValue",
    "AnalysisModelSpecification",
    "AnalysisPlan",
    "AnalysisPlanAmendment",
    "ConfoundingSensitivityReport",
    "CrossEngineResultValidator",
    "CsvPythonAnalysisOperator",
    "DualEngineValidationOutcome",
    "ExecutableAnalysisPlan",
    "ExecutionStatus",
    "HumanExecutionApproval",
    "InterpretationStatus",
    "MAPIEConformalAdapter",
    "MetaAnalysisOperator",
    "MetaAnalysisReport",
    "MultipleComparisonOperator",
    "MultipleComparisonReport",
    "MultiplicityMethod",
    "OutlierFinding",
    "OutlierReport",
    "PredictionInterval",
    "PyMAREMetaAnalysisAdapter",
    "PyODOutlierAdapter",
    "PythonAnalysisRequest",
    "PythonExecutionOutcome",
    "ReproducibilityManifest",
    "ResultConsistencyReport",
    "ResultValidationReport",
    "RobustnessAnalysisOperator",
    "RobustnessCheck",
    "RobustnessReport",
    "RobustnessStatus",
    "SensemakrAdapter",
    "SingleEngineResultValidator",
    "SpssAdapter",
    "SpssAnalysisRequest",
    "SpssAvailability",
    "SpssExecutionOutcome",
    "StatisticalResultCard",
    "ValidationMode",
    "VarianceBoundaryPolicy",
]
