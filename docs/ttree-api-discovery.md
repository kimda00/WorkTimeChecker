# TTree API Discovery Notes

이 문서는 WorkTimeChecker에 TTree 휴가/출장 연동을 붙이기 위해 TTree API를 어떻게 찾았는지 기록한다. 목적은 나중에 TTree 화면이나 JS가 바뀌었을 때 같은 방식으로 다시 검증할 수 있게 하는 것이다.

## Scope And Safety

- 조사 대상은 사용자가 본인 계정으로 로그인해서 쓰는 TTree Electron 앱이다.
- 조사 중에는 읽기/조회 API와 로컬 UI/캐시 파일만 확인한다.
- 실제 신청 API(`POST /vcatn`, `POST /work/bsrp`)는 조사 단계에서 호출하지 않는다.
- 쿠키 값, 비밀번호, 토큰 원문은 문서나 로그에 남기지 않는다.
- `workUserId`, `sanctnId` 같은 값은 직접 입력받지 않고 로그인된 세션과 TTree 조회 결과에서 가져온다.

## Discovery Summary

TTree는 Windows Electron 앱이지만 실제 화면은 회사별 TTree 웹 URL을 로드한다.

- 실행 파일: `C:\ttree\ttree.exe`
- Electron 리소스: `C:\ttree\resources\app.asar`
- 회사별 TTree origin: `https://www.ttrsuresofttech.com`
- Electron 사용자 데이터: `%APPDATA%\ttree`
- CDP 실험 때 사용한 TTree 별도 프로필: `%APPDATA%\worktime\ttree_debug_profile` 또는 개발 폴더의 `ttree_debug_profile`

처음에는 TTree 앱 DevTools 화면에서 버튼/모달 DOM을 보고 단서를 잡았다. 이후 Electron 캐시에 남은 HTML/JS 파일을 검색해서 실제 API 경로와 페이로드 필드를 확인했다.

## Step 1. Electron App 구조 확인

먼저 TTree가 어떤 URL을 로드하는지 확인했다.

```powershell
rg -a -n -m 40 "base_url|ttrsuresofttech|cloud.ttree" "C:\ttree\resources\app.asar"
```

확인한 내용:

- `app.asar` 안에 `https://www.ttrsuresofttech.com` base URL이 있었다.
- 자동 업데이트 URL도 같은 회사별 TTree host를 가리켰다.
- Electron 앱은 로컬 네이티브 앱처럼 보이지만 실제 휴가/출장 화면은 웹 페이지와 JS로 구성되어 있었다.

## Step 2. 화면 DOM에서 시작점 찾기

TTree 화면에서 `내 근태관리` 쪽 버튼을 확인했다.

대표 단서:

- 휴가 신청 버튼: `#vcatnRegBtn`
- 휴가 신청 모달: `휴가 신청`
- 출장 신청 모달: `출장 신청`
- 결재선 select와 결재자 정보 영역
- 휴가 분류/휴가 구분/기간/시작일/시작시각/종료일/종료시각/신청사유 필드
- 출장 구분/기간/시작일/종료일/업체명/지역/첨부파일/사유 필드

이 단계의 목적은 API를 바로 맞히는 것이 아니라, JS 검색 키워드를 확보하는 것이었다.

검색 키워드 예:

```text
vcatnRegBtn
vcatn
bsrp
sanctn
duple
useday
worktime/except
httpAsyncDefaultSend
```

## Step 3. Electron Cache에서 JS/HTML 검색

F12나 `Ctrl+Shift+I`가 막힌 경우에도 Electron은 원격 페이지의 HTML/JS를 `%APPDATA%\ttree\Cache`에 저장한다. Chromium 캐시는 바이너리처럼 섞여 있으므로 `rg -a`로 텍스트 검색했다.

```powershell
rg -a -n -m 80 "/vcatn|/work/bsrp|sanctn|duple|vcatnRegBtn|bsrp|httpAsyncDefaultSend" "$env:APPDATA\ttree\Cache" --glob "f_*"
```

특정 파일에서 주변 라인을 확인할 때는 범위를 잘라서 봤다.

```powershell
$p = "$env:APPDATA\ttree\Cache\f_00040d"
$lines = Get-Content -Encoding UTF8 $p
for ($i = 240; $i -le 340; $i++) {
  if ($i -le $lines.Length) { "{0,5}: {1}" -f $i, $lines[$i - 1] }
}
```

이 방식으로 다음을 확인했다.

- TTree 공통 AJAX 래퍼는 `appJs.httpAsyncDefaultSend(...)` 계열이다.
- 로그인은 `/auth/login`으로 form serialize 값을 보낸다.
- 휴가/출장 신청 화면 JS에 조회, 중복 체크, 저장 endpoint가 그대로 들어 있다.
- 결재선 조회 응답에는 `sanctnInfoList`, `sanctnInfo.sanctnId`, `sanctnDtlInfoList`가 포함된다.

## Step 4. 로그인/세션 구조 확인

로그인 폼 캐시에서 확인한 로그인 요청 필드:

```text
POST /auth/login
userId
userPw
rememberMe
_giosis_remember_me
isMobileApp
fcmToken
connectType=PC
```

서버가 다음 응답을 주면 TTree UI는 "계정정보를 확인해주세요"를 띄운다.

```text
Invalid ISID or password
Bad credentials
```

중요한 결론:

- TTree 원본 Electron 앱이 이미 로그인되어 있어도 별도 Playwright 브라우저 로그인은 실패할 수 있다.
- Electron 쿠키 DB에는 재사용 가능한 세션 쿠키가 없고 remember 계열 쿠키만 남을 수 있다.
- 그래서 최종 구현은 ID/PW 재로그인 방식이 아니라, TTree Electron 세션에 붙는 방식으로 바꿨다.

## Step 5. CDP 연결 방식 확인

Electron은 시작할 때 `--remote-debugging-port`가 붙어야 Chrome DevTools Protocol(CDP) endpoint가 열린다. 이미 일반 모드로 실행 중인 TTree에는 나중에 포트를 추가할 수 없다.

기본 확인:

```powershell
Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:9223/json/version" -TimeoutSec 2
```

기존 TTree를 끌 수 없는 환경에서는 별도 user data dir로 연결용 TTree 인스턴스를 하나 더 띄웠다.

```powershell
$profile = "$env:APPDATA\worktime\ttree_debug_profile"
New-Item -ItemType Directory -Force -Path $profile | Out-Null
Start-Process -FilePath "C:\ttree\ttree.exe" -ArgumentList @(
  "--remote-debugging-port=9223",
  "--remote-allow-origins=*",
  "--user-data-dir=$profile"
)
```

정상적으로 열리면 `/json/version`에서 Electron/Chrome 버전과 `webSocketDebuggerUrl`이 보인다. `/json/list`에서는 TTree 페이지 URL이 보인다.

이 방식은 기존 TTree를 끌 수 없는 환경에서 실험했지만, 현재 WorkTimeChecker 기본 구현은 사용하지 않는다. 현재 기본 흐름은 WorkTimeChecker가 별도 Playwright 브라우저 로그인창을 띄우고 `.ttree_state.json`에 세션을 저장하는 방식이다.

## Step 6. 읽기 API로 세션 검증

세션이 살아 있는지는 `/main` 페이지에 포함된 JS 전역값으로 확인했다.

```text
_sessUserId
_sessCompId
_sessUserNm
_sessDeptNm
```

현재 WorkTimeChecker 구현에서는 저장된 Playwright storage state를 먼저 사용하고, 없거나 만료되면 Electron 쿠키 복사를 fallback으로 시도한다. 세션 저장은 별도 Playwright 로그인창에서 사용자가 직접 로그인했을 때 수행한다.

관련 코드:

- `ttree._session_context()`
- `ttree._current_user()`
- `ttree.login()`
- `ttree.browser_login()`

## Endpoint Evidence

아래 endpoint는 TTree 캐시 JS의 호출 코드와 읽기 API 응답을 바탕으로 정리했다. TTree가 공개 문서로 보장한 API가 아니므로 외부 시스템 계약으로 취급하고 `ttree.py` 내부 adapter 뒤에 숨긴다.

### 결재선

```http
GET /users/sanctn?searchRepUserId={userId}
GET /users/sanctn?searchRepUserId={userId}&searchSanctnSe=VCATN
GET /users/sanctn/{sanctnId}
```

사용 필드:

```text
sanctnInfoList[].sanctnInfo.sanctnId
sanctnInfoList[].sanctnInfo.sanctnNm
sanctnInfoList[].sanctnDtlInfoList[].sanctnUserNm
```

### 휴가 코드/검증

```http
POST /vcatn/cl/get
POST /vcatn/se/get
GET  /work/preset/user?userId={userId}&companyId={companyId}
GET  /vcatn/fileYnChk
GET  /vcatn/worktime/except
POST /vcatn/duple
POST /vcatn/usedaylist/get
```

확인한 역할:

- `/vcatn/cl/get`: 휴가 분류 조회
- `/vcatn/se/get`: 휴가 구분 조회. body는 `{"vcatnClCd":"..."}` 형태
- `/work/preset/user`: 오전/오후 반차와 기본 근무 시간 preset
- `/vcatn/worktime/except`: 휴가 시간/일수 계산
- `/vcatn/duple`: 휴가/출장/초과근무 중복 체크

### 휴가 신청

상태 변경 endpoint라 실제 확인은 payload preview와 JS 근거만으로 정리했고, 앱에서는 명시적 체크박스와 확인창 뒤에만 호출한다.

```http
POST /vcatn
Content-Type: application/json;charset=UTF-8
```

Payload 핵심 필드:

```json
{
  "vcatnBgnDe": "2026-07-01",
  "vcatnEndDe": "2026-07-01",
  "vcatnBgnTime": "080000",
  "vcatnEndTime": "120000",
  "vcatnTimeMnt": "240",
  "vcatnClCd": "...",
  "vcatnSeCd": "...",
  "vcatnCn": "reason",
  "vcatnDayCnt": "0.5",
  "workUserId": "...",
  "sanctnId": "...",
  "atchFileId": "",
  "maternitySplitYn": "N",
  "maternitySplitCnt": ""
}
```

### 출장 중복 체크

```http
GET /work/bsrp/duplechk?searchBgnDe=YYYYMMDD&searchEndDe=YYYYMMDD&searchBgnTime=HHmmss&searchEndTime=HHmmss
```

### 출장 신청

상태 변경 endpoint라 조사 단계에서는 호출하지 않았다.

```http
POST /work/bsrp
Content-Type: application/x-www-form-urlencoded; charset=UTF-8
```

Payload 핵심 필드:

```json
{
  "bsrpBgnDe": "20260701",
  "bsrpEndDe": "20260701",
  "bsrpBgnTime": "080000",
  "bsrpEndTime": "170000",
  "bsrpType": "bsrp",
  "bsrpCn": "reason",
  "customer": "customer name",
  "location": "location",
  "sanctnId": "...",
  "atchFileId": ""
}
```

`bsrpType`:

- `bsrp`: 출장
- `edu`: 교육

### 신청 현황

```http
GET /vcatn/sanctn/my?searchBgnDe=YYYY-MM-DD&searchEndDe=YYYY-MM-DD&searchChkDel=Y&searchTypeYn=Y
GET /work/sanctn/my/bsrp?searchBgnDe=YYYY-MM-DD&searchEndDe=YYYY-MM-DD
```

상태 코드:

```text
000: 결재대기
800: 반려
900: 승인
delYn=Y: 취소/삭제로 표시
```

## Repeatable Checklist

TTree가 업데이트되어 연동이 깨지면 이 순서로 다시 본다.

1. `C:\ttree\resources\app.asar`에서 base URL이 바뀌었는지 확인한다.
2. `%APPDATA%\ttree\Cache`에서 `vcatn`, `bsrp`, `sanctn`, `duple` 키워드를 다시 검색한다.
3. 신청 버튼 ID와 모달 필드 이름이 바뀌었는지 확인한다.
4. `httpAsyncDefaultSend` 호출부 주변에서 method, URL, body 형식을 확인한다.
5. `/main`에서 `_sessUserId` 계열 값이 여전히 있는지 확인한다.
6. 먼저 `/users/sanctn`, `/vcatn/cl/get`, `/vcatn/sanctn/my` 같은 읽기/조회 API만 검증한다.
7. submit endpoint는 preview payload가 기존 JS와 일치하고 UI 확인 절차가 살아 있을 때만 사용한다.

## Implementation Notes

현재 WorkTimeChecker 구현은 다음 순서로 TTree 세션을 잡는다.

1. 사용자가 WorkTimeChecker의 TTree `로그인` 버튼을 누른다.
2. `ttree.login()`이 별도 Playwright 브라우저를 띄워 `ORIGIN + /main`으로 이동한다.
3. 사용자가 열린 브라우저에서 TTree에 로그인한다.
4. `/main`에서 `_sessUserId` 계열 값이 확인되면 `.ttree_state.json`에 세션을 저장한다.
5. 조회/신청 API는 저장된 Playwright 세션을 우선 사용하고, 실패하면 Electron cookie store 복사를 fallback으로 시도한다.

설정 키:

```json
{
  "ttreeOrigin": "https://www.ttrsuresofttech.com"
}
```

주의:

- TTree가 로그인 폼에서 서버 인증 실패를 반환하면 WorkTimeChecker가 세션을 저장할 수 없다.
- 이 경우 TTree 웹 로그인에 쓰는 정확한 로그인 ID 형식과 비밀번호를 다시 확인해야 한다.
- CDP 방식은 다시 필요해질 때를 대비한 조사 기록으로만 남긴다.
