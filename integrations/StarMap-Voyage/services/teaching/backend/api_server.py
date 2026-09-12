"""
星图学航 2.0 API Server
基于Few-shot教案生成的STEM自适应探究学习系统
"""
import json
import os
import re
import shutil
import sys
import uuid
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse, FileResponse, Response
from pydantic import BaseModel, Field, field_validator

# Local development reads credentials from the integration root. Production
# may continue to inject the same variables through systemd/Docker.
load_dotenv(Path(__file__).resolve().parents[3] / ".env", override=False)

from agents.plan_generator import generate_teaching_plan, get_bubble_topics
from agents.project_tutor import ProjectTutor
from agents.threed_designer import ThreeDDesignerAgent
from agents.arduino_gen import ArduinoCodeGenerator
from agents.difficulty_adapter import DifficultyAdapter
from agents.code_assistant import get_code_assistant
from agents.llm_config import resolve_chat_config
from api.literature import router as literature_router
from api.experiment import router as experiment_router

threed_agent = ThreeDDesignerAgent()
arduino_gen = ArduinoCodeGenerator()
difficulty_adapter = DifficultyAdapter()
code_assistant = get_code_assistant()
_LLM_CONFIG = resolve_chat_config()

# ---- App Init ----
APP_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(APP_DIR)
FRONTEND_DIR = os.path.join(PROJECT_ROOT, "frontend")
PROJECTS_DIR = os.path.join(PROJECT_ROOT, "projects")
DATA_DIR = os.path.join(PROJECT_ROOT, "data")

os.makedirs(PROJECTS_DIR, exist_ok=True)

app = FastAPI(title="星图学航 2.0 - 基于Few-shot教案生成的STEM自适应探究学习系统")

# Register sub-API modules
app.include_router(literature_router)
app.include_router(experiment_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve frontend
if os.path.isdir(FRONTEND_DIR):
    app.mount("/app", StaticFiles(directory=FRONTEND_DIR, html=True), name="app")

# In-memory tutor sessions
tutor_sessions: Dict[str, ProjectTutor] = {}


# ---- Schemas ----
class PlanGenerateRequest(BaseModel):
    query: str
    grade_level: str = "初中"
    difficulty: Optional[int] = None
    include_3d_print: bool = True


class TutorChatRequest(BaseModel):
    project_id: str
    message: str


class ProjectPublishRequest(BaseModel):
    plan_markdown: str
    title: str
    grade_level: str


class ExportDocxRequest(BaseModel):
    markdown: str
    title: str = "教学设计"


class ResearchGenRequest(BaseModel):
    plan_markdown: str
    title: str = "教学设计"
    grade_level: str = "初中"


# ---- API Endpoints ----

@app.get("/")
async def root():
    if os.path.isdir(FRONTEND_DIR):
        return RedirectResponse(url="/app/")
    return {"message": "星图学航 2.0 API 在线"}


@app.get("/api/health")
async def health():
    return {"status": "ok", "time": datetime.now().isoformat()}


# -------- Bubble Homepage --------

@app.get("/api/bubbles")
async def get_bubbles():
    """Return the 12 bubble topics for the homepage."""
    return {"bubbles": get_bubble_topics()}


@app.get("/api/projects")
async def list_projects():
    """List all published project spaces."""
    projects = []
    if os.path.isdir(PROJECTS_DIR):
        for proj_id in os.listdir(PROJECTS_DIR):
            proj_path = os.path.join(PROJECTS_DIR, proj_id)
            meta_path = os.path.join(proj_path, "meta.json")
            if os.path.exists(meta_path):
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                meta["id"] = proj_id
                projects.append(meta)
    return {"projects": sorted(projects, key=lambda p: p.get("created_at", ""), reverse=True)}


# -------- Teaching Plan Generation --------

@app.post("/api/generate-plan")
def api_generate_plan(req: PlanGenerateRequest):
    """Generate a STEM teaching plan for a student query."""
    try:
        result = generate_teaching_plan(
            user_query=req.query,
            grade_level=req.grade_level,
            difficulty=req.difficulty,
            include_3d_print=req.include_3d_print
        )
        return {
            "success": True,
            "plan": result
        }
    except Exception as e:
        detail = str(e)
        status = 503 if "API key" in detail or "LLM API error" in detail else 500
        raise HTTPException(status_code=status, detail=f"教案生成失败: {detail}")


@app.post("/api/publish-project")
async def api_publish_project(req: ProjectPublishRequest):
    """Save a generated teaching plan as a project space."""
    project_id = f"proj_{uuid.uuid4().hex[:8]}"
    proj_path = os.path.join(PROJECTS_DIR, project_id)
    os.makedirs(proj_path, exist_ok=True)

    # Save plan markdown
    plan_path = os.path.join(proj_path, "教案.md")
    with open(plan_path, "w", encoding="utf-8") as f:
        f.write(req.plan_markdown)

    # Create subdirectories
    os.makedirs(os.path.join(proj_path, "code"), exist_ok=True)
    os.makedirs(os.path.join(proj_path, "3d_models"), exist_ok=True)
    os.makedirs(os.path.join(proj_path, "data"), exist_ok=True)

    # Detect 3D print needs and generate models
    has_3d = any(kw in req.plan_markdown for kw in ["3D打印", "3d打印", "STL", "打印件", "三维模型"])
    generated_3d = []
    if has_3d:
        try:
            generated_3d = threed_agent.generate_all(req.plan_markdown, proj_path)
        except Exception as e:
            print(f"3D模型生成失败(非致命): {e}")

    # Extract code blocks and save
    code_blocks = re.findall(r'```(?:python|arduino|cpp|ino)?\s*\n(.*?)```', req.plan_markdown, re.DOTALL)
    code_files_count = len(code_blocks)
    for i, code in enumerate(code_blocks):
        if "void " in code or "pinMode" in code or "digitalWrite" in code:
            ext = ".ino"
        elif "import " in code or "def " in code:
            ext = ".py"
        else:
            ext = ".txt"
        code_path = os.path.join(proj_path, "code", f"code_{i+1}{ext}")
        with open(code_path, "w", encoding="utf-8") as f:
            f.write(code.strip())

    # Auto-generate Arduino code if sensors detected
    arduino_result = {"generated": False}
    try:
        arduino_result = arduino_gen.generate_all(req.plan_markdown, proj_path)
        if arduino_result.get("generated"):
            code_files_count += len(arduino_result.get("files", []))
    except Exception as e:
        print(f"Arduino代码生成失败(非致命): {e}")

    # Save metadata
    meta = {
        "title": req.title,
        "grade_level": req.grade_level,
        "created_at": datetime.now().isoformat(),
        "has_3d_print": has_3d,
        "code_files": code_files_count,
        "3d_models": len(generated_3d),
        "arduino_sensors": arduino_result.get("sensors_detected", []),
        "status": "published"
    }
    with open(os.path.join(proj_path, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    return {
        "success": True,
        "project_id": project_id,
        "project_path": proj_path,
        "plan_markdown": req.plan_markdown,
        "meta": meta
    }


# -------- Project Space --------

@app.get("/api/project/{project_id}")
async def get_project(project_id: str):
    """Get project details including plan, code, and files."""
    proj_path = os.path.join(PROJECTS_DIR, project_id)
    if not os.path.isdir(proj_path):
        raise HTTPException(status_code=404, detail="项目不存在")

    result = {"id": project_id, "path": proj_path}

    # Load metadata
    meta_path = os.path.join(proj_path, "meta.json")
    if os.path.exists(meta_path):
        with open(meta_path, "r", encoding="utf-8") as f:
            result["meta"] = json.load(f)

    # Load plan
    plan_path = os.path.join(proj_path, "教案.md")
    if os.path.exists(plan_path):
        with open(plan_path, "r", encoding="utf-8") as f:
            result["plan_markdown"] = f.read()

    # List files
    files = {}
    for subdir in ["code", "3d_models", "data"]:
        subpath = os.path.join(proj_path, subdir)
        if os.path.exists(subpath):
            files[subdir] = os.listdir(subpath)
    result["files"] = files

    return result


@app.post("/api/export-docx")
async def export_docx(req: ExportDocxRequest):
    """把教学设计 markdown 转成 Word (.docx) 文档返回。"""
    from urllib.parse import quote
    from export_docx import markdown_to_docx_bytes

    title = (req.title or "教学设计").strip()[:80]
    try:
        docx_bytes = markdown_to_docx_bytes(req.markdown, title)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DOCX 生成失败: {str(e)}")

    filename = quote(f"{title}.docx")
    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


# -------- 师范生助研（说课稿 / 教学反思 / 教材课标分析） --------

@app.post("/api/research/shuoke")
async def api_research_shuoke(req: ResearchGenRequest):
    """基于教案生成说课稿。"""
    from agents.teaching_research_skill import generate_shuoke
    try:
        result = generate_shuoke(req.plan_markdown, req.title, req.grade_level)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"说课稿生成失败: {str(e)}")
    return {"success": True, "result": result}


@app.post("/api/research/reflection")
async def api_research_reflection(req: ResearchGenRequest):
    """基于教案生成教学反思。"""
    from agents.teaching_research_skill import generate_reflection
    try:
        result = generate_reflection(req.plan_markdown, req.title)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"教学反思生成失败: {str(e)}")
    return {"success": True, "result": result}


@app.post("/api/research/analysis")
async def api_research_analysis(req: ResearchGenRequest):
    """基于教案生成教材/课标分析。"""
    from agents.teaching_research_skill import generate_curriculum_analysis
    try:
        result = generate_curriculum_analysis(req.plan_markdown, req.title, req.grade_level)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"教材课标分析生成失败: {str(e)}")
    return {"success": True, "result": result}


@app.delete("/api/project/{project_id}")
async def delete_project(project_id: str):
    """Delete a teaching project."""
    proj_path = os.path.join(PROJECTS_DIR, project_id)
    if not os.path.isdir(proj_path):
        raise HTTPException(status_code=404, detail="项目不存在")

    import shutil
    shutil.rmtree(proj_path)
    return {"success": True, "message": f"项目 {project_id} 已删除"}


@app.get("/api/project/{project_id}/file/{filepath:path}")
async def get_project_file(project_id: str, filepath: str):
    """Serve a project file."""
    full_path = os.path.join(PROJECTS_DIR, project_id, filepath)
    full_path = os.path.normpath(full_path)
    if not full_path.startswith(os.path.normpath(os.path.join(PROJECTS_DIR, project_id))):
        raise HTTPException(status_code=403, detail="路径遍历禁止")

    if not os.path.isfile(full_path):
        raise HTTPException(status_code=404, detail="文件不存在")

    return FileResponse(full_path)


# -------- Code Sandbox --------

@app.post("/api/run-code")
async def run_code(code: str = None, language: str = "python", file: UploadFile = File(None)):
    """Execute code in sandbox (Python only for now)."""
    execution_enabled = os.environ.get("STARMAP_ENABLE_CODE_EXECUTION", "").strip().lower()
    if execution_enabled not in {"1", "true", "yes"}:
        raise HTTPException(
            status_code=403,
            detail="代码执行默认关闭；仅可信本地环境可设置 STARMAP_ENABLE_CODE_EXECUTION=true 启用。",
        )

    if file:
        code = (await file.read()).decode("utf-8")
    if not code:
        raise HTTPException(status_code=400, detail="请提供代码")

    if language != "python":
        raise HTTPException(status_code=400, detail="目前仅支持Python代码执行")

    # Write to temp file and execute
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8")
    try:
        tmp.write(code)
        tmp.close()

        result = subprocess.run(
            [sys.executable, tmp.name],
            capture_output=True, text=True, timeout=30, encoding="utf-8", errors="replace"
        )

        return {
            "stdout": result.stdout[:5000] if result.stdout else "",
            "stderr": result.stderr[:5000] if result.stderr else "",
            "returncode": result.returncode
        }
    except subprocess.TimeoutExpired:
        return {"stdout": "", "stderr": "代码执行超时（30秒）", "returncode": -1}
    except Exception as e:
        return {"stdout": "", "stderr": str(e), "returncode": -1}
    finally:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass


# -------- AI Tutor --------

@app.post("/api/tutor/start")
async def tutor_start(project_id: str):
    """Start a new AI tutor session for a project."""
    proj_path = os.path.join(PROJECTS_DIR, project_id)
    if not os.path.isdir(proj_path):
        raise HTTPException(status_code=404, detail="项目不存在")

    session_id = uuid.uuid4().hex[:8]
    tutor = ProjectTutor(proj_path)
    tutor_sessions[session_id] = tutor

    return {
        "session_id": session_id,
        "project_id": project_id,
        "info": tutor.get_summary()
    }


@app.post("/api/tutor/chat")
async def tutor_chat(req: TutorChatRequest):
    """Chat with the project AI tutor."""
    # Use project_id as session key (simplified - one session per project)
    session_key = f"tutor_{req.project_id}"

    if session_key not in tutor_sessions:
        proj_path = os.path.join(PROJECTS_DIR, req.project_id)
        if not os.path.isdir(proj_path):
            raise HTTPException(status_code=404, detail="项目不存在")
        tutor_sessions[session_key] = ProjectTutor(proj_path)

    tutor = tutor_sessions[session_key]
    reply = tutor.chat(req.message)

    return {
        "reply": reply,
        "session_key": session_key
    }


@app.post("/api/tutor/reset")
async def tutor_reset(project_id: str):
    """Reset the AI tutor conversation."""
    session_key = f"tutor_{project_id}"
    if session_key in tutor_sessions:
        tutor_sessions[session_key].reset()
    return {"status": "ok"}


# -------- 3D Model Generation --------

class Analyze3DRequest(BaseModel):
    plan_markdown: str


@app.post("/api/analyze-3d-opportunities")
async def api_analyze_3d(req: Analyze3DRequest):
    """Analyze a teaching plan for 3D printing opportunities."""
    tasks = threed_agent.analyze_plan(req.plan_markdown)
    return {"opportunities": tasks, "count": len(tasks)}


@app.post("/api/generate-3d-models")
async def api_generate_3d(project_id: str = None, plan_markdown: str = None):
    """Generate 3D models for a project or plan content."""
    if project_id:
        proj_path = os.path.join(PROJECTS_DIR, project_id)
        if not os.path.isdir(proj_path):
            raise HTTPException(status_code=404, detail="项目不存在")
        plan_path = os.path.join(proj_path, "教案.md")
        if os.path.exists(plan_path):
            with open(plan_path, "r", encoding="utf-8") as f:
                plan_markdown = f.read()

    if not plan_markdown:
        raise HTTPException(status_code=400, detail="请提供plan_markdown或project_id")

    if project_id:
        proj_path = os.path.join(PROJECTS_DIR, project_id)
    else:
        proj_path = tempfile.mkdtemp()

    generated = threed_agent.generate_all(plan_markdown, proj_path)

    return {
        "success": True,
        "models": [{
            "filename": g["filename"],
            "name": g["name"],
            "template": g["template"],
            "params": g["params"],
            "reason": g["reason"],
            "priority": g["priority"]
        } for g in generated],
        "count": len(generated)
    }


@app.get("/api/project/{project_id}/3d-preview/{filename}")
async def api_3d_preview(project_id: str, filename: str):
    """Get OpenSCAD code for preview."""
    filepath = os.path.join(PROJECTS_DIR, project_id, "3d_models", filename)
    filepath = os.path.normpath(filepath)
    if not filepath.startswith(os.path.normpath(os.path.join(PROJECTS_DIR, project_id))):
        raise HTTPException(status_code=403, detail="路径遍历禁止")
    if not os.path.isfile(filepath):
        raise HTTPException(status_code=404, detail="文件不存在")

    with open(filepath, "r", encoding="utf-8") as f:
        code = f.read()
    return {"filename": filename, "scad_code": code}


# -------- Arduino Code Generation --------

class ArduinoGenerateRequest(BaseModel):
    plan_markdown: str
    board: str = "arduino:avr:uno"


@app.post("/api/detect-sensors")
async def api_detect_sensors(req: Analyze3DRequest):
    """Detect Arduino-compatible sensors/components in a plan."""
    sensors = arduino_gen.detect_sensors(req.plan_markdown)
    return {"sensors": sensors, "count": len(sensors)}


@app.post("/api/generate-arduino")
async def api_generate_arduino(req: ArduinoGenerateRequest):
    """Generate Arduino code based on detected components."""
    sensors = arduino_gen.detect_sensors(req.plan_markdown)
    sketch = arduino_gen.generate_sketch(sensors, "STEM_Project", req.board)

    return {
        "success": True,
        "sensors_detected": [s["id"] for s in sensors],
        "sketch": sketch,
        "board": req.board
    }


@app.post("/api/compile-arduino")
async def api_compile_arduino(sketch_code: str = None, board: str = "arduino:avr:uno"):
    """Compile-check Arduino sketch (requires arduino-cli)."""
    if not sketch_code:
        raise HTTPException(status_code=400, detail="请提供sketch_code")

    result = arduino_gen.compile_check(sketch_code, board)
    return result


# -------- Code Assistant --------

class CodeExplainRequest(BaseModel):
    code: str
    language: str = "python"


class CodeGenerateRequest(BaseModel):
    description: str
    language: str = "python"
    context: str = ""


class CodeDebugRequest(BaseModel):
    code: str
    error_msg: str = ""
    language: str = "python"


class CodeReviewRequest(BaseModel):
    code: str
    language: str = "python"
    requirements: str = ""


@app.post("/api/code/explain")
async def api_code_explain(req: CodeExplainRequest):
    """Explain what a piece of code does."""
    result = code_assistant.explain_code(req.code, req.language)
    return {"success": True, "explanation": result}


@app.post("/api/code/generate")
async def api_code_generate(req: CodeGenerateRequest):
    """Generate code from natural language description."""
    result = code_assistant.generate_code(req.description, req.language, req.context)
    return {"success": True, "code": result}


@app.post("/api/code/debug")
async def api_code_debug(req: CodeDebugRequest):
    """Debug code with error analysis."""
    result = code_assistant.debug_code(req.code, req.error_msg, req.language)
    return {"success": True, "debug_result": result}


@app.post("/api/code/review")
async def api_code_review(req: CodeReviewRequest):
    """Review code quality."""
    result = code_assistant.review_code(req.code, req.language, req.requirements)
    return {"success": True, "review": result}


# -------- Code Design Agent (interactive) --------

# Store active code design sessions
code_design_sessions: Dict[str, List[Dict]] = {}


@app.post("/api/code/design/start")
async def code_design_start(project_id: str = "", requirements: str = ""):
    """Start an interactive code design session."""
    session_id = uuid.uuid4().hex[:8]

    # Gather project context
    context = ""
    if project_id:
        proj_path = os.path.join(PROJECTS_DIR, project_id)
        plan_path = os.path.join(proj_path, "教案.md")
        if os.path.exists(plan_path):
            with open(plan_path, "r", encoding="utf-8") as f:
                plan = f.read()
                # Extract materials and objectives sections
                materials_match = re.search(r'## 你需要准备什么\？\n(.*?)(?=##|\Z)', plan, re.DOTALL)
                objectives_match = re.search(r'## 你需要学会什么\？\n(.*?)(?=##|\Z)', plan, re.DOTALL)
                if materials_match:
                    context += f"项目材料:\n{materials_match.group(1)[:500]}\n"
                if objectives_match:
                    context += f"学习目标:\n{objectives_match.group(1)[:500]}\n"

    system_msg = f"""你是一个STEM编程设计助手。你的任务是帮助学生设计和编写代码。

## 你的工作方式
1. 先理解学生想要实现什么功能
2. 分析需要哪些硬件/库/数据
3. 设计代码结构（函数划分、数据流）
4. 逐步生成代码，每次一个完整的功能模块
5. 每段代码都要有详细的中文注释

## 项目背景
{context if context else "通用STEM项目"}

## 规则
- 用鼓励的语气，让学生感觉编程不难
- 先给思路再给代码，不要一次性输出全部
- 代码要完整可运行
- 如果是Arduino，注意引脚分配
- 每步询问学生是否理解、是否需要调整
"""

    code_design_sessions[session_id] = [
        {"role": "system", "content": system_msg}
    ]

    welcome = "你好！我是代码设计助手 🤖\n\n请告诉我你想实现什么功能？比如：\n- \"我想让Arduino读取温度传感器并在OLED上显示\"\n- \"我需要一个Python程序来分析CSV数据并画图\"\n\n你也可以直接粘贴现有代码，我会帮你分析和改进。"

    if requirements:
        code_design_sessions[session_id].append({"role": "user", "content": requirements})
        reply = _code_design_reply(session_id)
        return {"session_id": session_id, "reply": reply}

    return {"session_id": session_id, "reply": welcome}


@app.post("/api/code/design/chat")
async def code_design_chat(session_id: str, message: str, current_code: str = ""):
    """Continue the code design conversation."""
    if session_id not in code_design_sessions:
        raise HTTPException(status_code=404, detail="会话不存在，请先 start")

    # Include current code as context
    if current_code:
        message = f"{message}\n\n[当前编辑器中的代码]\n```\n{current_code[:2000]}\n```"

    code_design_sessions[session_id].append({"role": "user", "content": message})
    reply = _code_design_reply(session_id)
    return {"reply": reply}


@app.post("/api/code/design/import")
async def code_design_import(session_id: str = None, code: str = "", project_id: str = ""):
    """Import code into the design session for analysis."""
    if not session_id:
        # Start a new session with the imported code
        result = await code_design_start(project_id)
        session_id = result["session_id"]

    analyze_msg = f"我导入了以下代码，请帮我分析：\n\n```\n{code[:3000]}\n```\n\n请告诉我：1)这段代码做什么 2)有什么可以改进的 3)如何扩展功能"
    code_design_sessions[session_id].append({"role": "user", "content": analyze_msg})
    reply = _code_design_reply(session_id)
    return {"session_id": session_id, "reply": reply}


def _code_design_reply(session_id: str) -> str:
    """Generate reply from the code design agent."""
    messages = code_design_sessions.get(session_id, [])
    if len(messages) > 20:
        messages = [messages[0]] + messages[-19:]  # Keep system + last 19

    try:
        resp = requests.post(
            _LLM_CONFIG["url"],
            json={
                "model": _LLM_CONFIG["model"],
                "messages": messages,
                "max_tokens": 2048,
                "temperature": 0.5,
            },
            headers={"Authorization": f"Bearer {_LLM_CONFIG['api_key']}"},
            timeout=90
        )
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"]
        return f"AI服务暂时不可用 (HTTP {resp.status_code})，请稍后重试。"
    except Exception as e:
        return f"请求失败: {str(e)}"


# -------- Adaptive Difficulty --------

class QuizAnswers(BaseModel):
    topic: str = "STEM项目"
    grade_level: str = "初中"
    quiz_questions: Optional[List[Dict]] = None  # Reuse existing quiz
    answers: Dict[str, str] = Field(default_factory=dict)

    @field_validator("topic", mode="before")
    @classmethod
    def normalize_topic(cls, value: object) -> str:
        return str(value).strip() if value is not None and str(value).strip() else "STEM项目"

    @field_validator("grade_level", mode="before")
    @classmethod
    def normalize_grade_level(cls, value: object) -> str:
        return str(value).strip() if value is not None and str(value).strip() else "初中"

    @field_validator("answers", mode="before")
    @classmethod
    def normalize_answers(cls, value: object) -> Dict[str, str]:
        return value if isinstance(value, dict) else {}


class AdaptivePlanRequest(BaseModel):
    query: str = "STEM项目"
    grade_level: str = "初中"
    quiz_questions: Optional[List[Dict]] = None
    answers: Optional[Dict[str, str]] = None
    include_3d_print: bool = True

    @field_validator("query", mode="before")
    @classmethod
    def normalize_query(cls, value: object) -> str:
        return str(value).strip() if value is not None and str(value).strip() else "STEM项目"

    @field_validator("grade_level", mode="before")
    @classmethod
    def normalize_plan_grade_level(cls, value: object) -> str:
        return str(value).strip() if value is not None and str(value).strip() else "初中"

    @field_validator("answers", mode="before")
    @classmethod
    def normalize_plan_answers(cls, value: object) -> Optional[Dict[str, str]]:
        return value if isinstance(value, dict) else None


def _difficulty_from_assessment(level: object) -> Optional[int]:
    """Convert quiz proficiency labels into the plan generator's 1-4 scale."""
    return {
        "beginner": 1,
        "basic": 2,
        "intermediate": 3,
        "advanced": 4,
    }.get(str(level).strip().lower())


@app.post("/api/generate-quiz")
async def api_generate_quiz(topic: str = None, grade_level: str = "初中", query: str = None):
    """Generate a knowledge assessment quiz for a topic."""
    subject = topic or query or "STEM项目"
    quiz = difficulty_adapter.generate_quiz(subject, grade_level)
    return {"success": True, "quiz": quiz}


@app.post("/api/assess-quiz")
async def api_assess_quiz(req: QuizAnswers):
    """Assess quiz answers and return knowledge gaps. Reuses existing quiz if provided."""
    if req.quiz_questions:
        quiz = {"topic": req.topic, "grade_level": req.grade_level, "questions": req.quiz_questions}
    else:
        quiz = difficulty_adapter.generate_quiz(req.topic, req.grade_level)
    result = difficulty_adapter.assess_results(quiz, req.answers)
    return {"success": True, "assessment": result}


@app.post("/api/generate-plan-adaptive")
async def api_generate_plan_adaptive(req: AdaptivePlanRequest):
    """Generate adaptive teaching plan. Reuses provided quiz to avoid duplicate LLM calls."""
    assessment = None
    prerequisites = ""
    adjusted_grade = req.grade_level

    if req.answers and req.quiz_questions:
        quiz = {"topic": req.query, "grade_level": req.grade_level, "questions": req.quiz_questions}
        assessment = difficulty_adapter.assess_results(quiz, req.answers)

        if assessment.get("knowledge_gaps"):
            prerequisites = difficulty_adapter.generate_prerequisites(
                assessment["knowledge_gaps"], req.query, req.grade_level
            )

        if assessment["score"] < 40:
            levels = ["小学低段", "小学中段", "小学高段", "初中", "高中"]
            current_idx = levels.index(req.grade_level) if req.grade_level in levels else 2
            adjusted_grade = levels[max(0, current_idx - 1)]

    elif req.answers:
        quiz = difficulty_adapter.generate_quiz(req.query, req.grade_level)
        assessment = difficulty_adapter.assess_results(quiz, req.answers)

    plan = generate_teaching_plan(
        user_query=req.query,
        grade_level=adjusted_grade,
        difficulty=_difficulty_from_assessment(assessment.get("level")) if assessment else None,
        include_3d_print=req.include_3d_print
    )

    if prerequisites:
        plan["markdown"] = difficulty_adapter.inject_prerequisites(plan["markdown"], prerequisites)
        plan["has_prerequisites"] = True
        plan["prerequisite_content"] = prerequisites
    else:
        plan["has_prerequisites"] = False

    plan["assessment"] = assessment
    return {"success": True, "plan": plan}


# -------- Collaboration --------

class CollabJoinRequest(BaseModel):
    project_id: str
    student_name: str
    role: str = "member"  # leader or member


@app.post("/api/collab/create-team")
async def create_team(project_id: str, leader_name: str):
    """Create a collaboration team for a project."""
    proj_path = os.path.join(PROJECTS_DIR, project_id)
    if not os.path.isdir(proj_path):
        raise HTTPException(status_code=404, detail="项目不存在")

    team_path = os.path.join(proj_path, "team.json")
    team = {
        "project_id": project_id,
        "created_at": datetime.now().isoformat(),
        "members": [{
            "name": leader_name,
            "role": "leader",
            "joined_at": datetime.now().isoformat()
        }],
        "chat_history": [{
            "type": "system",
            "message": f"团队已创建！{leader_name} 是组长。",
            "timestamp": datetime.now().isoformat()
        }],
        "shared_code": "",
        "activity_log": [{
            "action": "team_created",
            "user": leader_name,
            "timestamp": datetime.now().isoformat()
        }]
    }

    with open(team_path, "w", encoding="utf-8") as f:
        json.dump(team, f, ensure_ascii=False, indent=2)

    return {"success": True, "team": team}


@app.post("/api/collab/join")
async def join_team(req: CollabJoinRequest):
    """Join an existing team."""
    team_path = os.path.join(PROJECTS_DIR, req.project_id, "team.json")
    if not os.path.exists(team_path):
        raise HTTPException(status_code=404, detail="团队不存在，请先创建团队")

    with open(team_path, "r", encoding="utf-8") as f:
        team = json.load(f)

    if len(team["members"]) >= 3:
        raise HTTPException(status_code=400, detail="团队最多3人")

    if any(m["name"] == req.student_name for m in team["members"]):
        raise HTTPException(status_code=400, detail="该学生已在团队中")

    team["members"].append({
        "name": req.student_name,
        "role": req.role,
        "joined_at": datetime.now().isoformat()
    })
    team["chat_history"].append({
        "type": "system",
        "message": f"{req.student_name} 加入了团队！",
        "timestamp": datetime.now().isoformat()
    })
    team["activity_log"].append({
        "action": "member_joined",
        "user": req.student_name,
        "timestamp": datetime.now().isoformat()
    })

    with open(team_path, "w", encoding="utf-8") as f:
        json.dump(team, f, ensure_ascii=False, indent=2)

    return {"success": True, "team": team}


@app.get("/api/collab/team/{project_id}")
async def get_team(project_id: str):
    """Get team info for a project."""
    team_path = os.path.join(PROJECTS_DIR, project_id, "team.json")
    if not os.path.exists(team_path):
        return {"has_team": False}
    with open(team_path, "r", encoding="utf-8") as f:
        team = json.load(f)
    team["has_team"] = True
    return team


@app.post("/api/collab/chat")
async def collab_chat(project_id: str, student_name: str, message: str):
    """Send a message in the team chat."""
    team_path = os.path.join(PROJECTS_DIR, project_id, "team.json")
    if not os.path.exists(team_path):
        raise HTTPException(status_code=404, detail="团队不存在")

    with open(team_path, "r", encoding="utf-8") as f:
        team = json.load(f)

    team["chat_history"].append({
        "type": "user",
        "user": student_name,
        "message": message,
        "timestamp": datetime.now().isoformat()
    })

    # Also get AI tutor response
    session_key = f"tutor_{project_id}"
    ai_reply = "收到！关于这个问题..."
    if session_key in tutor_sessions:
        try:
            ai_reply = tutor_sessions[session_key].chat(f"[{student_name}问] {message}")
        except:
            pass

    team["chat_history"].append({
        "type": "assistant",
        "message": ai_reply,
        "timestamp": datetime.now().isoformat()
    })

    # Keep only last 100 messages
    if len(team["chat_history"]) > 100:
        team["chat_history"] = team["chat_history"][-100:]

    with open(team_path, "w", encoding="utf-8") as f:
        json.dump(team, f, ensure_ascii=False, indent=2)

    return {"reply": ai_reply, "chat_history": team["chat_history"][-20:]}


@app.get("/api/collab/activity/{project_id}")
async def get_activity(project_id: str):
    """Get team activity log."""
    team_path = os.path.join(PROJECTS_DIR, project_id, "team.json")
    if not os.path.exists(team_path):
        return {"activities": []}
    with open(team_path, "r", encoding="utf-8") as f:
        team = json.load(f)
    return {"activities": team.get("activity_log", [])}


# -------- Student Progress --------

@app.get("/api/progress/{student_id}")
async def get_progress(student_id: str):
    """Get a student's learning progress (simplified - file-based)."""
    progress_path = os.path.join(DATA_DIR, "progress", f"{student_id}.json")
    if not os.path.exists(progress_path):
        return {"student_id": student_id, "completed_projects": [], "knowledge_stars": []}
    with open(progress_path, "r", encoding="utf-8") as f:
        return json.load(f)


@app.post("/api/progress/{student_id}")
async def update_progress(student_id: str, project_id: str = None, concept: str = None):
    """Update student progress when completing a project or learning a concept."""
    progress_dir = os.path.join(DATA_DIR, "progress")
    os.makedirs(progress_dir, exist_ok=True)
    progress_path = os.path.join(progress_dir, f"{student_id}.json")

    progress = {"student_id": student_id, "completed_projects": [], "knowledge_stars": []}
    if os.path.exists(progress_path):
        with open(progress_path, "r", encoding="utf-8") as f:
            progress = json.load(f)

    if project_id and project_id not in progress["completed_projects"]:
        progress["completed_projects"].append(project_id)
    if concept and concept not in progress["knowledge_stars"]:
        progress["knowledge_stars"].append(concept)

    with open(progress_path, "w", encoding="utf-8") as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)

    return progress


# -------- Notes System --------

class NoteSaveRequest(BaseModel):
    project_id: str
    stage_id: str
    content: str


@app.post("/api/notes/save")
async def save_note(req: NoteSaveRequest):
    """Save a note for a specific project stage."""
    notes_dir = os.path.join(PROJECTS_DIR, req.project_id, "notes")
    os.makedirs(notes_dir, exist_ok=True)
    note_path = os.path.join(notes_dir, f"{req.stage_id}.md")
    with open(note_path, "w", encoding="utf-8") as f:
        f.write(req.content)
    return {"success": True}


@app.get("/api/notes/{project_id}/{stage_id}")
async def load_note(project_id: str, stage_id: str):
    """Load a note for a specific project stage."""
    note_path = os.path.join(PROJECTS_DIR, project_id, "notes", f"{stage_id}.md")
    if os.path.exists(note_path):
        with open(note_path, "r", encoding="utf-8") as f:
            return {"success": True, "content": f.read()}
    return {"success": True, "content": ""}


@app.get("/api/notes/{project_id}")
async def list_notes(project_id: str):
    """List all notes for a project."""
    notes_dir = os.path.join(PROJECTS_DIR, project_id, "notes")
    if not os.path.exists(notes_dir):
        return {"notes": []}
    notes = []
    for fname in sorted(os.listdir(notes_dir)):
        if fname.endswith(".md"):
            notes.append({"stage_id": fname.replace(".md", ""), "filename": fname})
    return {"notes": notes}


# -------- Resource Recommendation --------

class ResourceRequest(BaseModel):
    topic: str
    stage_title: str = ""
    grade_level: str = "初中"
    stage_description: str = ""


@app.post("/api/resources/recommend")
async def recommend_resources(req: ResourceRequest):
    """AI recommends learning resources for a project stage."""
    prompt = f"""你是一位STEM教育资源推荐专家。请为以下学习项目推荐学习资源：

项目主题: {req.topic}
当前阶段: {req.stage_title}
学段: {req.grade_level}
阶段内容: {req.stage_description[:500]}

请推荐3-5个高质量学习资源，返回JSON数组（不要markdown标记）。每个资源包含:
- title: 资源标题
- type: 类型（video/article/simulation/tool）
- query: 在B站或百度搜索的关键词（中文，5-10个字），系统会自动拼接真实搜索链接
- description: 简短描述（20字以内）
- why: 为什么推荐这个资源（与当前阶段的关系，15字以内）

注意：不要生成url，只生成query关键词。系统会基于query自动生成可用的搜索链接。
直接返回JSON数组:"""

    try:
        resp = requests.post(
            _LLM_CONFIG["url"],
            json={"model": _LLM_CONFIG["model"], "messages": [
                {"role": "system", "content": "你是STEM教育资源推荐专家。返回纯JSON数组，只包含query搜索关键词，不要url。"},
                {"role": "user", "content": prompt}
            ], "max_tokens": 800, "temperature": 0.5},
            headers={"Authorization": f"Bearer {_LLM_CONFIG['api_key']}"},
            timeout=30
        )
        if resp.status_code == 200:
            content = resp.json()["choices"][0]["message"]["content"]
            match = re.search(r'\[.*\]', content, re.DOTALL)
            if match:
                resources = json.loads(match.group())
                # Build real URLs from search queries
                for r in resources:
                    query = r.get("query", r.get("title", ""))
                    encoded = requests.utils.quote(query)
                    if r.get("type") == "video":
                        r["url"] = f"https://search.bilibili.com/all?keyword={encoded}"
                    elif r.get("type") == "simulation":
                        r["url"] = f"https://phet.colorado.edu/zh_CN/search?query={encoded}"
                    else:
                        r["url"] = f"https://www.baidu.com/s?wd={encoded}"
                return {"success": True, "resources": resources}
    except Exception as e:
        print(f"Resource recommendation failed: {e}")

    encoded = requests.utils.quote(req.topic)
    return {"success": True, "resources": [
        {"title": f"B站搜索「{req.topic}」教学视频", "type": "video", "url": f"https://search.bilibili.com/all?keyword={encoded}", "description": "在B站找到相关教学视频", "why": "视频讲解直观易懂"},
        {"title": f"PhET模拟实验", "type": "simulation", "url": f"https://phet.colorado.edu/zh_CN/", "description": "交互式科学模拟实验", "why": "动手操作加深理解"},
        {"title": f"百度百科 - {req.topic}", "type": "article", "url": f"https://baidu.com/s?wd={encoded}", "description": "了解基础概念和背景知识", "why": "建立知识框架"},
    ]}


# -------- Learning Report PDF --------

@app.get("/api/project/{project_id}/report")
async def generate_report(project_id: str, student_name: str = "学生"):
    """Generate a comprehensive learning report as HTML (print to PDF)."""
    proj_path = os.path.join(PROJECTS_DIR, project_id)
    if not os.path.isdir(proj_path):
        raise HTTPException(status_code=404, detail="项目不存在")

    # Load plan
    plan_md = ""
    plan_path = os.path.join(proj_path, "教案.md")
    if os.path.exists(plan_path):
        with open(plan_path, "r", encoding="utf-8") as f:
            plan_md = f.read()

    # Load metadata
    meta = {}
    meta_path = os.path.join(proj_path, "meta.json")
    if os.path.exists(meta_path):
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)

    # Load stage feedbacks
    stages_html = ""
    plan_headings = re.findall(r'^## (.+)$', plan_md, re.MULTILINE)
    for i, heading in enumerate(plan_headings):
        stage_id = f"stage_{i}"
        note_content = ""
        note_path = os.path.join(proj_path, "notes", f"{stage_id}.md")
        if os.path.exists(note_path):
            with open(note_path, "r", encoding="utf-8") as f:
                note_content = f.read()

        stages_html += f"""
        <div class="stage-block">
            <h3>阶段{i+1}：{heading}</h3>
            <div class="note-content">{note_content.replace(chr(10), '<br>') if note_content else '<em>暂无笔记</em>'}</div>
        </div>
        """

    title = meta.get("title", "STEM项目")
    grade = meta.get("grade_level", "")
    date = meta.get("created_at", "")[:10]

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>{title} - 学习报告</title>
<style>
body {{ font-family: 'Microsoft YaHei', sans-serif; max-width: 800px; margin: 0 auto; padding: 40px; color: #1e2761; line-height: 1.8; }}
.cover {{ text-align: center; padding: 60px 0; border-bottom: 3px solid #4F46E5; margin-bottom: 40px; }}
.cover h1 {{ font-size: 28px; color: #4F46E5; }}
.cover .meta {{ color: #6366F1; font-size: 14px; margin-top: 10px; }}
h2 {{ color: #4F46E5; border-bottom: 2px solid #EEF2FF; padding-bottom: 8px; margin-top: 30px; }}
.stage-block {{ background: #f8f9ff; border-radius: 12px; padding: 16px 20px; margin: 12px 0; border-left: 4px solid #4F46E5; }}
.stage-block h3 {{ margin: 0 0 8px 0; font-size: 16px; }}
.note-content {{ color: #312e81; font-size: 14px; }}
.footer {{ text-align: center; color: #818CF8; font-size: 12px; margin-top: 40px; border-top: 1px solid #EEF2FF; padding-top: 20px; }}
</style></head>
<body>
<div class="cover">
    <h1>{title}</h1>
    <div class="meta">学生：{student_name} | 学段：{grade} | 日期：{date}</div>
    <p style="margin-top:20px;color:#6366F1;">星图学航 · STEM自适应探究学习平台</p>
</div>
<h2>📋 项目教案</h2>
<div>{plan_md.replace(chr(10), '<br>')}</div>
<h2>📝 阶段笔记</h2>
{stages_html}
<div class="footer">本报告由星图学航自动生成 | 基于Few-shot教案生成的STEM自适应探究学习系统</div>
</body></html>"""

    return Response(content=html, media_type="text/html")


# -------- Stage Checkpoint Evaluation --------

class StageEvalRequest(BaseModel):
    summary: str
    stage_index: int = 0
    project_id: str = ""

    @field_validator("stage_index", mode="before")
    @classmethod
    def normalize_stage_index(cls, value: object) -> int:
        if value is None or value == "":
            return 0
        try:
            normalized = int(value)
        except (TypeError, ValueError):
            return 0
        return max(0, normalized)

    @field_validator("project_id", mode="before")
    @classmethod
    def normalize_project_id(cls, value: object) -> str:
        return "" if value is None else str(value)


@app.post("/api/evaluate-stage")
async def api_evaluate_stage(req: StageEvalRequest):
    """Evaluate a student's stage summary using AI."""
    # Get project context
    project_context = ""
    if req.project_id:
        proj_path = os.path.join(PROJECTS_DIR, req.project_id)
        plan_path = os.path.join(proj_path, "教案.md")
        if os.path.exists(plan_path):
            with open(plan_path, "r", encoding="utf-8") as f:
                plan = f.read()
                # Extract the relevant stage heading
                headings = re.findall(r'^## (.+)$', plan, re.MULTILINE)
                if req.stage_index < len(headings):
                    project_context = f"当前阶段: {headings[req.stage_index]}\n项目内容: {plan[:2000]}"

    prompt = f"""你是一位STEM教育评估专家。请评价学生的阶段学习总结。

{project_context}

学生的总结:
{req.summary}

请从以下维度评估（返回JSON格式，不要markdown标记）:
1. completion: 完成度百分比(0-100)
2. feedback: 简短反馈(100字以内)，先说优点再说改进建议，语气鼓励
3. stars: 星级(1-3颗星，completion>=80得3星，>=60得2星，否则1星)
4. missing: 缺失的关键内容(如果有，一句话说明；如果没有，填null)

直接返回JSON:"""

    try:
        resp = requests.post(
            _LLM_CONFIG["url"],
            json={
                "model": _LLM_CONFIG["model"],
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 500, "temperature": 0.3,
            },
            headers={"Authorization": f"Bearer {_LLM_CONFIG['api_key']}"},
            timeout=30
        )

        if resp.status_code == 200:
            content = resp.json()["choices"][0]["message"]["content"]
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                evaluation = json.loads(json_match.group())
                return {"success": True, "evaluation": evaluation}
    except Exception as e:
        print(f"Stage evaluation failed: {e}")

    # Fallback evaluation (rule-based)
    summary_len = len(req.summary)
    completion = min(90, max(30, summary_len // 3))
    stars = 3 if completion >= 80 else (2 if completion >= 60 else 1)
    return {
        "success": True,
        "evaluation": {
            "completion": completion,
            "feedback": "总结得不错！" if completion >= 70 else "可以再详细一些，描述具体做了什么、学到了什么。",
            "stars": stars,
            "missing": None if completion >= 70 else "可以补充具体的实验数据或观察结果"
        }
    }


# -------- Literature-Experiment Bridge --------

class SyncProjectsRequest(BaseModel):
    projects: List[Dict] = []


@app.post("/api/bridge/sync-projects")
async def sync_projects(req: SyncProjectsRequest):
    """Sync projects from React literature module to shared storage for RCO."""
    shared_dir = os.path.join(DATA_DIR, "literature", "projects")
    os.makedirs(shared_dir, exist_ok=True)

    count = 0
    for proj in req.projects:
        proj_id = proj.get("id", f"proj_{uuid.uuid4().hex[:8]}")
        fpath = os.path.join(shared_dir, f"{proj_id}.json")
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(proj, f, ensure_ascii=False, indent=2)
        count += 1

    return {"success": True, "synced": count, "path": shared_dir}


@app.get("/api/bridge/projects")
async def get_synced_projects():
    """Get synced projects for RCO Streamlit to read."""
    shared_dir = os.path.join(DATA_DIR, "literature", "projects")
    if not os.path.exists(shared_dir):
        return {"projects": []}

    projects = []
    for fname in os.listdir(shared_dir):
        if fname.endswith(".json"):
            with open(os.path.join(shared_dir, fname), "r", encoding="utf-8") as f:
                projects.append(json.load(f))
    return {"projects": projects}


# -------- Project Export --------

@app.get("/api/project/{project_id}/export")
async def export_project(project_id: str):
    """Export complete project as ZIP package."""
    import zipfile
    import io

    proj_path = os.path.join(PROJECTS_DIR, project_id)
    if not os.path.isdir(proj_path):
        raise HTTPException(status_code=404, detail="项目不存在")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(proj_path):
            for file in files:
                full_path = os.path.join(root, file)
                arcname = os.path.relpath(full_path, proj_path)
                zf.write(full_path, arcname)

    buf.seek(0)
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=project_{project_id}.zip"}
    )


# -------- Achievement Wall --------

@app.post("/api/achievement/publish")
async def publish_achievement(
    project_id: str = None,
    student_name: str = "匿名",
    description: str = "",
    photo: UploadFile = File(None)
):
    """Publish a completed project to the achievement wall."""
    ach_dir = os.path.join(DATA_DIR, "achievements")
    os.makedirs(ach_dir, exist_ok=True)

    ach_id = uuid.uuid4().hex[:8]
    photo_path = None

    if photo:
        photo_ext = os.path.splitext(photo.filename)[1] or ".jpg"
        photo_path = f"photos/{ach_id}{photo_ext}"
        photo_dir = os.path.join(ach_dir, "photos")
        os.makedirs(photo_dir, exist_ok=True)
        with open(os.path.join(ach_dir, photo_path), "wb") as f:
            f.write(await photo.read())

    # Load project meta for context
    proj_meta = {}
    if project_id:
        meta_path = os.path.join(PROJECTS_DIR, project_id, "meta.json")
        if os.path.exists(meta_path):
            with open(meta_path, "r", encoding="utf-8") as f:
                proj_meta = json.load(f)

    achievement = {
        "id": ach_id,
        "project_id": project_id,
        "student_name": student_name,
        "description": description,
        "photo_path": photo_path,
        "project_title": proj_meta.get("title", ""),
        "grade_level": proj_meta.get("grade_level", ""),
        "published_at": datetime.now().isoformat(),
        "likes": 0
    }

    ach_path = os.path.join(ach_dir, f"{ach_id}.json")
    with open(ach_path, "w", encoding="utf-8") as f:
        json.dump(achievement, f, ensure_ascii=False, indent=2)

    return {"success": True, "achievement": achievement}


@app.get("/api/achievements")
async def list_achievements():
    """List all published achievements."""
    ach_dir = os.path.join(DATA_DIR, "achievements")
    if not os.path.exists(ach_dir):
        return {"achievements": []}

    achievements = []
    for fname in os.listdir(ach_dir):
        if fname.endswith(".json"):
            with open(os.path.join(ach_dir, fname), "r", encoding="utf-8") as f:
                achievements.append(json.load(f))

    achievements.sort(key=lambda a: a.get("published_at", ""), reverse=True)
    return {"achievements": achievements}


@app.get("/api/achievements/photo/{filename}")
async def get_photo(filename: str):
    """Serve achievement photo."""
    photo_path = os.path.join(DATA_DIR, "achievements", "photos", filename)
    if not os.path.exists(photo_path):
        raise HTTPException(status_code=404, detail="照片不存在")
    return FileResponse(photo_path)


# -------- Parent Portal --------

@app.get("/api/parent/overview/{student_id}")
async def parent_overview(student_id: str):
    """Parent dashboard: overview of child's learning."""
    progress_dir = os.path.join(DATA_DIR, "progress")
    progress_path = os.path.join(progress_dir, f"{student_id}.json")

    completed_projects = []
    knowledge_stars = []
    if os.path.exists(progress_path):
        with open(progress_path, "r", encoding="utf-8") as f:
            p = json.load(f)
            completed_projects = p.get("completed_projects", [])
            knowledge_stars = p.get("knowledge_stars", [])

    # Get project details for completed projects
    project_details = []
    for pid in completed_projects:
        meta_path = os.path.join(PROJECTS_DIR, pid, "meta.json")
        if os.path.exists(meta_path):
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
                meta["id"] = pid
                project_details.append(meta)

    # Calculate knowledge radar
    radar = _calculate_knowledge_radar(knowledge_stars, project_details)

    return {
        "student_id": student_id,
        "completed_count": len(completed_projects),
        "knowledge_count": len(knowledge_stars),
        "recent_projects": project_details[-5:],
        "knowledge_radar": radar,
        "total_learning_hours": len(completed_projects) * 4  # rough estimate
    }


def _calculate_knowledge_radar(stars: List[str], projects: List[Dict]) -> Dict:
    """Calculate knowledge distribution across STEM categories."""
    categories = {
        "物理": 0, "化学": 0, "生物": 0,
        "工程技术": 0, "编程": 0, "数学": 0, "地学": 0
    }

    # Count from knowledge stars
    for star in stars:
        for cat in categories:
            if cat in star:
                categories[cat] += 1

    # Also infer from project subjects
    for proj in projects:
        if "subjects" in proj:
            for subj in proj["subjects"]:
                for cat in categories:
                    if cat in subj:
                        categories[cat] += 0.5

    # Normalize to 100
    total = sum(categories.values()) or 1
    radar = {k: round(v / total * 100) for k, v in categories.items()}

    return radar


@app.get("/api/parent/learning-log/{student_id}")
async def parent_learning_log(student_id: str):
    """Get detailed learning log for a student."""
    progress_dir = os.path.join(DATA_DIR, "progress")
    progress_path = os.path.join(progress_dir, f"{student_id}.json")

    log = []
    if os.path.exists(progress_path):
        with open(progress_path, "r", encoding="utf-8") as f:
            p = json.load(f)
            log = p.get("learning_log", [])

    return {"student_id": student_id, "log": log}


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8002"))
    uvicorn.run(app, host="127.0.0.1", port=port)
