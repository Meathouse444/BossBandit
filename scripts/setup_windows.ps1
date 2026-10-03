# BossBandit one-time setup for Windows 10/11.
# Right-click the BossBandit folder > "Open in Terminal", then run:
#   powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Have($cmd) { [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }
function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [Environment]::GetEnvironmentVariable("Path", "User")
}

Write-Host "`n== BossBandit setup ==`n" -ForegroundColor Cyan

# 1. Python (the "py" launcher comes with the python.org / winget install)
if (-not (Have "py")) {
    Write-Host "Installing Python 3.12 (one time)..." -ForegroundColor Yellow
    winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
    Refresh-Path
    if (-not (Have "py")) {
        Write-Host "Python installed. CLOSE this window, open a new terminal, and run this script again." -ForegroundColor Yellow
        exit 0
    }
}

# 2. ffmpeg (video engine)
if (-not (Have "ffmpeg")) {
    Write-Host "Installing ffmpeg (one time)..." -ForegroundColor Yellow
    winget install -e --id Gyan.FFmpeg --accept-source-agreements --accept-package-agreements
    Refresh-Path
    if (-not (Have "ffmpeg")) {
        Write-Host "ffmpeg installed. CLOSE this window, open a new terminal, and run this script again." -ForegroundColor Yellow
        exit 0
    }
}

# 3. Private Python environment + BossBandit itself
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Creating Python environment..."
    py -3 -m venv .venv
}
& .\.venv\Scripts\python.exe -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"
if ($LASTEXITCODE -ne 0) {
    Write-Host "Python 3.11+ is required. Run: winget install -e --id Python.Python.3.12  then delete the .venv folder and re-run." -ForegroundColor Red
    exit 1
}
Write-Host "Installing BossBandit (a few minutes the first time)..."
& .\.venv\Scripts\python.exe -m pip install --upgrade pip --quiet
& .\.venv\Scripts\python.exe -m pip install -e ".[captions]" --quiet
if ($LASTEXITCODE -ne 0) { Write-Host "pip install failed - see the messages above." -ForegroundColor Red; exit 1 }

# 4. Config files
& .\.venv\Scripts\bossbandit.exe init

Write-Host "`nDone! Next steps:" -ForegroundColor Green
Write-Host "  1. Paste your keys into the .env file (it opens now in Notepad), save, close."
Write-Host "  2. Double-click scripts\run_now.bat  (first run takes a while: it downloads the captions model)"
Write-Host "  3. When happy, run:  powershell -ExecutionPolicy Bypass -File scripts\schedule_windows.ps1"
Start-Process notepad.exe (Join-Path $root ".env")
