@echo off
REM STEM-SCI unified launcher: local research workspace + StarMap teaching workspace
setlocal
set "ROOT=%~dp0"
set "STARMAP_ROOT=%ROOT%integrations\StarMap-Voyage"

if not exist "%STARMAP_ROOT%\web\package.json" (
  echo [ERROR] StarMap Voyage integration is missing: %STARMAP_ROOT%
  pause
  exit /b 1
)

if exist "%STARMAP_ROOT%\.env" (
  for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%STARMAP_ROOT%\.env") do if not "%%A"=="" set "%%A=%%B"
)

echo.
echo  ============================================
echo    STEM-SCI unified research + teaching platform
echo  ============================================
echo.

if not exist "%ROOT%frontend\node_modules" (
  echo [1/8] Installing STEM-SCI frontend dependencies...
  pushd "%ROOT%frontend"
  call npm.cmd install
  popd
)

if not exist "%STARMAP_ROOT%\web\node_modules" (
  echo [2/8] Installing StarMap frontend dependencies...
  pushd "%STARMAP_ROOT%\web"
  call npm.cmd install
  popd
)

echo [3/8] Starting STEM-SCI research backend  http://127.0.0.1:8013
start "STEM-SCI-Research-API" /D "%ROOT%backend" cmd /k "set PYTHONPATH=%ROOT%backend\src&& python -m uvicorn stem_sci.main:app --host 127.0.0.1 --port 8013"

echo [4/8] Starting STEM-SCI research frontend http://127.0.0.1:5177
start "STEM-SCI-Research-Web" /D "%ROOT%frontend" cmd /k "npm.cmd run dev -- --host 127.0.0.1 --port 5177"

echo [5/8] Starting StarMap teaching backend  http://127.0.0.1:8002
start "StarMap-Teaching-API" /D "%STARMAP_ROOT%\services\teaching\backend" cmd /k "python api_server.py"

echo [6/8] Starting StarMap course cases    http://127.0.0.1:8800
start "StarMap-Course-Cases" /D "%STARMAP_ROOT%\services\course-cases\backend" cmd /k "python -m uvicorn api_server:app --host 127.0.0.1 --port 8800"

echo [7/8] Starting StarMap research API     http://127.0.0.1:8000
start "StarMap-Research-API" /D "%STARMAP_ROOT%\services\research" cmd /k "python -m backend.main --port 8000"

echo [8/8] Starting StarMap teaching frontend http://127.0.0.1:5178
start "StarMap-Web" /D "%STARMAP_ROOT%\web" cmd /k "npm.cmd run dev -- --host 127.0.0.1 --port 5178"

echo.
echo  Unified entry: http://127.0.0.1:5177
echo  Research API: http://127.0.0.1:8013
echo  StarMap web:  http://127.0.0.1:5178
echo  StarMap APIs: http://127.0.0.1:8002 and http://127.0.0.1:8800
echo.
echo  Keep the opened service windows running.
pause
