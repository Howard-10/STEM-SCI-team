from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from stem_sci import api
from stem_sci.accounts import IdentityService
from stem_sci.artifacts.content_store import SQLiteArtifactContentStore
from stem_sci.context import ContextService
from stem_sci.context.provider import LocalContextProvider
from stem_sci.orchestration import ControlPlane, SQLiteControlPlaneRepository


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_research_memory_does_not_treat_an_analysis_question_as_a_goal() -> None:
    assert api._extract_research_memory_facts("你能分析一下这个回答为什么会误读吗？") == {}


def test_labelled_facts_are_saved_as_non_blocking_research_memory(tmp_path: Path, monkeypatch) -> None:
    """Structured details may be remembered without opening a checklist."""

    monkeypatch.setenv("STEM_SCI_EXTERNAL_SEARCH_PROVIDER", "none")
    context_service = ContextService(tmp_path / "context")
    monkeypatch.setattr(api, "service", context_service)
    monkeypatch.setattr(api.workflow_controller, "context_provider", LocalContextProvider(context_service))
    monkeypatch.setattr(api, "identity_service", IdentityService(tmp_path / "identity.db"))
    monkeypatch.setattr(api, "control_plane", ControlPlane(SQLiteControlPlaneRepository(tmp_path / "control.db")))
    monkeypatch.setattr(api, "artifact_content_store", SQLiteArtifactContentStore(tmp_path / "control.db"))
    client = TestClient(api.app)

    registration = client.post(
        "/api/v1/auth/register",
        json={"username": "compactintake", "email": "compact@example.test", "password": "research-pass-123"},
    )
    headers = _headers(registration.json()["access_token"])
    assert client.post(
        "/api/v1/projects",
        headers=headers,
        json={"project_id": "compact-project", "title": "Compact", "research_direction": "物理教学"},
    ).status_code == 200

    compact = client.post(
        "/api/v1/projects/compact-project/conversation/command",
        headers=headers,
        json={
            "project_id": "compact-project",
            "message": (
                "研究目标：比较计算建模与常规教学的计算思维变化；"
                "研究对象：本科一年级物理学生；"
                "预期贡献：为课程改进提供描述性证据；"
                "数据来源：去标识化前后测数据；"
                "研究方法：观察性前后测比较，不作因果结论；"
                "现实约束：需要课程许可，研究团队访问加密数据。"
            ),
        },
    )
    assert compact.status_code == 200, compact.text
    body = compact.json()
    assert body["kind"] == "qa"
    assert body.get("intake") is None
    user = api.identity_service.user_for_access_token(registration.json()["access_token"])
    memory = api.identity_service.get_research_memory(user, "compact-project")
    assert memory is not None
    assert memory.facts["data_source"].startswith("去标识化")
    assert memory.facts["research_focus"].startswith("本科一年级")


def test_open_question_does_not_create_a_six_step_intake(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("STEM_SCI_EXTERNAL_SEARCH_PROVIDER", "none")
    context_service = ContextService(tmp_path / "context")
    monkeypatch.setattr(api, "service", context_service)
    monkeypatch.setattr(api.workflow_controller, "context_provider", LocalContextProvider(context_service))
    monkeypatch.setattr(api, "identity_service", IdentityService(tmp_path / "identity.db"))
    monkeypatch.setattr(api, "control_plane", ControlPlane(SQLiteControlPlaneRepository(tmp_path / "control.db")))
    monkeypatch.setattr(api, "artifact_content_store", SQLiteArtifactContentStore(tmp_path / "control.db"))
    client = TestClient(api.app)

    registration = client.post(
        "/api/v1/auth/register",
        json={"username": "skipintake", "email": "skip@example.test", "password": "research-pass-123"},
    )
    headers = _headers(registration.json()["access_token"])
    assert client.post(
        "/api/v1/projects",
        headers=headers,
        json={"project_id": "skip-project", "title": "Skip", "research_direction": "物理教学"},
    ).status_code == 200
    question = client.post(
        "/api/v1/projects/skip-project/conversation/command",
        headers=headers,
        json={"project_id": "skip-project", "message": "请和我一起澄清本科物理教学中的计算建模研究。"},
    )
    assert question.status_code == 200, question.text
    assert question.json()["kind"] == "qa"
    assert question.json().get("intake") is None


def test_natural_conversation_builds_memory_before_explicit_orchestration(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("STEM_SCI_EXTERNAL_SEARCH_PROVIDER", "none")
    context_service = ContextService(tmp_path / "context")
    monkeypatch.setattr(api, "service", context_service)
    monkeypatch.setattr(api.workflow_controller, "context_provider", LocalContextProvider(context_service))
    monkeypatch.setattr(api, "identity_service", IdentityService(tmp_path / "identity.db"))
    monkeypatch.setattr(api, "control_plane", ControlPlane(SQLiteControlPlaneRepository(tmp_path / "control.db")))
    monkeypatch.setattr(api, "artifact_content_store", SQLiteArtifactContentStore(tmp_path / "control.db"))
    client = TestClient(api.app)

    registration = client.post(
        "/api/v1/auth/register",
        json={"username": "intakeuser", "email": "intake@example.test", "password": "research-pass-123"},
    )
    token = registration.json()["access_token"]
    headers = _headers(token)
    assert client.post(
        "/api/v1/projects",
        headers=headers,
        json={"project_id": "intake-project", "title": "Intake", "research_direction": "本科物理教学"},
    ).status_code == 200

    topic = client.post(
        "/api/v1/projects/intake-project/conversation/command",
        headers=headers,
        json={
            "project_id": "intake-project",
            "message": "请和我讨论一下。我想研究本科物理课里使用计算建模对学生学习体验的影响，先不要开始正式分析。",
        },
    )
    assert topic.status_code == 200, topic.text
    first = topic.json()
    assert first["kind"] == "qa"
    assert first["waiting_for_user"] is True
    assert first["gate"] is None
    assert first["route_decision"] is None
    assert first.get("intake") is None

    boundaries = client.post(
        "/api/v1/projects/intake-project/conversation/command",
        headers=headers,
        json={
            "project_id": "intake-project",
            "message": (
                "研究对象：某大学一年级普通物理必修课学生；"
                "数据来源：去标识化前后测和学习体验问卷；"
                "研究方法：只做描述性和关联分析，不做因果解释，也不进行个体随机分配。"
            ),
        },
    )
    assert boundaries.status_code == 200, boundaries.text
    second = boundaries.json()
    assert second["kind"] == "qa"
    assert second["gate"] is None
    assert second["route_decision"] is None
    assert second.get("intake") is None

    user = api.identity_service.user_for_access_token(token)
    memory = api.identity_service.get_research_memory(user, "intake-project")
    assert memory is not None
    assert "计算建模" in memory.facts["research_goal"]
    assert memory.facts["research_focus"].startswith("某大学一年级")
    assert memory.facts["data_source"].startswith("去标识化前后测")
    assert "不做因果" in memory.facts["method_boundary"]
    assert len(memory.source_messages) == 2
    assert api.identity_service.get_research_intake(user, "intake-project") is None

    started = client.post(
        "/api/v1/projects/intake-project/conversation/command",
        headers=headers,
        json={"project_id": "intake-project", "message": "现在直接检索相关真实论文。"},
    )
    assert started.status_code == 200, started.text
    assert started.json().get("intake") is None
    assert started.json()["gate"] is None
    assert started.json()["checkpoint"] == "RESEARCH_QUESTION_REVIEW"
    assert started.json()["route_decision"] is not None


def test_direct_search_skips_research_brief_and_search_command_never_answers_intake(
    tmp_path: Path, monkeypatch
) -> None:
    """An explicit direct-search request bypasses the mentoring brief."""

    monkeypatch.setenv("STEM_SCI_EXTERNAL_SEARCH_PROVIDER", "none")
    context_service = ContextService(tmp_path / "context")
    monkeypatch.setattr(api, "service", context_service)
    monkeypatch.setattr(api.workflow_controller, "context_provider", LocalContextProvider(context_service))
    identity = IdentityService(tmp_path / "identity.db")
    monkeypatch.setattr(api, "identity_service", identity)
    monkeypatch.setattr(api, "control_plane", ControlPlane(SQLiteControlPlaneRepository(tmp_path / "control.db")))
    monkeypatch.setattr(api, "artifact_content_store", SQLiteArtifactContentStore(tmp_path / "control.db"))
    client = TestClient(api.app)

    registration = client.post(
        "/api/v1/auth/register",
        json={"username": "searchfirst", "email": "searchfirst@example.test", "password": "research-pass-123"},
    )
    headers = _headers(registration.json()["access_token"])
    user = identity.get_user(registration.json()["user"]["user_id"])
    assert client.post(
        "/api/v1/projects",
        headers=headers,
        json={
            "project_id": "search-first-project",
            "title": "Search first",
            "research_direction": "高中物理教师计算思维整合",
        },
    ).status_code == 200

    topic = client.post(
        "/api/v1/projects/search-first-project/conversation/command",
        headers=headers,
        json={
            "project_id": "search-first-project",
            "message": "直接检索：我想研究高中物理教师如何通过同步在线 Python 专业学习整合计算思维到物理教学中，采用定性内容分析。",
        },
    )
    assert topic.status_code == 200, topic.text
    assert topic.json().get("intake") is None
    assert topic.json()["gate"] is None
    assert topic.json()["checkpoint"] == "RESEARCH_QUESTION_REVIEW"

    # Simulate a separate project created under the former intake-first behavior.
    assert client.post(
        "/api/v1/projects",
        headers=headers,
        json={
            "project_id": "legacy-intake-project",
            "title": "Legacy intake",
            "research_direction": "高中物理教师计算思维整合",
        },
    ).status_code == 200
    identity.start_research_intake(
        user,
        "legacy-intake-project",
        research_topic="高中物理教师计算思维整合的定性研究",
        first_question_key="research_focus",
    )
    identity.merge_research_intake_answers(
        user,
        "legacy-intake-project",
        answers={"research_focus": "高中物理教师", "data_source": "既有访谈记录"},
    )
    search = client.post(
        "/api/v1/projects/legacy-intake-project/conversation/command",
        headers=headers,
        json={"project_id": "legacy-intake-project", "message": "继续搜索：补充同步在线教师专业学习文献"},
    )
    assert search.status_code == 200, search.text
    assert search.json()["gate"] is None
    assert search.json()["checkpoint"] == "RESEARCH_QUESTION_REVIEW"
    deferred = client.get("/api/v1/projects/legacy-intake-project/research-intake", headers=headers)
    assert deferred.status_code == 200, deferred.text
    assert deferred.json()["status"] == "DEFERRED"
    assert deferred.json()["answers"]["research_focus"] == "高中物理教师"
    migrated = identity.get_research_memory(user, "legacy-intake-project")
    assert migrated is not None
    assert migrated.facts["research_topic"] == "高中物理教师计算思维整合的定性研究"
    assert migrated.facts["research_focus"] == "高中物理教师"


def test_uploaded_reference_is_visible_in_the_first_evidence_review_package(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("STEM_SCI_EXTERNAL_SEARCH_PROVIDER", "none")
    context_service = ContextService(tmp_path / "context")
    monkeypatch.setattr(api, "service", context_service)
    monkeypatch.setattr(api.workflow_controller, "context_provider", LocalContextProvider(context_service))
    monkeypatch.setattr(api, "identity_service", IdentityService(tmp_path / "identity.db"))
    monkeypatch.setattr(api, "control_plane", ControlPlane(SQLiteControlPlaneRepository(tmp_path / "control.db")))
    monkeypatch.setattr(api, "artifact_content_store", SQLiteArtifactContentStore(tmp_path / "control.db"))
    client = TestClient(api.app)

    registration = client.post(
        "/api/v1/auth/register",
        json={"username": "sourceuser", "email": "source@example.test", "password": "research-pass-123"},
    )
    headers = _headers(registration.json()["access_token"])
    assert client.post(
        "/api/v1/projects",
        headers=headers,
        json={"project_id": "source-project", "title": "Source", "research_direction": "物理计算建模"},
    ).status_code == 200
    assert client.post(
        "/api/v1/projects/source-project/documents",
        headers=headers,
        json={
            "title": "计算建模论文",
            "document_type": "reference",
            "format": "text",
            "content": "Python and VPython computational modelling supported physics students' computational thinking in a pretest posttest course study.",
        },
    ).status_code == 200

    command = client.post(
        "/api/v1/projects/source-project/conversation/command",
        headers=headers,
        json={
            "project_id": "source-project",
            "message": "直接检索：研究本科物理课程 Python 计算建模对学生计算思维和物理概念的影响，采用前测后测比较。",
        },
    )
    assert command.status_code == 200, command.text
    assert command.json()["gate"] is None
    assert command.json()["checkpoint"] == "RESEARCH_QUESTION_REVIEW"
    review = client.get("/api/v1/projects/source-project/evidence-review", headers=headers)
    assert review.status_code == 200, review.text
    coverage = review.json()["body"]["coverage"]
    assert coverage["source_count"] >= 1
    assert coverage["evidence_count"] >= 1
    assert review.json()["body"]["evidence_matrix"]
