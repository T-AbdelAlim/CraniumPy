# One-shot setup for a fresh checkout on Windows: creates .venv, installs the
# pinned Python dependencies, and builds the frontend (frontend/dist isn't in
# git, and both the web and desktop app serve the built output).
#
#   powershell -ExecutionPolicy Bypass -File setup.ps1
#
# Needs Python 3.11+ (tested on 3.14) and Node.js 20+ on PATH.

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Require($cmd, $hint) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        Write-Error "$cmd not found on PATH - $hint"
    }
}
Require python "install Python 3.11+ from https://www.python.org/downloads/"
Require npm "install Node.js 20+ from https://nodejs.org/"

if (-not (Test-Path .venv)) {
    Write-Host "Creating .venv..."
    python -m venv .venv
}
$py = ".venv\Scripts\python.exe"

Write-Host "Installing Python dependencies..."
& $py -m pip install --upgrade pip
& $py -m pip install -r requirements.txt -e .
if ($LASTEXITCODE -ne 0) { Write-Error "pip install failed" }

Write-Host "Building the frontend..."
npm --prefix frontend ci
if ($LASTEXITCODE -ne 0) { Write-Error "npm ci failed" }
npm --prefix frontend run build
if ($LASTEXITCODE -ne 0) { Write-Error "frontend build failed" }

Write-Host ""
Write-Host "Done. Run the desktop app with:"
Write-Host "  .venv\Scripts\python.exe -m desktop.app"
