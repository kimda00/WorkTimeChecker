# -*- coding: utf-8 -*-
"""전자결재(지출결의서) 기안 도우미.

편의 도우미만 담당한다 — 실제 결재 '제출'은 사용자가 정식 다우오피스 화면에서 한다.
  1) 제목 조립: "n월 지출결의서(개인경비) - 000"
  2) 지급예정일: 재무톡톡 게시판(financeBoardId=46)의 '{지급월}월 지급일정 공지'에서
     '개인경비(법인카드…' 줄의 날짜(MM/DD)를 파싱 (읽기 — 식단 게시판과 동일 패턴)
  3) prefill: EHR 세션(.ehr_state.json)을 로드한 Playwright 헤드풀 창으로 결재 폼을 열고
     텍스트 필드(제목/지급처/지급요청일)를 자동채움. 카드내역/검토/제출은 사용자 몫.
  4) 기본 프로젝트: 전표 각 행의 '프로젝트' 셀에 앱에서 설정한 프로젝트를 채운다.
     폼은 '프로젝트 일괄등록' 팝업으로 체크된 행에만 넣지만, 제출 시 읽는 값은 행의
     td.dzproject 의 data-code/data-name 과 input 값이라 그걸 직접 쓴다. 카드내역으로
     행이 나중에 추가되므로 창이 열려 있는 동안 비어 있는 행을 계속 채운다.
     프로젝트 검색은 폼이 쓰는 같은 API(/api/amaranth/project/projectDepts)를 쓴다.

인증/세션은 ehr.py 와 같은 .ehr_state.json 을 재사용한다.
"""
import datetime
import json
import os
import re
import sys
import time

import ehr

ORIGIN = ehr.ORIGIN
STATE = ehr.STATE
DEFAULT_FINANCE_BOARD = 46
DEFAULT_APPROVAL_URL = ORIGIN + "/app/approval/document/new/352/3101"
LIST_SORT = "sortCriteria+desc%2CthreadRootCode+desc%2CthreadCode+asc"
_WEEKDAY = ["월", "화", "수", "목", "금", "토", "일"]


def _config(key, default=None):
    cands = []
    if getattr(sys, "frozen", False):
        cands.append(os.path.join(getattr(sys, "_MEIPASS", ""), "config.json"))
        cands.append(os.path.join(ehr._data_dir(), "config.json"))
    else:
        cands.append(os.path.join(ehr.BASE, "config.json"))
    for p in cands:
        try:
            with open(p, "r", encoding="utf-8") as f:
                v = (json.load(f) or {}).get(key)
                if v:
                    return v
        except Exception:
            pass
    return default


def _finance_board():
    try:
        return int(_config("financeBoardId", DEFAULT_FINANCE_BOARD))
    except Exception:
        return DEFAULT_FINANCE_BOARD


def _approval_url():
    return _config("approvalUrl", DEFAULT_APPROVAL_URL)


def _dept_from_url(url):
    """결재 폼 URL '/document/new/{기안부서id}/{양식id}' 에서 부서 id. 프로젝트 검색은 부서별이다."""
    m = re.search(r"/document/new/(\d+)/", url or "")
    return int(m.group(1)) if m else None


def _project_api(ctx, keyword, dept):
    """폼의 '프로젝트 관리' 팝업이 쓰는 검색 API. 이름으로 찾고, 없으면 코드로 다시 찾는다.
    [{code, name}] 반환(최대 20건)."""
    items = _project_api_by(ctx, keyword, dept, "name")
    return items or _project_api_by(ctx, keyword, dept, "code")


def _project_api_by(ctx, keyword, dept, field):
    import urllib.parse
    params = json.dumps({"depts": [dept] if dept else [], "code": "", "name": "", field: keyword or ""},
                        ensure_ascii=False)
    u = "%s/api/amaranth/project/projectDepts?params=%s&flag=false&offset=20&page=0&property=projectCode&direction=desc" % (
        ORIGIN, urllib.parse.quote(params))
    r = ctx.request.get(u, headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"})
    if not r.ok:
        raise RuntimeError("프로젝트 검색 실패 (HTTP %d)" % r.status)
    items = (r.json() or {}).get("data") or []
    return [{"code": it.get("projectCode") or "", "name": it.get("projectName") or ""} for it in items]


def _pick_project(items, keyword):
    """검색 결과에서 하나를 고른다: 코드/이름 완전 일치 > 유일한 결과. 못 고르면 None."""
    kw = (keyword or "").strip()
    for it in items:
        if kw and kw in (it["code"], it["name"]):
            return it
    return items[0] if len(items) == 1 else None


def search_projects(keyword):
    """앱의 '기본 프로젝트' 설정용 검색. {status, projects:[{code,name}]}"""
    if not os.path.exists(STATE):
        return {"status": "login_required", "message": "EHR 로그인이 필요해요."}
    if not (keyword or "").strip():
        return {"status": "error", "message": "프로젝트 이름(일부)을 입력하세요."}
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        return {"status": "error", "message": "playwright 미설치: %s" % e}
    try:
        with sync_playwright() as p:
            b = ehr._launch(p, headless=True)
            ctx = b.new_context(storage_state=STATE)
            try:
                if not ehr._user_id(ctx):
                    return {"status": "login_required", "message": "세션이 만료됐어요."}
                items = _project_api(ctx, keyword.strip(), _dept_from_url(_approval_url()))
                return {"status": "ok", "projects": items}
            finally:
                ctx.close()
                b.close()
    except Exception as e:
        return {"status": "error", "message": str(e)}


def _headers(board):
    return {"Accept": "application/json, text/plain, */*",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": ORIGIN + "/app/board/%d" % board}


def compose_title(expense_month, name=""):
    """지출결의서 제목: 'n월 지출결의서(개인경비) - {이름}' (이름 없으면 000)."""
    m = int(expense_month)
    tail = name.strip() if (name and name.strip()) else "000"
    return "%d월 지출결의서(개인경비) - %s" % (m, tail)


def _fmt_date_kr(iso):
    """'2026-07-21' → '2026-07-21(화)' (폼의 기안일 표기 형식에 맞춤)."""
    try:
        d = datetime.date.fromisoformat(iso[:10])
        return "%s(%s)" % (d.isoformat(), _WEEKDAY[d.weekday()])
    except Exception:
        return iso or ""


def _strip_html(h):
    h = re.sub(r"<br\s*/?>", "\n", h or "")
    h = re.sub(r"</(p|div|tr|li|h\d|td)>", "\n", h)
    h = re.sub(r"<[^>]+>", " ", h)
    h = re.sub(r"&nbsp;", " ", h)
    h = re.sub(r"[ \t]+", " ", h)
    return re.sub(r"\n\s*\n+", "\n", h).strip()


def _pay_notice_month(expense_month, today=None):
    """지출월 M → 지급일정 공지월 M+1 (연도 넘김)."""
    today = today or datetime.date.today()
    m = int(expense_month)
    y = today.year
    pm = m + 1
    if pm > 12:
        pm, y = 1, y + 1
    return y, pm


def _parse_payday(content, year, pay_month):
    """본문에서 '개인경비(법인카드…' 줄의 MM/DD → 'YYYY-MM-DD'. 실패 시 None."""
    text = _strip_html(content)
    for line in text.splitlines():
        if "개인경비" in line:
            m = re.search(r"(\d{1,2})\s*/\s*(\d{1,2})", line)
            if m:
                return "%04d-%02d-%02d" % (year, int(m.group(1)), int(m.group(2)))
    m = re.search(r"(%d)\s*/\s*(\d{1,2})" % pay_month, text)   # 폴백
    if m:
        return "%04d-%02d-%02d" % (year, int(m.group(1)), int(m.group(2)))
    return None


def fetch_payday(expense_month):
    """지출월(expense_month)의 지급예정일을 재무톡톡 게시판에서 파싱해 반환."""
    if not os.path.exists(STATE):
        return {"status": "login_required", "message": "EHR 로그인이 필요해요."}
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        return {"status": "error", "message": "playwright 미설치: %s" % e}

    board = _finance_board()
    headers = _headers(board)
    year, pay_month = _pay_notice_month(expense_month)
    try:
        with sync_playwright() as p:
            b = ehr._launch(p, headless=True)
            ctx = b.new_context(storage_state=STATE)
            try:
                if not ehr._user_id(ctx):
                    return {"status": "login_required", "message": "세션이 만료됐어요."}
                posts = []
                for suffix in ("", "/notice"):
                    u = "%s/api/board/%d/posts/classic%s?page=0&offset=30&sorts=%s" % (
                        ORIGIN, board, suffix, LIST_SORT)
                    r = ctx.request.get(u, headers=headers)
                    if r.ok:
                        posts.extend((r.json() or {}).get("data") or [])
                pat = re.compile(r"%d\s*월\s*지급일정" % pay_month)
                cand = [pp for pp in posts if pat.search(pp.get("title") or "")]
                if not cand:
                    return {"status": "not_found",
                            "message": "%d월 지급일정 공지를 못 찾았어요." % pay_month,
                            "payNoticeMonth": pay_month}
                post = cand[0]
                dr = ctx.request.get("%s/api/board/%d/post/%d/classic" % (ORIGIN, board, post["id"]),
                                     headers=headers)
                d = (dr.json() or {}).get("data") or {}
                payday = _parse_payday(d.get("content"), year, pay_month)
                return {"status": "ok" if payday else "no_date",
                        "payday": payday, "sourceTitle": d.get("title"),
                        "payNoticeMonth": pay_month,
                        "boardUrl": ORIGIN + "/app/board/%d" % board}
            finally:
                ctx.close()
                b.close()
    except Exception as e:
        return {"status": "error", "message": str(e)}


# 폼 자동채움 JS. 제목은 안정적 id(#subject), 지급처/지급요청일은 표 헤더 텍스트로 런타임 탐색.
# React/프레임워크가 value 를 관리하는 경우까지 커버하려 네이티브 setter + input/change 이벤트를 쓴다.
_AUTOFILL_JS = r"""
(data) => {
  const setVal = (el, v) => {
    if (!el) return false;
    const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
    setter.call(el, v);
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
    el.dispatchEvent(new Event('blur', { bubbles: true }));
    return true;
  };
  const byHeader = (label) => {
    const inputs = document.querySelectorAll('td input, td textarea');
    for (const el of inputs) {
      const td = el.closest('td'); if (!td) continue;
      const tr = td.closest('tr'); if (!tr) continue;
      const idx = Array.from(tr.children).indexOf(td);
      let prev = tr.previousElementSibling, hdr = '';
      while (prev && !hdr) {
        const c = prev.children[idx];
        if (c) hdr = (c.innerText || '').replace(/\s+/g, '');
        prev = prev.previousElementSibling;
      }
      if (hdr === label) return el;
    }
    return null;
  };
  const done = {};
  if (data.title)  done.title  = setVal(document.getElementById('subject'), data.title);
  if (data.payee)  done.payee  = setVal(byHeader('지급처'), data.payee);
  if (data.payday) done.payday = setVal(byHeader('지급요청일'), data.payday);
  return done;
};
"""

# 전표 행의 프로젝트 셀 채우기. 비어 있는 행만 채워 사용자가 직접 고른 프로젝트는 건드리지 않는다.
# (폼 JS 의 '프로젝트 일괄등록' 콜백과 같은 방식: input 값 + td 의 data-code/data-name)
_PROJECT_FILL_JS = r"""
(pj) => {
  let filled = 0, total = 0;
  document.querySelectorAll('#slipBplTable .dzproject').forEach(td => {
    const inp = td.querySelector('input'); if (!inp) return;
    total++;
    if ((inp.value || '').trim()) return;
    inp.value = pj.name;
    td.setAttribute('data-code', pj.code);
    td.setAttribute('data-name', pj.name);
    filled++;
  });
  return { filled, total };
};
"""


def _resolve_project(ctx, project, url):
    """payload.project ({code,name} 또는 {keyword} / 문자열) → {code,name} 또는 None(+사유)."""
    if not project:
        return None, ""
    if isinstance(project, str):
        project = {"keyword": project}
    code = (project.get("code") or "").strip()
    name = (project.get("name") or "").strip()
    if code and name:
        return {"code": code, "name": name}, ""
    kw = (project.get("keyword") or name or code).strip()
    if not kw:
        return None, ""
    try:
        items = _project_api(ctx, kw, _dept_from_url(url))
    except Exception as e:
        return None, str(e)
    pick = _pick_project(items, kw)
    if pick:
        return pick, ""
    if not items:
        return None, "'%s' 프로젝트를 못 찾았어요." % kw
    return None, "'%s' 검색 결과가 %d건이라 고르지 못했어요." % (kw, len(items))


def prefill(payload):
    """헤드풀 브라우저로 결재 폼을 열고 텍스트 필드를 자동채움. 창은 사용자가 닫을 때까지 유지.
    payload: {title, payee, payday, project}. 카드내역/검토/제출은 사용자 몫.
    project 가 있으면 창이 열려 있는 동안 전표 행의 빈 프로젝트 셀을 계속 채운다."""
    if not os.path.exists(STATE):
        return {"status": "login_required", "message": "EHR 로그인이 필요해요."}
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        return {"status": "error", "message": "playwright 미설치: %s" % e}

    data = {
        "title": (payload or {}).get("title") or "",
        "payee": (payload or {}).get("payee") or "",
        "payday": _fmt_date_kr((payload or {}).get("payday") or ""),
    }
    url = _approval_url()
    try:
        with sync_playwright() as p:
            b = ehr._launch(p, headless=False)
            ctx = b.new_context(storage_state=STATE, viewport={"width": 1400, "height": 1000})
            page = ctx.new_page()
            if not ehr._user_id(ctx):
                try:
                    ctx.close(); b.close()
                except Exception:
                    pass
                return {"status": "login_required", "message": "세션이 만료됐어요. EHR 로그인 후 다시."}
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
            except Exception:
                pass
            filled = {}
            try:
                page.wait_for_selector("#subject", timeout=30000)
                page.wait_for_timeout(1200)
                filled = page.evaluate(_AUTOFILL_JS, data) or {}
            except Exception as e:
                filled = {"error": str(e)}
            project, why = _resolve_project(ctx, (payload or {}).get("project"), url)
            if project:
                filled["project"] = project
            elif why:
                filled["projectError"] = why
            # 사용자가 검토·카드입력·제출 후 창을 닫을 때까지 대기 (최대 15분).
            # 그동안 카드내역 등으로 생긴 행의 빈 프로젝트 셀을 2초마다 채운다.
            project_rows = 0
            for i in range(900):
                if not ctx.pages:
                    break
                if project and i % 2 == 0:
                    try:
                        r = page.evaluate(_PROJECT_FILL_JS, project) or {}
                        project_rows += int(r.get("filled") or 0)
                    except Exception:
                        pass   # 페이지 이동/닫힘 중이면 다음 턴에 다시
                time.sleep(1)
            filled["projectRows"] = project_rows
            try:
                ctx.storage_state(path=STATE)   # 세션 연장
            except Exception:
                pass
            try:
                ctx.close(); b.close()
            except Exception:
                pass
            return {"status": "ok", "filled": filled}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def _read_stdin_payload():
    try:
        raw = sys.stdin.read()
        return json.loads(raw) if raw and raw.strip() else {}
    except Exception:
        return {}


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "test"
    if cmd == "paydayjson":
        payload = _read_stdin_payload()
        month = int(payload.get("month") or datetime.date.today().month)
        print(json.dumps(fetch_payday(month), ensure_ascii=False))
    elif cmd == "prefilljson":
        print(json.dumps(prefill(_read_stdin_payload()), ensure_ascii=False))
    elif cmd == "projectjson":
        payload = _read_stdin_payload()
        print(json.dumps(search_projects(payload.get("keyword") or ""), ensure_ascii=False))
    else:
        month = int(sys.argv[2]) if len(sys.argv) > 2 else datetime.date.today().month
        print("title:", compose_title(month, "홍길동"))
        print(json.dumps(fetch_payday(month), ensure_ascii=False))
