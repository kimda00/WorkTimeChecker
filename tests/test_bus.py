"""Offline checks for bus.py (no network): .venv\\Scripts\\python -m unittest discover -s tests -p test_bus.py -v"""
import json
import os
import tempfile
import time
import unittest
from unittest.mock import patch

import bus


class BusTestCase(unittest.TestCase):
    """개발 폴더 config.json 의 배포 키와 무관하게 '키 없음'을 기본으로 검사한다(네트워크 차단).
    실시간 도착이 남기는 도착 기록은 임시 폴더에 쓴다."""
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.bus_dir = tmp.name
        for p in (patch.object(bus, "_config", return_value=None), patch.object(bus, "BUS_DIR", tmp.name),
                  patch.dict(bus._hist_pending, clear=True), patch.object(bus, "_hist_swept", "")):
            p.start()
            self.addCleanup(p.stop)


class DemoProfileTests(BusTestCase):
    def test_same_route_and_stop_always_get_the_same_schedule(self):
        a = bus.demo_profile("3100", "osm:1")
        self.assertEqual(a, bus.demo_profile("3100", "osm:1"))
        self.assertEqual(a["source"], "demo")
        self.assertIn(a["iv"]["wd"], (15, 18, 20, 25))          # 4자리 광역/직행
        self.assertGreaterEqual(a["iv"]["sun"], a["iv"]["sat"])
        self.assertGreaterEqual(a["iv"]["sat"], a["iv"]["wd"])
        self.assertRegex(a["first"], r"^05:\d0$")
        self.assertTrue(0 <= a["offset"] <= 40)

    def test_hhmm_normalizes_api_times(self):
        self.assertEqual(bus._hhmm("0530"), "05:30")
        self.assertEqual(bus._hhmm(530), "05:30")
        self.assertEqual(bus._hhmm("23:10"), "23:10")
        self.assertEqual(bus._hhmm(""), "")
        self.assertEqual(bus._hhmm("9999"), "")


class OsmRouteTests(BusTestCase):
    def test_routes_come_from_stop_lines_without_another_request(self):
        stop = {"id": "osm:7", "routes": ["101", "9007"], "lines": {
            "9007": {"to": "강남역"},
            "101": {"interval": "00:12", "opening_hours": "05:30-23:40"},
        }, "source": "osm"}
        with patch.object(bus, "_http_json", side_effect=AssertionError("no network")):
            res = bus.stop_routes(stop)
        self.assertEqual(res["status"], "ok")
        self.assertEqual([r["no"] for r in res["routes"]], ["101", "9007"])
        r101, r9007 = res["routes"]
        self.assertEqual((r101["first"], r101["last"], r101["iv"]["wd"], r101["source"]), ("05:30", "23:40", 12, "osm"))
        self.assertEqual((r9007["dest"], r9007["source"]), ("강남역", "demo"))

    def test_overpass_result_maps_relations_to_member_stops(self):
        payload = {"elements": [
            {"type": "node", "id": 1, "lat": 37.0, "lon": 127.0, "tags": {"name": "판교역", "ref": "07073", "route_ref": "101"}},
            {"type": "relation", "id": 9, "tags": {"ref": "3100", "to": "강남"}, "members": [{"type": "node", "ref": 1}]},
        ]}
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(bus, "_overpass", return_value=payload) as overpass, \
                patch.object(bus, "BUS_DIR", tmp):
            res = bus.nearby_stops(37.0, 127.0, 300)
            again = bus.nearby_stops(37.0, 127.0, 300)       # 같은 지역은 디스크 캐시
        self.assertEqual(overpass.call_count, 1)
        self.assertEqual(again["stops"], res["stops"])
        stop = res["stops"][0]
        self.assertEqual((stop["name"], stop["no"], stop["routes"]), ("판교역", "07073", ["101", "3100"]))
        self.assertEqual(stop["lines"]["3100"], {"to": "강남"})


class TagoTests(BusTestCase):
    def setUp(self):
        super().setUp()
        # 경기도 밖 TAGO 정류장(대전) — 경기도 정류장(GGB…)은 경기도 API 로 가므로 TAGO 경로는 이걸로 본다
        self.stop = {"id": "tago:25:DJB1", "nodeId": "DJB1", "cityCode": "25", "source": "tago", "name": "대전역"}

    @staticmethod
    def envelope(item):
        return {"response": {"header": {"resultCode": "00"}, "body": {"items": {"item": item} if item is not None else ""}}}

    def test_single_item_dict_and_empty_items_are_normalized(self):
        with patch.object(bus, "_http_json", return_value=self.envelope({"routeno": 101})):
            self.assertEqual(bus._tago("X/y", {}, "k"), [{"routeno": 101}])
        with patch.object(bus, "_http_json", return_value=self.envelope(None)):
            self.assertEqual(bus._tago("X/y", {}, "k"), [])

    def test_error_result_code_is_reported(self):
        bad = {"response": {"header": {"resultCode": "30", "resultMsg": "SERVICE KEY IS NOT REGISTERED ERROR."}}}
        with patch.object(bus, "_http_json", return_value=bad):
            res = bus.arrivals(self.stop, "key")
        self.assertEqual(res["status"], "error")
        self.assertIn("SERVICE KEY", res["message"])

    def test_route_profile_uses_interval_and_stop_order(self):
        def fake(url, data=None, timeout=20):
            if "getSttnThrghRouteList" in url:
                return self.envelope([{"routeid": "R1", "routeno": 3100, "endnodenm": "강남역"}])
            if "getRouteInfoIem" in url:
                return self.envelope({"startvehicletime": "0530", "endvehicletime": "2310",
                                      "intervaltime": 15, "intervalsattime": 20, "intervalsuntime": ""})
            if "getRouteAcctoThrghSttnList" in url:
                return self.envelope([{"nodeid": "X", "nodeord": 1}, {"nodeid": "DJB1", "nodeord": 11}])
            raise AssertionError(url)
        with patch.object(bus, "_http_json", side_effect=fake):
            res = bus.stop_routes(self.stop, "a+b/c=")
        p = res["routes"][0]
        self.assertEqual((p["no"], p["first"], p["last"], p["dest"]), ("3100", "05:30", "23:10", "강남역"))
        self.assertEqual(p["iv"], {"wd": 15, "sat": 20, "sun": 20})
        self.assertEqual(p["offset"], 16)       # (11-1) 정류장 × 1.6분
        self.assertEqual(p["source"], "tago")

    def test_decoding_key_is_url_encoded_and_encoded_key_kept(self):
        seen = []
        with patch.object(bus, "_http_json", side_effect=lambda url, **k: seen.append(url) or self.envelope(None)):
            bus._tago("A/b", {}, "a+b/c=")
            bus._tago("A/b", {}, "a%2Bb%2Fc%3D")
        self.assertIn("serviceKey=a%2Bb%2Fc%3D&", seen[0])
        self.assertIn("serviceKey=a%2Bb%2Fc%3D&", seen[1])

    def test_arrivals_without_key_or_for_osm_stop_are_unsupported(self):
        self.assertEqual(bus.arrivals(self.stop, "")["status"], "unsupported")
        self.assertEqual(bus.arrivals({"source": "osm"}, "key")["status"], "unsupported")


class GbisTests(BusTestCase):
    NONE = {"response": {"msgHeader": {"resultCode": 4, "resultMessage": "결과가 존재하지 않습니다."}}}

    @staticmethod
    def ok(list_key, items):
        return {"response": {"msgHeader": {"resultCode": 0}, "msgBody": {list_key: items}}}

    def fake(self, url, data=None, timeout=20):
        if "getBusStationViaRouteListv2" in url:
            return self.ok("busRouteList", [
                {"routeId": 241213007, "routeName": 87, "routeDestName": "사기막골", "routeTypeName": "마을버스", "staOrder": 2},
                {"routeId": 233000031, "routeName": 310, "routeDestName": "판교역", "staOrder": 34},
                {"routeId": 102000001, "routeName": "서울07출근", "staOrder": 6}])
        if "getBusArrivalListv2" in url:
            return self.ok("busArrivalList", [
                {"routeId": 241213007, "routeName": 87, "turnSeq": 42, "predictTime1": "", "locationNo1": ""},
                {"routeId": 233000031, "routeName": 310, "turnSeq": 32, "predictTime1": 26, "locationNo1": 18,
                 "predictTime2": 45, "locationNo2": 24},
                {"routeId": 102000001, "routeName": "서울07출근", "turnSeq": 5, "predictTime1": ""}])
        if "getBusRouteInfoItemv2" in url:
            if "routeId=102000001" in url:
                return self.NONE                                 # 시간표 없는 노선
            if "routeId=241213007" in url:
                return self.ok("busRouteInfoItem", {
                    "upFirstTime": "05:00", "upLastTime": "22:00", "downFirstTime": "05:55", "downLastTime": "22:55",
                    "satUpFirstTime": "05:30", "satUpLastTime": "21:00", "peekAlloc": 10, "nPeekAlloc": 25,
                    "satPeekAlloc": 25, "satNPeekAlloc": 35, "sunPeekAlloc": 0, "sunNPeekAlloc": 0})
            return self.ok("busRouteInfoItem", {"upFirstTime": "06:00", "upLastTime": "23:30", "downFirstTime": "06:40",
                                                "downLastTime": "00:10", "peekAlloc": 10, "nPeekAlloc": 20})
        if "getBusStationAroundListv2" in url:
            if "x=127.38" in url:
                return self.NONE                                 # 경기도 밖
            return self.ok("busStationAroundList", [
                {"stationId": 204000158, "stationName": "텔레칩스", "mobileNo": " 05341", "x": 127.0873667, "y": 37.40645}])
        if "getCrdntPrxmtSttnList" in url:
            return {"response": {"header": {"resultCode": "00"}, "body": {"items": {"item": {
                "nodeid": "DJB8001793", "nodenm": "대전역", "citycode": 25, "gpslati": 36.35, "gpslong": 127.38}}}}}
        raise AssertionError(url)

    def test_tago_gyeonggi_stop_uses_gyeonggi_routes_with_direction_and_peak(self):
        stop = {"id": "tago:31020:GGB204000158", "nodeId": "GGB204000158", "cityCode": "31020", "source": "tago"}
        with patch.object(bus, "_http_json", side_effect=self.fake):
            res = bus.stop_routes(stop, "k")
        r = {p["no"]: p for p in res["routes"]}
        self.assertEqual(set(r), {"87", "310", "서울07출근"})             # TAGO 에 없던 마을버스 포함
        p = r["87"]                                                    # 기점 다음 정류장 = 상행
        self.assertEqual((p["first"], p["last"], p["offset"], p["source"]), ("05:00", "22:00", 2, "gbis"))
        self.assertEqual((p["iv"], p["ivOff"]), ({"wd": 10, "sat": 25, "sun": 0}, {"wd": 25, "sat": 35, "sun": 0}))
        self.assertEqual(p["span"], {"sat": {"first": "05:30", "last": "21:00"}, "sun": {"first": "05:00", "last": "22:00"}})
        self.assertEqual((r["310"]["first"], r["310"]["last"], r["310"]["offset"]), ("06:40", "00:10", 3))   # 회차 뒤 = 하행
        self.assertEqual((r["서울07출근"]["first"], r["서울07출근"]["iv"]), ("", {}))            # 지어내지 않음

    def test_gyeonggi_arrivals_are_minutes_and_fall_back_to_tago_without_access(self):
        with patch.object(bus, "_http_json", side_effect=self.fake):
            res = bus.arrivals({"id": "gbis:204000158", "stationId": "204000158", "source": "gbis"}, "k")
        self.assertEqual(res["arrivals"], [{"no": "310", "id": "233000031", "sec": 1560, "prev": 18},
                                           {"no": "310", "id": "233000031", "sec": 2700, "prev": 24}])

        def no_gbis(url, data=None, timeout=20):
            if "/6410000/" in url:
                raise bus.urllib.error.HTTPError(url, 403, "Forbidden", None, None)
            return TagoTests.envelope([{"routeno": 3100, "routeid": "GGB204000170", "arrtime": 300, "arrprevstationcnt": 2}])
        stop = {"id": "gbis:204000158", "stationId": "204000158", "nodeId": "GGB204000158", "cityCode": "31020", "source": "gbis"}
        with patch.object(bus, "_http_json", side_effect=no_gbis):
            res = bus.arrivals(stop, "k")
        self.assertEqual(res["arrivals"], [{"no": "3100", "id": "GGB204000170", "sec": 300, "prev": 2}])
        with patch.object(bus, "_http_json", side_effect=no_gbis):
            self.assertEqual(bus.arrivals({"id": "gbis:1", "stationId": "1", "source": "gbis"}, "k")["status"], "error")

    def test_saved_gyeonggi_stop_without_station_id_still_gets_live_arrivals(self):
        # 예전 저장본: stationId · nodeId · cityCode 가 비어 있고 id 에만 정류장 번호가 있다
        saved = {"id": "gbis:204000158", "name": "텔레칩스", "no": "05341", "source": "gbis",
                 "cityCode": "", "nodeId": ""}
        self.assertEqual(bus._gbis_id(saved), "204000158")
        with patch.object(bus, "_http_json", side_effect=self.fake):
            res = bus.arrivals(saved, "k")
        self.assertEqual(res["status"], "ok")
        self.assertEqual([a["no"] for a in res["arrivals"]], ["310", "310"])
        self.assertEqual(bus._gbis_id({"source": "gbis", "id": "osm:1"}), "")      # 번호를 알 수 없으면 그대로 미지원
        self.assertEqual(bus.arrivals({"source": "gbis", "id": "osm:1"}, "k")["status"], "unsupported")

    def test_nearby_uses_gyeonggi_then_tago_outside_gyeonggi(self):
        with patch.object(bus, "_http_json", side_effect=self.fake):
            gg = bus.nearby_stops(37.40645, 127.0873667, 450, "k")
            dj = bus.nearby_stops(36.35, 127.38, 450, "k")
        self.assertEqual((gg["source"], gg["stops"][0]["id"], gg["stops"][0]["no"]), ("gbis", "gbis:204000158", "05341"))
        self.assertEqual((dj["source"], dj["stops"][0]["name"]), ("tago", "대전역"))


class DeployKeyTests(BusTestCase):
    def test_personal_key_wins_and_deploy_key_fills_in(self):
        with patch.object(bus, "_config", return_value=" deploy "):
            self.assertEqual(bus._key(" mine "), "mine")
            self.assertEqual(bus._key(""), "deploy")
            self.assertTrue(bus.has_default_key())
        self.assertIsNone(bus._key(None))
        self.assertFalse(bus.has_default_key())

    def test_screen_without_key_uses_deploy_key_for_tago(self):
        seen = []
        with patch.object(bus, "_config", return_value="deploy"),                 patch.object(bus, "_tago_nearby", side_effect=lambda lat, lng, key: seen.append(key) or []):
            res = bus.nearby_stops(37.0, 127.0, 300, None)
        self.assertEqual((res["source"], seen), ("tago", ["deploy"]))


def hm(text):
    """'15:04' → 하루 초"""
    h, m = text.split(":")
    return int(h) * 3600 + int(m) * 60


class HistoryTests(BusTestCase):
    STOP = {"id": "gbis:204000158", "stationId": "204000158", "source": "gbis"}
    DAY = time.strftime("%Y-%m-%d")                      # 기록은 최근 10주만 남기므로 오늘 날짜로

    def poll(self, hhmm, *buses, stop=None):
        """hhmm 에 실시간 도착을 받았다: buses = (노선 id, 남은 초, 차량 id)"""
        now = time.mktime(time.strptime(self.DAY + " " + hhmm, "%Y-%m-%d %H:%M"))
        arrivals = [{"no": "311", "id": rid, "sec": sec, **({"veh": veh} if veh else {})} for rid, sec, veh in buses]
        bus.record_arrivals(stop or self.STOP, arrivals, now)

    def saved(self, key="gbis_204000158"):
        with open(os.path.join(self.bus_dir, "history_%s.json" % key), encoding="utf-8") as f:
            return json.load(f)["days"][self.DAY]

    def test_bus_seen_right_before_the_stop_is_recorded_when_it_passes(self):
        self.poll("15:00", ("204000192", 600, "v1"))                   # 10분 전 — 지켜보기만
        self.poll("15:04", ("204000192", 360, "v1"))
        self.poll("15:08", ("204000192", 120, "v1"))                   # 2분 전
        self.poll("15:09", ("204000192", 60, "v1"), ("204000192", 1500, "v2"))
        self.poll("15:11", ("204000192", 1380, "v2"))                  # v1 이 빠짐 → 15:10 에 지나감
        self.poll("15:12")                                            # v2 는 멀리서 사라짐 → 기록 안 함
        day = self.saved()
        self.assertEqual(day["arr"], {"204000192": [hm("15:10")]})
        self.assertEqual(day["cover"], [[hm("15:00"), hm("15:12")]])

    def test_without_vehicle_id_nearby_predictions_are_the_same_bus_and_gaps_are_not_guessed(self):
        tago = {"id": "tago:31020:GGB204000158", "nodeId": "GGB204000158", "cityCode": "31020", "source": "tago"}
        self.poll("15:00", ("GGB204000192", 180, None), stop=tago)    # TAGO: 차량 id 없음, 노선 id 에 GGB
        self.poll("15:01", ("GGB204000192", 100, None), stop=tago)
        self.poll("15:02", ("GGB204000192", 30, None), stop=tago)
        self.poll("15:03", stop=tago)                                  # 15:02:30 에 지나감
        self.poll("15:30", ("GGB204000192", 60, None), stop=tago)     # 조회가 27분 끊겼다가 다시
        self.poll("15:50", stop=tago)                                  # 또 끊김 — 언제 지나갔는지 몰라 기록 안 함
        day = self.saved()                                             # TAGO 로 저장한 경기도 정류장도 같은 기록 파일
        self.assertEqual(day["arr"], {"204000192": [hm("15:02") + 30]})
        self.assertEqual(day["cover"], [[hm("15:00"), hm("15:03")], [hm("15:30"), hm("15:30")], [hm("15:50"), hm("15:50")]])

    def test_history_groups_same_trips_by_weekday_kind_with_earliest_and_latest(self):
        days = {
            "2026-10-26": {"cover": [[hm("15:00"), hm("17:00")]], "arr": {"204000192": [hm("15:04"), hm("15:36")]}},  # 월
            "2026-10-27": {"cover": [[hm("15:00"), hm("17:00")]], "arr": {"204000192": [hm("15:08"), hm("15:32")],
                                                                          "204000194": [hm("15:05"), hm("15:07")]}},  # 화
            "2026-10-28": {"cover": [[hm("16:00"), hm("18:00")]], "arr": {"204000192": [hm("16:30")]}},               # 수
            "2026-10-31": {"cover": [[hm("15:00"), hm("17:00")]], "arr": {"204000192": [hm("15:20")]}},               # 토
            "2026-10-09": {"cover": [[hm("15:00"), hm("16:00")]], "arr": {"204000192": [hm("15:50")]}},               # 한글날(금)
        }
        os.makedirs(self.bus_dir, exist_ok=True)
        with open(os.path.join(self.bus_dir, "history_gbis_204000158.json"), "w", encoding="utf-8") as f:
            json.dump({"days": days}, f)
        res = bus.history(self.STOP)
        wd = res["kinds"]["wd"]
        self.assertEqual((wd["days"], wd["cover"]), (3, [[hm("15:00"), hm("18:00")]]))
        self.assertEqual(wd["routes"]["204000192"], [
            {"at": hm("15:06"), "lo": hm("15:04"), "hi": hm("15:08"), "n": 2},
            {"at": hm("15:34"), "lo": hm("15:32"), "hi": hm("15:36"), "n": 2},
            {"at": hm("16:30"), "lo": hm("16:30"), "hi": hm("16:30"), "n": 1}])
        self.assertEqual([t["at"] for t in wd["routes"]["204000194"]], [hm("15:05"), hm("15:07")])   # 같은 날 두 대는 따로
        self.assertEqual((res["kinds"]["sat"]["days"], res["kinds"]["sun"]["days"]), (1, 1))          # 공휴일은 일요일 배차
        self.assertEqual(bus.history({"source": "osm", "id": "osm:1"})["status"], "unsupported")

    def test_old_days_and_unused_stop_files_are_removed(self):
        ago = lambda days: time.strftime("%Y-%m-%d", time.localtime(time.time() - days * 86400))
        mine = os.path.join(self.bus_dir, "history_gbis_204000158.json")
        with open(mine, "w", encoding="utf-8") as f:
            json.dump({"days": {ago(d): {"cover": [[54000, 54060]], "arr": {}} for d in (100, 71, 69, 1)}}, f)
        files = {name: os.path.join(self.bus_dir, name) for name in
                 ("history_gbis_1.json", "history_tago_25_X.json", "history_gbis_2.json.tmp", "osm_37.0_127.0_300.json")}
        for path in files.values():
            with open(path, "w", encoding="utf-8") as f:
                f.write("{}")
        stale = time.time() - 80 * 86400                               # 80일 동안 기록 없음
        for name in ("history_gbis_1.json", "history_gbis_2.json.tmp", "osm_37.0_127.0_300.json"):
            os.utime(files[name], (stale, stale))
        self.poll("15:00")
        with open(mine, encoding="utf-8") as f:                        # 이 정류장은 10주 넘은 날짜만 빠진다
            self.assertEqual(sorted(json.load(f)["days"]), [ago(69), ago(1), self.DAY])
        self.assertEqual(sorted(n for n in os.listdir(self.bus_dir)),   # 안 쓰는 정류장 기록만 지운다(지도 캐시는 그대로)
                         ["history_gbis_204000158.json", "history_tago_25_X.json", "osm_37.0_127.0_300.json"])

    def test_live_arrivals_are_recorded_and_recording_errors_never_break_them(self):
        rows = {"response": {"msgHeader": {"resultCode": 0}, "msgBody": {"busArrivalList": [
            {"routeId": 204000192, "routeName": 311, "predictTime1": 2, "predictTimeSec1": 95, "vehId1": 7001,
             "locationNo1": 1, "predictTime2": ""}]}}}
        with patch.object(bus, "_http_json", return_value=rows):
            res = bus.arrivals(self.STOP, "k")
        self.assertEqual(res["arrivals"], [{"no": "311", "id": "204000192", "sec": 95, "prev": 1, "veh": "7001"}])
        self.assertEqual(bus._hist_pending["gbis_204000158"][0]["veh"], "7001")
        with patch.object(bus, "_http_json", return_value=rows), \
                patch.object(bus, "_hist_write", side_effect=OSError("disk full")):
            self.assertEqual(bus.arrivals(self.STOP, "k")["status"], "ok")


class TileTests(BusTestCase):
    def test_out_of_range_tiles_are_rejected_before_any_request(self):
        with patch.object(bus.urllib.request, "urlopen", side_effect=AssertionError("no network")):
            self.assertIsNone(bus.tile(3, 8, 0))
            self.assertIsNone(bus.tile(20, 0, 0))
            self.assertIsNone(bus.tile("x", 0, 0))


if __name__ == "__main__":
    unittest.main()
