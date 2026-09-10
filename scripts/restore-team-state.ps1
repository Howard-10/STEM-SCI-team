param(
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$bundle = Join-Path $repoRoot ".team-bootstrap\STEM-SCI-runtime-v1.zip"

if (-not (Test-Path -LiteralPath $bundle)) {
    throw "Runtime bundle is missing. Run 'git lfs pull' and retry."
}

$destinations = @(
    (Join-Path $repoRoot "backend\.stem_sci"),
    (Join-Path $repoRoot ".stem_sci"),
    (Join-Path $repoRoot "data\local"),
    (Join-Path $repoRoot "acceptance_runs\cgt_blind_output_rerun_046")
)

if (-not $Force) {
    $existing = @($destinations | Where-Object { Test-Path -LiteralPath $_ })
    if ($existing.Count -gt 0) {
        Write-Host "Runtime state already exists; restore skipped to avoid overwriting local work."
        Write-Host "Use .\scripts\restore-team-state.ps1 -Force to replace it."
        return
    }
}

$extractRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("stem-sci-runtime-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $extractRoot | Out-Null
try {
    Expand-Archive -LiteralPath $bundle -DestinationPath $extractRoot -Force
    $payload = Join-Path $extractRoot "runtime"
    if (-not (Test-Path -LiteralPath $payload)) {
        throw "The runtime bundle has an invalid layout."
    }
    Copy-Item -LiteralPath (Join-Path $payload "backend_state") -Destination (Join-Path $repoRoot "backend\.stem_sci") -Recurse -Force
    Copy-Item -LiteralPath (Join-Path $payload "root_state") -Destination (Join-Path $repoRoot ".stem_sci") -Recurse -Force
    Copy-Item -LiteralPath (Join-Path $payload "data_local") -Destination (Join-Path $repoRoot "data\local") -Recurse -Force
    if (Test-Path -LiteralPath (Join-Path $payload "synergy_cache.sqlite")) {
        Copy-Item -LiteralPath (Join-Path $payload "synergy_cache.sqlite") -Destination (Join-Path $repoRoot "backend\synergy_cache.sqlite") -Force
    }
    New-Item -ItemType Directory -Path (Join-Path $repoRoot "acceptance_runs") -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $payload "acceptance_rerun_046") -Destination (Join-Path $repoRoot "acceptance_runs\cgt_blind_output_rerun_046") -Recurse -Force
} finally {
    Remove-Item -LiteralPath $extractRoot -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host "All shared databases, project records, uploads, generated artifacts, local retrieval data, and rerun 046 were restored."
