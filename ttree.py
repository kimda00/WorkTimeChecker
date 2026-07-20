# -*- coding: utf-8 -*-
"""TTree leave and business-trip integration.

This module uses the same Playwright storage_state approach as ehr.py.  Read
operations fetch application status and lookup data.  Submit operations call the
same endpoints used by the TTree web UI, but only when explicitly invoked by the
desktop UI.
"""
import datetime as _dt
import json
import os
import re
import sys
import time
from urllib.parse import urlencode, urlparse

BASE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ORIGIN = "https://www.ttrsuresofttech.com"


def _load_config():
    cands = []
    if getattr(sys, "frozen", False):
        cands.append(os.path.join(getattr(sys, "_MEIPASS", ""), "config.json"))
        cands.append(os.path.join(_data_dir(), "config.json"))
    else:
        cands.append(os.path.join(BASE, "config.json"))
    for p in cands:
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f) or {}
        except Exception:
            pass
    return {}


def _cfg(*keys, default=None):
    cfg = _load_config()
    for key in keys:
        v = cfg.get(key)
        if v not in (None, ""):
            return v
    return default


def _data_dir():
    if getattr(sys, "frozen", False):
        d = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "worktime")
        try:
            os.makedirs(d, exist_ok=True)
        except Exception:
            pass
        return d
    return BASE


def _load_origin():
    v = _cfg("ttreeOrigin", "ttree_origin", "ttreeUrl", "ttree_url")
    if v:
        return str(v).rstrip("/")
    return (os.environ.get("WORKTIME_TTREE_URL") or DEFAULT_ORIGIN).rstrip("/")


ORIGIN = _load_origin()
STATE = os.path.join(_data_dir(), ".ttree_state.json")
HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Referer": ORIGIN + "/main",
    "X-Requested-With": "XMLHttpRequest",
}
JSON_HEADERS = dict(HEADERS, **{"Content-Type": "application/json;charset=UTF-8"})
FORM_HEADERS = dict(HEADERS, **{"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"})
LAUNCH_ARGS = ["--disable-blink-features=AutomationControlled"]
_CHANNELS = ["chrome", "msedge", None]


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


def _today():
    return _dt.date.today()


def _iso_date(v):
    if not v:
        return ""
    s = str(v).strip()
    if re.fullmatch(r"\d{8}", s):
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return s


def _compact_date(v):
    return _iso_date(v).replace("-", "")


def _compact_time(v):
    if not v:
        return ""
    s = str(v).strip()
    digits = re.sub(r"\D", "", s)
    if len(digits) == 4:
        return digits + "00"
    if len(digits) == 6:
        return digits
    return ""


def _hhmm(v):
    s = _compact_time(v)
    return f"{s[:2]}:{s[2:4]}" if len(s) >= 4 else ""


def _date_span_days(start, end):
    try:
        a = _dt.date.fromisoformat(_iso_date(start))
        b = _dt.date.fromisoformat(_iso_date(end))
        return max(1, (b - a).days + 1)
    except Exception:
        return 1


def _json_response(resp):
    try:
        return resp.json()
    except Exception:
        try:
            return {"text": resp.text()[:500]}
        except Exception:
            return {}


def _get(ctx, path, params=None):
    return ctx.request.get(ORIGIN + path, params=params or {}, headers=HEADERS)


def _post_json(ctx, path, data):
    return ctx.request.post(ORIGIN + path, data=json.dumps(data or {}, ensure_ascii=False), headers=JSON_HEADERS)


def _post_form(ctx, path, data):
    encoded = urlencode(data or {})
    return ctx.request.post(ORIGIN + path, data=encoded, headers=FORM_HEADERS)


def _current_user(ctx):
    r = _get(ctx, "/main")
    if not r.ok:
        return None
    text = r.text()
    user_id = _find_js_var(text, "_sessUserId")
    comp_id = _find_js_var(text, "_sessCompId")
    if not user_id:
        return None
    return {
        "userId": user_id,
        "companyId": comp_id or "sure",
        "userName": _find_js_var(text, "_sessUserNm") or "",
        "deptName": _find_js_var(text, "_sessDeptNm") or "",
    }


def _find_js_var(text, name):
    m = re.search(r"var\s+%s\s*=\s*['\"]([^'\"]*)['\"]" % re.escape(name), text or "")
    if m:
        return m.group(1)
    m = re.search(r"%s\s*=\s*['\"]([^'\"]*)['\"]" % re.escape(name), text or "")
    return m.group(1) if m else ""


def _chrome_time_to_unix(expires_utc):
    try:
        v = int(expires_utc or 0)
    except Exception:
        return None
    if v <= 0:
        return None
    # Chromium stores cookie time as microseconds since 1601-01-01 UTC.
    unix = int((v / 1000000) - 11644473600)
    return unix if unix > int(time.time()) else None


def _decrypt_dpapi_cookie(encrypted_value):
    if not encrypted_value or sys.platform != "win32":
        return ""
    data = bytes(encrypted_value)
    if data.startswith(b"v10") or data.startswith(b"v11"):
        return ""
    try:
        import ctypes
        import ctypes.wintypes

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [("cbData", ctypes.wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

        buf = ctypes.create_string_buffer(data)
        blob_in = DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
        blob_out = DATA_BLOB()
        ok = ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
        )
        if not ok:
            return ""
        try:
            raw = ctypes.string_at(blob_out.pbData, blob_out.cbData)
            return raw.decode("utf-8", "replace")
        finally:
            ctypes.windll.kernel32.LocalFree(blob_out.pbData)
    except Exception:
        return ""


def _electron_cookie_db_paths():
    base = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "ttree")
    return [
        os.path.join(base, "Cookies"),
        os.path.join(base, "Network", "Cookies"),
    ]


def _electron_cookies_for_origin():
    try:
        import sqlite3
    except Exception:
        return []
    host = urlparse(ORIGIN).hostname or ""
    if not host:
        return []
    cookies = []
    for db_path in _electron_cookie_db_paths():
        if not os.path.exists(db_path):
            continue
        try:
            con = sqlite3.connect("file:" + db_path + "?mode=ro", uri=True)
            try:
                cur = con.cursor()
                rows = cur.execute(
                    """
                    select host_key, name, value, path, expires_utc, is_secure, is_httponly, encrypted_value, samesite
                    from cookies
                    where host_key = ? or host_key = ? or host_key like ?
                    """,
                    (host, "." + host, "%" + host),
                ).fetchall()
            finally:
                con.close()
        except Exception:
            continue
        for host_key, name, value, path, expires_utc, is_secure, is_httponly, encrypted_value, samesite in rows:
            cookie_value = value or _decrypt_dpapi_cookie(encrypted_value)
            if not cookie_value:
                continue
            item = {
                "name": name,
                "value": cookie_value,
                "domain": host_key,
                "path": path or "/",
                "secure": bool(is_secure),
                "httpOnly": bool(is_httponly),
            }
            expires = _chrome_time_to_unix(expires_utc)
            if expires:
                item["expires"] = expires
            if samesite == 0:
                item["sameSite"] = "None"
            elif samesite == 1:
                item["sameSite"] = "Lax"
            elif samesite == 2:
                item["sameSite"] = "Strict"
            cookies.append(item)
    return cookies


def _with_context(headless=True, prefer_electron=False):
    from playwright.sync_api import sync_playwright
    p = sync_playwright().start()
    browser = _launch(p, headless=headless)
    kwargs = {}
    if os.path.exists(STATE) and not prefer_electron:
        kwargs["storage_state"] = STATE
    ctx = browser.new_context(**kwargs)
    if prefer_electron or not os.path.exists(STATE):
        cookies = _electron_cookies_for_origin()
        if cookies:
            try:
                ctx.add_cookies(cookies)
            except Exception:
                pass
    return p, browser, ctx

def _close(p, browser, ctx, save=True):
    try:
        if save:
            ctx.storage_state(path=STATE)
    except Exception:
        pass
    try:
        ctx.close()
    except Exception:
        pass
    try:
        browser.close()
    except Exception:
        pass
    try:
        p.stop()
    except Exception:
        pass


def _session_context():
    attempts = []
    if os.path.exists(STATE):
        attempts.append(False)
    attempts.append(True)
    last_err = None
    for prefer_electron in attempts:
        try:
            p, browser, ctx = _with_context(headless=True, prefer_electron=prefer_electron)
            user = _current_user(ctx)
            if user:
                return p, browser, ctx, user, None
            _close(p, browser, ctx, save=False)
        except Exception as e:
            last_err = e
            try:
                _close(p, browser, ctx, save=False)
            except Exception:
                pass
    if last_err:
        return None, None, None, None, {"status": "error", "message": str(last_err)}
    return None, None, None, None, {
        "status": "login_required",
        "message": "TTree 로그인이 필요합니다. 로그인 버튼을 눌러 주세요.",
    }


def login(timeout_sec=600):
    return browser_login(timeout_sec=timeout_sec)


def browser_login(timeout_sec=600):
    try:
        p, browser, ctx = _with_context(headless=False)
        page = ctx.new_page()
        try:
            page.goto(ORIGIN + "/main", wait_until="domcontentloaded", timeout=60000)
        except Exception:
            pass
        ok = False
        user = None
        for _ in range(timeout_sec):
            try:
                user = _current_user(ctx)
                if user:
                    ok = True
                    break
            except Exception:
                pass
            if not ctx.pages:
                break
            time.sleep(1)
        _close(p, browser, ctx, save=ok)
        return {"status": "ok", "user": user} if ok else {"status": "cancelled"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def _status_name(code, deleted=False):
    if deleted:
        return "취소/삭제"
    return {
        "000": "결재대기",
        "800": "반려",
        "900": "승인",
        "999": "취소/삭제",
    }.get(str(code or ""), str(code or ""))


def _normalize_leave(item):
    deleted = item.get("delYn") == "Y"
    code = "999" if deleted else (item.get("vcatnConfmCd") or item.get("confmCd") or "")
    return {
        "kind": "leave",
        "id": item.get("vcatnId") or item.get("confmId") or "",
        "title": item.get("vcatnSeNm") or item.get("vcatnClNm") or "휴가",
        "startDate": _iso_date(item.get("vcatnBgnDe")),
        "endDate": _iso_date(item.get("vcatnEndDe")),
        "startTime": _hhmm(item.get("vcatnBgnTime")),
        "endTime": _hhmm(item.get("vcatnEndTime")),
        "dayCount": item.get("vcatnDayCnt") or "",
        "statusCode": code,
        "statusName": _status_name(code, deleted),
        "reason": item.get("vcatnCn") or "",
    }


_BSRP_TYPE_NAMES = {"bsrp": "출장", "edu": "교육"}


def _normalize_bsrp(item):
    code = item.get("confmCd") or item.get("bsrpConfmCd") or item.get("workModConfmCd") or ""
    # API가 이름(bsrpTypeNm) 없이 타입 코드("bsrp"/"edu")만 주는 경우가 있어 한글로 매핑한다
    raw_type = item.get("bsrpType") or ""
    type_name = item.get("bsrpTypeNm") or _BSRP_TYPE_NAMES.get(raw_type, raw_type)
    return {
        "kind": "businessTrip",
        "id": item.get("confmId") or item.get("bsrpSeq") or "",
        "title": type_name or "출장",
        "startDate": _iso_date(item.get("bsrpBgnDe") or item.get("workBgnDe") or item.get("searchBgnDe")),
        "endDate": _iso_date(item.get("bsrpEndDe") or item.get("workEndDe") or item.get("searchEndDe")),
        "startTime": _hhmm(item.get("bsrpBgnTime") or item.get("workBgnTime")),
        "endTime": _hhmm(item.get("bsrpEndTime") or item.get("workEndTime")),
        "statusCode": code,
        "statusName": _status_name(code),
        "customer": item.get("customer") or item.get("custNm") or "",
        "location": item.get("location") or item.get("bsrpPlace") or "",
        "reason": item.get("bsrpCn") or item.get("workChghy") or "",
    }


def fetch_status(days_before=90, days_after=90):
    p, browser, ctx, user, err = _session_context()
    if err:
        return err
    try:
        today = _today()
        begin = (today - _dt.timedelta(days=int(days_before))).isoformat()
        end = (today + _dt.timedelta(days=int(days_after))).isoformat()
        leave_resp = _get(ctx, "/vcatn/sanctn/my", {
            "searchBgnDe": begin,
            "searchEndDe": end,
            "searchChkDel": "Y",
            "searchTypeYn": "Y",
        })
        bsrp_resp = _get(ctx, "/work/sanctn/my/bsrp", {
            "searchBgnDe": begin,
            "searchEndDe": end,
        })
        if not leave_resp.ok and not bsrp_resp.ok:
            return {"status": "error", "message": "TTree status lookup failed."}
        leave_json = _json_response(leave_resp) if leave_resp.ok else {}
        bsrp_json = _json_response(bsrp_resp) if bsrp_resp.ok else {}
        leave = [_normalize_leave(x) for x in (leave_json.get("myVcatnSanctnReqInfoList") or [])]
        bsrp = [_normalize_bsrp(x) for x in (bsrp_json.get("myBsrpSanctnReqInfoList") or [])]
        return {"status": "ok", "user": user, "range": {"begin": begin, "end": end}, "leave": leave, "businessTrip": bsrp}
    finally:
        _close(p, browser, ctx)


def _approval_lines(ctx, user_id, sanctn_se=None):
    params = {"searchRepUserId": user_id}
    if sanctn_se:
        params["searchSanctnSe"] = sanctn_se
    r = _get(ctx, "/users/sanctn", params)
    if not r.ok:
        return []
    data = _json_response(r)
    result = []
    for row in data.get("sanctnInfoList") or []:
        info = row.get("sanctnInfo") or {}
        details = row.get("sanctnDtlInfoList") or []
        result.append({
            "id": info.get("sanctnId") or "",
            "name": info.get("sanctnNm") or "",
            "details": [
                {
                    "ordNo": d.get("ordNo"),
                    "userId": d.get("sanctnUserId"),
                    "userName": d.get("sanctnUserNm"),
                    "deptName": d.get("sanctnDeptNm"),
                }
                for d in sorted(details, key=lambda x: x.get("ordNo") or 0)
            ],
        })
    return result


def _select_approval_id(lines, requested_id="", requested_name=""):
    requested_id = str(requested_id or "")
    requested_name = str(requested_name or "")
    if requested_id:
        for line in lines:
            if line.get("id") == requested_id:
                return requested_id
    if requested_name:
        for line in lines:
            if line.get("name") == requested_name:
                return line.get("id")
    for preferred in ("차상위자", "차상위자 - 최고관리자"):
        for line in lines:
            if line.get("name") == preferred:
                return line.get("id")
    return lines[0].get("id") if lines else ""


def fetch_lookups():
    p, browser, ctx, user, err = _session_context()
    if err:
        return err
    try:
        classes = []
        r = _post_json(ctx, "/vcatn/cl/get", {})
        if r.ok:
            for row in (_json_response(r).get("vcatnClInfo") or []):
                cl = {
                    "code": row.get("vcatnClCd") or "",
                    "name": row.get("vcatnClNm") or "",
                    "types": [],
                }
                sr = _post_json(ctx, "/vcatn/se/get", {"vcatnClCd": cl["code"]})
                if sr.ok:
                    for item in (_json_response(sr).get("vcatnSeInfo") or []):
                        cl["types"].append({
                            "code": item.get("vcatnSeCd") or "",
                            "name": item.get("vcatnSeNm") or "",
                            "dayUnit": item.get("vcatnDayUnit"),
                            "approvalLineName": item.get("approvalLineName") or "",
                            "rangeTypeJson": item.get("rangeTypeJson") or "",
                        })
                classes.append(cl)
        preset = {}
        pr = _get(ctx, "/work/preset/user", {"userId": user["userId"], "companyId": user["companyId"]})
        if pr.ok:
            preset = _json_response(pr).get("preset") or _json_response(pr)
        approvals = _approval_lines(ctx, user["userId"])
        return {"status": "ok", "user": user, "leaveClasses": classes, "approvals": approvals, "preset": preset}
    finally:
        _close(p, browser, ctx)


def _leave_minutes(ctx, user, payload):
    params = {
        "vcatnSeCd": payload["vcatnSeCd"],
        "vcatnClCd": payload["vcatnClCd"],
        "workBgnDe": payload["vcatnBgnDe"],
        "workEndDe": payload["vcatnEndDe"],
        "workBgnTime": payload.get("vcatnBgnTime") or "",
        "workEndTime": payload.get("vcatnEndTime") or "",
        "workUserId": user["userId"],
        "isVcatnChk": "Y",
    }
    r = _get(ctx, "/vcatn/worktime/except", params)
    if r.ok:
        data = _json_response(r)
        if "worktime" in data:
            try:
                return max(0, int(float(data.get("worktime") or 0)))
            except Exception:
                pass
    return None


def build_leave_payload(draft, user=None, ctx=None, approvals=None):
    draft = draft or {}
    start = _iso_date(draft.get("startDate"))
    end = _iso_date(draft.get("endDate") or start)
    cl = str(draft.get("vcatnClCd") or "")
    se = str(draft.get("vcatnSeCd") or "")
    reason = str(draft.get("reason") or "").strip()
    if not start or not end or not cl or not se:
        raise ValueError("휴가 시작일, 종료일, 분류, 구분은 필수입니다.")
    if not reason:
        raise ValueError("휴가 신청 사유를 입력해 주세요.")
    range_code = str(draft.get("rangeCode") or "DAY")
    include_time = range_code in ("AM_HALF_VAC", "PM_HALF_VAC", "CUSTOM") or bool(draft.get("includeTimes"))
    bgn_time = _compact_time(draft.get("startTime")) if include_time else ""
    end_time = _compact_time(draft.get("endTime")) if include_time else ""
    payload = {
        "vcatnBgnDe": start,
        "vcatnEndDe": end,
        "vcatnBgnTime": bgn_time,
        "vcatnEndTime": end_time,
        "vcatnTimeMnt": "",
        "vcatnClCd": cl,
        "vcatnSeCd": se,
        "vcatnCn": reason,
        "vcatnDayCnt": "",
        "workUserId": user["userId"] if user else str(draft.get("workUserId") or ""),
        "sanctnId": "",
        "atchFileId": "",
        "maternitySplitYn": "N",
        "maternitySplitCnt": "",
    }
    minutes = _leave_minutes(ctx, user, payload) if ctx and user else None
    if minutes is None:
        if include_time and bgn_time and end_time:
            bh, bm = int(bgn_time[:2]), int(bgn_time[2:4])
            eh, em = int(end_time[:2]), int(end_time[2:4])
            minutes = max(0, (eh * 60 + em) - (bh * 60 + bm))
        else:
            minutes = 480 * _date_span_days(start, end)
    day_cnt = minutes / 480.0 if minutes else 0
    if include_time and minutes <= 240:
        day_cnt = 0.5
    payload["vcatnTimeMnt"] = str(int(minutes))
    payload["vcatnDayCnt"] = str(int(day_cnt)) if float(day_cnt).is_integer() else str(day_cnt)
    approval_name = draft.get("approvalLineName") or draft.get("approvalName") or ""
    if approvals is not None:
        payload["sanctnId"] = _select_approval_id(approvals, draft.get("sanctnId") or "", approval_name)
    else:
        payload["sanctnId"] = str(draft.get("sanctnId") or "")
    if not payload["sanctnId"]:
        raise ValueError("결재선을 선택해 주세요.")
    return payload


def preview_leave(draft):
    try:
        return {"status": "ok", "endpoint": "POST /vcatn", "contentType": "application/json", "payload": build_leave_payload(draft)}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def submit_leave(draft):
    p, browser, ctx, user, err = _session_context()
    if err:
        return err
    try:
        approvals = _approval_lines(ctx, user["userId"])
        payload = build_leave_payload(draft, user=user, ctx=ctx, approvals=approvals)
        dup = _post_json(ctx, "/vcatn/duple", {
            "searchUserId": user["userId"],
            "searchBgnDe": payload["vcatnBgnDe"],
            "searchEndDe": payload["vcatnEndDe"],
            "searchBgnTime": payload.get("vcatnBgnTime") or "",
            "searchEndTime": payload.get("vcatnEndTime") or "",
            "vcatnSeCd": payload["vcatnSeCd"],
            "vcatnClCd": payload["vcatnClCd"],
        })
        if dup.ok:
            dj = _json_response(dup)
            if int(dj.get("dupleCnt") or 0) > 0:
                return {"status": "duplicate", "message": "이미 등록된 휴가/출장/초과근무 정보와 겹칩니다.", "payload": payload}
        r = _post_json(ctx, "/vcatn", payload)
        body = _json_response(r)
        if not r.ok:
            return {"status": "error", "message": body.get("text") or "휴가 신청 실패", "payload": payload}
        return {"status": "ok", "message": body.get("resultMsg") or "휴가 신청 완료", "payload": payload, "response": body}
    finally:
        _close(p, browser, ctx)


def build_bsrp_payload(draft, approvals=None):
    draft = draft or {}
    start = _compact_date(draft.get("startDate"))
    end = _compact_date(draft.get("endDate") or draft.get("startDate"))
    bgn_time = _compact_time(draft.get("startTime") or "09:00")
    end_time = _compact_time(draft.get("endTime") or "18:00")
    reason = str(draft.get("reason") or "").strip()
    customer = str(draft.get("customer") or "").strip()
    location = str(draft.get("location") or "").strip()
    if not start or not end or not bgn_time or not end_time:
        raise ValueError("출장 일자와 시간을 입력해 주세요.")
    if not reason or not customer or not location:
        raise ValueError("출장 사유, 고객사, 장소를 입력해 주세요.")
    payload = {
        "bsrpBgnDe": start,
        "bsrpEndDe": end,
        "bsrpBgnTime": bgn_time,
        "bsrpEndTime": end_time,
        "bsrpType": str(draft.get("bsrpType") or "bsrp"),
        "bsrpCn": reason,
        "customer": customer,
        "location": location,
        "sanctnId": "",
        "atchFileId": "",
    }
    if approvals is not None:
        payload["sanctnId"] = _select_approval_id(approvals, draft.get("sanctnId") or "", draft.get("approvalName") or "")
    else:
        payload["sanctnId"] = str(draft.get("sanctnId") or "")
    if not payload["sanctnId"]:
        raise ValueError("결재선을 선택해 주세요.")
    return payload


def preview_bsrp(draft):
    try:
        return {"status": "ok", "endpoint": "POST /work/bsrp", "contentType": "application/x-www-form-urlencoded", "payload": build_bsrp_payload(draft)}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def submit_bsrp(draft):
    p, browser, ctx, user, err = _session_context()
    if err:
        return err
    try:
        approvals = _approval_lines(ctx, user["userId"])
        payload = build_bsrp_payload(draft, approvals=approvals)
        dup = _get(ctx, "/work/bsrp/duplechk", {
            "searchBgnDe": payload["bsrpBgnDe"],
            "searchEndDe": payload["bsrpEndDe"],
            "searchBgnTime": payload["bsrpBgnTime"],
            "searchEndTime": payload["bsrpEndTime"],
        })
        if dup.ok:
            dj = _json_response(dup)
            dup_count = dj.get("dupleCnt") or dj.get("duplicateCnt") or dj.get("cnt") or 0
            try:
                if int(dup_count) > 0:
                    return {"status": "duplicate", "message": "이미 등록된 출장/휴가 정보와 겹칩니다.", "payload": payload}
            except Exception:
                pass
        r = _post_form(ctx, "/work/bsrp", payload)
        body = _json_response(r)
        if not r.ok:
            return {"status": "error", "message": body.get("text") or "출장 신청 실패", "payload": payload}
        return {"status": "ok", "message": body.get("resultMsg") or "출장 신청 완료", "payload": payload, "response": body}
    finally:
        _close(p, browser, ctx)


def _read_stdin_json():
    try:
        raw = sys.stdin.read()
        return json.loads(raw) if raw.strip() else {}
    except Exception:
        return {}


def _write_out(res, out_path=None):
    text = json.dumps(res, ensure_ascii=False)
    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(text)
    else:
        print(text)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "statusjson"
    out_path = sys.argv[2] if len(sys.argv) > 2 and sys.argv[1].startswith("--") else None
    in_path = sys.argv[3] if len(sys.argv) > 3 and sys.argv[1].startswith("--") else None
    payload = {}
    if in_path:
        try:
            with open(in_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception:
            payload = {}
    elif cmd in ("submitleavejson", "submitbsrpjson", "previewleavejson", "previewbsrpjson"):
        payload = _read_stdin_json()

    if cmd == "--ttree-login":
        res = login()
    elif cmd == "--ttree-status":
        res = fetch_status()
    elif cmd == "--ttree-lookups":
        res = fetch_lookups()
    elif cmd == "--ttree-submit-leave":
        res = submit_leave(payload)
    elif cmd == "--ttree-submit-bsrp":
        res = submit_bsrp(payload)
    elif cmd == "loginjson":
        res = login()
    elif cmd == "lookupsjson":
        res = fetch_lookups()
    elif cmd == "submitleavejson":
        res = submit_leave(payload)
    elif cmd == "submitbsrpjson":
        res = submit_bsrp(payload)
    elif cmd == "previewleavejson":
        res = preview_leave(payload)
    elif cmd == "previewbsrpjson":
        res = preview_bsrp(payload)
    else:
        res = fetch_status()
    _write_out(res, out_path)


if __name__ == "__main__":
    main()
