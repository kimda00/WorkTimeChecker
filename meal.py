# -*- coding: utf-8 -*-
"""주간식단표(게시판) 조회.

DaouOffice 그룹웨어 게시판(주간메뉴 board)의 최신 글에서 본문 인라인 이미지를
받아 { 'image':'data:image/png;base64,...', 'title':..., 'createdAt':... } 로 반환한다.

인증/세션은 ehr.py 와 같은 .ehr_state.json 을 재사용한다(같은 그룹웨어 세션 —
별도 로그인 불필요, 만료 시 EHR 로그인으로 커버). board id 는 config.json 의
mealBoardId(기본 380).

발견한 API (Chrome 캡처):
  GET /api/board/{id}/posts/classic?page=0&offset=20&sorts=sortCriteria+desc,...
       -> data[]: {id, title, createdAt, hasAttach}  (정렬 desc → 최신이 앞)
  GET /api/board/{id}/post/{postId}/classic
       -> data.content(본문 HTML; 인라인 <img src="/thumb/attach/original/..">),
          data.attaches[](첨부; pdf 등)
  GET {origin}{img src} -> 이미지 바이트
"""
import base64
import json
import os
import re
import sys

import ehr  # ORIGIN / STATE / BASE / _data_dir / _launch / _user_id 재사용

ORIGIN = ehr.ORIGIN
STATE = ehr.STATE
DEFAULT_BOARD_ID = 380
MEAL_DIR = os.path.join(ehr._data_dir(), "meal")
MANIFEST = os.path.join(MEAL_DIR, "meal.json")

# 정렬: 최신(sortCriteria desc)이 앞으로. (URL-encoded ',' = %2C, '+' = 공백)
LIST_SORT = "sortCriteria+desc%2CthreadRootCode+desc%2CthreadCode+asc"


def _board_id():
    """config.json 의 mealBoardId (없으면 기본 380)."""
    cands = []
    if getattr(sys, "frozen", False):
        cands.append(os.path.join(getattr(sys, "_MEIPASS", ""), "config.json"))
        cands.append(os.path.join(ehr._data_dir(), "config.json"))
    else:
        cands.append(os.path.join(ehr.BASE, "config.json"))
    for p in cands:
        try:
            with open(p, "r", encoding="utf-8") as f:
                v = (json.load(f) or {}).get("mealBoardId")
                if v:
                    return int(v)
        except Exception:
            pass
    return DEFAULT_BOARD_ID


def _headers(board):
    return {
        "Accept": "application/json, text/plain, */*",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": ORIGIN + "/app/board/%d" % board,
    }


def _board_url(board):
    return ORIGIN + "/app/board/%d" % board


def _data_uri(path):
    ext = os.path.splitext(path)[1].lstrip(".").lower() or "png"
    mime = "image/jpeg" if ext in ("jpg", "jpeg") else "image/" + ext
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return "data:%s;base64,%s" % (mime, b64)


def _prune_except(keep_name):
    """meal 폴더에서 keep_name(+manifest) 외 파일 삭제 → 최신 1개만 유지."""
    keep = {keep_name, os.path.basename(MANIFEST)}
    try:
        for fn in os.listdir(MEAL_DIR):
            if fn not in keep:
                try:
                    os.remove(os.path.join(MEAL_DIR, fn))
                except Exception:
                    pass
    except Exception:
        pass


def _latest_post(ctx, board, headers):
    """게시판에서 작성일(createdAt) 최신 글 1개. 일반+공지 목록을 합쳐 최신을 고른다."""
    urls = [
        "%s/api/board/%d/posts/classic?page=0&offset=20&sorts=%s" % (ORIGIN, board, LIST_SORT),
        "%s/api/board/%d/posts/classic/notice?page=0&sorts=%s" % (ORIGIN, board, LIST_SORT),
    ]
    best = None
    for u in urls:
        try:
            r = ctx.request.get(u, headers=headers)
            if not r.ok:
                continue
            for post in ((r.json() or {}).get("data") or []):
                if best is None or (post.get("createdAt") or "") > (best.get("createdAt") or ""):
                    best = post
        except Exception:
            continue
    return best


def load_cache():
    """네트워크 없이 저장된 최신 식단 이미지를 반환(앱 진입 시 즉시 표시용)."""
    try:
        with open(MANIFEST, "r", encoding="utf-8") as f:
            m = json.load(f)
        img = os.path.join(MEAL_DIR, m.get("file", ""))
        if not (m.get("file") and os.path.exists(img)):
            return {"status": "empty"}
        return {
            "status": "ok", "cached": True,
            "postId": m.get("postId"), "title": m.get("title"),
            "createdAt": m.get("createdAt"), "pdfName": m.get("pdfName"),
            "boardUrl": _board_url(_board_id()), "image": _data_uri(img),
        }
    except Exception:
        return {"status": "empty"}


def fetch():
    """게시판 최신 주간식단표를 조회해 이미지(data URI)로 반환.
    미로그인/만료 시 login_required(EHR 로그인 재사용)."""
    if not ORIGIN:
        return {"status": "error", "message": "그룹웨어 주소 미설정 (config.json 의 origin)"}
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        return {"status": "error", "message": "playwright 미설치: %s" % e}
    if not os.path.exists(STATE):
        return {"status": "login_required", "message": "EHR 로그인이 필요해요."}

    board = _board_id()
    headers = _headers(board)
    try:
        with sync_playwright() as p:
            browser = ehr._launch(p, headless=True)
            ctx = browser.new_context(storage_state=STATE)
            try:
                if not ehr._user_id(ctx):
                    return {"status": "login_required",
                            "message": "세션이 만료됐어요. 다시 로그인해 주세요."}

                post = _latest_post(ctx, board, headers)
                if not post:
                    return {"status": "empty", "message": "게시판에 글이 없어요.",
                            "boardUrl": _board_url(board)}
                pid = post.get("id")

                dr = ctx.request.get("%s/api/board/%d/post/%d/classic" % (ORIGIN, board, pid),
                                     headers=headers)
                if not dr.ok:
                    return {"status": "error", "message": "상세 조회 실패 (%d)" % dr.status}
                d = (dr.json() or {}).get("data") or {}
                content = d.get("content") or ""
                attaches = d.get("attaches") or []
                pdf = next((a for a in attaches if (a.get("extention") or "").lower() == "pdf"), None)

                srcs = re.findall(r'<img[^>]*?\ssrc="([^"]+)"', content)
                if not srcs:
                    return {"status": "no_image", "message": "본문에 이미지가 없어요.",
                            "title": d.get("title"), "createdAt": d.get("createdAt"),
                            "pdfName": pdf.get("name") if pdf else None,
                            "boardUrl": _board_url(board)}
                src = srcs[0]
                url = src if src.startswith("http") else ORIGIN + src
                ir = ctx.request.get(url, headers={"Referer": headers["Referer"]})
                if not ir.ok:
                    return {"status": "error", "message": "이미지 다운로드 실패 (%d)" % ir.status}
                body = ir.body()
                ct = (ir.headers or {}).get("content-type", "")
                ext = "jpg" if "jpeg" in ct else "png"

                try:
                    os.makedirs(MEAL_DIR, exist_ok=True)
                except Exception:
                    pass
                fname = "meal_%s.%s" % (pid, ext)
                fpath = os.path.join(MEAL_DIR, fname)
                with open(fpath, "wb") as f:
                    f.write(body)
                with open(MANIFEST, "w", encoding="utf-8") as f:
                    json.dump({
                        "postId": pid, "title": d.get("title"),
                        "createdAt": d.get("createdAt"), "file": fname,
                        "pdfName": pdf.get("name") if pdf else None,
                    }, f, ensure_ascii=False)
                _prune_except(fname)   # 이전 주 파일 삭제 → 최신 1개만

                try:
                    ctx.storage_state(path=STATE)   # 세션 연장
                except Exception:
                    pass

                return {
                    "status": "ok", "cached": False,
                    "postId": pid, "title": d.get("title"),
                    "createdAt": d.get("createdAt"),
                    "pdfName": pdf.get("name") if pdf else None,
                    "boardUrl": _board_url(board), "image": _data_uri(fpath),
                }
            finally:
                ctx.close()
                browser.close()
    except Exception as e:
        return {"status": "error", "message": str(e)}


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "test"
    if cmd in ("mealjson", "cachejson"):
        # app.py 가 별도 프로세스로 호출 → 마지막 줄에 JSON 출력
        res = load_cache() if cmd == "cachejson" else fetch()
        print(json.dumps(res, ensure_ascii=False))
    else:
        res = fetch()
        print("status:", res.get("status"), "|", res.get("title"), "|", res.get("createdAt"))
        if res.get("status") != "ok":
            print(res.get("message"))
