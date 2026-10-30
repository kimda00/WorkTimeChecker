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
  5) 출장비용지급품의(prefill_trip): 같은 전표 구조의 출장 양식(기본 3279)을 열어
     제목('YY/MM/DD 목적지')·지급처·지급요청일을 채우고, '카드내역' 팝업으로 출장 기간의
     법인카드 사용내역을 전부 가져와(식대) 기본적요·시간대별 상세내용(아침/점심/저녁식대)을
     넣고 한 끼 상한(기본 12,000원)을 넘는 행은 공급가액을 상한으로 깎은 뒤(폼이 부가세 0·
     비과세로 바꾼다), '행추가'로 유류대·톨비·숙박 개인카드 행을 만들어 기본적요·증빙일자·
     공급가액·상세내용을 채운다. 창이 열려 있는 동안 사용자가 카드내역을 더 눌러 추가한
     행에도 식대 처리를 이어서 한다.
     대중교통 출장(mode=public)은 출장 전 N일(기본 14)부터의 카드내역에서 버스·철도·항공 결제만
     승차권으로 골라 6071(교통) 행을 만들고(택시·주차는 6079 제반), 개인 결제 교통비는 6071 개인카드
     행으로 넣는다. 카드 행 분류는 가맹점명 키워드(config tripTransportKeywords/tripMiscKeywords).
     기본적요는 폼의 팝업이 쓰는 부서별 목록 API(/api/amaranth/accountDept)에서 코드로 고르고,
     지급처·행 거래처(본인)는 거래처 검색 API(/api/amaranth/integration/trade)로 코드를 찾아
     td 의 data-code/data-name 까지 맞춘다(제출 시 읽는 값). 첨부·검토·제출은 사용자 몫.

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
DEFAULT_TRIP_FORM_ID = 3279        # 출장비용지급품의(AMARANTH 10) 양식 id
DEFAULT_FUEL_RATE = 250            # 자차 유류대 단가(원/km)
DEFAULT_MEAL_CAP = 12000           # 식대 한 끼 상한(원). 0 이면 제한 없음
DEFAULT_TICKET_LOOKBACK = 60       # 대중교통: 승차권은 출장 며칠 전에 사므로 카드내역 조회를 이만큼 앞당긴다(교통 키워드 결제만 가져오므로 넉넉히)
# 카드내역 가맹점명으로 행을 분류하는 키워드(대소문자 무시). config.json 의 tripTransportKeywords / tripMiscKeywords 로 덮어쓴다.
DEFAULT_TRANSPORT_KEYWORDS = ["고속버스", "KOBUS", "코버스", "시외버스", "버스터미널", "버스", "코레일", "KORAIL", "레츠코레일",
                              "KTX", "SRT", "철도", "기차", "지하철", "대한항공", "아시아나", "제주항공", "진에어", "티웨이",
                              "에어부산", "에어서울", "이스타", "항공"]
DEFAULT_MISC_KEYWORDS = ["택시", "카카오T", "카카오 T", "카카오택시", "타다", "TADA", "주차", "파킹", "PARKING", "하이패스",
                         "톨게이트", "도로공사"]
# 출장비용지급품의 행에 쓰는 기본적요 코드(그룹웨어 '기본적요' 목록의 rmkNo).
TRIP_ACCTS = {
    "meal": "6075",      # (용역) 법카 - 출장외근비(식대)
    "transport": "6071", # (용역) 법카 - 출장외근비(교통) — 승차권(법인카드) · 개인 결제 교통비
    "misc": "6079",      # (용역) 법카 - 출장외근비(제반-톨비,택시,주차료) — 법인카드 택시·주차
    "fuel": "6377",      # (용역) 개인 - 출장외근비(유류대)
    "toll": "6379",      # (용역) 개인 - 출장외근비(제반-톨비)
    "lodging": "6073",   # (용역) 법카 - 출장외근비(숙박) — 개인 숙박 적요가 없어 개인카드로 쓴다
}
_API_HEADERS = {"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"}
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


def _trip_url():
    """출장비용지급품의 새 폼 URL. config 의 tripApprovalUrl 이 있으면 그걸, 없으면 지출결의서 URL 의
    양식 id 만 tripFormId(기본 3279)로 바꾼다(기안부서 id 는 같다)."""
    u = _config("tripApprovalUrl")
    if u:
        return u
    form_id = _config("tripFormId", DEFAULT_TRIP_FORM_ID)
    return re.sub(r"/\d+/?$", "/%s" % form_id, _approval_url())


def _card_keywords():
    """카드 행 분류 키워드 {transport:[..], misc:[..]} (config 로 덮어쓰기 가능)."""
    tr = _config("tripTransportKeywords")
    ms = _config("tripMiscKeywords")
    return {"transport": list(tr) if isinstance(tr, list) and tr else DEFAULT_TRANSPORT_KEYWORDS,
            "misc": list(ms) if isinstance(ms, list) and ms else DEFAULT_MISC_KEYWORDS}


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
    r = ctx.request.get(u, headers=_API_HEADERS)
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


def _acct_list(ctx, dept, company="1000"):
    """폼의 '기본적요' 팝업이 쓰는 부서별 기본적요 목록. [{rmkNo, rmk, crAcctCode, ...}]"""
    import urllib.parse
    params = json.dumps({"depts": [dept] if dept else [], "cdCompany": company})
    r = ctx.request.get("%s/api/amaranth/accountDept?params=%s" % (ORIGIN, urllib.parse.quote(params)),
                        headers=_API_HEADERS)
    if not r.ok:
        raise RuntimeError("기본적요 목록 조회 실패 (HTTP %d)" % r.status)
    return (r.json() or {}).get("data") or []


def _trade_lookup(ctx, name, company="1000"):
    """거래처 검색(폼의 '거래처'/'지급처' 팝업과 같은 API). 이름이 정확히 같은 일반 거래처
    (법인카드 거래처 trFg=9 제외) → {code, name, regNb}. 못 찾으면 None."""
    kw = (name or "").strip()
    if not kw:
        return None
    r = ctx.request.get(ORIGIN + "/api/amaranth/integration/trade",
                        params={"coCd": company, "trFg": "", "searchtype": "trNm", "keyword": kw,
                                "offset": 20, "page": 0},
                        headers=_API_HEADERS)
    if not r.ok:
        return None
    items = [it for it in ((r.json() or {}).get("data") or [])
             if (it.get("trNm") or "").strip() == kw and str(it.get("trFg") or "") != "9"]
    if not items:
        return None
    it = items[0]
    return {"code": it.get("trCd") or "", "name": it.get("trNm") or "", "regNb": it.get("regNb") or ""}


def _headers(board):
    return {"Accept": "application/json, text/plain, */*",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": ORIGIN + "/app/board/%d" % board}


def compose_title(expense_month, name=""):
    """지출결의서 제목: 'n월 지출결의서(개인경비) - {이름}' (이름 없으면 000)."""
    m = int(expense_month)
    tail = name.strip() if (name and name.strip()) else "000"
    return "%d월 지출결의서(개인경비) - %s" % (m, tail)


def _num(v):
    """'69,500' / 69500.0 / '' → int. 숫자가 아니면 0."""
    try:
        return int(round(float(str(v).replace(",", "").strip() or 0)))
    except Exception:
        return 0


def compose_trip_title(start, end="", dest=""):
    """출장비용지급품의 제목: 'YY/MM/DD 목적지'. 여러 날이면 'YY/MM/DD~DD'(같은 달) 또는 'YY/MM/DD~MM/DD'."""
    dest = (dest or "").strip()
    try:
        s = datetime.date.fromisoformat((start or "")[:10])
    except Exception:
        return dest
    head = s.strftime("%y/%m/%d")
    try:
        e = datetime.date.fromisoformat((end or "")[:10])
    except Exception:
        e = s
    if e > s:
        head += "~" + (e.strftime("%d") if (e.year, e.month) == (s.year, s.month) else e.strftime("%m/%d"))
    return (head + " " + dest).strip()


def trip_rows(payload):
    """출장 입력 → 개인카드 전표 행 [{kind, acct, amount, date, detail}].
    개인 결제 교통비(fare, 6071) · 유류대 = 왕복 km × 단가(기본 250원) · 톨비 · 숙박은 금액 그대로. 0 이면 행을 만들지 않는다.
    식대(법인카드)는 카드내역 팝업에서 가져오므로 여기 없다."""
    payload = payload or {}
    km = _num(payload.get("km"))
    rate = _num(payload.get("rate")) or DEFAULT_FUEL_RATE
    toll = _num(payload.get("toll"))
    lodging = _num(payload.get("lodging"))
    fare = _num(payload.get("fare"))
    date = (payload.get("start") or "")[:10]
    rows = []
    if fare > 0:
        rows.append({"kind": "fare", "acct": TRIP_ACCTS["transport"], "amount": fare, "date": date,
                     "detail": "출장 교통비(개인 결제 승차권)"})
    if km > 0:
        rows.append({"kind": "fuel", "acct": TRIP_ACCTS["fuel"], "amount": km * rate, "date": date,
                     "detail": "왕복 %dkm(자차 이용)" % km})
    if toll > 0:
        rows.append({"kind": "toll", "acct": TRIP_ACCTS["toll"], "amount": toll, "date": date,
                     "detail": "왕복 하이패스 비용"})
    if lodging > 0:
        rows.append({"kind": "lodging", "acct": TRIP_ACCTS["lodging"], "amount": lodging, "date": date,
                     "detail": "출장 숙박비"})
    return rows


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


# 지급처(.tradeCd) td 에 거래처 코드 부여 — 폼의 '거래처' 팝업이 하는 것과 같다(제출 시 data-code 를 읽는다).
_PAYEE_ATTR_JS = r"""
(tr) => {
  const td = document.querySelector('.tradeCd'); if (!td) return false;
  td.setAttribute('data-code', tr.code); td.setAttribute('data-name', tr.name); td.setAttribute('data-regNb', tr.regNb || '');
  return true;
};
"""

# 개인카드(카드내역이 아닌) 행의 빈 '거래처' 셀을 지급처(본인)로 채운다.
_TRADE_FILL_JS = r"""
(tr) => {
  let filled = 0;
  document.querySelectorAll('#slipBplTable tr.debitTr:not(.corp_card_row)').forEach(tr1 => {
    const td = tr1.nextElementSibling && tr1.nextElementSibling.querySelector('.dztrade'); if (!td) return;
    const inp = td.querySelector('input'); if (!inp || (inp.value || '').trim()) return;
    inp.value = tr.name; td.setAttribute('data-code', tr.code); td.setAttribute('data-name', tr.name); td.setAttribute('data-regNb', tr.regNb || '');
    filled++;
  });
  return filled;
};
"""

# 방금 '행추가'로 생긴 마지막 행(3줄: debitTr / debitTr2 / debitTr3)을 채운다.
# 기본적요는 팝업 콜백과 같은 data-* 를 td 에 넣고, 증빙유형 '개인카드', 증빙일자, 공급가액(부가세 0), 상세내용.
# change 이벤트로 폼 JS 가 행 합계·결의금액·회계일자를 다시 계산한다.
_ROW_FILL_JS = r"""
(row) => {
  const trs = document.querySelectorAll('#slipBplTable tr.debitTr');
  const tr1 = trs[trs.length - 1]; if (!tr1) return { error: 'no row' };
  const tr2 = tr1.nextElementSibling, tr3 = tr2 && tr2.nextElementSibling;
  if (!tr2 || !tr3) return { error: 'row shape' };
  const fire = (el, t) => el && el.dispatchEvent(new Event(t, { bubbles: true }));
  const a = row.acct;
  const rmkTd = tr1.querySelector('.debitRmk'), rmkIn = rmkTd && rmkTd.querySelector('input');
  if (!rmkIn) return { error: 'no rmk' };
  rmkIn.value = a.rmkNo + ' / ' + a.rmk;
  const attrs = { 'data-id': a.id, 'data-code': a.rmkNo, 'data-name': a.rmk,
    'data-cr_acct': a.crAcctCode, 'data-cr_acct_name': a.crAcctName, 'data-dr_acct': a.drAcctCode, 'data-dr_acct_name': a.drAcctName,
    'data-vat_acct': a.vatAcctCode, 'data-vat_acct_name': a.vatAcctName, 'data-vat_crdr': a.vatAcctCrdr };
  for (const k in attrs) rmkTd.setAttribute(k, attrs[k] == null ? '' : String(attrs[k]));
  if (!String(a.crAcctName || '').includes('차량유지비')) {   // 폼의 checkCrAcctWorkCar 와 동일
    const wc = tr2.querySelector('.workcar input'); if (wc) { wc.value = ''; wc.disabled = true; }
    const wtd = tr2.querySelector('.workcar'); if (wtd) { wtd.setAttribute('data-code', ''); wtd.setAttribute('data-name', ''); }
  }
  const sel = tr1.querySelector('.taxInvestigationDivision select'); if (sel) { sel.value = '개인카드'; fire(sel, 'change'); }
  const dt = tr1.querySelector('.taxDate input'); if (dt) { dt.value = row.date; fire(dt, 'change'); }
  const sup = tr2.querySelector('.valueOfSupply input'); if (sup) { sup.value = row.amount; fire(sup, 'change'); }
  const vat = tr2.querySelector('.valueOfVAT input'); if (vat) { vat.value = '0'; fire(vat, 'change'); }
  const sm = tr3.querySelector('.summary input'); if (sm) { sm.value = row.detail; fire(sm, 'change'); }
  if (row.trade) {
    const td = tr2.querySelector('.dztrade'); const inp = td && td.querySelector('input');
    if (inp) { inp.value = row.trade.name; td.setAttribute('data-code', row.trade.code); td.setAttribute('data-name', row.trade.name); td.setAttribute('data-regNb', row.trade.regNb || ''); }
  }
  return { tot: ((tr2.querySelector('.valueOfTot') || {}).textContent || '').trim(), rows: trs.length };
};
"""

# 카드내역으로 들어온 행(corp_card_row) 중 아직 처리하지 않은 것(data-wt-meal 없음)을 가맹점명으로 분류해 채운다:
#  - 제반 키워드(택시·주차…) → x.misc(6079), 상세 '출장외근비 - 제반(가맹점)'
#  - 교통 키워드(버스·철도·항공…) → x.transport(6071), 상세 '출장외근비 - 교통(가맹점)'
#  - 그 외 → x.meal(6075), 승인시간으로 '출장외근비 - 아침/점심/저녁식대' (10:30 전 아침, 15:30 전 점심, 그 뒤 저녁),
#    합계가 상한(cap)을 넘으면 공급가액을 상한으로 바꾸고 change → 폼이 부가세 0 · 법인카드(비과세)로 정리
# 기본적요·상세내용은 비어 있을 때만 넣는다(직접 고른 값은 유지).
_CARD_ROWS_JS = r"""
(x) => {
  let n = 0, capped = 0; const cap = Number(x.cap) || 0; const kw = x.keywords || {};
  const num = s => Number(String(s || '').replace(/[^\d.-]/g, '')) || 0;
  const up = s => String(s || '').toUpperCase();
  const hit = (name, list) => (list || []).some(k => k && up(name).includes(up(k)));
  const mealOf = t => { const p = String(t || '').split(':'); const h = parseInt(p[0], 10), m = parseInt(p[1], 10) || 0; if (isNaN(h)) return '식대';
    const mins = h * 60 + m; return mins < 10 * 60 + 30 ? '아침식대' : (mins < 15 * 60 + 30 ? '점심식대' : '저녁식대'); };
  const setAcct = (td, a) => {
    const inp = td.querySelector('input'); if (!inp) return;
    inp.value = a.rmkNo + ' / ' + a.rmk;
    const attrs = { 'data-id': a.id, 'data-code': a.rmkNo, 'data-name': a.rmk,
      'data-cr_acct': a.crAcctCode, 'data-cr_acct_name': a.crAcctName, 'data-dr_acct': a.drAcctCode, 'data-dr_acct_name': a.drAcctName,
      'data-vat_acct': a.vatAcctCode, 'data-vat_acct_name': a.vatAcctName, 'data-vat_crdr': a.vatAcctCrdr };
    for (const k in attrs) td.setAttribute(k, attrs[k] == null ? '' : String(attrs[k]));
  };
  document.querySelectorAll('#slipBplTable tr.debitTr.corp_card_row').forEach(tr1 => {
    if (tr1.getAttribute('data-wt-meal')) return;
    const tr2 = tr1.nextElementSibling, tr3 = tr2 && tr2.nextElementSibling;
    if (!tr2 || !tr3) return;
    const chain = ((tr2.querySelector('.dztrade input') || {}).value || '').trim();
    const kind = hit(chain, kw.misc) ? 'misc' : (hit(chain, kw.transport) ? 'transport' : 'meal');
    const acct = x[kind];
    const rmkTd = tr1.querySelector('.debitRmk'), rmkIn = rmkTd && rmkTd.querySelector('input');
    if (acct && rmkIn && !(rmkIn.value || '').trim()) setAcct(rmkTd, acct);
    const sm = tr3.querySelector('.summary input');
    if (sm && !(sm.value || '').trim()) {
      sm.value = kind === 'misc' ? '출장외근비 - 제반(' + chain + ')' : kind === 'transport' ? '출장외근비 - 교통(' + chain + ')'
               : '출장외근비 - ' + mealOf((tr1.querySelector('.apprTime input') || {}).value);
      sm.dispatchEvent(new Event('change', { bubbles: true }));
    }
    if (kind === 'meal') {
      const tot = num((tr2.querySelector('.valueOfTot') || {}).textContent);
      const sup = tr2.querySelector('.valueOfSupply input');
      if (cap > 0 && sup && tot > cap) {
        sup.value = cap.toLocaleString('en-US');
        sup.dispatchEvent(new Event('change', { bubbles: true }));
        capped++;
      }
    }
    tr1.setAttribute('data-wt-meal', kind);
    n++;
  });
  return { rows: n, capped };
};
"""

# 카드내역 팝업: 기간 입력 → 조회 → 결과 전체 체크 → '입력'. (팝업은 체크박스의 checked 속성으로 선택을 읽는다)
_CARD_DATES_JS = r"""
(d) => {
  const s = document.getElementById('apprDateStart'), e = document.getElementById('apprDateEnd');
  if (!s || !e) return false;
  s.value = d.start; e.value = d.end;
  s.dispatchEvent(new Event('change', { bubbles: true })); e.dispatchEvent(new Event('change', { bubbles: true }));
  return true;
};
"""
# 조회 결과 중 가져올 행만 체크. f = {from, to, all, transport, meals, keywords}
#  all: 출장 기간(from~to) 안의 내역 전부(자차 출장)
#  transport: 가맹점명이 교통 키워드(버스·철도·항공)면 기간 어디든(승차권은 미리 산다)
#  meals: 교통이 아닌 내역 중 출장 기간 안의 것(식대)
_CARD_CHECK_JS = r"""
(f) => {
  const up = s => String(s || '').toUpperCase();
  const isTr = name => (f.keywords || []).some(k => k && up(name).includes(up(k)));
  let n = 0;
  document.querySelectorAll('#dataList tbody tr').forEach(tr => {
    const cb = tr.querySelector('.dataTd input[type=checkbox]'); if (!cb) return;
    const chain = ((tr.querySelector('.chainName') || {}).textContent || '').trim();
    const dt = ((tr.querySelector('.issDt') || {}).textContent || '').trim();
    const inTrip = (!f.from || dt >= f.from) && (!f.to || dt <= f.to);
    const tr_ = isTr(chain);
    const take = f.all ? inTrip : ((f.transport && tr_) || (f.meals && inTrip && !tr_));
    if (!take) return;
    cb.checked = true; cb.setAttribute('checked', 'checked'); n++;
  });
  return n;
};
"""


def _add_card_rows(page, start, end, pick=None):
    """'카드내역' 팝업으로 start~end(YYYY-MM-DD) 의 법인카드 사용내역을 조회해 pick(_CARD_CHECK_JS 의 f) 에 맞는 행을
    체크해 전표 행으로 가져온다. pick 이 없으면 전부. 페이지 안에서만 일어나는 일(제출 아님). {found, added} 또는 {error}."""
    out = {"found": 0, "added": 0}
    btn = page.locator("#corpCardUsagePopupBtn")
    if not btn.count() or not btn.first.is_visible():
        out["error"] = "카드내역 버튼이 없어요."
        return out
    before = page.evaluate("document.querySelectorAll('#slipBplTable tr.debitTr.corp_card_row').length")
    btn.first.click(timeout=5000)
    page.wait_for_selector("#apprDateStart", timeout=20000)
    page.wait_for_timeout(1500)
    page.evaluate(_CARD_DATES_JS, {"start": start, "end": end})
    page.locator("#searchBtn").click(timeout=5000)
    try:   # 조회 결과(또는 '내역 없음' 행)가 다시 그려질 때까지
        page.wait_for_function("document.querySelectorAll('#dataList tbody tr').length > 0", timeout=15000)
    except Exception:
        pass
    page.wait_for_timeout(1200)
    n = page.evaluate(_CARD_CHECK_JS, pick or {"all": True})
    out["found"] = int(n or 0)
    popup = page.locator("#corpCardUsagePopup")
    if out["found"]:
        popup.locator("a.btn_major_s", has_text="입력").first.click(timeout=5000)
        page.wait_for_timeout(2000)
        after = page.evaluate("document.querySelectorAll('#slipBplTable tr.debitTr.corp_card_row').length")
        out["added"] = max(0, int(after) - int(before))
    else:
        popup.locator("a.btn_minor_s", has_text="닫기").first.click(timeout=5000)
        page.wait_for_timeout(500)
    return out


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
    project 가 있으면 창이 열려 있는 동안 전표 행의 빈 프로젝트 셀을 계속 채운다.
    payload.form == 'trip' 이면 출장비용지급품의(prefill_trip)."""
    payload = payload or {}
    if payload.get("form") == "trip":
        return prefill_trip(payload)
    return _run_form(_approval_url(), payload, None)


def prefill_trip(payload):
    """출장비용지급품의 폼을 열어 제목·지급처·지급요청일 + 식대(카드내역) + 유류대·톨비·숙박 행을 채운다.
    payload: {title?, payee, payday, project, start, end, dest, mode, km, rate, toll, lodging, fare, meals, mealCap}.
    mode 'car'(기본): 출장 기간의 카드내역 전부(식대) + 유류대·톨비 행. 'public': 출장 tripTicketLookback일(기본 60) 전부터의 카드내역에서
    승차권(교통 키워드)과 출장 기간 식대만 골라 오고 개인 결제 교통비(fare) 행.
    mealCap(기본 12,000, 0 이면 제한 없음)을 넘는 식대 행은 공급가액을 상한으로 깎는다."""
    payload = dict(payload or {})
    meal_cap = _num(payload["mealCap"]) if "mealCap" in payload else DEFAULT_MEAL_CAP
    mode = "public" if (payload.get("mode") or "car") == "public" else "car"
    lookback = max(0, int(_num(_config("tripTicketLookback", DEFAULT_TICKET_LOOKBACK)))) if mode == "public" else 0
    keywords = _card_keywords()
    if not (payload.get("title") or "").strip():
        payload["title"] = compose_trip_title(payload.get("start"), payload.get("end"), payload.get("dest"))
    rows = trip_rows(payload)
    start = (payload.get("start") or "")[:10]
    end = (payload.get("end") or start)[:10] or start

    def steps(page, ctx, filled, dept, trade):
        want_meals = bool(payload.get("meals"))
        if (want_meals or mode == "public") and start:
            try:
                range_start = (datetime.date.fromisoformat(start) - datetime.timedelta(days=lookback)).isoformat()
                pick = {"from": start, "to": end, "all": mode != "public", "transport": mode == "public",
                        "meals": want_meals, "keywords": keywords["transport"]}
                filled["cards"] = _add_card_rows(page, range_start, end, pick)
                filled["cards"]["range"] = [range_start, end]
            except Exception as e:
                filled["cards"] = {"error": str(e)}
        try:
            accts = {str(a.get("rmkNo")): a for a in _acct_list(ctx, dept)}
        except Exception as e:
            accts = {}
            filled["acctError"] = str(e)
        card_arg = {"meal": accts.get(TRIP_ACCTS["meal"]), "transport": accts.get(TRIP_ACCTS["transport"]),
                    "misc": accts.get(TRIP_ACCTS["misc"]), "keywords": keywords, "cap": meal_cap}
        filled["mealRows"] = 0
        filled["mealCapped"] = 0

        def meal_tick():
            """카드내역 행을 교통/제반/식대로 분류해 적요·상세·상한 적용. 창이 열려 있는 동안 반복해 사용자가 더 넣은 행도 처리."""
            r = page.evaluate(_CARD_ROWS_JS, card_arg) or {}
            filled["mealRows"] += int(r.get("rows") or 0)
            filled["mealCapped"] += int(r.get("capped") or 0)

        try:
            meal_tick()
        except Exception as e:
            filled["mealError"] = str(e)
        done = []
        for row in rows:
            acct = accts.get(row["acct"])
            if not acct:
                done.append({"kind": row["kind"], "error": "기본적요 %s 가 부서 목록에 없어요." % row["acct"]})
                continue
            try:
                page.locator("#plusRow").first.click(timeout=5000)
                page.wait_for_timeout(600)
                r = page.evaluate(_ROW_FILL_JS, {"acct": acct, "date": _fmt_date_kr(row["date"]),
                                                 "amount": "{:,}".format(row["amount"]), "detail": row["detail"],
                                                 "trade": trade}) or {}
            except Exception as e:
                r = {"error": str(e)}
            done.append(dict({"kind": row["kind"], "amount": row["amount"]}, **r))
        filled["rows"] = done
        return meal_tick

    return _run_form(_trip_url(), payload, steps)


def _run_form(url, payload, steps):
    """결재 폼을 헤드풀로 열고 공통 자동채움(제목·지급처·지급요청일·프로젝트) 뒤 steps(page, ctx, filled, dept, trade)
    를 실행하고, 창이 닫힐 때까지(최대 15분) 빈 프로젝트/거래처 셀을 2초마다 채운다.
    steps 가 함수를 돌려주면 그 함수(tick)도 같은 주기로 부른다."""
    if not os.path.exists(STATE):
        return {"status": "login_required", "message": "EHR 로그인이 필요해요."}
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        return {"status": "error", "message": "playwright 미설치: %s" % e}

    payload = payload or {}
    data = {
        "title": payload.get("title") or "",
        "payee": payload.get("payee") or "",
        "payday": _fmt_date_kr(payload.get("payday") or ""),
    }
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
            dept = _dept_from_url(url)
            # 지급처(본인) 거래처 코드 — 폼은 팝업으로 고른 td 의 data-code 를 제출에 쓴다.
            trade = None
            if data["payee"]:
                try:
                    trade = _trade_lookup(ctx, data["payee"])
                    if trade:
                        page.evaluate(_PAYEE_ATTR_JS, trade)
                        filled["payeeCode"] = trade["code"]
                except Exception as e:
                    filled["payeeError"] = str(e)
            project, why = _resolve_project(ctx, payload.get("project"), url)
            if project:
                filled["project"] = project
            elif why:
                filled["projectError"] = why
            tick = None
            if steps:
                try:
                    tick = steps(page, ctx, filled, dept, trade)
                except Exception as e:
                    filled["stepsError"] = str(e)
            # 사용자가 검토·카드입력·제출 후 창을 닫을 때까지 대기 (최대 15분).
            # 그동안 카드내역/행추가로 생긴 행의 빈 프로젝트·거래처 셀을 2초마다 채운다.
            project_rows = 0
            trade_rows = 0
            for i in range(900):
                if not ctx.pages:
                    break
                if i % 2 == 0:
                    try:
                        if project:
                            r = page.evaluate(_PROJECT_FILL_JS, project) or {}
                            project_rows += int(r.get("filled") or 0)
                        if trade:
                            trade_rows += int(page.evaluate(_TRADE_FILL_JS, trade) or 0)
                        if tick:
                            tick()
                    except Exception:
                        pass   # 페이지 이동/닫힘 중이면 다음 턴에 다시
                time.sleep(1)
            filled["projectRows"] = project_rows
            filled["tradeRows"] = trade_rows
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
    elif cmd == "tripjson":
        print(json.dumps(prefill_trip(_read_stdin_payload()), ensure_ascii=False))
    else:
        month = int(sys.argv[2]) if len(sys.argv) > 2 else datetime.date.today().month
        print("title:", compose_title(month, "홍길동"))
        print("trip title:", compose_trip_title("2026-10-28", "2026-10-28", "대전 한수원"),
              json.dumps(trip_rows({"start": "2026-10-28", "km": 278, "toll": 7500}), ensure_ascii=False))
        print(json.dumps(fetch_payday(month), ensure_ascii=False))
