# -*- coding: utf-8 -*-
"""다우오피스 캘린더 API 발견용 탐침 스크립트 (일회성).

캘린더 페이지(/app/calendar)를 실제 브라우저로 열고, 페이지가 호출하는
모든 /api/ 네트워크 요청(URL/메서드/상태)과 캘린더 관련 응답 본문을 캡처해
콘솔 + tools/probe_calendar_out.json 에 덤프한다.

- 세션이 유효하면(.ehr_state.json) headless 로 바로 캡처.
- 만료됐으면 headful 로 열어 사용자가 직접 로그인하면, 로그인 후 이어서 캡처.
"""
import json
import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
import ehr  # ORIGIN / STATE / _launch / _user_id 재사용

ORIGIN = ehr.ORIGIN
STATE = ehr.STATE
OUT = os.path.join(BASE, "tools", "probe_calendar_out.json")

captured = []          # {method,url,status,ct}
bodies = {}            # url -> parsed json (calendar 관련만)


def _want_body(url):
    u = url.lower()
    return "/api/" in u and any(k in u for k in (
        "calendar", "schedule", "event", "colabo", "organization", "member", "user"))


def run(headless):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = ehr._launch(p, headless=headless)
        kw = {}
        if os.path.exists(STATE):
            kw["storage_state"] = STATE
        ctx = browser.new_context(viewport={"width": 1400, "height": 900}, **kw)
        page = ctx.new_page()

        def on_response(resp):
            try:
                req = resp.request
                url = resp.url
                if "/api/" not in url:
                    return
                ct = (resp.headers or {}).get("content-type", "")
                captured.append({"method": req.method, "url": url,
                                 "status": resp.status, "ct": ct})
                if _want_body(url) and "json" in ct and resp.status == 200:
                    try:
                        bodies[url] = resp.json()
                    except Exception:
                        pass
            except Exception:
                pass

        page.on("response", on_response)

        # 1) 로그인 확인 (없으면 headful 로그인 대기)
        try:
            page.goto(ORIGIN + "/", wait_until="domcontentloaded", timeout=60000)
        except Exception:
            pass
        if not ehr._user_id(ctx):
            if headless:
                print("SESSION_EXPIRED")  # 상위에서 headful 재시도
                ctx.close(); browser.close()
                return "expired"
            print(">> 브라우저에서 로그인해 주세요. (최대 5분 대기)")
            for _ in range(300):
                if ehr._user_id(ctx):
                    break
                if not ctx.pages:
                    break
                time.sleep(1)
            try:
                ctx.storage_state(path=STATE)
            except Exception:
                pass

        uid = ehr._user_id(ctx)
        print(">> userId =", uid)

        # 2) 캘린더 페이지 열어 XHR 캡처
        captured.clear(); bodies.clear()
        try:
            page.goto(ORIGIN + "/app/calendar", wait_until="networkidle", timeout=60000)
        except Exception:
            pass
        time.sleep(6)  # lazy XHR 여유

        # 세션 저장(연장)
        try:
            ctx.storage_state(path=STATE)
        except Exception:
            pass
        ctx.close(); browser.close()
    return "ok"


def dump():
    seen = set()
    print("\n===== /api/ 요청 목록 =====")
    for c in captured:
        key = (c["method"], c["url"].split("?")[0])
        if key in seen:
            continue
        seen.add(key)
        print("%-4s %3d  %s" % (c["method"], c["status"], c["url"]))
    print("\n===== 캘린더 관련 응답 본문 (키 구조) =====")
    for url, body in bodies.items():
        print("\n---", url)
        _print_shape(body, depth=0)
    try:
        with open(OUT, "w", encoding="utf-8") as f:
            json.dump({"requests": captured, "bodies": bodies}, f, ensure_ascii=False, indent=2)
        print("\n>> 전체 덤프 저장:", OUT)
    except Exception as e:
        print("save error:", e)


def _print_shape(obj, depth, key=""):
    ind = "  " * depth
    if depth > 4:
        return
    if isinstance(obj, dict):
        print("%s%s{" % (ind, (key + ": ") if key else ""))
        for k, v in list(obj.items())[:30]:
            _print_shape(v, depth + 1, str(k))
        print("%s}" % ind)
    elif isinstance(obj, list):
        print("%s%s[%d]" % (ind, (key + ": ") if key else "", len(obj)))
        if obj:
            _print_shape(obj[0], depth + 1, "[0]")
    else:
        s = repr(obj)
        if len(s) > 60:
            s = s[:60] + "…"
        print("%s%s = %s" % (ind, key, s))


if __name__ == "__main__":
    r = run(headless=True)
    if r == "expired":
        print(">> 세션 만료 — 로그인 창을 엽니다…")
        run(headless=False)
    dump()
