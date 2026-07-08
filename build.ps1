# Build the app into a single exe: dist\WorkTime.exe
# Run this (or build.bat) after changing code/UI to regenerate the exe.
# (ASCII-only on purpose: Windows PowerShell 5.1 misparses UTF-8 Hangul without a BOM.)
$ErrorActionPreference = "Stop"
$dir = $PSScriptRoot
$py = "$dir\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
  Write-Host "[ERROR] .venv not found. Create it and install requirements first:" -ForegroundColor Red
  Write-Host "  python -m venv .venv; .venv\Scripts\python -m pip install -r requirements.txt pyinstaller"
  Read-Host "Press Enter to exit"; exit 1
}

# Ensure pyinstaller is installed
& $py -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) { & $py -m pip install pyinstaller --quiet }

# Optional groupware URL override. If config.json is missing, ehr.py uses its built-in default.
$dataArgs = @("--add-data", "$dir\ui;ui")
if (Test-Path "$dir\config.json") {
  $dataArgs += @("--add-data", "$dir\config.json;.")
}

# Close any running WorkTime.exe (a running exe locks the output file => build fails)
Get-Process "WorkTime" -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Milliseconds 400

Write-Host "Building... (2-4 min)" -ForegroundColor Cyan
$pyinstallerArgs = @(
  "--noconfirm",
  "--onefile",
  "--windowed",
  "--name", "WorkTime",
  "--icon", "$dir\icon.ico"
) + $dataArgs + @(
  "--collect-all", "playwright",
  "--collect-all", "webview",
  "--collect-all", "holidays",
  "--hidden-import", "ehr",
  "--hidden-import", "meal",
  "--hidden-import", "cal",
  "--hidden-import", "pystray._win32",
  "--hidden-import", "clr",
  "--distpath", "$dir\dist",
  "--workpath", "$dir\build",
  "--specpath", "$dir\build",
  "$dir\app.py"
)
& "$dir\.venv\Scripts\pyinstaller.exe" @pyinstallerArgs

if (Test-Path "$dir\dist\WorkTime.exe") {
  $mb = [math]::Round((Get-Item "$dir\dist\WorkTime.exe").Length / 1MB, 1)
  Write-Host "`nDone! dist\WorkTime.exe ($mb MB)" -ForegroundColor Green
  Write-Host "Send just this one file to others (no Python needed)."
} else {
  Write-Host "Build failed - check the log above." -ForegroundColor Red
}
Read-Host "`nPress Enter to exit"
