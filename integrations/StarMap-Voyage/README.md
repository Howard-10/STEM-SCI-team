# StarMap Voyage · 星图学航

> STEM 教学与科研一体化平台，整合教学设计、自适应课程案例、文献阅读和科研实验能力。

前端为单一 React 应用（`web/`），统一承载教学设计、课程案例、文献阅读和科研实验入口。

---

## 一、目录结构

```
StarMap-Voyage/
├── web/                     # 唯一前端 UI（React + TypeScript + Vite + Tailwind）
│   ├── src/config.ts        #   集中管理各后端地址（可用 .env 覆盖）
│   ├── src/routes/          #   页面（含 teaching/ 教学模块）
│   ├── src/components/      #   组件（layout / common / research …）
│   └── src/services/ai/     #   AI provider（mock / http）
├── api/                     # 备用 AI 服务（Node + Express，OpenAI，端口 3001，当前前端未接入）
├── services/
│   ├── teaching/            # 教学设计后端（FastAPI，端口 8002）
│   │   ├── backend/         #   api_server.py + agents/ + api/ + data_pipeline/
│   │   ├── data/            #   教学语料 / 检索索引
│   │   └── projects/        #   教学项目数据
│   ├── course-cases/        # 自适应 STEM 学习路径系统（FastAPI，端口 8800）
│   │   ├── backend/         #   知识图谱、题库与 Agent 服务
│   │   └── frontend/        #   课程案例静态界面
│   └── research/            # 科研实验平台（FastAPI 8000 + Streamlit 8501）
│       ├── backend/         #   引擎：文献/代码/实验/可视化 + Agent + MCP
│       ├── frontend/        #   Streamlit 界面 (app.py)
│       └── requirements.txt
├── docs/                    # 归档文档与演示材料
│   ├── presentations/       #   PPT / PDF 演示文件
│   ├── legacy/              #   被取代的原生前端、历史日志
│   └── *.md                 #   功能清单 / 答辩稿 / 演讲稿 / 操作手册
├── start-all.bat            # Windows 一键启动全部服务
├── start-all.sh             # macOS/Linux 一键启动
└── README.md
```

---

## 二、启动方式

### 一键启动（推荐）

- Windows：双击 `start-all.bat`，或 `.\start-all.bat`
- macOS/Linux：`bash start-all.sh`

脚本会依次启动 5 个服务：

| 服务 | 目录 | 命令 | 端口 |
|---|---|---|---|
| 教学设计后端 | `services/teaching/backend` | `python api_server.py` | 8002 |
| 课程案例服务 | `services/course-cases/backend` | `python -m uvicorn api_server:app --host 127.0.0.1 --port 8800` | 8800 |
| 科研实验后端 | `services/research` | `python -m backend.main --port 8000` | 8000 |
| 科研实验界面 | `services/research` | `streamlit run frontend/app.py --server.port 8501` | 8501 |
| 前端 UI | `web` | `npm run dev -- --host 127.0.0.1 --port 5178` | 5178 |

> 打开 http://127.0.0.1:5178 即可使用。课程案例代码已包含在本仓库中，不依赖电脑上的其他项目目录。

### 手动分步启动

```powershell
# 1. 前端 UI
cd web
npm.cmd install        # 首次
npm.cmd run dev -- --host 127.0.0.1 --port 5178

# 2. 教学设计后端
cd ../services/teaching/backend
python api_server.py   # http://127.0.0.1:8002

# 3. 课程案例服务
cd ../../course-cases/backend
python -m uvicorn api_server:app --host 127.0.0.1 --port 8800

# 4. 科研实验后端 + Streamlit 界面
cd ../../research
python -m backend.main --port 8000        # http://127.0.0.1:8000
streamlit run frontend/app.py --server.port 8501   # http://127.0.0.1:8501

# 5. （可选）备用 AI 服务 Node
cd ../../api
npm.cmd install        # 首次
npm.cmd run dev        # http://localhost:3001

```

### 仅看前端 UI（无需后端）

文献阅读模块自带 `mock` 本地演示模式。修改 `web/.env`：

```env
VITE_AI_PROVIDER=mock
```

即可不启动任何后端直接预览前端（教学设计/科研实验仍需对应后端）。

---

## 三、环境变量

- `web/.env`：前端配置（见 `web/.env.example`）
  - `VITE_AI_PROVIDER`：`mock`（本地演示）或 `http`（走教学后端）
  - `VITE_API_BASE_URL`：文献阅读 AI 基础地址（默认教学后端 8002）
  - `VITE_TEACHING_API_URL`：教学设计后端（默认 8002）
  - `VITE_RESEARCH_STREAMLIT_URL`：科研实验 Streamlit（默认 8501）
  - `VITE_COURSE_CASE_URL`：课程案例自适应 STEM 学习路径服务（默认 8800）
- `services/teaching`：教学后端使用 `SILICONFLOW_API_KEY`
- `STARMAP_ENABLE_CODE_EXECUTION`：是否允许教学模块执行用户提交的 Python，默认 `false`；仅可信本地环境可开启
- `services/course-cases/backend`：课程案例 Agent 使用 `SILICONFLOW_API_KEY`；未配置时保留题库与基础路径功能
- `services/research`：科研实验后端使用 `DEEPSEEK_API_KEY`
- `api/.env`：备用 AI 服务使用 `OPENAI_*`

仓库不包含任何真实密钥。启动前在当前终端设置所需变量，例如：

```powershell
$env:SILICONFLOW_API_KEY="你的密钥"
$env:DEEPSEEK_API_KEY="你的密钥"
.\start-all.bat
```

---

## 四、依赖

- **前端 / 备用 API**：Node.js ≥ 20、npm
- **教学后端**：Python ≥ 3.10，`pip install -r services/teaching/requirements.txt`
- **课程案例**：`pip install -r services/course-cases/backend/requirements.txt`
- **科研实验后端**：Python ≥ 3.10，`pip install -r services/research/requirements.txt`

---

## 五、质量检查

```powershell
cd web
npm.cmd run lint
npm.cmd run build

cd ..\services\teaching\backend
python -m pytest -q

cd ..\..\research
python -m pytest -q
```
