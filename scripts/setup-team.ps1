param(
    [switch]$Full
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$backendRoot = Join-Path $repoRoot "backend"
$frontendRoot = Join-Path $repoRoot "frontend"
$python = Get-Command py -ErrorAction SilentlyContinue

if (-not $python) {
    throw "Python launcher 'py' was not found. Install Python 3.11 or newer first."
}
if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
    throw "npm.cmd was not found. Install Node.js 20 or newer first."
}

$venvPython = Join-Path $backendRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPython)) {
    & py -3.11 -m venv (Join-Path $backendRoot ".venv")
}

$extras = if ($Full) {
    ".[dev,hybrid-retrieval,advanced-algorithms,research-algorithms]"
} else {
    ".[dev,hybrid-retrieval]"
}

Push-Location $backendRoot
try {
    & $venvPython -m pip install --upgrade pip
    & $venvPython -m pip install -e $extras
} finally {
    Pop-Location
}

Push-Location $frontendRoot
try {
    & npm.cmd ci
} finally {
    Pop-Location
}

$envFile = Join-Path $repoRoot ".env.local"
if (-not (Test-Path -LiteralPath $envFile)) {
    Copy-Item -LiteralPath (Join-Path $repoRoot ".env.example") -Destination $envFile
}

& (Join-Path $PSScriptRoot "restore-team-state.ps1")

Write-Host "Setup complete. Add the team's model API key to .env.local before live-model runs."
Write-Host "Backend:  cd backend; .\.venv\Scripts\python.exe -m uvicorn stem_sci.api:app --host 127.0.0.1 --port 8015"
Write-Host "Frontend: cd frontend; npm.cmd run dev"
