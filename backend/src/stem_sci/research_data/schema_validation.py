"""Optional Pandera-backed schema validation with a deterministic fallback."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class SchemaFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1)
    column: str | None = None
    message: str = Field(min_length=1)


class SchemaValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_id: str = Field(min_length=1)
    validator_id: str = Field(min_length=1)
    passed: bool
    findings: list[SchemaFinding] = Field(default_factory=list)


class ColumnRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    required: bool = True
    type: str = "string"
    minimum: float | None = None
    maximum: float | None = None


class DeclaredDataSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    columns: list[ColumnRule] = Field(min_length=1)


class DeclaredSchemaValidator:
    """Dependency-free schema gate used when Pandera is not installed."""

    validator_id = "declared-schema-v1"

    def validate_rows(
        self, *, report_id: str, rows: list[dict[str, object]], schema: DeclaredDataSchema
    ) -> SchemaValidationReport:
        findings: list[SchemaFinding] = []
        for index, row in enumerate(rows):
            for rule in schema.columns:
                value = row.get(rule.name)
                if value is None or value == "":
                    if rule.required:
                        findings.append(SchemaFinding(code="COLUMN_REQUIRED", column=rule.name, message=f"row {index} is missing a required value"))
                    continue
                if rule.type == "number":
                    try:
                        numeric = float(value)
                    except (TypeError, ValueError):
                        findings.append(SchemaFinding(code="TYPE_INVALID", column=rule.name, message=f"row {index} is not numeric"))
                        continue
                    if rule.minimum is not None and numeric < rule.minimum:
                        findings.append(SchemaFinding(code="VALUE_BELOW_MINIMUM", column=rule.name, message=f"row {index} is below the minimum"))
                    if rule.maximum is not None and numeric > rule.maximum:
                        findings.append(SchemaFinding(code="VALUE_ABOVE_MAXIMUM", column=rule.name, message=f"row {index} is above the maximum"))
                elif rule.type == "string" and not isinstance(value, str):
                    findings.append(SchemaFinding(code="TYPE_INVALID", column=rule.name, message=f"row {index} is not text"))
        return SchemaValidationReport(report_id=report_id, validator_id=self.validator_id, passed=not findings, findings=findings)


class PanderaSchemaValidator:
    """Validate a DataFrame against a declared schema without mutating it."""

    validator_id = "pandera-schema-v1"

    def validate(self, *, report_id: str, frame: object, schema: object) -> SchemaValidationReport:
        try:
            import pandera.pandas as pa  # type: ignore[import-not-found]
        except ImportError:
            return SchemaValidationReport(
                report_id=report_id,
                validator_id=self.validator_id,
                passed=False,
                findings=[SchemaFinding(code="PANDERA_UNAVAILABLE", message="Pandera is not installed.")],
            )
        try:
            schema.validate(frame, lazy=True)
        except pa.errors.SchemaErrors as error:
            findings = [
                SchemaFinding(code="SCHEMA_INVALID", column=str(row.get("column") or ""), message=str(row.get("failure_case")))
                for row in error.failure_cases.to_dict(orient="records")
            ]
            return SchemaValidationReport(report_id=report_id, validator_id=self.validator_id, passed=False, findings=findings)
        except (AttributeError, TypeError) as error:
            return SchemaValidationReport(
                report_id=report_id,
                validator_id=self.validator_id,
                passed=False,
                findings=[
                    SchemaFinding(
                        code="PANDERA_INVALID_INPUT",
                        message=f"Pandera schema validation could not run: {type(error).__name__}",
                    )
                ],
            )
        return SchemaValidationReport(report_id=report_id, validator_id=self.validator_id, passed=True)
