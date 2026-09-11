@echo off
REM Research-Copilot-OS Windows 启动脚本

echo ======================================
echo   Research-Copilot-OS 启动脚本
echo ======================================

REM 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.10+
    pause
    exit /b 1
)

REM 检查 API Key
if "%DEEPSEEK_API_KEY%"=="" (
    echo [警告] DEEPSEEK_API_KEY 未设置
    echo   请设置环境变量: set DEEPSEEK_API_KEY=sk-xxxx
    echo.
)

REM 安装依赖
echo [1/3] 安装依赖...
pip install -r requirements.txt -q

echo [2/3] 启动后端服务...
start "RCO-Backend" cmd /c "python -m backend.main --port 8000 --reload"

REM 等待后端启动
timeout /t 3 /nobreak >nul

echo [3/3] 启动前端界面...
streamlit run frontend/app.py --server.port 8501

pause
