"""Research data-version contracts."""

from .analysis_dataset import DeterministicDataProcessor
from .audit import ModelEligibilityEvaluator, StructuralDataAuditor, StructuralDataAuditReport
from .freeze import DataFreezeService, FrozenDatasetIntegrityError
from .models import (
    AnalysisDatasetRef,
    AnalysisDatasetSerializationPolicy,
    DatasetRef,
    FrozenDatasetRef,
    ModelEligibilityManifest,
    ParticipantEligibilityManifest,
    ProcessedDatasetRef,
    RawDatasetRef,
    SyntheticDatasetGenerationManifest,
)
from .processing import DataProcessingService
from .schema_validation import (
    ColumnRule,
    DeclaredDataSchema,
    DeclaredSchemaValidator,
    PanderaSchemaValidator,
    SchemaFinding,
    SchemaValidationReport,
)

__all__ = [
    "AnalysisDatasetRef",
    "AnalysisDatasetSerializationPolicy",
    "ColumnRule",
    "DataFreezeService",
    "DataProcessingService",
    "DatasetRef",
    "DeclaredDataSchema",
    "DeclaredSchemaValidator",
    "DeterministicDataProcessor",
    "FrozenDatasetIntegrityError",
    "FrozenDatasetRef",
    "ModelEligibilityEvaluator",
    "ModelEligibilityManifest",
    "PanderaSchemaValidator",
    "ParticipantEligibilityManifest",
    "ProcessedDatasetRef",
    "RawDatasetRef",
    "SchemaFinding",
    "SchemaValidationReport",
    "StructuralDataAuditReport",
    "StructuralDataAuditor",
    "SyntheticDatasetGenerationManifest",
]
