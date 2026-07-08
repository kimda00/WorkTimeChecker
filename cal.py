# -*- coding: utf-8 -*-
"""캘린더(일정) 조회 — 다우오피스 캘린더 API.

다우오피스 그룹웨어 캘린더에서 내 캘린더 + 구독(다른 사람/팀) 캘린더 목록과
지정한 달(월 그리드 범위)의 일정을 읽어 프론트에 넘긴다. '누구 일정까지 볼지'는
프론트의 체크박스(캘린더별)로 거르고, 공휴일(휴일 캘린더)은 빨간날로 표시한다.

인증은 ehr.py 가 저장한 로그인 세션(.ehr_state.json)의 **쿠키만** 재사용한다.
브라우저(Playwright)를 띄우지 않고 순수 HTTP(urllib)로 JSON API를 직접 부르므로
빠르다(브라우저 기동 3~5초 → 수백 ms). 세션 파일은 읽기만 하고 쓰지 않는다
(EHR 로그인 브라우저와의 파일 경합 방지). 만료 시 login_required.

발견한 API (Chrome 네트워크 캡처 — tools/probe_calendar.py):
  GET /api/user/session                          -> data.id (userId)
  GET /api/calendar/user/{userId}/calendar
       -> data[]: {id, name, color, type('normal'|'holiday'|'company'),
                   owner:{id,name}, defaultCalendar}   (내 캘린더 + 전사/휴일)
  GET /api/calendar/feed?sort=sequence+asc
       -> data[]: {id(feedId), color, state, calendar:{id,name,color,type,owner:{id,name}}}
          (내가 구독한 다른 사람/팀 캘린더. color = 내가 지정한 표시색)
  GET /api/calendar/event?timeMin={ISO}&timeMax={ISO}&includingAttendees=true
                          &calendarIds[]=..&calendarIds[]=..
       -> data[]: {id, calendarId, calendarName, calendarOwnerId, color, type,
                   creator:{id,name}, summary, description, location,
                   timeType('allday'|'timed'), visibility, startTime, endTime, ...}
  시각 포맷: ISO8601 +09:00  (예: 2026-07-04T23:59:59.999+09:00)
"""
import datetime
import json
import os
import sys
import urllib.error
import urllib.request
from urllib.parse import quote, urlparse

import ehr  # ORIGIN / STATE / _data_dir 재사용

ORIGIN = ehr.ORIGIN
STATE = ehr.STATE
CAL_DIR = os.path.join(ehr._data_dir(), "calendar")
KST = "+09:00"

# 캘린더 색상 팔레트(번호->hex). 다우오피스 프론트 CSS(.txtcolorN)에서 추출.
# (tools/probe_colors.py) — 프론트에도 동일 팔레트가 있어 참고용으로 백엔드도 보관.
PALETTE = {
    "0": "#a3a3a3", "1": "#905341", "2": "#d06b64", "3": "#d75269", "4": "#fa573c",
    "5": "#ff7537", "6": "#ffad46", "7": "#42d692", "8": "#16a765", "9": "#7bd148",
    "10": "#b3dc6c", "11": "#fbe983", "12": "#fad165", "13": "#f691b2", "14": "#cd74e6",
    "15": "#9a9cff", "16": "#b99aff", "17": "#6691e5", "18": "#9fc6e7",
}


class _AuthError(Exception):
    """세션 만료/미로그인(로그인 필요)."""


def _cookie_header():
    """.ehr_state.json 의 쿠키 중 그룹웨어 도메인용을 'a=b; c=d' 형태로. 없으면 None."""
    try:
        with open(STATE, "r", encoding="utf-8") as f:
            st = json.load(f)
    except Exception:
        return None
    host = urlparse(ORIGIN).hostname or ""
    parts = []
    for c in (st.get("cookies") or []):
        dom = (c.get("domain") or "").lstrip(".")
        if not dom:
            continue
        if host == dom or host.endswith("." + dom) or dom == host:
            parts.append("%s=%s" % (c.get("name"), c.get("value")))
    return "; ".join(parts) if parts else None


def _headers(cookie):
    return {
        "Cookie": cookie,
        "Accept": "application/json, text/plain, */*",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": ORIGIN + "/app/calendar",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    }


def _get_json(url, headers):
    """JSON GET. 인증 실패(4xx/로그인 HTML)는 _AuthError, 그 외 네트워크 오류는 그대로 raise."""
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            body = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise _AuthError()
        raise
    try:
        return json.loads(body)
    except Exception:
        # 세션 만료 시 로그인 페이지 HTML 이 오는 경우 → 로그인 필요로 처리
        raise _AuthError()


def _user_id(headers):
    j = _get_json(ORIGIN + "/api/user/session", headers)
    return ((j or {}).get("data") or {}).get("id")


def _parse_month(month):
    """'YYYY-MM' → (year, month). 없거나 이상하면 이번 달."""
    try:
        y, m = str(month).split("-")[:2]
        y, m = int(y), int(m)
        if 1 <= m <= 12:
            return y, m
    except Exception:
        pass
    t = datetime.date.today()
    return t.year, t.month


def _grid_range(year, month):
    """월 달력 그리드(일요일 시작) 범위 [gridStart(일), gridEnd(토)] 반환.
    다우오피스 캘린더가 일요일 시작 그리드를 쓰므로 동일하게 맞춘다."""
    first = datetime.date(year, month, 1)
    start = first - datetime.timedelta(days=(first.weekday() + 1) % 7)  # 직전(또는 당일) 일요일
    if month == 12:
        nxt = datetime.date(year + 1, 1, 1)
    else:
        nxt = datetime.date(year, month + 1, 1)
    last = nxt - datetime.timedelta(days=1)
    end = last + datetime.timedelta(days=(6 - ((last.weekday() + 1) % 7)))  # 직후(또는 당일) 토요일
    return start, end


def _label(name, ctype, owner_name, mine):
    """체크박스에 보일 캘린더 라벨."""
    if ctype == "holiday":
        return name or "휴일일정"
    if ctype == "company":
        return name or "전사일정"
    if mine:
        return "내 일정"
    if name and name != "내 일정":
        return name                      # 팀 캘린더 등
    return owner_name or "이름 없음"      # 개인 '내 일정' → 소유자 이름


def _list_calendars(uid, headers):
    """내 캘린더 + 구독 캘린더를 통합 목록으로."""
    cals = []
    seen = set()

    def add(cid, name, color, ctype, owner_id, owner_name, mine):
        if cid is None or cid in seen:
            return
        seen.add(cid)
        cals.append({
            "id": cid, "name": name, "color": str(color) if color is not None else "0",
            "type": ctype or "normal", "ownerId": owner_id, "ownerName": owner_name,
            "mine": bool(mine), "label": _label(name, ctype, owner_name, mine),
        })

    # 내 캘린더(전사/휴일 포함)
    j = _get_json("%s/api/calendar/user/%s/calendar" % (ORIGIN, uid), headers)
    for c in ((j or {}).get("data") or []):
        ow = c.get("owner") or {}
        add(c.get("id"), c.get("name"), c.get("color"), c.get("type"),
            ow.get("id"), ow.get("name"), True)

    # 구독(피드) 캘린더
    j = _get_json("%s/api/calendar/feed?sort=%s" % (ORIGIN, quote("sequence asc")), headers)
    for f in ((j or {}).get("data") or []):
        c = f.get("calendar") or {}
        ow = c.get("owner") or {}
        mine = (ow.get("id") == uid)
        # 표시색: 내가 지정한 피드 색(f.color) 우선(이벤트 색과 일치), 없으면 캘린더 색
        color = f.get("color") if f.get("color") is not None else c.get("color")
        add(c.get("id"), c.get("name"), color, c.get("type"),
            ow.get("id"), ow.get("name"), mine)

    return cals


def _fetch_events(cal_ids, tmin, tmax, headers):
    """지정 캘린더들의 일정을 조회해 간결한 형태로 정규화."""
    if not cal_ids:
        return []
    q = "timeMin=%s&timeMax=%s&includingAttendees=true" % (quote(tmin), quote(tmax))
    for cid in cal_ids:
        q += "&calendarIds%5B%5D=" + str(cid)
    j = _get_json(ORIGIN + "/api/calendar/event?" + q, headers)
    out = []
    for ev in ((j or {}).get("data") or []):
        cr = ev.get("creator") or {}
        out.append({
            "id": ev.get("id"),
            "calendarId": ev.get("calendarId"),
            "calendarName": ev.get("calendarName"),
            "color": str(ev.get("color")) if ev.get("color") is not None else "0",
            "type": ev.get("type"),
            "summary": ev.get("summary") or "",
            "location": ev.get("location") or "",
            "creator": cr.get("name") or "",
            "allday": ev.get("timeType") == "allday",
            "start": ev.get("startTime"),
            "end": ev.get("endTime"),
        })
    return out


def _cache_path(month):
    return os.path.join(CAL_DIR, "cal_%s.json" % month)


def _prune_cache(keep=4):
    """오래된 월 캐시 정리(최근 몇 개만 유지)."""
    try:
        files = [fn for fn in os.listdir(CAL_DIR) if fn.startswith("cal_") and fn.endswith(".json")]
        files.sort(reverse=True)
        for fn in files[keep:]:
            try:
                os.remove(os.path.join(CAL_DIR, fn))
            except Exception:
                pass
    except Exception:
        pass


def load_cache(month=None):
    """네트워크 없이 저장된 해당 월 캐시를 반환(탭 진입 시 즉시 표시용)."""
    y, m = _parse_month(month)
    mkey = "%04d-%02d" % (y, m)
    try:
        with open(_cache_path(mkey), "r", encoding="utf-8") as f:
            data = json.load(f)
        data["status"] = "ok"
        data["cached"] = True
        return data
    except Exception:
        return {"status": "empty", "month": mkey}


def fetch(month=None, calendar_ids=None):
    """해당 월의 캘린더 목록 + 일정을 조회(쿠키 HTTP, 브라우저 없음).
    미로그인/만료 시 login_required. calendar_ids 가 None 이면 전체 캘린더 대상."""
    if not ORIGIN:
        return {"status": "error", "message": "그룹웨어 주소 미설정 (config.json 의 origin)"}
    if not os.path.exists(STATE):
        return {"status": "login_required", "message": "EHR 로그인이 필요해요."}
    cookie = _cookie_header()
    if not cookie:
        return {"status": "login_required", "message": "세션이 없어요. 다시 로그인해 주세요."}
    headers = _headers(cookie)

    y, m = _parse_month(month)
    mkey = "%04d-%02d" % (y, m)
    g0, g1 = _grid_range(y, m)
    tmin = "%sT00:00:00.000%s" % (g0.isoformat(), KST)
    tmax = "%sT23:59:59.999%s" % (g1.isoformat(), KST)

    try:
        uid = _user_id(headers)
        if not uid:
            return {"status": "login_required", "message": "세션이 만료됐어요. 다시 로그인해 주세요."}
        calendars = _list_calendars(uid, headers)
        all_ids = [c["id"] for c in calendars if c.get("id") is not None]
        if calendar_ids:
            want = [cid for cid in all_ids if cid in set(calendar_ids)]
        else:
            want = all_ids
        events = _fetch_events(want, tmin, tmax, headers)
    except _AuthError:
        return {"status": "login_required", "message": "세션이 만료됐어요. 다시 로그인해 주세요."}
    except Exception as e:
        return {"status": "error", "message": str(e)}

    result = {
        "status": "ok", "cached": False, "month": mkey,
        "gridStart": g0.isoformat(), "gridEnd": g1.isoformat(),
        "userId": uid, "calendars": calendars, "events": events,
        "boardUrl": ORIGIN + "/app/calendar",
    }
    # 전체 캘린더 기준으로 캐시(체크박스는 프론트에서 거름) —
    # 부분 선택으로 조회한 경우엔 캐시를 덮어쓰지 않는다.
    if not calendar_ids:
        try:
            os.makedirs(CAL_DIR, exist_ok=True)
            with open(_cache_path(mkey), "w", encoding="utf-8") as f:
                json.dump({k: result[k] for k in
                           ("month", "gridStart", "gridEnd", "calendars", "events", "boardUrl")},
                          f, ensure_ascii=False)
            _prune_cache()
        except Exception:
            pass
    return result


def _ids_from_env():
    raw = os.environ.get("WT_CAL_IDS", "").strip()
    if not raw:
        return None
    ids = []
    for part in raw.split(","):
        part = part.strip()
        if part:
            try:
                ids.append(int(part))
            except Exception:
                ids.append(part)
    return ids or None


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "test"
    month = os.environ.get("WT_CAL_MONTH") or (sys.argv[2] if len(sys.argv) > 2 else None)
    if cmd in ("caljson", "calcachejson"):
        res = load_cache(month) if cmd == "calcachejson" else fetch(month, _ids_from_env())
        print(json.dumps(res, ensure_ascii=False))
    else:
        import time
        t = time.time()
        res = fetch(month, _ids_from_env())
        print("status:", res.get("status"), "| month:", res.get("month"), "| %.2fs" % (time.time() - t))
        if res.get("status") == "ok":
            print("calendars:", len(res["calendars"]))
            for c in res["calendars"]:
                print("  - id=%s %-10s type=%s color=%s" % (c["id"], c["label"], c["type"], c["color"]))
            print("events:", len(res["events"]))
            for e in res["events"][:12]:
                print("  *", e["start"], "|", e["type"], "|", e["summary"], "(", e["calendarName"], ")")
        else:
            print(res.get("message"))
