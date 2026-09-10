"""Fail-closed, optional physics checks for generated research code.

The validator runs in the Controller process, never inside generated code or
the research sandbox.  It validates an approved set of equations, units and
variable bounds supplied by the caller; it does not infer new scientific
claims from arbitrary source text.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from uuid import uuid4

from stem_sci.coding.models import CodeArtifact

from .models import PhysicsCheck, PhysicsValidationReport


class PhysicsValidationGate:
    """Run SymPy, Pint and Z3 checks when those dependencies are installed."""

    gate_id = "PhysicsValidationGate"
    gate_version = "physics-validation-v1"

    def validate(
        self,
        *,
        project_id: str,
        artifact: CodeArtifact,
        equations: list[str] | None = None,
        units: dict[str, str] | None = None,
        bounds: dict[str, dict[str, float]] | None = None,
    ) -> PhysicsValidationReport:
        checks: list[PhysicsCheck] = []
        findings: list[str] = []
        source = self._read_source(artifact, checks, findings)
        return self._validate_source(
            project_id=project_id,
            code_artifact_ref=artifact.ref,
            source=source,
            checks=checks,
            findings=findings,
            equations=equations,
            units=units,
            bounds=bounds,
        )

    def validate_source(
        self,
        *,
        project_id: str,
        code_artifact_ref: str,
        source: str,
        equations: list[str] | None = None,
        units: dict[str, str] | None = None,
        bounds: dict[str, dict[str, float]] | None = None,
    ) -> PhysicsValidationReport:
        """Validate source supplied by an API/UI without creating an artifact first."""
        checks: list[PhysicsCheck] = []
        findings: list[str] = []
        return self._validate_source(
            project_id=project_id,
            code_artifact_ref=code_artifact_ref,
            source=source,
            checks=checks,
            findings=findings,
            equations=equations,
            units=units,
            bounds=bounds,
        )

    def _validate_source(
        self,
        *,
        project_id: str,
        code_artifact_ref: str,
        source: str | None,
        checks: list[PhysicsCheck],
        findings: list[str],
        equations: list[str] | None,
        units: dict[str, str] | None,
        bounds: dict[str, dict[str, float]] | None,
    ) -> PhysicsValidationReport:
        if source is not None:
            try:
                tree = ast.parse(source)
                checks.append(PhysicsCheck(
                    check_id=f"ast-{uuid4().hex}", kind="formula", passed=True,
                    message="Python source syntax is valid.",
                ))
                self._check_source_safety(tree, checks, findings)
            except SyntaxError:
                findings.append("PHYSICS_PYTHON_SYNTAX_INVALID")
                checks.append(PhysicsCheck(
                    check_id=f"ast-{uuid4().hex}", kind="formula", passed=False,
                    message="Python source cannot be parsed.",
                ))

        if equations:
            self._check_equations(equations, checks, findings)
        if units:
            self._check_units(units, checks, findings)
        if bounds:
            self._check_bounds(bounds, checks, findings)

        passed = not findings
        return PhysicsValidationReport(
            report_id=f"physics-validation-{uuid4().hex}",
            project_id=project_id,
            code_artifact_ref=code_artifact_ref,
            passed=passed,
            requires_human_review=not passed,
            checks=checks,
            finding_codes=sorted(set(findings)),
        )

    @staticmethod
    def _check_source_safety(
        tree: ast.AST, checks: list[PhysicsCheck], findings: list[str]
    ) -> None:
        forbidden_imports = {
            "os", "socket", "subprocess", "requests", "urllib", "ctypes", "shutil"
        }
        forbidden_calls = {"eval", "exec", "compile", "__import__"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots = {item.name.split(".", 1)[0] for item in node.names}
                if roots & forbidden_imports:
                    findings.append("PHYSICS_PROHIBITED_IMPORT")
            elif isinstance(node, ast.ImportFrom):
                root = (node.module or "").split(".", 1)[0]
                if root in forbidden_imports:
                    findings.append("PHYSICS_PROHIBITED_IMPORT")
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in forbidden_calls:
                    findings.append("PHYSICS_PROHIBITED_OPERATION")
        if any(code.startswith("PHYSICS_PROHIBITED") for code in findings):
            checks.append(PhysicsCheck(
                check_id=f"safety-{uuid4().hex}", kind="dependency", passed=False,
                message="Source contains a prohibited import or dynamic execution call.",
            ))
        else:
            checks.append(PhysicsCheck(
                check_id=f"safety-{uuid4().hex}", kind="dependency", passed=True,
                message="Source passed the physics validator safety pre-check.",
            ))

    @staticmethod
    def _read_source(
        artifact: CodeArtifact,
        checks: list[PhysicsCheck],
        findings: list[str],
    ) -> str | None:
        try:
            content = Path(artifact.content_uri).read_bytes()
        except OSError:
            findings.append("PHYSICS_CODE_ARTIFACT_UNAVAILABLE")
            checks.append(PhysicsCheck(
                check_id=f"source-{uuid4().hex}", kind="dependency", passed=False,
                message="Physics validator could not read the code artifact.",
            ))
            return None
        from stem_sci.utils.hash_utils import sha256_bytes

        if sha256_bytes(content) != artifact.sha256:
            findings.append("PHYSICS_CODE_ARTIFACT_HASH_MISMATCH")
            checks.append(PhysicsCheck(
                check_id=f"source-{uuid4().hex}", kind="dependency", passed=False,
                message="Code artifact hash does not match its stored content.",
            ))
            return None
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError:
            findings.append("PHYSICS_CODE_ARTIFACT_NOT_UTF8")
            return None

    @staticmethod
    def _check_equations(
        equations: list[str], checks: list[PhysicsCheck], findings: list[str]
    ) -> None:
        try:
            from sympy import Symbol, sympify
        except ImportError:
            findings.append("PHYSICS_SYMPY_UNAVAILABLE")
            checks.append(PhysicsCheck(
                check_id=f"sympy-{uuid4().hex}", kind="dependency", passed=False,
                message="SymPy is not installed; formula validation is unavailable.",
            ))
            return
        for index, equation in enumerate(equations):
            try:
                if not re.fullmatch(r"[A-Za-z0-9_+\-*/^=().,\s]+", equation):
                    raise ValueError("formula contains unsupported characters")
                if equation.count("=") > 1:
                    raise ValueError("formula contains multiple equality signs")
                if "=" in equation:
                    left, right = (part.strip() for part in equation.split("=", 1))
                    if not left or not right:
                        raise ValueError("formula equality has an empty side")
                    names = set(re.findall(r"[A-Za-z_]\w*", equation))
                    local_symbols = {name: Symbol(name) for name in names}
                    sympify(left, locals=local_symbols, evaluate=False)
                    sympify(right, locals=local_symbols, evaluate=False)
                else:
                    names = set(re.findall(r"[A-Za-z_]\w*", equation))
                    sympify(
                        equation,
                        locals={name: Symbol(name) for name in names},
                        evaluate=False,
                    )
            except (TypeError, ValueError, SyntaxError):
                findings.append("PHYSICS_FORMULA_INVALID")
                checks.append(PhysicsCheck(
                    check_id=f"formula-{index}", kind="formula", passed=False,
                    message=f"Formula cannot be parsed: {equation}", source=equation,
                ))
            else:
                checks.append(PhysicsCheck(
                    check_id=f"formula-{index}", kind="formula", passed=True,
                    message="Formula parsed by SymPy.", source=equation,
                ))

    @staticmethod
    def _check_units(
        units: dict[str, str], checks: list[PhysicsCheck], findings: list[str]
    ) -> None:
        try:
            from pint import UnitRegistry
            from pint.errors import PintError
        except ImportError:
            findings.append("PHYSICS_PINT_UNAVAILABLE")
            checks.append(PhysicsCheck(
                check_id=f"pint-{uuid4().hex}", kind="dependency", passed=False,
                message="Pint is not installed; unit validation is unavailable.",
            ))
            return
        registry = UnitRegistry()
        for variable, unit in units.items():
            try:
                registry.Unit(unit)
            except (PintError, ValueError, TypeError):
                findings.append("PHYSICS_UNIT_INVALID")
                checks.append(PhysicsCheck(
                    check_id=f"unit-{variable}", kind="unit", passed=False,
                    message=f"Unknown unit for {variable}: {unit}", source=unit,
                ))
            else:
                checks.append(PhysicsCheck(
                    check_id=f"unit-{variable}", kind="unit", passed=True,
                    message=f"Unit for {variable} is recognized.", source=unit,
                ))

    @staticmethod
    def _check_bounds(
        bounds: dict[str, dict[str, float]], checks: list[PhysicsCheck], findings: list[str]
    ) -> None:
        try:
            from z3 import Real, Solver, sat
        except ImportError:
            findings.append("PHYSICS_Z3_UNAVAILABLE")
            checks.append(PhysicsCheck(
                check_id=f"z3-{uuid4().hex}", kind="dependency", passed=False,
                message="Z3 is not installed; constraint validation is unavailable.",
            ))
            return
        solver = Solver()
        variables = {name: Real(name) for name in bounds}
        for name, rules in bounds.items():
            if "min" in rules:
                solver.add(variables[name] >= rules["min"])
            if "max" in rules:
                solver.add(variables[name] <= rules["max"])
        result = solver.check()
        passed = result == sat
        if not passed:
            findings.append("PHYSICS_CONSTRAINTS_UNSAT")
        checks.append(PhysicsCheck(
            check_id=f"constraints-{uuid4().hex}", kind="constraint", passed=passed,
            message="Variable bounds are satisfiable." if passed else "Variable bounds are contradictory.",
        ))
