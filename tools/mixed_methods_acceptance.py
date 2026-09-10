"""Run a bounded Mixed Methods acceptance flow against the local API."""

from __future__ import annotations

import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request
import uuid


BASE = os.environ.get("STEM_SCI_ACCEPTANCE_BASE", "http://127.0.0.1:8000/api/v1")
ROOT = pathlib.Path(__file__).resolve().parents[1]
QUAL_DATA = ROOT / "test_data" / "public_reanalysis" / "cgt_physics_education" / "Textual_descriptions_utf8.txt"
# The quantitative MVP deliberately accepts the narrow, auditable schema
# ``group,transfer_score``.  Keep this acceptance fixture aligned with that
# contract instead of changing the production pipeline to accommodate a
# differently named exploratory CSV.
QUANT_DATA = ROOT / "test_data" / "mixed_methods_quantitative.csv"
OUT = ROOT / "docs" / "reports" / "MIXED_METHODS_ACCEPTANCE_2026-08-31.json"


def call(method: str, path: str, *, token: str | None = None, body: object | None = None,
         file: pathlib.Path | None = None) -> dict:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    payload: bytes | None = None
    if file is not None:
        boundary = f"----stem-sci-{uuid.uuid4().hex}"
        payload = b"".join([
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="file"; filename="{file.name}"\r\n'.encode(),
            b"Content-Type: application/octet-stream\r\n\r\n",
            file.read_bytes(), b"\r\n", f"--{boundary}--\r\n".encode(),
        ])
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    elif body is not None:
        payload = json.dumps(body, ensure_ascii=False).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(BASE.rstrip("/") + path, data=payload, headers=headers, method=method)
    try:
        # A Codex generation attempt is optional and may consume its bounded
        # provider timeout before the deterministic fallback continues the
        # exact frozen specification.  Give this acceptance client enough
        # time to observe that controlled fallback instead of abandoning the
        # HTTP request at the same instant.
        with urllib.request.urlopen(request, timeout=90) as response:
            raw = response.read().decode("utf-8")
            return {"status": response.status, "body": json.loads(raw) if raw else {}}
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {"raw": raw}
        return {"status": error.code, "body": parsed}


def require(response: dict, label: str) -> dict:
    if not 200 <= response["status"] < 300:
        raise RuntimeError(f"{label} failed: {response['status']} {response['body']}")
    return response["body"]


def register(prefix: str) -> tuple[str, str]:
    username = f"{prefix}{uuid.uuid4().hex[:10]}"
    body = require(call("POST", "/auth/register", body={
        "username": username, "email": f"{username}@example.test", "password": "research-pass-123",
    }), "register")
    return username, body["access_token"]


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    researcher, researcher_token = register("mixedresearch")
    reviewer, reviewer_token = register("mixedreview")
    project_id = f"mixed-accept-{uuid.uuid4().hex[:12]}"
    topic = "混合方法研究 Python 教学对学生计算思维表现的影响，并访谈教师了解实施过程和专业学习需求。"
    require(call("POST", "/projects", token=researcher_token, body={
        "project_id": project_id, "title": "Mixed Methods 长流程验收", "research_direction": topic,
    }), "create project")
    require(call("PUT", f"/projects/{project_id}/members", token=researcher_token, body={
        "username": reviewer, "role": "reviewer",
    }), "add reviewer")
    started = require(call("POST", f"/projects/{project_id}/conversation/command", token=researcher_token, body={
        "project_id": project_id, "message": topic,
    }), "start mixed workflow")

    records: list[dict[str, object]] = []
    uploads = {"QUALITATIVE": QUAL_DATA, "EXPERIMENTAL": QUANT_DATA}
    uploaded_routes: set[str] = set()
    for _ in range(100):
        state = require(call("GET", f"/projects/{project_id}/control-state", token=researcher_token), "control state")
        if state.get("lifecycle_status") == "COMPLETED":
            break
        gate_id = state.get("active_gate_id")
        if not gate_id:
            advanced = require(call("POST", f"/projects/{project_id}/orchestration/continue", token=researcher_token), "continue")
            time.sleep(0.15)
            if advanced.get("gate") is None and advanced.get("task") is None:
                raise RuntimeError(f"workflow stopped without gate: {advanced}")
            continue
        gate = require(call("GET", f"/projects/{project_id}/gates/{gate_id}", token=researcher_token), "gate")
        stream = next(item for item in state["workstreams"] if item["workstream_id"] == gate["workstream_id"])
        route = stream["route"]
        gate_type = gate["gate_type"]
        print(f"GATE {gate_type} route={route} step={stream.get('current_step_index')}")
        if gate_type == "raw_data_import_approval" and route not in uploaded_routes:
            print(f"UPLOAD {route} {uploads[route]}")
            require(call("POST", f"/projects/{project_id}/primary-data/upload", token=researcher_token, file=uploads[route]), f"upload {route}")
            uploaded_routes.add(route)
        actor_token = reviewer_token if gate_type == "reviewer_final_confirmation_approval" else researcher_token
        decision: dict[str, object] = {"decision": "approve"}
        if gate.get("warnings"):
            decision["risk_acceptance"] = ["验收者已查看当前风险和候选产物边界"]
        require(call("POST", f"/projects/{project_id}/gates/{gate_id}/decision", token=actor_token, body=decision), f"approve {gate_type}")
        records.append({"route": route, "gate_type": gate_type, "warnings": gate.get("warnings", [])})
        time.sleep(0.15)
    final_state = require(call("GET", f"/projects/{project_id}/control-state", token=researcher_token), "final state")
    contents = require(call("GET", f"/workflow/projects/{project_id}/artifact-contents", token=researcher_token), "artifact contents")
    claims = require(call("GET", f"/projects/{project_id}/claims", token=researcher_token), "claims")
    artifact_type_counts: dict[str, int] = {}
    for item in contents:
        artifact_type = str(item.get("artifact_type", "unknown"))
        artifact_type_counts[artifact_type] = artifact_type_counts.get(artifact_type, 0) + 1
    merged = next((item for item in contents if item.get("artifact_type") == "MixedMethodsManuscript"), None)
    merged_body = (merged or {}).get("body") or {}
    merged_components = merged_body.get("components") if isinstance(merged_body, dict) else None
    merged_claims = [
        item for item in claims
        if isinstance(item, dict) and item.get("manuscript_artifact_id") == (merged or {}).get("artifact_id")
    ]
    report = {
        "project_id": project_id,
        "researcher": researcher,
        "reviewer": reviewer,
        "route": (final_state.get("route_decision") or {}).get("primary_route"),
        "started_kind": started.get("kind"),
        "uploaded_routes": sorted(uploaded_routes),
        "gate_count": len(records),
        "gates_by_route": {
            route: sum(1 for item in records if item["route"] == route)
            for route in sorted({str(item["route"]) for item in records})
        },
        "artifact_count": len(contents),
        "artifact_type_counts": artifact_type_counts,
        "claim_count": len(claims),
        "merged_claim_count": len(merged_claims),
        "merged_manuscript_artifact_id": (merged or {}).get("artifact_id"),
        "final_lifecycle": final_state.get("lifecycle_status"),
        "workstreams": [
            {"route": item["route"], "status": item["status"], "step_index": item["current_step_index"]}
            for item in final_state.get("workstreams", [])
        ],
        "quality_assertions": {
            "mixed_route": (final_state.get("route_decision") or {}).get("primary_route") == "MIXED_METHODS",
            "two_workstreams": len(final_state.get("workstreams", [])) == 2,
            "both_routes_uploaded": uploaded_routes == {"QUALITATIVE", "EXPERIMENTAL"},
            "completed": final_state.get("lifecycle_status") == "COMPLETED",
            "claims_present": bool(claims),
            "merged_manuscript_present": merged is not None,
            "merged_components_present": (
                isinstance(merged_components, list)
                and {str(item.get("route")) for item in merged_components if isinstance(item, dict)}
                == {"QUALITATIVE", "EXPERIMENTAL"}
            ),
            "merged_claims_present": bool(merged_claims),
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    failed_assertions = [
        name for name, passed in report["quality_assertions"].items()
        if not passed
    ]
    if failed_assertions:
        raise RuntimeError(
            "Mixed Methods acceptance assertions failed: " + ", ".join(failed_assertions)
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
