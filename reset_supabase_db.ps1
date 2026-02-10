# PowerShell script to reset Supabase database
# Run this in PowerShell: .\reset_supabase_db.ps1

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "SUPABASE DATABASE RESET TOOL (PowerShell)" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# Check if Python is available
try {
    $pythonVersion = python --version 2>&1
    Write-Host "Python found: $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "ERROR: Python is not installed or not in PATH" -ForegroundColor Red
    Write-Host "Please install Python or add it to your PATH" -ForegroundColor Yellow
    exit 1
}

# Check if script exists
if (-not (Test-Path "reset_supabase_db.py")) {
    Write-Host "ERROR: reset_supabase_db.py not found in current directory" -ForegroundColor Red
    Write-Host "Current directory: $(Get-Location)" -ForegroundColor Yellow
    exit 1
}

# Run the Python script
Write-Host "Running Python script..." -ForegroundColor Green
Write-Host ""

python reset_supabase_db.py

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "ERROR: Script execution failed with exit code $LASTEXITCODE" -ForegroundColor Red
    exit $LASTEXITCODE
}
