# WorkTimeChecker (근태)

출퇴근 시간을 관리하는 작은 Windows 데스크톱 앱. 회사 그룹웨어(DaouOffice EHR)에서 실제 출퇴근을 자동으로 가져오고, **주 40시간 기준 잔여·연장 시간을 실시간 계산**한다. 트레이에 상주하며, 단일 `.exe` 하나로 배포된다.

## 기능
- 🕒 **실시간 계산** — 출근/퇴근만 넣으면 근무·잔여·연장 자동 (점심 1시간 제외)
- 🔄 **EHR 자동채움** — 앱 켤 때 그룹웨어에서 과거+오늘 출퇴근 자동 입력 (미래는 직접)
- 📊 **주 40시간 기준** — 두 줄 요약: `현재 시각 기준` / `예정 포함(입력한 퇴근시간까지)`, 40h 초과 시 빨간 연장(+)
- 🏖️ **연차 / 반차** — 연차·휴일 8h 인정, 오전/오후 반차(출근·퇴근 13:00 자동 + 4h 인정)
- 📅 **공휴일 자동** — 한국 공휴일(설날·추석·대체공휴일 포함, 오프라인 `holidays` 라이브러리) 자동 8h 인정
- 🖥️ **트레이 상주** — 닫으면 트레이로 숨김, Python 없이 도는 단일 exe로 배포

## 코드 구조
| 경로 | 역할 |
|---|---|
| `app.py` | pywebview 창 + pystray 트레이 + JS 브리지(저장 / EHR / 공휴일). **exe 진입점** |
| `ui/index.html` · `ui/style.css` · `ui/app.js` | 그리드 UI와 **모든 시간 계산 로직**(다크+민트 테마) |
| `ehr.py` | Playwright로 DaouOffice 근태 API를 조회. 로그인 세션은 `.ehr_state.json`에 저장 |
| `build.ps1` · `build.bat` | PyInstaller로 단일 `dist/WorkTime.exe` 빌드 |
| `requirements.txt` | pywebview, pythonnet, pystray, Pillow, playwright, holidays |

- 입력값/세션 저장: 개발 시 폴더 안(`data.json`·`.ehr_state.json`), exe 배포 시 `%APPDATA%\worktime\`
- 계산: `근무 = (퇴근−출근) − 점심(12:00~13:00 겹치는 만큼)`, 주 목표 40h(`settings.weeklyTarget`)

## 개발 환경
```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\pythonw app.py        # 실행 (콘솔 없이)
```

## exe 빌드 · 배포
- **`build.bat` 더블클릭** → `dist/WorkTime.exe` 생성 (~60MB, 받는 사람은 Python 불필요)
- 받는 사람: exe 실행 → 우측 **로그인** 버튼으로 본인 그룹웨어 1회 로그인 → 이후 자동
- 필요 조건: Windows + **Chrome 또는 Edge**(기본 탑재) + WebView2 런타임(대개 이미 있음)

## 설정 (그룹웨어 주소)
회사 그룹웨어 주소는 **`config.json`** 에 넣는다 (개인정보라 저장소엔 `config.example.json`만 포함, 실제 `config.json`은 `.gitignore`).
```powershell
copy config.example.json config.json     # origin 값을 본인 회사 DaouOffice 주소로 수정
```
`build.bat` 가 `config.json` 을 exe에 함께 묶으므로, 빌드 전에 먼저 설정해야 한다.

## EHR 연동 메모 (DaouOffice)
DaouOffice 공통 API를 쓴다:
```
GET /api/user/session                          -> data.id (userId)
GET /api/ehr/timeline/month?baseDate=&userId=  -> weekList[].dailyList[] (clockInTime/clockOutTime)
```
> 회사 보안정책이 PyInstaller 번들 크롬 실행을 막는 경우가 있어, Playwright는 **시스템에 설치된 Chrome→Edge**(`channel`)를 사용한다.
