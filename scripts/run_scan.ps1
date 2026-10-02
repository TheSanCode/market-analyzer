# Runs one Market Watcher scan. Used by Windows Task Scheduler (see README).
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run_scan.ps1
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "Virtual environment not found at $Python" }

New-Item -ItemType Directory -Force -Path (Join-Path $Root "logs") | Out-Null
$Log = Join-Path $Root ("logs\scan_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))

$ConfigArgs = @()
if (Test-Path (Join-Path $Root "config.toml")) { $ConfigArgs = @("-c", "config.toml") }

# Native stderr must not abort the script under ErrorActionPreference=Stop.
$ErrorActionPreference = "Continue"
& $Python -m market_watcher @ConfigArgs scan --export 2>&1 | Tee-Object -FilePath $Log
exit $LASTEXITCODE
