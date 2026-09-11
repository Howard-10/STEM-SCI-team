#!/bin/bash
# Research-Copilot-OS Linux/macOS 启动脚本

echo "======================================"
echo "  Research-Copilot-OS 启动脚本"
echo "======================================"

# 检查 Python
if ! command -v python3 &> /dev/null; then
    echo "[错误] 未找到 python3，请先安装 Python 3.10+"
    exit 1
fi

# 检查 API Key
if [ -z "$DEEPSEEK_API_KEY" ]; then
    echo "[警告] DEEPSEEK_API_KEY 未设置"
    echo "  请设置: export DEEPSEEK_API_KEY=sk-xxxx"
fi

# 安装依赖
echo "[1/3] 安装依赖..."
pip install -r requirements.txt -q

# 启动后端
echo "[2/3] 启动后端服务..."
python -m backend.main --port 8000 --reload &
BACKEND_PID=$!
sleep 3

# 启动前端
echo "[3/3] 启动前端界面..."
streamlit run frontend/app.py --server.port 8501 &
FRONTEND_PID=$!

echo ""
echo "后端 API:  http://127.0.0.1:8000"
echo "前端界面:  http://127.0.0.1:8501"
echo ""
echo "按 Ctrl+C 停止所有服务"

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" INT TERM
wait
