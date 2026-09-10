from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from stem_sci.agents.contracts import AgentResult, ApprovalRequest
from stem_sci.artifacts.models import ArtifactRef
from stem_sci.controller.router import ControllerWorkflowState, PlanningRunResult
from stem_sci.core.enums import ProjectStage
from stem_sci.knowledge.qa_tools import QAToolExecutor, tool_definitions


def test_tool_definitions_expose_bounded_read_only_capabilities() -> None:
    names = [item["function"]["name"] for item in tool_definitions()]

    assert {
        "graph_search",
        "vector_search",
        "hybrid_search",
        "paper_lookup",
        "workflow_agent",
        "start_research_workflow",
        "get_workflow_status",
        "run_next_workflow_agent",
        "get_workflow_artifacts",
        "prepare_workflow_approval",
        "external_paper_search",
    }.issubset(names)
    assert all(
        item["function"]["parameters"]["additionalProperties"] is False
        for item in tool_definitions()
    )


def test_external_search_is_explicitly_fail_closed(monkeypatch) -> None:
    monkeypatch.setenv("STEM_SCI_EXTERNAL_SEARCH_PROVIDER", "none")
    result = QAToolExecutor(object()).execute(
        name="external_paper_search",
        arguments={"query": "graph rag"},
        project_id="demo",
        default_query="graph rag",
    )

    assert result["status"] == "NOT_CONFIGURED"
    assert "external_search_not_configured" in result["risk_flags"]


def test_external_search_returns_bibliographic_candidates(tmp_path) -> None:
    class FakeExternalSearch:
        def search(self, query: str, max_results: int = 8):
            return {
                "ok": True,
                "status": "OK",
                "provider": "openalex",
                "query": query,
                "results": [{"title": "A paper", "doi": "10.1234/example"}],
                "result_count": 1,
                "risk_flags": ["external_metadata_only"],
            }

        def save_candidates(self, *, project_id, query, results, storage_root):
            (storage_root / "external-discovery.db").write_bytes(b"test")
            return ["ext_test"]

    result = QAToolExecutor(
        object(), external_search=FakeExternalSearch(), storage_root=tmp_path
    ).execute(
        name="external_paper_search",
        arguments={"query": "graph rag", "max_results": 3},
        project_id="demo",
        default_query="graph rag",
    )

    assert result["status"] == "OK"
    assert result["provider"] == "openalex"
    assert result["results"][0]["doi"] == "10.1234/example"
    assert result["candidate_ids"]
    assert (tmp_path / "external-discovery.db").exists()


def test_external_search_reuses_recent_project_candidates(tmp_path) -> None:
    class CountingExternalSearch:
        def __init__(self):
            self.calls = 0

        def search(self, query: str, max_results: int = 8):
            self.calls += 1
            return {
                "ok": True,
                "status": "OK",
                "provider": "openalex",
                "query": query,
                "results": [{"title": "Computational thinking in physics education"}],
                "result_count": 1,
                "risk_flags": ["external_metadata_only"],
            }

        def save_candidates(self, *, project_id, query, results, storage_root):
            import json
            import sqlite3
            from datetime import UTC, datetime
            database = storage_root / "external-discovery.db"
            with sqlite3.connect(database) as connection:
                connection.execute(
                    "create table external_candidates (candidate_id text, project_id text, query text, provider text, title text, doi text, landing_page_url text, full_text_url text, payload text, status text, created_at text)"
                )
                item = results[0]
                connection.execute(
                    "insert into external_candidates values (?,?,?,?,?,?,?,?,?,?,?)",
                    ("ext_cached", project_id, query, "openalex", item["title"], None, None, None, json.dumps(item), "DISCOVERED", datetime.now(UTC).isoformat()),
                )
                connection.commit()
            return ["ext_cached"]

    client = CountingExternalSearch()
    executor = QAToolExecutor(
        object(), external_search=client, storage_root=tmp_path
    )
    first = executor.execute(
        name="external_paper_search", arguments={"query": "physics education"},
        project_id="demo", default_query="physics education",
    )
    second = executor.execute(
        name="external_paper_search", arguments={"query": "physics education"},
        project_id="demo", default_query="physics education",
    )

    assert first["ok"] is True
    assert second["ok"] is True
    assert client.calls == 1
    assert "external_cache_hit" in second["risk_flags"]


def test_workflow_tool_is_proposal_only() -> None:
    result = QAToolExecutor(object()).execute(
        name="workflow_agent",
        arguments={"agent": "EvidenceReviewAgent", "task": "review sources"},
        project_id="demo",
        default_query="review sources",
    )

    assert result["mode"] == "proposal_only"
    assert "does not create" in result["message"]


class FakeWorkflowController:
    def __init__(self) -> None:
        self.approval = ApprovalRequest(
            request_id="approval-1",
            artifact_ref="candidate://demo/ResearchScope",
            approval_type="research_scope",
            reason="Review the research scope.",
            risk_summary="Candidate output is not approved.",
        )
        self.state = ControllerWorkflowState(
            project_id="demo",
            current_stage=ProjectStage.WAITING_HUMAN,
            pending_approval_ref=self.approval.request_id,
        )

    def start_planning(self, request):
        result = SimpleNamespace(
            workflow_state=self.state,
            agent_result=SimpleNamespace(agent_id="mentor_planning"),
            approval_request=self.approval,
        )
        return PlanningRunResult.model_validate(
            {
                "workflow_state": result.workflow_state.model_dump(mode="json"),
                "agent_result": AgentResult(
                    agent_run_id="run-1",
                    agent_id="mentor_planning",
                    agent_version="v1",
                    candidate_artifact_refs=["candidate://demo/ResearchScope"],
                    created_at=datetime.now(UTC),
                ),
                "approval_request": self.approval,
                "route_decision": None,
            }
        )

    def get_state(self, _: str) -> ControllerWorkflowState:
        return self.state

    def get_pending_approval(self, _: str) -> ApprovalRequest:
        return self.approval


class FakeArtifactStore:
    def list_project(self, project_id: str) -> list[ArtifactRef]:
        return [
            ArtifactRef(
                artifact_id="artifact-1",
                project_id=project_id,
                artifact_type="ResearchScope",
                version=1,
                content_uri="artifact-content://demo/artifact-1/1",
                sha256="a" * 64,
                created_at=datetime.now(UTC),
                created_by="mentor_planning",
            )
        ]


def test_workflow_tools_call_controller_and_prepare_approval() -> None:
    executor = QAToolExecutor(
        object(),
        workflow_controller=FakeWorkflowController(),
        artifact_store=FakeArtifactStore(),
    )

    started = executor.execute(
        name="start_research_workflow",
        arguments={"research_intent": "研究虚拟现实物理教学"},
        project_id="demo",
        default_query="研究虚拟现实物理教学",
    )
    assert started["status"] == "STARTED"
    assert started["workflow_action"]["selected_agent"] == "mentor_planning"

    approval = executor.execute(
        name="prepare_workflow_approval",
        arguments={},
        project_id="demo",
        default_query="批准",
    )
    assert approval["status"] == "APPROVAL_REQUIRED"
    assert approval["workflow_action"]["confirmation_required"] is True
    assert approval["workflow_action"]["approval_request_id"] == "approval-1"

    artifacts = executor.execute(
        name="get_workflow_artifacts",
        arguments={},
        project_id="demo",
        default_query="查看工件",
    )
    assert artifacts["workflow_action"]["artifacts"][0]["artifact_type"] == "ResearchScope"
