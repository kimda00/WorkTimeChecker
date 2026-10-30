# -*- coding: utf-8 -*-
"""근태 — 트레이 상주 데스크톱 앱 (pywebview + pystray)

- 작은 창에서 출근/퇴근/유형을 직접 입력하고 근무·잔여·퇴근가능 시간을 자동 계산
- 창을 닫으면 트레이로 숨김, 트레이 아이콘 클릭으로 다시 열기
- 앱을 켤 때 EHR(ehr.fetch)에서 실제 출퇴근을 자동으로 가져와 채움
"""
import json
import os
import socket
import subprocess
import sys
import threading

import webview

try:
    import pystray
    from PIL import Image, ImageDraw
    HAS_TRAY = True
except Exception as _e:  # pystray/Pillow 미설치 시에도 일반 창으로 동작
    HAS_TRAY = False

BASE = os.path.dirname(os.path.abspath(__file__))


def resource_dir():
    """번들 리소스(ui 등) 위치. exe(frozen)면 _MEIPASS, 아니면 스크립트 폴더."""
    return getattr(sys, "_MEIPASS", BASE)


def data_dir():
    """입력값/세션 저장 위치. exe면 %APPDATA%\\worktime, 아니면 스크립트 폴더."""
    if getattr(sys, "frozen", False):
        d = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "worktime")
        try:
            os.makedirs(d, exist_ok=True)
        except Exception:
            pass
        return d
    return BASE


DATA = os.path.join(data_dir(), "data.json")
UI = os.path.join(resource_dir(), "ui", "index.html")
EHR_PY = os.path.join(BASE, "ehr.py")
MEAL_PY = os.path.join(BASE, "meal.py")
# 캘린더는 쿠키 HTTP(브라우저 없음)라 별도 프로세스 없이 인-프로세스로 처리(cal.fetch).
TTREE_PY = os.path.join(BASE, "ttree.py")
APPROVAL_PY = os.path.join(BASE, "approval.py")

# EHR(Playwright) 작업은 콘솔 stdio가 있는 별도 프로세스로 실행한다.
# pythonw.exe(콘솔 없음)에서 헤드풀 크롬을 직접 spawn 하면 "spawn UNKNOWN"이 나기 때문.
_PY = sys.executable
if _PY.lower().endswith("pythonw.exe"):
    _PY = _PY[:-len("pythonw.exe")] + "python.exe"
_CREATE_NO_WINDOW = 0x08000000


def _worker_env(env_extra=None):
    """작업 프로세스는 새 번들을 사용해 장기 실행 중 임시파일 정리에 대비한다."""
    env = dict(os.environ)
    if env_extra:
        env.update({k: str(v) for k, v in env_extra.items()})
    if getattr(sys, "frozen", False):
        # onefile 자식이 오래된 _MEIPASS를 재사용하면, OS 임시파일 정리 후
        # greenlet 확장 모듈/Playwright 드라이버 등을 불러올 수 없다.
        # 독립 인스턴스로 풀면 메인 앱 종료 후에도 결재 창을 유지할 수 있다.
        env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env


def _run_pw(cmd, script, flag, timeout, env_extra=None):
    """Playwright 작업(EHR/식단/캘린더)을 콘솔 stdio 있는 별도 프로세스로 실행하고
    JSON 결과를 받는다. env_extra 로 추가 파라미터(예: 캘린더 월/선택)를 넘긴다."""
    env = _worker_env(env_extra)
    # exe(frozen): 자기 자신을 재실행해 결과를 임시파일로 받음 (번들엔 별도 .py 없음)
    if getattr(sys, "frozen", False):
        import tempfile
        tf = os.path.join(tempfile.gettempdir(), "worktime_%s_%d.json" % (cmd, os.getpid()))
        try:
            subprocess.run(
                [sys.executable, flag, tf],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                creationflags=_CREATE_NO_WINDOW,
                timeout=timeout,
                env=env,
            )
            with open(tf, "r", encoding="utf-8") as f:
                return json.load(f)
        except subprocess.TimeoutExpired:
            return {"status": "error", "message": "처리 시간 초과"}
        except Exception as e:
            return {"status": "error", "message": str(e)}
        finally:
            try:
                os.remove(tf)
            except Exception:
                pass
    # 개발(스크립트) 모드: 대상 .py 를 별도 프로세스로
    try:
        proc = subprocess.run(
            [_PY, script, cmd],
            cwd=BASE,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=_CREATE_NO_WINDOW,
            timeout=timeout,
            env=env,
        )
        out = (proc.stdout or "").strip()
        for line in reversed(out.splitlines()):
            line = line.strip()
            if line.startswith("{"):
                return json.loads(line)
        msg = (proc.stderr or out or "출력 없음").strip()
        return {"status": "error", "message": msg[:300]}
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": "처리 시간 초과"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def _run_ehr(cmd, timeout):
    flag = "--ehr-login" if cmd == "loginjson" else "--ehr-fetch"
    return _run_pw(cmd, EHR_PY, flag, timeout)

def _run_ttree(cmd, timeout, payload=None):
    """Run TTree Playwright/API work in a console-capable helper process."""
    flag_map = {
        "loginjson": "--ttree-login",
        "statusjson": "--ttree-status",
        "lookupsjson": "--ttree-lookups",
        "submitleavejson": "--ttree-submit-leave",
        "submitbsrpjson": "--ttree-submit-bsrp",
        "submitovertimejson": "--ttree-submit-overtime",
    }
    flag = flag_map.get(cmd)
    if getattr(sys, "frozen", False):
        import tempfile
        tf = os.path.join(tempfile.gettempdir(), "worktime_%s_%d.json" % (cmd, os.getpid()))
        inf = None
        try:
            args = [sys.executable, flag, tf]
            if payload is not None:
                fd, inf = tempfile.mkstemp(prefix="worktime_ttree_", suffix=".json")
                os.close(fd)
                with open(inf, "w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False)
                args.append(inf)
            subprocess.run(
                args,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                creationflags=_CREATE_NO_WINDOW,
                timeout=timeout,
                env=_worker_env(),
            )
            with open(tf, "r", encoding="utf-8") as f:
                return json.load(f)
        except subprocess.TimeoutExpired:
            return {"status": "error", "message": "처리 시간 초과"}
        except Exception as e:
            return {"status": "error", "message": str(e)}
        finally:
            for p in (tf, inf):
                if p:
                    try:
                        os.remove(p)
                    except Exception:
                        pass
    try:
        proc = subprocess.run(
            [_PY, TTREE_PY, cmd],
            cwd=BASE,
            env=dict(os.environ, PYTHONIOENCODING="utf-8"),
            input=json.dumps(payload, ensure_ascii=False) if payload is not None else None,
            **({} if payload is not None else {"stdin": subprocess.DEVNULL}),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=_CREATE_NO_WINDOW,
            timeout=timeout,
        )
        out = (proc.stdout or "").strip()
        for line in reversed(out.splitlines()):
            line = line.strip()
            if line.startswith("{"):
                return json.loads(line)
        msg = (proc.stderr or out or "출력 없음").strip()
        return {"status": "error", "message": msg[:300]}
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": "처리 시간 초과"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def _run_approval(cmd, timeout, payload=None):
    """전자결재 도우미(approval.py) 작업을 별도 프로세스로 실행. payload 는 stdin(dev)/임시파일(frozen)로 전달."""
    flag_map = {"paydayjson": "--approval-payday", "prefilljson": "--approval-prefill"}
    flag = flag_map.get(cmd)
    if getattr(sys, "frozen", False):
        import tempfile
        tf = os.path.join(tempfile.gettempdir(), "worktime_%s_%d.json" % (cmd, os.getpid()))
        inf = None
        try:
            args = [sys.executable, flag, tf]
            if payload is not None:
                fd, inf = tempfile.mkstemp(prefix="worktime_appr_", suffix=".json")
                os.close(fd)
                with open(inf, "w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False)
                args.append(inf)
            subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True,
                           creationflags=_CREATE_NO_WINDOW, timeout=timeout,
                           env=_worker_env())
            with open(tf, "r", encoding="utf-8") as f:
                return json.load(f)
        except subprocess.TimeoutExpired:
            return {"status": "error", "message": "처리 시간 초과"}
        except Exception as e:
            return {"status": "error", "message": str(e)}
        finally:
            for p in (tf, inf):
                if p:
                    try:
                        os.remove(p)
                    except Exception:
                        pass
    try:
        kwargs = dict(cwd=BASE, capture_output=True, text=True, encoding="utf-8",
                      errors="replace", creationflags=_CREATE_NO_WINDOW, timeout=timeout)
        if payload is not None:
            kwargs["input"] = json.dumps(payload, ensure_ascii=False)   # input 이 stdin=PIPE 를 함의
        else:
            kwargs["stdin"] = subprocess.DEVNULL
        proc = subprocess.run([_PY, APPROVAL_PY, cmd], **kwargs)
        out = (proc.stdout or "").strip()
        for line in reversed(out.splitlines()):
            line = line.strip()
            if line.startswith("{"):
                return json.loads(line)
        msg = (proc.stderr or out or "출력 없음").strip()
        return {"status": "error", "message": msg[:300]}
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": "처리 시간 초과"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def _run_approval_prefill_background(payload=None):
    """결재 폼은 열린 창을 오래 유지하므로 helper만 띄우고 메인 UI는 바로 반환한다."""
    try:
        import ehr
        if not os.path.exists(ehr.STATE):
            return {"status": "login_required", "message": "EHR 로그인이 필요해요."}
    except Exception:
        pass

    payload = payload or {}
    try:
        if getattr(sys, "frozen", False):
            import tempfile
            fd, inf = tempfile.mkstemp(prefix="worktime_appr_bg_", suffix=".json")
            os.close(fd)
            with open(inf, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
            subprocess.Popen(
                [sys.executable, "--approval-prefill-bg", inf],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=_CREATE_NO_WINDOW,
                env=_worker_env(),
            )
        else:
            proc = subprocess.Popen(
                [_PY, APPROVAL_PY, "prefilljson"],
                cwd=BASE,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=_CREATE_NO_WINDOW,
            )
            if proc.stdin:
                proc.stdin.write(json.dumps(payload, ensure_ascii=False))
                proc.stdin.close()
        return {"status": "started", "message": "결재 창을 열고 자동채움을 시작했어요."}
    except Exception as e:
        return {"status": "error", "message": str(e)}


DEFAULT = {
    "settings": {
        "dailyTarget": 28800,   # 8h
        "halfTarget": 14400,    # 4h (반차)
        "lunchStart": 43200,    # 12:00
        "lunchEnd": 46800,      # 13:00
        "weeklyTarget": 144000,  # 40h (주 목표)
    },
    "weeks": {},
}


def load_data():
    try:
        with open(DATA, "r", encoding="utf-8") as f:
            d = json.load(f)
        if not isinstance(d, dict) or "settings" not in d:
            raise ValueError("bad data")
        d.setdefault("weeks", {})
        return d
    except Exception:
        return json.loads(json.dumps(DEFAULT))


def save_data(d):
    tmp = DATA + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DATA)


class Api:
    """JS(window.pywebview.api)에서 호출하는 브리지."""

    def load(self):
        return load_data()

    def save(self, data):
        try:
            save_data(data)
            return True
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def fetch_ehr(self):
        """EHR 실제 출퇴근 조회 (별도 프로세스).
        반환: {'status':'ok','records':{'YYYY-MM-DD':{'in':'HH:MM:SS','out':'HH:MM:SS'}}}
        """
        return _run_ehr("fetchjson", timeout=150)

    def ehr_login(self):
        """헤드풀 브라우저를 열어 EHR(DaouOffice)에 1회 로그인 (별도 프로세스)."""
        return _run_ehr("loginjson", timeout=660)

    def fetch_meal(self):
        """게시판 최신 주간식단표 조회 (별도 프로세스). 반환에 image(data URI) 포함."""
        return _run_pw("mealjson", MEAL_PY, "--meal-fetch", timeout=150)


    def ttree_login(self):
        """Open a browser for TTree login and save the session."""
        return _run_ttree("loginjson", timeout=660)

    def ttree_status(self):
        """Fetch my leave/business-trip application status from TTree."""
        return _run_ttree("statusjson", timeout=150)

    def ttree_lookups(self):
        """Fetch TTree leave codes, approval lines, and work preset."""
        return _run_ttree("lookupsjson", timeout=150)

    def ttree_preview_leave(self, data):
        try:
            import ttree
            return ttree.preview_leave(data or {})
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def ttree_preview_bsrp(self, data):
        try:
            import ttree
            return ttree.preview_bsrp(data or {})
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def ttree_submit_leave(self, data):
        return _run_ttree("submitleavejson", timeout=150, payload=data or {})

    def ttree_submit_bsrp(self, data):
        return _run_ttree("submitbsrpjson", timeout=150, payload=data or {})

    def ttree_preview_overtime(self, data):
        import ttree
        return ttree.preview_overtime(data or {})

    def ttree_submit_overtime(self, data):
        return _run_ttree("submitovertimejson", timeout=150, payload=data or {})

    def load_meal(self):
        """네트워크 없이 저장된 최신 식단 이미지를 반환(앱 진입 시 즉시 표시)."""
        try:
            import meal
            return meal.load_cache()
        except Exception as e:
            return {"status": "empty", "message": str(e)}

    def fetch_calendar(self, month=None, calendar_ids=None):
        """해당 월의 캘린더 목록 + 일정 조회. 쿠키 HTTP(브라우저 없음)라 인-프로세스로 빠르게.
        month='YYYY-MM', calendar_ids=[..](없으면 전체). 반환에 calendars/events 포함."""
        try:
            import cal
            return cal.fetch(month or None, calendar_ids or None)
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def load_calendar(self, month=None):
        """네트워크 없이 저장된 해당 월 캐시를 반환(탭 진입 시 즉시 표시)."""
        try:
            import cal
            return cal.load_cache(month)
        except Exception as e:
            return {"status": "empty", "message": str(e)}

    def bus_info(self):
        """배포 기본 키(config.json busApiKey) 유무만 — 키 값은 화면에 넘기지 않는다."""
        try:
            import bus
            return {"defaultKey": bus.has_default_key()}
        except Exception:
            return {"defaultKey": False}

    def bus_search(self, query):
        """지도 이동용 장소 검색(OSM Nominatim). 반환: places[{name,detail,lat,lng}]"""
        try:
            import bus
            return bus.search_place(query)
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def bus_nearby(self, lat, lng, radius=None, api_key=None):
        """지도 중심 근처 정류장. config.json 키가 있으면 경기도 API/TAGO, 없으면 OSM(데모 배차)."""
        try:
            import bus
            return bus.nearby_stops(lat, lng, radius, api_key or None)
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def bus_stop_routes(self, stop, api_key=None):
        """정류장 경유 노선 프로필(첫차·막차·요일별 배차·정류장 오프셋)."""
        try:
            import bus
            return bus.stop_routes(stop, api_key or None)
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def bus_tile(self, z, x, y):
        """버스 지도 배경 타일(OSM, 캐시) — data URI. 실패 시 None."""
        try:
            import bus
            return bus.tile(z, x, y)
        except Exception:
            return None

    def bus_arrivals(self, stop, api_key=None):
        """실시간 도착 예정(TAGO 정류장 + 키가 있을 때만)."""
        try:
            import bus
            return bus.arrivals(stop, api_key or None)
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def bus_history(self, stop):
        """정류장 도착 기록 시간표(요일 종류별 회차 · 기록한 구간). 실시간 도착을 받을 때마다 쌓인다."""
        try:
            import bus
            return bus.history(stop)
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def open_url(self, url):
        """식단 원본 등 그룹웨어 링크를 기본 브라우저로 연다(그룹웨어 도메인만 허용)."""
        try:
            import ehr
            import webbrowser
            if url and ehr.ORIGIN and str(url).startswith(ehr.ORIGIN):
                webbrowser.open(url)
                return True
        except Exception:
            pass
        return False

    def approval_title(self, month, name=""):
        """지출결의서 제목 조립(로컬)."""
        try:
            import approval
            return approval.compose_title(month, name or "")
        except Exception:
            return "%s월 지출결의서(개인경비) - 000" % month

    def approval_payday(self, month):
        """지출월의 지급예정일을 재무톡톡 게시판에서 파싱(읽기, 별도 프로세스)."""
        return _run_approval("paydayjson", timeout=150, payload={"month": month})

    def approval_prefill(self, data):
        """결재 폼을 헤드풀로 열고 텍스트 필드 자동채움. 메인 UI는 기다리지 않는다."""
        return _run_approval_prefill_background(data or {})

    def holidays(self, years):
        """한국 공휴일(대체공휴일 포함). 반환: {'YYYY-MM-DD': '이름', ...}"""
        try:
            import holidays as hol
            kr = hol.SouthKorea(years=list(years))
            return {d.isoformat(): str(name) for d, name in kr.items()}
        except Exception:
            return {}


window = None
_quitting = False


def _make_icon_image(size=256):
    """다크 라운드 사각 + 민트 시계 (트레이/exe 공용)."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    mint = (63, 224, 197, 255)
    pad = size * 0.055
    rad = int(size * 0.23)
    d.rounded_rectangle(
        [pad, pad, size - pad, size - pad],
        radius=rad, fill=(14, 20, 23, 255),
        outline=(43, 184, 159, 150), width=max(2, int(size / 64)),
    )
    cx = cy = size / 2.0
    r = size * 0.275
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=mint, width=max(3, int(size * 0.055)))
    hw = max(3, int(size * 0.052))   # 시침
    mw = max(2, int(size * 0.042))   # 분침
    hx, hy = cx, cy - r * 0.5
    mx, my = cx + r * 0.6, cy + r * 0.34
    d.line([cx, cy, hx, hy], fill=mint, width=hw)
    d.line([cx, cy, mx, my], fill=mint, width=mw)
    for ex, ey, w in ((hx, hy, hw), (mx, my, mw)):       # 둥근 끝
        rr = w / 2.0
        d.ellipse([ex - rr, ey - rr, ex + rr, ey + rr], fill=mint)
    cd = size * 0.045
    d.ellipse([cx - cd, cy - cd, cx + cd, cy + cd], fill=mint)
    return img


def show_window(icon=None, item=None):
    if window:
        window.show()


def refresh_ehr(icon=None, item=None):
    if window:
        window.evaluate_js("window.appRefreshEhr && window.appRefreshEhr()")


def ehr_login_tray(icon=None, item=None):
    def run():
        _run_ehr("loginjson", timeout=660)
        refresh_ehr()
    threading.Thread(target=run, daemon=True).start()


def _flush_ui_state():
    """종료 직전 화면의 최신 상태를 바로 저장한다(0.4초 디바운스 저장을 기다리던 변경도 잃지 않도록)."""
    if not window:
        return
    try:
        raw = window.evaluate_js("typeof state === 'object' && state && state.settings ? JSON.stringify(state) : ''")
        if raw:
            save_data(json.loads(raw))
    except Exception:
        pass


def quit_app(icon=None, item=None):
    global _quitting
    _quitting = True
    _flush_ui_state()
    try:
        if icon is not None:
            icon.stop()
    except Exception:
        pass
    if window:
        window.destroy()


def on_closing():
    # 종료가 아니고 트레이가 있으면: 닫기 대신 숨김
    if _quitting or not HAS_TRAY:
        return True
    if window:
        window.hide()
    return False


def run_tray():
    image = _make_icon_image()
    menu = pystray.Menu(
        pystray.MenuItem("열기", show_window, default=True),
        pystray.MenuItem("EHR 새로고침", refresh_ehr),
        pystray.MenuItem("EHR 로그인", ehr_login_tray),
        pystray.MenuItem("종료", quit_app),
    )
    icon = pystray.Icon("worktime", image, "근태", menu)
    icon.run()


# 단일 인스턴스: Windows에서는 named mutex를 사용한다. 고정 TCP 포트는
# Windows 제외 포트 범위에 들어가면 WSAEACCES가 나서 앱이 조용히 종료될 수 있다.
# 비-Windows 환경에서만 기존 루프백 소켓 방식을 fallback으로 사용한다.
_LOCK_PORT = 49517
_MUTEX_NAME = "Local\\WorkTimeChecker.SingleInstance"


def _show_existing_native_window():
    """숨겨진 기존 Windows 창을 찾아 복원한다."""
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.FindWindowW.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR)
        user32.FindWindowW.restype = wintypes.HWND
        user32.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
        user32.SetForegroundWindow.argtypes = (wintypes.HWND,)
        hwnd = user32.FindWindowW(None, "근태")
        if not hwnd:
            return False
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.SetForegroundWindow(hwnd)
        return True
    except Exception:
        return False


def acquire_single_instance():
    """유일한 인스턴스면 잠금 객체를, 이미 실행 중이면 None을 반환한다."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = kernel32.CreateMutexW(None, False, _MUTEX_NAME)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
            kernel32.CloseHandle(handle)
            _show_existing_native_window()
            return None
        return handle

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", _LOCK_PORT))
    except OSError:
        s.close()
        try:
            with socket.create_connection(("127.0.0.1", _LOCK_PORT), timeout=2) as c:
                c.sendall(b"show")
        except OSError:
            pass
        return None
    s.listen(1)
    return s


def serve_single_instance(lock):
    """다른 실행이 신호를 보내오면 창을 다시 표시한다(데몬 스레드)."""
    while True:
        try:
            conn, _ = lock.accept()
        except OSError:
            return
        try:
            conn.recv(16)
        except OSError:
            pass
        finally:
            conn.close()
        show_window()


def release_single_instance(lock):
    if lock is None:
        return
    if isinstance(lock, socket.socket):
        try:
            lock.close()
        except OSError:
            pass
        return
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
            kernel32.CloseHandle(lock)
        except Exception:
            pass


def main():
    global window
    lock = acquire_single_instance()
    if lock is None:
        return  # 이미 실행 중 — 그 인스턴스 창을 띄우게 신호만 보내고 끝낸다
    api = Api()
    window = webview.create_window(
        "근태",
        UI,
        js_api=api,
        width=900,
        height=530,
        min_size=(720, 450),
    )
    window.events.closing += on_closing
    if isinstance(lock, socket.socket):
        threading.Thread(target=serve_single_instance, args=(lock,), daemon=True).start()
    if HAS_TRAY:
        threading.Thread(target=run_tray, daemon=True).start()
    try:
        webview.start()
    finally:
        release_single_instance(lock)


def _maybe_run_ehr_mode():
    """exe(frozen)에서 _run_pw 가 자기 자신을 재실행한 경우: GUI 대신 작업 수행 후 종료."""
    if getattr(sys, "frozen", False) and len(sys.argv) >= 3 and sys.argv[1] in ("--ehr-fetch", "--ehr-login", "--meal-fetch", "--ttree-login", "--ttree-status", "--ttree-lookups", "--ttree-submit-leave", "--ttree-submit-bsrp", "--ttree-submit-overtime", "--approval-payday", "--approval-prefill", "--approval-prefill-bg"):
        if sys.argv[1] == "--approval-prefill-bg":
            import approval
            payload = {}
            try:
                with open(sys.argv[2], "r", encoding="utf-8") as f:
                    payload = json.load(f)
            except Exception:
                payload = {}
            try:
                os.remove(sys.argv[2])
            except Exception:
                pass
            approval.prefill(payload)
            sys.exit(0)
        if sys.argv[1] == "--meal-fetch":
            import meal
            res = meal.fetch()
        elif sys.argv[1].startswith("--approval"):
            import approval
            payload = {}
            if len(sys.argv) >= 4:
                try:
                    with open(sys.argv[3], "r", encoding="utf-8") as f:
                        payload = json.load(f)
                except Exception:
                    payload = {}
            if sys.argv[1] == "--approval-payday":
                res = approval.fetch_payday(int(payload.get("month") or 1))
            else:
                res = approval.prefill(payload)
        elif sys.argv[1].startswith("--ttree"):
            import ttree
            payload = {}
            if len(sys.argv) >= 4:
                try:
                    with open(sys.argv[3], "r", encoding="utf-8") as f:
                        payload = json.load(f)
                except Exception:
                    payload = {}
            if sys.argv[1] == "--ttree-login":
                res = ttree.login()
            elif sys.argv[1] == "--ttree-status":
                res = ttree.fetch_status()
            elif sys.argv[1] == "--ttree-lookups":
                res = ttree.fetch_lookups()
            elif sys.argv[1] == "--ttree-submit-leave":
                res = ttree.submit_leave(payload)
            elif sys.argv[1] == "--ttree-submit-overtime":
                res = ttree.submit_overtime(payload)
            else:
                res = ttree.submit_bsrp(payload)
        else:
            import ehr
            res = ehr.login() if sys.argv[1] == "--ehr-login" else ehr.fetch()
        try:
            with open(sys.argv[2], "w", encoding="utf-8") as f:
                json.dump(res, f, ensure_ascii=False)
        except Exception:
            pass
        sys.exit(0)


if __name__ == "__main__":
    _maybe_run_ehr_mode()
    main()
