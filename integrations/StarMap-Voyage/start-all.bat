@echo off
REM =====================================================
REM  ResearchPilot one-click launcher (Windows)
REM  Starts: teaching API + course cases + research API + Streamlit + web UI
REM =====================================================
setlocal
set "ROOT=%~dp0"

if exist "%ROOT%.env" (
  for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%ROOT%.env") do if not "%%A"=="" set "%%A=%%B"
)

echo.
echo  ============================================
echo    ResearchPilot - Teaching + Research Platform
echo  ============================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python 3.10+
    pause
    exit /b 1
)

if not exist "%ROOT%web\node_modules" (
    echo [1/6] Installing frontend dependencies...
    pushd "%ROOT%web"
    call npm.cmd install
    popd
)

echo [2/6] Starting teaching backend   http://127.0.0.1:8002
start "ResearchPilot-Teaching" /D "%ROOT%services\teaching\backend" cmd /k "python api_server.py"

echo [3/6] Starting course cases       http://127.0.0.1:8800/app/
start "ResearchPilot-Course-Cases" /D "%ROOT%services\course-cases\backend" cmd /k "python -m uvicorn api_server:app --host 127.0.0.1 --port 8800"

echo [4/6] Starting research backend   http://127.0.0.1:8000
start "ResearchPilot-Research-API" /D "%ROOT%services\research" cmd /k "python -m backend.main --port 8000"

echo [5/6] Starting research UI (Streamlit)   http://127.0.0.1:8501
start "ResearchPilot-Streamlit" /D "%ROOT%services\research" cmd /k "streamlit run frontend/app.py --server.port 8501"

echo [6/6] Starting web UI   http://127.0.0.1:5178
start "ResearchPilot-Web" /D "%ROOT%web" cmd /k "npm.cmd run dev -- --host 127.0.0.1 --port 5178"

echo.
echo  URLs:
echo    Web UI:        http://127.0.0.1:5178
echo    Teaching API:  http://127.0.0.1:8002/docs
echo    Research API:  http://127.0.0.1:8000/docs
echo    Research UI:   http://127.0.0.1:8501
echo    Course cases:  http://127.0.0.1:8800/app/
echo.
echo  Optional Node AI service (port 3001, not wired):  cd api ^&^& npm run dev
echo.
echo  Each service runs in its own window. Keep those windows open.
echo.
pause
