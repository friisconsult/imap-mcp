# Set up imap-mcp on a new machine.
# Only requires Python 3.11+ installed and on PATH.
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot

if (-not (Test-Path "$root\.venv")) {
    Write-Host "Creating virtual environment..."
    python -m venv "$root\.venv"
}
Write-Host "Installing dependencies..."
& "$root\.venv\Scripts\python.exe" -m pip install --quiet -r "$root\requirements.txt"

& "$root\.venv\Scripts\python.exe" "$root\install.py"
