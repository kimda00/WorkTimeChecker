# -*- coding: utf-8 -*-
"""EHR(DaouOffice 근태) 출퇴근 조회.

DaouOffice 그룹웨어 근태 API에서 일자별 출/퇴근을 읽어
{ 'YYYY-MM-DD': {'in':'HH:MM:SS','out':'HH:MM:SS'}, ... } 형태로 반환한다.
(그룹웨어 주소는 config.json 의 origin 으로 설정 — 저장소엔 포함 안 함)

인증: 최초 1회 login()으로 로그인하면 세션을 .ehr_state.json 에 저장하고,
이후 fetch()가 그 상태를 재사용한다. 세션이 만료되면 login_required 반환.
(세션 쿠키가 디스크에 안 남는 경우까지 커버하려고 storage_state 파일을 사용)

발견한 API (Chrome으로 확인):
  GET /api/user/session                         -> data.id = userId
  GET /api/ehr/timeline/month?baseDate=&userId= -> weekList[].dailyList[]
       dailyList item: detailDay.day, clockInTime, clockOutTime, holiDay, afterNow
"""
import datetime
import os
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ORIGIN = "https://gw.suresofttech.com"


def _data_dir():
    """세션/설정 저장 위치. exe(frozen)면 %APPDATA%\\worktime, 아니면 스크립트 폴더."""
    if getattr(sys, "frozen", False):
        d = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "worktime")
        try:
            os.makedirs(d, exist_ok=True)
        except Exception:
            pass
        return d
    return BASE


def _load_origin():
    """그룹웨어 주소(회사마다 다름). config.json 의 origin → 없으면 환경변수.
    공개 저장소에 도메인을 두지 않으려고 config.json(gitignore)으로 분리한다."""
    import json
    cands = []
    if getattr(sys, "frozen", False):
        cands.append(os.path.join(getattr(sys, "_MEIPASS", ""), "config.json"))  # 빌드 시 번들된 값
        cands.append(os.path.join(_data_dir(), "config.json"))                    # 사용자 직접 설정
    else:
        cands.append(os.path.join(BASE, "config.json"))
    for p in cands:
        try:
            with open(p, "r", encoding="utf-8") as f:
                v = (json.load(f) or {}).get("origin")
                if v:
                    origin = v.rstrip("/")
                    if "your-company.com" not in origin:
                        return origin
        except Exception:
            pass
    return (os.environ.get("WORKTIME_GROUPWARE_URL") or DEFAULT_ORIGIN).rstrip("/")


ORIGIN = _load_origin()
STATE = os.path.join(_data_dir(), ".ehr_state.json")

# 쿠키만으로 인증되지만, 브라우저 호출처럼 보이게 헤더를 맞춘다.
HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Referer": (ORIGIN or "") + "/app/ehr",
    "X-Requested-With": "XMLHttpRequest",
}
LAUNCH_ARGS = ["--disable-blink-features=AutomationControlled"]
# 회사 PC 정책이 %LOCALAPPDATA% 의 번들 크롬 실행을 막는 경우가 있어,
# 시스템에 설치된 Chrome → Edge 를 우선 사용하고 번들은 마지막에 시도한다.
_CHANNELS = ["chrome", "msedge", None]


def _clock_time(value):
    """HH:MM:SS 로 정규화(초 보존). EHR 초 단위를 근무시간 계산에 그대로 쓴다.
    (화면 표시는 프론트의 fmt24/fmtDur가 분 단위로 내림)"""
    if not value:
        return ""
    parts = str(value).split(":")
    if len(parts) < 2:
        return ""
    try:
        h = int(parts[0])
        m = int(parts[1])
        s = int(parts[2]) if len(parts) > 2 else 0
    except Exception:
        return ""
    if h < 0 or h > 47 or m < 0 or m > 59 or s < 0 or s > 59:
        return ""
    return f"{h:02d}:{m:02d}:{s:02d}"


def _launch(p, headless):
    last = None
    for ch in _CHANNELS:
        try:
            if ch:
                return p.chromium.launch(headless=headless, channel=ch, args=LAUNCH_ARGS)
            return p.chromium.launch(headless=headless, args=LAUNCH_ARGS)
        except Exception as e:
            last = e
    raise last


def _basedates(today=None):
    """이번 달 + 지난 달의 baseDate(매월 15일). 월 타임라인은 앞뒤 주를
    포함하므로 두 달만 부르면 최근 몇 주가 모두 커버된다."""
    today = today or datetime.date.today()
    this_mid = today.replace(day=15)
    first = today.replace(day=1)
    prev_mid = (first - datetime.timedelta(days=1)).replace(day=15)
    return [this_mid.isoformat(), prev_mid.isoformat()]


def _parse_month(j, records):
    for wk in (j.get("weekList") or []):
        for d in (wk.get("dailyList") or []):
            dd = d.get("detailDay") or {}
            day = dd.get("day")
            if not day or dd.get("afterNow"):
                continue
            cin = d.get("clockInTime")
            cout = d.get("clockOutTime")
            if not (cin or cout):
                continue
            rec = records.setdefault(day, {})
            if cin:
                rec["in"] = _clock_time(cin)
            if cout:
                rec["out"] = _clock_time(cout)
    return records


def _user_id(ctx):
    r = ctx.request.get(ORIGIN + "/api/user/session", headers=HEADERS)
    if not r.ok:
        return None
    try:
        return ((r.json() or {}).get("data") or {}).get("id")
    except Exception:
        return None


def fetch():
    """저장된 세션으로 근태를 조회. 미로그인/만료 시 login_required 반환."""
    if not ORIGIN:
        return {"status": "error", "message": "그룹웨어 주소 미설정 (config.json 의 origin)"}
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        return {"status": "error", "message": "playwright 미설치: %s" % e}

    if not os.path.exists(STATE):
        return {"status": "login_required", "message": "EHR 로그인이 필요해요."}

    try:
        with sync_playwright() as p:
            browser = _launch(p, headless=True)
            ctx = browser.new_context(storage_state=STATE)
            try:
                uid = _user_id(ctx)
                if not uid:
                    return {"status": "login_required",
                            "message": "세션이 만료됐어요. 다시 로그인해 주세요."}
                records = {}
                for base in _basedates():
                    r = ctx.request.get(
                        ORIGIN + "/api/ehr/timeline/month",
                        params={"baseDate": base, "userId": uid},
                        headers=HEADERS,
                    )
                    if not r.ok:
                        continue
                    try:
                        _parse_month(r.json(), records)
                    except Exception:
                        continue
                # 갱신된 쿠키를 다시 저장 (세션 연장)
                try:
                    ctx.storage_state(path=STATE)
                except Exception:
                    pass
                return {"status": "ok", "userId": uid, "records": records}
            finally:
                ctx.close()
                browser.close()
    except Exception as e:
        return {"status": "error", "message": str(e)}


def login(timeout_sec=600):
    """헤드풀 브라우저로 사용자가 직접 로그인. 성공 시 세션을 STATE에 저장."""
    if not ORIGIN:
        return {"status": "error", "message": "그룹웨어 주소 미설정 (config.json 의 origin)"}
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        return {"status": "error", "message": "playwright 미설치: %s" % e}

    try:
        with sync_playwright() as p:
            browser = _launch(p, headless=False)
            ctx = browser.new_context(viewport={"width": 1200, "height": 860})
            page = ctx.new_page()
            try:
                page.goto(ORIGIN + "/", wait_until="domcontentloaded", timeout=60000)
            except Exception:
                pass
            ok = False
            for _ in range(timeout_sec):
                try:
                    if _user_id(ctx):
                        ok = True
                        break
                except Exception:
                    pass
                if not ctx.pages:  # 사용자가 창을 닫음
                    break
                time.sleep(1)
            if ok:
                try:
                    ctx.storage_state(path=STATE)
                except Exception:
                    pass
            try:
                ctx.close()
                browser.close()
            except Exception:
                pass
            return {"status": "ok" if ok else "cancelled"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "test"
    if cmd in ("fetchjson", "loginjson"):
        # app.py 가 별도 프로세스로 호출 → 마지막 줄에 JSON 출력
        import json as _json
        if cmd == "loginjson":
            to = int(sys.argv[2]) if len(sys.argv) > 2 else 600
            res = login(timeout_sec=to)
        else:
            res = fetch()
        print(_json.dumps(res, ensure_ascii=False))
    elif cmd == "login":
        print(login())
    else:
        res = fetch()
        print("status:", res.get("status"))
        if res.get("status") == "ok":
            recs = res.get("records", {})
            print("records:", len(recs), "days")
            for day in sorted(recs)[-12:]:
                print(" ", day, recs[day])
        else:
            print(res.get("message"))
