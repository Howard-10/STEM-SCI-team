#!/bin/bash
# ResearchPilot 一键启动脚本 (macOS/Linux)
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"

if [ -f "$ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$ROOT/.env"
  set +a
fi

echo ""
echo "============================================"
echo "  ResearchPilot - 星图学航 科研教学一体化平台"
echo "============================================"
echo ""

if ! command -v python3 &> /dev/null; then
  echo "[错误] 未找到 python3，请先安装 Python 3.10+"
  exit 1
fi

if [ ! -d "$ROOT/web/node_modules" ]; then
  echo "[1/6] 安装前端依赖..."
  (cd "$ROOT/web" && npm install)
fi

echo "[2/6] 启动教学设计后端 http://127.0.0.1:8002"
(cd "$ROOT/services/teaching/backend" && python3 api_server.py) &
PID_TEACH=$!

echo "[3/6] 启动课程案例服务 http://127.0.0.1:8800/app/"
(cd "$ROOT/services/course-cases/backend" && python3 -m uvicorn api_server:app --host 127.0.0.1 --port 8800) &
PID_COURSE=$!

echo "[4/6] 启动科研实验后端 http://127.0.0.1:8000"
(cd "$ROOT/services/research" && python3 -m backend.main --port 8000) &
PID_RESEARCH=$!

echo "[5/6] 启动科研实验界面 Streamlit http://127.0.0.1:8501"
(cd "$ROOT/services/research" && streamlit run frontend/app.py --server.port 8501) &
PID_STREAMLIT=$!

echo "[6/6] 启动前端界面 http://127.0.0.1:5178"
(cd "$ROOT/web" && npm run dev -- --host 127.0.0.1 --port 5178) &
PID_WEB=$!

echo ""
echo "访问地址："
echo "  前端界面:      http://127.0.0.1:5178"
echo "  教学设计 API:  http://127.0.0.1:8002/docs"
echo "  课程案例:      http://127.0.0.1:8800/app/"
echo "  科研实验后端:  http://127.0.0.1:8000/docs"
echo "  科研实验界面:  http://127.0.0.1:8501"
echo ""
echo "按 Ctrl+C 停止所有服务"

trap "kill $PID_TEACH $PID_COURSE $PID_RESEARCH $PID_STREAMLIT $PID_WEB 2>/dev/null; exit" INT TERM
wait
