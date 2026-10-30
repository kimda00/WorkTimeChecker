# -*- coding: utf-8 -*-
"""퇴근 버스 — 정류장 검색 · 경유 노선 · 배차(시간표) · 실시간 도착 조회.

지도에서 퇴근 정류장을 고르면 그 정류장을 지나는 노선들의 '노선 프로필'
(첫차 · 막차 · 평일/토/일 배차 · 기점→정류장 소요)을 돌려준다. 해당 일자의 도착
시각 목록과 '도착 N분 전 퇴근' 계산은 프론트(ui/app.js)가 이 프로필로 한다
(요일·공휴일마다 다시 부르지 않아도 되고, 오프라인에서도 동작).

데이터 소스 — 모두 순수 HTTP(urllib), 브라우저 없음.
1) 키 없이(기본 · 데모): OpenStreetMap
   Overpass API  정류장 위치/이름/번호(ref)/경유 노선(route_ref, route relation) — 한 번에 받아 캐시
   Nominatim     장소 검색(지도 이동)
   타일 서버     지도 배경(앱 UA 로 받아 캐시 → data URI)
   OSM 에는 배차가 거의 없어 노선번호로 만든 '데모 추정' 배차를 쓴다
   (relation 에 interval / opening_hours 태그가 있으면 그 값을 우선).
2) 공공데이터포털 서비스키가 있으면: 국토교통부 TAGO (전국 시내버스 · 서울 제외)
   키는 config.json 의 busApiKey (build 시 exe 에 묶임)를 항상 쓴다. 화면에는 키 입력이 없다.
   GET /1613000/BusSttnInfoInqireService/getCrdntPrxmtSttnList?gpsLati=&gpsLong=
        -> gpslati, gpslong, nodeid, nodenm, citycode         (좌표 반경 500m 정류장)
   GET /1613000/BusSttnInfoInqireService/getSttnThrghRouteList?cityCode=&nodeid=
        -> routeid, routeno, routetp, startnodenm, endnodenm   (정류장 경유 노선)
   GET /1613000/BusRouteInfoInqireService/getRouteInfoIem?cityCode=&routeId=
        -> startvehicletime, endvehicletime(HHMM), intervaltime, intervalsattime, intervalsuntime(분)
   GET /1613000/BusRouteInfoInqireService/getRouteAcctoThrghSttnList?cityCode=&routeId=
        -> nodeid, nodeord   (정류장 순번 → 기점 출발 후 도착까지 소요 추정)
   GET /1613000/ArvlInfoInqireService/getSttnAcctoArvlPrearngeInfoList?cityCode=&nodeId=
        -> routeno, routeid, arrtime(초), arrprevstationcnt   (실시간 도착 예정)
   응답: response.header.resultCode('00') / response.body.items.item (1건이면 dict, 0건이면 "")
3) 같은 키로 경기도 버스 API(GBIS)도 활용신청했으면 경기도 정류장은 이쪽을 쓴다 — TAGO 에 없는
   마을버스 등 노선이 더 있고, 첫차·막차가 방향/요일별, 배차가 출퇴근(peak)/평시로 나온다.
   (TAGO 경기도 정류장 nodeid 'GGB204000158' = 경기도 stationId 204000158)
   GET /6410000/busstationservice/v2/getBusStationAroundListv2?x=경도&y=위도
        -> stationId, stationName, mobileNo, x, y, distance        (반경 약 500m, 경기도 밖이면 결과 없음)
   GET /6410000/busstationservice/v2/getBusStationViaRouteListv2?stationId=
        -> routeId, routeName, routeTypeName, routeDestName, staOrder(이 정류장의 노선 순번)
   GET /6410000/busrouteservice/v2/getBusRouteInfoItemv2?routeId=
        -> up/downFirstTime·LastTime, sat·sunUp/Down…, peekAlloc·nPeekAlloc, sat·sunPeekAlloc·NPeekAlloc(분)
   GET /6410000/busarrivalservice/v2/getBusArrivalListv2?stationId=
        -> routeId, routeName, turnSeq(회차 순번 → 상·하행 판단), predictTime1·2(분), locationNo1·2(정류장 전)
   응답: response.msgHeader.resultCode(0 정상 · 4 결과 없음) / response.msgBody.{목록 키}

CLI(개발 확인용):  python bus.py nearby 37.3947 127.1112
                   python bus.py search 판교역
"""
import base64
import json
import math
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
import zlib
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote, urlencode

import ehr  # _data_dir 재사용

BUS_DIR = os.path.join(ehr._data_dir(), "bus")
OSM_CACHE_SEC = 14 * 86400     # 정류장 위치/노선은 자주 안 바뀐다
UA = "WorkTimeChecker/1.0 (desktop worktime app; bus departure helper)"
OVERPASS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)
NOMINATIM = "https://nominatim.openstreetmap.org/search"
TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
TILE_CACHE_SEC = 7 * 86400
_TILE_SLOTS = threading.Semaphore(2)   # OSM 타일 서버 동시 요청 2개 이하
TAGO = "https://apis.data.go.kr/1613000"
GBIS = "https://apis.data.go.kr/6410000"
MAX_ROUTES = 24               # 정류장 하나에 노선이 너무 많을 때 상세 조회 상한
MIN_PER_STOP = 1.6            # 기점→정류장 소요 추정(정류장당 분) — 실시간 도착으로 앱이 보정


class BusError(Exception):
    """사용자에게 그대로 보여줄 오류(키 오류 · 서비스 응답 오류 등)."""


def _config(key, default=None):
    """config.json 값: exe 에 묶인 것 → %APPDATA%\\worktime → (개발) 프로젝트 폴더."""
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


def _key(api_key):
    """config.json 의 busApiKey. 인자로 키를 넘기면 그 키(개발 · 테스트용). 둘 다 없으면 None."""
    return (api_key or "").strip() or str(_config("busApiKey") or "").strip() or None


def has_default_key():
    """배포 기본 키가 있는지만 알려준다(키 값은 화면으로 넘기지 않는다)."""
    return bool(_key(None))


def _http(url, data=None, timeout=20):
    req = urllib.request.Request(url, data=data, headers={
        "User-Agent": UA,
        "Accept": "application/json, */*",
        "Accept-Language": "ko",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def _http_json(url, data=None, timeout=20):
    body = _http(url, data=data, timeout=timeout)
    try:
        return json.loads(body)
    except ValueError:
        # 공공데이터포털은 키 오류 시 _type=json 이어도 XML 을 준다
        m = re.search(r"<returnAuthMsg>([^<]+)</returnAuthMsg>|<resultMsg>([^<]+)</resultMsg>", body)
        msg = (m.group(1) or m.group(2)) if m else body[:120]
        raise BusError("API 응답 오류: " + msg.strip())


def _dist_m(lat1, lng1, lat2, lng2):
    """두 좌표 사이 거리(m) — 근거리라 평면 근사로 충분."""
    k = 111320.0
    dx = (lng2 - lng1) * k * math.cos(math.radians((lat1 + lat2) / 2))
    dy = (lat2 - lat1) * k
    return math.hypot(dx, dy)


def _hhmm(v):
    """'0530' / 530 / '05:30' → '05:30'. 이상하면 ''."""
    s = re.sub(r"\D", "", str(v or ""))
    if not s:
        return ""
    s = s.zfill(4)[-4:]
    h, m = int(s[:2]), int(s[2:])
    if h > 29 or m > 59:
        return ""
    return "%02d:%02d" % (h, m)


def _route_sort_key(no):
    """노선번호 자연 정렬: 숫자 앞부분 기준, 그다음 문자열."""
    m = re.match(r"\D*(\d+)", no or "")
    return (int(m.group(1)) if m else 99999, no or "")


# ------------------------------------------------------------------ 지도 타일
def tile(z, x, y):
    """OSM 표준 지도 타일을 data URI 로. 앱 창(file://)은 Referer 가 없어 OSM 타일 서버가
    막으므로 여기서 앱 UA 로 받아 7일 캐시한다(OSM 타일 사용 정책: 식별 UA · 로컬 캐시 · 동시 2개)."""
    try:
        z, x, y = int(z), int(x), int(y)
    except (TypeError, ValueError):
        return None
    if not (0 <= z <= 19 and 0 <= x < 2 ** z and 0 <= y < 2 ** z):
        return None
    path = os.path.join(BUS_DIR, "tiles", str(z), str(x), "%d.png" % y)
    data = None
    try:
        if time.time() - os.path.getmtime(path) < TILE_CACHE_SEC:
            with open(path, "rb") as f:
                data = f.read()
    except OSError:
        pass
    if data is None:
        try:
            with _TILE_SLOTS:
                req = urllib.request.Request(TILE_URL.format(z=z, x=x, y=y), headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=15) as r:
                    data = r.read()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(data)
        except Exception:
            try:                      # 네트워크가 안 되면 오래된 캐시라도
                with open(path, "rb") as f:
                    data = f.read()
            except OSError:
                return None
    return "data:image/png;base64," + base64.b64encode(data).decode("ascii")


# ------------------------------------------------------------------ 장소 검색
def search_place(query):
    """Nominatim 으로 장소를 찾아 지도 이동용 좌표 목록을 돌려준다."""
    q = (query or "").strip()
    if not q:
        return {"status": "ok", "places": []}
    url = NOMINATIM + "?" + urlencode({
        "q": q, "format": "jsonv2", "limit": 6, "countrycodes": "kr", "accept-language": "ko",
    })
    try:
        rows = _http_json(url, timeout=15) or []
    except Exception as e:
        return {"status": "error", "message": "장소 검색 실패: %s" % e}
    places = []
    for r in rows:
        parts = [p.strip() for p in (r.get("display_name") or "").split(",") if p.strip()]
        places.append({
            "name": r.get("name") or (parts[0] if parts else q),
            "detail": " ".join(reversed(parts[1:4])),
            "lat": float(r["lat"]),
            "lng": float(r["lon"]),
        })
    return {"status": "ok", "places": places}


# ------------------------------------------------------------------ OSM (키 없음)
def _overpass(query):
    """공개 Overpass 는 붐비면 502/429 를 준다 → 잠깐 쉬고 재시도, 마지막엔 미러."""
    last = None
    for ep, wait in ((OVERPASS[0], 0), (OVERPASS[0], 3), (OVERPASS[0], 8), (OVERPASS[1], 0)):
        if wait:
            time.sleep(wait)
        try:
            return _http_json(ep, data=urlencode({"data": query}).encode("utf-8"), timeout=60)
        except urllib.error.HTTPError as e:
            last = "HTTP %s" % e.code
            if e.code not in (429, 502, 503, 504):
                break
        except Exception as e:
            last = e
    raise BusError("OpenStreetMap 서버가 혼잡해요 (%s) — 잠시 후 다시 시도하세요" % last)


def _cache_path(lat, lng, radius):
    key = "%.3f_%.3f_%d" % (lat, lng, radius)
    return os.path.join(BUS_DIR, "osm_%s.json" % key)


def _osm_nearby(lat, lng, radius):
    """bbox 안 정류장 + 그 정류장을 지나는 노선 relation 을 한 번에 받는다.
    (공개 서버가 느려 요청 수를 줄이고, 결과는 지역별로 디스크에 캐시)"""
    path = _cache_path(lat, lng, radius)
    try:
        if time.time() - os.path.getmtime(path) < OSM_CACHE_SEC:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    dlat = radius / 111320.0
    dlng = radius / (111320.0 * math.cos(math.radians(lat)))
    bbox = "%.6f,%.6f,%.6f,%.6f" % (lat - dlat, lng - dlng, lat + dlat, lng + dlng)
    j = _overpass(
        "[out:json][timeout:50];"
        "(node[highway=bus_stop](%s);node[public_transport=platform][bus=yes](%s);)->.s;"
        ".s out body;rel(bn.s)[route=bus];out body;" % (bbox, bbox)
    )
    els = j.get("elements") or []
    lines = {}                       # node id -> {노선번호: relation 태그}
    for r in (e for e in els if e.get("type") == "relation"):
        t = r.get("tags") or {}
        no = (t.get("ref") or "").strip()
        if not no:
            continue
        for m in r.get("members") or []:
            if m.get("type") == "node":
                lines.setdefault(m.get("ref"), {}).setdefault(no, {
                    k: t[k] for k in ("to", "interval", "opening_hours") if t.get(k)
                })
    stops = []
    for e in (e for e in els if e.get("type") == "node"):
        t = e.get("tags") or {}
        mine = dict(lines.get(e["id"]) or {})
        for no in re.split(r"[;,]", t.get("route_ref") or ""):
            if no.strip():
                mine.setdefault(no.strip(), {})
        stops.append({
            "id": "osm:%s" % e["id"],
            "name": t.get("name:ko") or t.get("name") or "이름 없는 정류장",
            "no": t.get("ref") or "",
            "lat": e["lat"],
            "lng": e["lon"],
            "routes": sorted(mine, key=_route_sort_key),
            "lines": mine,
            "source": "osm",
        })
    try:
        os.makedirs(BUS_DIR, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(stops, f, ensure_ascii=False)
    except Exception:
        pass
    return stops


def _parse_interval(v):
    """OSM interval 태그('15', '00:15', '10-15') → 분."""
    s = str(v or "").strip()
    m = re.match(r"^(\d{1,2}):(\d{2})", s)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))
    m = re.match(r"^(\d+)", s)
    return int(m.group(1)) if m else 0


def demo_profile(no, stop_id, dest=""):
    """배차 정보가 없는 노선의 '데모 추정' 프로필. 같은 노선·정류장은 늘 같은 값."""
    h = zlib.crc32(("route:" + no).encode("utf-8"))
    hs = zlib.crc32(("%s:%s" % (stop_id, no)).encode("utf-8"))
    digits = re.sub(r"\D", "", no)
    if no.upper().startswith("M") or (len(digits) == 4 and digits[0] in "1389"):
        choices = (15, 18, 20, 25)        # 광역 · 직행좌석
    elif "-" in no or len(digits) <= 2:
        choices = (10, 12, 15, 20)        # 마을 · 지선
    else:
        choices = (8, 10, 12, 15)         # 일반 시내
    wd = choices[h % len(choices)]
    return {
        "no": no,
        "id": "",
        "dest": dest,
        "first": "05:%02d" % (10 * (h % 5)),
        "last": "%02d:%02d" % (22 + (h // 7) % 2, 30 if (h // 3) % 2 else 50),
        "iv": {"wd": wd, "sat": int(round(wd * 1.25)), "sun": int(round(wd * 1.5))},
        "offset": hs % 41,
        "source": "demo",
    }


def _osm_routes(stop):
    """정류장 조회 때 받아둔 노선(relation 태그)으로 프로필을 만든다 — 추가 요청 없음."""
    lines = stop.get("lines") or {no: {} for no in stop.get("routes") or []}
    out = []
    for no, t in lines.items():
        p = demo_profile(no, stop.get("id"), t.get("to") or "")
        iv = _parse_interval(t.get("interval"))
        oh = re.search(r"(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})", t.get("opening_hours") or "")
        if iv:
            p["iv"] = {"wd": iv, "sat": iv, "sun": iv}
            p["source"] = "osm"
        if oh:
            p["first"], p["last"] = _hhmm(oh.group(1)), _hhmm(oh.group(2))
            p["source"] = "osm"
        out.append(p)
    return sorted(out, key=lambda p: _route_sort_key(p["no"]))


# ------------------------------------------------------------------ TAGO (서비스키)
def _tago(path, params, key):
    k = (key or "").strip()
    k = k if "%" in k else quote(k, safe="")      # 인코딩/디코딩 키 모두 허용
    url = "%s/%s?serviceKey=%s&_type=json&%s" % (TAGO, path, k, urlencode(params))
    try:
        j = _http_json(url, timeout=15)
    except urllib.error.HTTPError as e:
        raise BusError("TAGO API 오류 (HTTP %s) — 서비스키/활용신청을 확인하세요" % e.code)
    resp = (j or {}).get("response") or {}
    head = resp.get("header") or {}
    if str(head.get("resultCode", "00")) not in ("00", "0"):
        raise BusError("TAGO: %s" % (head.get("resultMsg") or head.get("resultCode")))
    items = ((resp.get("body") or {}).get("items")) or {}
    item = items.get("item") if isinstance(items, dict) else None
    if item is None:
        return []
    return item if isinstance(item, list) else [item]


def _tago_nearby(lat, lng, key):
    rows = _tago("BusSttnInfoInqireService/getCrdntPrxmtSttnList",
                 {"gpsLati": lat, "gpsLong": lng, "numOfRows": 100, "pageNo": 1}, key)
    return [{
        "id": "tago:%s:%s" % (r.get("citycode"), r.get("nodeid")),
        "nodeId": str(r.get("nodeid") or ""),
        "cityCode": str(r.get("citycode") or ""),
        "name": r.get("nodenm") or "",
        "no": str(r.get("nodeno") or ""),
        "lat": float(r.get("gpslati")),
        "lng": float(r.get("gpslong")),
        "routes": [],
        "source": "tago",
    } for r in rows if r.get("gpslati") and r.get("gpslong")]


def _tago_profile(stop, route, key):
    city, rid, no = stop["cityCode"], str(route.get("routeid")), str(route.get("routeno"))
    p = {"no": no, "id": rid, "dest": route.get("endnodenm") or "", "kind": route.get("routetp") or "",
         "first": "", "last": "", "iv": {}, "offset": 0, "source": "tago"}
    info = _tago("BusRouteInfoInqireService/getRouteInfoIem", {"cityCode": city, "routeId": rid}, key)
    if info:
        i = info[0]
        wd = int(i.get("intervaltime") or 0)
        sat = int(i.get("intervalsattime") or 0) or wd
        sun = int(i.get("intervalsuntime") or 0) or sat
        p.update(first=_hhmm(i.get("startvehicletime")), last=_hhmm(i.get("endvehicletime")),
                 iv={"wd": wd, "sat": sat, "sun": sun})
    try:
        nodes = _tago("BusRouteInfoInqireService/getRouteAcctoThrghSttnList",
                      {"cityCode": city, "routeId": rid, "numOfRows": 1000, "pageNo": 1}, key)
        ords = [int(n.get("nodeord") or 0) for n in nodes if str(n.get("nodeid")) == stop["nodeId"]]
        if ords:
            p["offset"] = min(180, int(round((min(ords) - 1) * MIN_PER_STOP)))
    except BusError:
        pass
    if not p["first"] or not p["last"] or not p["iv"].get("wd"):
        demo = demo_profile(no, stop.get("id"), p["dest"])   # 빠진 값만 데모로 보완
        p["first"] = p["first"] or demo["first"]
        p["last"] = p["last"] or demo["last"]
        if not p["iv"].get("wd"):
            p["iv"] = demo["iv"]
        p["source"] = "tago+demo"
    return p


def _tago_routes(stop, key):
    rows = _tago("BusSttnInfoInqireService/getSttnThrghRouteList",
                 {"cityCode": stop["cityCode"], "nodeid": stop["nodeId"], "numOfRows": 200, "pageNo": 1}, key)
    rows = rows[:MAX_ROUTES]
    with ThreadPoolExecutor(max_workers=6) as ex:
        profiles = list(ex.map(lambda r: _tago_profile(stop, r, key), rows))
    return sorted(profiles, key=lambda p: _route_sort_key(p["no"]))


def _tago_arrivals(stop, key):
    rows = _tago("ArvlInfoInqireService/getSttnAcctoArvlPrearngeInfoList",
                 {"cityCode": stop["cityCode"], "nodeId": stop["nodeId"], "numOfRows": 100, "pageNo": 1}, key)
    return [{
        "no": str(r.get("routeno") or ""),
        "id": str(r.get("routeid") or ""),
        "sec": int(r.get("arrtime") or 0),
        "prev": int(r.get("arrprevstationcnt") or 0),
    } for r in rows]


# ------------------------------------------------------------------ 경기도 버스 API (GBIS · 같은 서비스키)
def _gbis(path, params, key, list_key):
    k = (key or "").strip()
    k = k if "%" in k else quote(k, safe="")
    url = "%s/%s?serviceKey=%s&format=json&%s" % (GBIS, path, k, urlencode(params))
    try:
        j = _http_json(url, timeout=15)
    except urllib.error.HTTPError as e:
        raise BusError("경기도 버스 API 오류 (HTTP %s) — 활용신청을 확인하세요" % e.code)
    resp = (j or {}).get("response") or j or {}
    head = resp.get("msgHeader") or {}
    code = str(head.get("resultCode", "0"))
    if code == "4":                          # 결과가 존재하지 않습니다(경기도 밖 · 노선 정보 없음 등)
        return []
    if code not in ("0", "00"):
        raise BusError("경기도 버스 API: %s" % (head.get("resultMessage") or code))
    items = (resp.get("msgBody") or {}).get(list_key)
    if not items:
        return []
    return items if isinstance(items, list) else [items]


def _gbis_id(stop):
    """경기도 정류장 id: 경기도 API 정류장이면 stationId, TAGO 경기도 정류장(GGB…)이면 앞 GGB 를 뗀 값."""
    if stop.get("source") == "gbis":
        sid, ident = str(stop.get("stationId") or ""), str(stop.get("id") or "")
        if not sid and ident.startswith("gbis:"):      # stationId 없이 저장된 정류장 — id('gbis:204000158')에 들어 있다
            sid = ident[len("gbis:"):]
        return sid
    node = str(stop.get("nodeId") or "")
    return node[3:] if stop.get("source") == "tago" and node.startswith("GGB") else ""


def _gbis_nearby(lat, lng, key):
    rows = _gbis("busstationservice/v2/getBusStationAroundListv2", {"x": lng, "y": lat}, key, "busStationAroundList")
    return [{
        "id": "gbis:%s" % r.get("stationId"),
        "stationId": str(r.get("stationId")),
        "name": r.get("stationName") or "",
        "no": str(r.get("mobileNo") or "").strip(),
        "lat": float(r.get("y")),
        "lng": float(r.get("x")),
        "routes": [],
        "source": "gbis",
    } for r in rows if r.get("x") and r.get("y")]


def _num(v):
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def _gbis_profile(row, turn_seq, key):
    rid, no = str(row.get("routeId")), str(row.get("routeName"))
    order = _num(row.get("staOrder"))
    down = bool(turn_seq) and order > turn_seq          # 회차 뒤 정류장 = 하행(회차지에서 출발)
    p = {"no": no, "id": rid, "dest": row.get("routeDestName") or "", "kind": row.get("routeTypeName") or "",
         "first": "", "last": "", "iv": {}, "offset": 0, "source": "gbis"}
    info = _gbis("busrouteservice/v2/getBusRouteInfoItemv2", {"routeId": rid}, key, "busRouteInfoItem")
    if info:
        i = info[0]
        side = "Down" if down else "Up"

        def hhmm(day, which):                          # day: '' 평일 · 'sat' · 'sun'
            return _hhmm(i.get((day + side if day else side.lower()) + which))
        p["first"], p["last"] = hhmm("", "FirstTime"), hhmm("", "LastTime")
        p["span"] = {d: {"first": hhmm(d, "FirstTime") or p["first"], "last": hhmm(d, "LastTime") or p["last"]}
                     for d in ("sat", "sun")}
        peak = {"wd": _num(i.get("peekAlloc")), "sat": _num(i.get("satPeekAlloc")), "sun": _num(i.get("sunPeekAlloc"))}
        off = {"wd": _num(i.get("nPeekAlloc")), "sat": _num(i.get("satNPeekAlloc")), "sun": _num(i.get("sunNPeekAlloc"))}
        p["iv"] = {d: peak[d] or off[d] for d in peak}          # 출퇴근 배차
        p["ivOff"] = {d: off[d] or peak[d] for d in off}        # 평시 배차
    stops_before = (order - turn_seq) if down else (order - 1)
    p["offset"] = min(180, int(round(max(0, stops_before) * MIN_PER_STOP)))
    if not p["iv"].get("wd"):
        p["first"] = p["last"] = ""        # 시간표가 없는 노선(출근 전용 등)은 지어내지 않고 실시간만 쓴다
    return p


def _gbis_routes(sid, key):
    rows = _gbis("busstationservice/v2/getBusStationViaRouteListv2", {"stationId": sid}, key, "busRouteList")
    try:                                   # 회차 순번(turnSeq)은 도착 정보에만 있다 — 상·하행 판단용
        turns = {str(a.get("routeId")): _num(a.get("turnSeq")) for a in _gbis(
            "busarrivalservice/v2/getBusArrivalListv2", {"stationId": sid}, key, "busArrivalList")}
    except BusError:
        turns = {}
    rows = rows[:MAX_ROUTES]
    with ThreadPoolExecutor(max_workers=6) as ex:
        profiles = list(ex.map(lambda r: _gbis_profile(r, turns.get(str(r.get("routeId")), 0), key), rows))
    return sorted(profiles, key=lambda p: _route_sort_key(p["no"]))


def _gbis_arrivals(sid, key):
    rows = _gbis("busarrivalservice/v2/getBusArrivalListv2", {"stationId": sid}, key, "busArrivalList")
    out = []
    for r in rows:
        for n in ("1", "2"):                          # 다가오는 버스 2대까지(분 단위)
            if str(r.get("predictTime" + n) or "").strip():
                out.append({"no": str(r.get("routeName")), "id": str(r.get("routeId")),
                            "sec": _num(r.get("predictTime" + n)) * 60, "prev": _num(r.get("locationNo" + n))})
    return out


# ------------------------------------------------------------------ 공개 함수 (app.py 브리지)
def nearby_stops(lat, lng, radius=450, api_key=None):
    """지도 중심 근처 정류장. 키가 있으면 경기도 API → (경기도 밖·실패면) TAGO,
    키가 없으면 OSM. 가까운 순."""
    api_key = _key(api_key)
    try:
        lat, lng = float(lat), float(lng)
        radius = max(150, min(900, int(radius or 450)))
        if api_key:
            try:
                stops, source = _gbis_nearby(lat, lng, api_key), "gbis"
            except BusError:                  # 경기도 API 를 활용신청 안 한 키 등
                stops = []
            if not stops:
                stops, source = _tago_nearby(lat, lng, api_key), "tago"
        else:
            stops, source = _osm_nearby(lat, lng, radius), "osm"
    except BusError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        return {"status": "error", "message": "정류장 조회 실패: %s" % e}
    for s in stops:
        s["dist"] = int(_dist_m(lat, lng, s["lat"], s["lng"]))
    stops.sort(key=lambda s: s["dist"])
    return {"status": "ok", "source": source, "stops": stops}


def _tago_ready(stop):
    return bool(stop.get("cityCode") and stop.get("nodeId"))


def stop_routes(stop, api_key=None):
    """정류장을 지나는 노선의 프로필 목록. 경기도 정류장은 경기도 API 우선, 안 되면 TAGO."""
    stop = stop or {}
    api_key = _key(api_key)
    try:
        if stop.get("source") in ("tago", "gbis"):
            if not api_key:
                return {"status": "error", "message": "이 정류장은 공공데이터포털 키가 필요해요"}
            sid = _gbis_id(stop)
            if sid:
                try:
                    return {"status": "ok", "routes": _gbis_routes(sid, api_key)}
                except BusError:
                    if not _tago_ready(stop):
                        raise
            routes = _tago_routes(stop, api_key)
        else:
            routes = _osm_routes(stop)
    except BusError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        return {"status": "error", "message": "노선 조회 실패: %s" % e}
    return {"status": "ok", "routes": routes}


def arrivals(stop, api_key=None):
    """실시간 도착 예정(경기도 API · TAGO 정류장 + 키가 있을 때만). 그 외엔 unsupported."""
    stop = stop or {}
    api_key = _key(api_key)
    sid = _gbis_id(stop)
    if stop.get("source") not in ("tago", "gbis") or not api_key or not (sid or _tago_ready(stop)):
        return {"status": "unsupported"}
    try:
        out = None
        if sid:
            try:
                out = _gbis_arrivals(sid, api_key)
            except BusError:
                if not _tago_ready(stop):
                    raise
        if out is None:
            out = _tago_arrivals(stop, api_key)
    except BusError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        return {"status": "error", "message": "실시간 도착 조회 실패: %s" % e}
    out.sort(key=lambda a: a["sec"])
    return {"status": "ok", "arrivals": out}


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "nearby":
        res = nearby_stops(sys.argv[2], sys.argv[3])
        if res.get("stops"):
            res["stops"] = res["stops"][:8]
            res["firstRoutes"] = stop_routes(res["stops"][0])
    elif cmd == "search":
        res = search_place(" ".join(sys.argv[2:]))
    else:
        res = {"status": "error", "message": "usage: bus.py nearby LAT LNG | search QUERY"}
    print(json.dumps(res, ensure_ascii=False, indent=1))
