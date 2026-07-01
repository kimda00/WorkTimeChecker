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

# EHR(Playwright) 작업은 콘솔 stdio가 있는 별도 프로세스로 실행한다.
# pythonw.exe(콘솔 없음)에서 헤드풀 크롬을 직접 spawn 하면 "spawn UNKNOWN"이 나기 때문.
_PY = sys.executable
if _PY.lower().endswith("pythonw.exe"):
    _PY = _PY[:-len("pythonw.exe")] + "python.exe"
_CREATE_NO_WINDOW = 0x08000000


def _run_pw(cmd, script, flag, timeout):
    """Playwright 작업(EHR/식단)을 콘솔 stdio 있는 별도 프로세스로 실행하고 JSON 결과를 받는다."""
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

    def load_meal(self):
        """네트워크 없이 저장된 최신 식단 이미지를 반환(앱 진입 시 즉시 표시)."""
        try:
            import meal
            return meal.load_cache()
        except Exception as e:
            return {"status": "empty", "message": str(e)}

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


def quit_app(icon=None, item=None):
    global _quitting
    _quitting = True
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


# 단일 인스턴스: 루프백 포트를 잠금 겸 "창 표시" 신호 채널로 쓴다.
# 닫으면 트레이로 숨는 앱이라, 두 번째 실행이 새 프로세스를 띄우는 대신
# 이미 떠 있는 창을 다시 보여주고 즉시 끝낸다(백그라운드 누적 방지).
_LOCK_PORT = 49517


def acquire_single_instance():
    """유일한 인스턴스면 listen 상태의 잠금 소켓을, 이미 실행 중이면
    그 인스턴스에 '창 표시'를 신호한 뒤 None 을 돌려준다."""
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
        height=490,
        min_size=(720, 450),
    )
    window.events.closing += on_closing
    threading.Thread(target=serve_single_instance, args=(lock,), daemon=True).start()
    if HAS_TRAY:
        threading.Thread(target=run_tray, daemon=True).start()
    webview.start()


def _maybe_run_ehr_mode():
    """exe(frozen)에서 _run_pw 가 자기 자신을 재실행한 경우: GUI 대신 작업 수행 후 종료."""
    if getattr(sys, "frozen", False) and len(sys.argv) >= 3 and sys.argv[1] in ("--ehr-fetch", "--ehr-login", "--meal-fetch"):
        if sys.argv[1] == "--meal-fetch":
            import meal
            res = meal.fetch()
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
