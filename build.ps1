# 근태 앱을 단일 exe(dist\WorkTime.exe)로 빌드한다.
# 코드/UI를 수정한 뒤 이 스크립트(또는 빌드.bat)를 실행하면 exe가 새로 생성됨.
$ErrorActionPreference = "Stop"
$dir = $PSScriptRoot
$py = "$dir\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
  Write-Host "[오류] .venv 가 없습니다. 먼저 가상환경을 만들고 requirements.txt 를 설치하세요:" -ForegroundColor Red
  Write-Host "  python -m venv .venv; .venv\Scripts\python -m pip install -r requirements.txt pyinstaller"
  Read-Host "엔터로 종료"; exit 1
}

# pyinstaller 설치 확인
& $py -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) { & $py -m pip install pyinstaller --quiet }

# 그룹웨어 주소(config.json) 확인 — exe 에 번들됨
if (-not (Test-Path "$dir\config.json")) {
  Write-Host "[안내] config.json 이 없습니다. 그룹웨어 주소를 먼저 설정하세요:" -ForegroundColor Yellow
  Write-Host "  copy config.example.json config.json   (그리고 origin 값을 회사 주소로 수정)"
  Read-Host "엔터로 종료"; exit 1
}

Write-Host "빌드 중... (2~4분)" -ForegroundColor Cyan
& "$dir\.venv\Scripts\pyinstaller.exe" --noconfirm --onefile --windowed --name "WorkTime" `
  --icon "$dir\icon.ico" `
  --add-data "$dir\ui;ui" `
  --add-data "$dir\config.json;." `
  --collect-all playwright `
  --collect-all webview `
  --collect-all holidays `
  --hidden-import ehr `
  --hidden-import pystray._win32 `
  --hidden-import clr `
  --distpath "$dir\dist" `
  --workpath "$dir\build" `
  --specpath "$dir\build" `
  "$dir\app.py"

if (Test-Path "$dir\dist\WorkTime.exe") {
  $mb = [math]::Round((Get-Item "$dir\dist\WorkTime.exe").Length / 1MB, 1)
  Write-Host "`n완료! dist\WorkTime.exe ($mb MB)" -ForegroundColor Green
  Write-Host "이 파일 하나만 다른 사람에게 주면 됩니다 (Python 설치 불필요)."
} else {
  Write-Host "빌드 실패 — 위 로그를 확인하세요." -ForegroundColor Red
}
Read-Host "`n엔터로 종료"
