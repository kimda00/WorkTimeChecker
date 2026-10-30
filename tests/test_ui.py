r"""Offline UI checks: .venv\Scripts\python -m unittest discover -s tests -v"""
import datetime
import json
from pathlib import Path
import unittest

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]


class WorkTimeUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(channel="msedge", headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.context = self.browser.new_context(viewport={"width": 900, "height": 530}, timezone_id="Asia/Seoul")
        self.page = self.context.new_page()
        self.errors = []
        self.page.on("pageerror", lambda exc: self.errors.append(str(exc)))
        self.page.clock.install(time=datetime.datetime(2026, 10, 29, 12, tzinfo=datetime.timezone(datetime.timedelta(hours=9))))
        fixture = {"settings": {"defaultIn": "07:49", "theme": "excel"}, "weeks": {}}
        self.page.add_init_script("localStorage.setItem('worktime', " + json.dumps(json.dumps(fixture)) + ");")
        self.page.goto((ROOT / "ui/index.html").as_uri())
        self.page.locator('#rowIn input[data-day="fri"]').wait_for()

    def tearDown(self):
        self.assertEqual(self.errors, [])
        self.context.close()

    def edit(self, day, field, value):
        self.page.locator(f'.cellinput[data-day="{day}"][data-field="{field}"]').fill(value)
        self.page.locator("#weekLabel").click()

    def text(self, selector):
        return self.page.locator(selector).text_content()

    def test_out_only_uses_default_without_storing_a_clock_in(self):
        start = self.page.locator('#rowIn input[data-day="fri"]')
        self.assertEqual(start.get_attribute("placeholder"), "07:49")
        self.assertEqual(start.input_value(), "")
        self.assertEqual(self.text("#sCumNow"), "0:00")
        self.edit("fri", "out", "16:49")
        self.assertEqual(self.text('#rowWork td[data-day="fri"]'), "8:00")
        self.assertEqual(self.text("#sCumPlan"), "8:00")
        self.assertEqual(self.text("#sCumNow"), "0:00")
        saved = self.page.evaluate("async () => { await doSave(); return JSON.parse(localStorage.getItem('worktime')); }")
        self.assertEqual(saved["weeks"]["2026-10-26"]["fri"]["in"], "")
        self.assertEqual(start.input_value(), "")
        self.edit("fri", "in", "08:49")
        self.assertEqual(self.text('#rowWork td[data-day="fri"]'), "7:00")
        self.edit("fri", "in", "")
        self.assertEqual(self.text('#rowWork td[data-day="fri"]'), "8:00")
        self.edit("fri", "out", "")
        self.assertEqual(self.text("#sCumPlan"), "0:00")

    def test_default_change_updates_past_and_future_out_only_totals(self):
        self.edit("mon", "out", "16:49")
        self.edit("fri", "out", "16:49")
        self.assertEqual(self.text("#sCumNow"), "8:00")
        self.assertEqual(self.text("#sCumPlan"), "16:00")
        self.page.locator("#defaultIn").fill("08:49")
        self.page.locator("#weekLabel").click()
        self.assertEqual(self.text("#sCumPlan"), "14:00")
        self.assertEqual(self.page.locator('#rowIn input[data-day="mon"]').get_attribute("placeholder"), "08:49")
        self.page.locator("#prevWeek").click()
        self.assertEqual(self.text("#sCumNow"), "0:00")

    def test_leave_and_halfday_keep_their_work_credit_and_boundaries(self):
        select = lambda day: self.page.locator(f'.typesel[data-day="{day}"]')
        select("mon").select_option("연차")
        self.assertEqual(self.text('#rowWork td[data-day="mon"]'), "8:00")
        self.assertTrue(self.page.locator('#rowIn input[data-day="mon"]').is_disabled())
        self.assertEqual(self.page.locator('#rowIn input[data-day="mon"]').get_attribute("placeholder"), "—")
        select("tue").select_option("오전반차")
        self.edit("tue", "out", "17:00")
        self.assertEqual(self.page.locator('#rowIn input[data-day="tue"]').input_value(), "13:00")
        self.assertEqual(self.text('#rowWork td[data-day="tue"]'), "8:00")
        select("wed").select_option("오후반차")
        self.assertEqual(self.text('#rowWork td[data-day="wed"]'), "8:11")
        self.edit("thu", "out", "11:49")
        self.assertEqual(self.text('#rowWork td[data-day="thu"]'), "4:00")

    def test_remaining_completion_overtime_have_distinct_status_and_progress(self):
        self.assertEqual(self.page.locator("#sRemainPlan").get_attribute("data-tone"), "remaining")
        for day in ("mon", "tue", "wed", "thu"):
            self.edit(day, "out", "16:49")
        self.assertEqual(self.text("#sRemainPlan"), "8:00남음")
        self.assertEqual(self.page.locator("#sRemainPlan").get_attribute("data-tone"), "near")
        self.edit("fri", "out", "16:49")
        self.assertEqual(self.text("#sRemainPlan"), "0:00달성")
        self.assertEqual(self.page.locator("#sRemainPlan").get_attribute("data-tone"), "complete")
        self.edit("fri", "out", "17:49")
        self.assertEqual(self.text("#sRemainPlan"), "+1:00연장")
        self.assertEqual(self.page.locator("#sRemainPlan").get_attribute("data-tone"), "overtime")
        self.assertEqual(self.page.locator("#progressPlan").get_attribute("aria-valuenow"), "100")
        self.assertEqual(self.page.locator("#progressPlan").get_attribute("aria-valuetext"), "41:00 / 40:00")

    def nav(self, view):
        return self.page.locator(f'#sideNav .navitem[data-view="{view}"]')

    def test_navigation_has_stable_labels_and_a_dedicated_work_button(self):
        for view, panel, label in (("bus", "busPanel", "버스"), ("cal", "calPanel", "캘린더"), ("meal", "mealPanel", "식단"), ("ttree", "ttreePanel", "휴가·출장"), ("approval", "approvalPanel", "결재")):
            for _ in range(2):
                self.nav(view).click()
                self.assertTrue(self.page.locator("#" + panel).is_visible())
                self.assertEqual(self.nav(view).text_content().strip(), label)
                self.assertEqual(self.nav(view).get_attribute("aria-current"), "page")
                self.assertEqual(self.page.locator('#sideNav .navitem[aria-current="page"]').count(), 1)
            self.nav("work").click()
            self.assertTrue(self.page.locator("#grid").is_visible())
            self.assertFalse(self.page.locator("#" + panel).is_visible())

    def install_bus_stop(self, save=True):
        """가짜 브리지로 정류장 1곳(노선 100: 10분 배차, 200: 30분 배차)을 지도에서 누르고, save 면 저장한다."""
        self.page.evaluate("""async () => {
          window.pywebview = {api: {
            save: async s => { window.savedState = JSON.parse(JSON.stringify(s)); return true; },
            bus_tile: async () => null,
            bus_stop_routes: async () => ({status: 'ok', routes: [
              {no: '100', first: '06:00', last: '23:00', iv: {wd: 10, sat: 20, sun: 30}, offset: 0, source: 'demo'},
              {no: '200', first: '06:05', last: '22:00', iv: {wd: 30}, offset: 0, source: 'demo'},
            ]}),
          }};
          document.querySelector('#sideNav .navitem[data-view="bus"]').click();
          await previewBusStop({id: 'osm:1', name: '테스트정류장', no: '07073', lat: 37.39, lng: 127.11, routes: ['100', '200'], source: 'osm'});
        }""")
        if save:
            self.page.locator("#busPrevSave").click()

    def test_stop_click_previews_buses_before_saving(self):
        self.install_bus_stop(save=False)
        self.assertEqual(self.text("#busTabStop"), "정류장 · 테스트정류장")
        self.assertTrue(self.page.locator("#busStopPane").is_visible())
        self.assertTrue(self.page.locator("#busTodayPane").is_hidden())
        self.assertIsNone(self.page.evaluate("busCfg().stop"))               # 누르기만 해선 저장 안 됨
        rows = self.page.locator("#busPrevRoutes .busprevroute")
        self.assertEqual(rows.count(), 2)
        self.assertEqual(rows.first.locator(".busprevtimes b").all_text_contents(), ["12:00", "12:10", "12:20"])
        self.assertEqual(self.text("#busPrevSave"), "이 정류장으로 저장")
        rows.nth(1).locator("input").uncheck()
        self.page.locator("#busPrevSave").click()
        self.assertTrue(self.page.locator("#busTodayPane").is_visible())     # 저장하면 오늘의 버스가 열을 차지
        self.assertTrue(self.page.locator("#busTabStop").is_hidden())
        self.assertEqual(self.page.evaluate("[busCfg().stop.name, busCfg().take]"), ["테스트정류장", ["100"]])
        self.assertEqual(self.text("#busStopEdit"), "테스트정류장 · 07073 ›")
        self.page.locator("#busStopEdit").click()                           # 정류장 이름 → 탈 버스 바꾸기
        self.assertEqual(self.text("#busPrevSave"), "탈 버스 저장")
        self.assertEqual(self.page.locator("#busPrevRoutes input:checked").count(), 1)

    def test_bus_tab_lists_todays_buses_with_leave_times(self):
        for day in ("mon", "tue", "wed"):
            self.edit(day, "out", "16:49")
        self.install_bus_stop()
        self.assertTrue(self.page.locator("#busPanel").is_visible())
        self.assertIn("데모 배차", self.text("#busSrc"))
        self.assertEqual(self.text("#busNeed"), "예상 퇴근 16:49")
        first = self.page.locator("#busToday .busopt").first          # 예상 퇴근 30분 전부터 보여준다
        self.assertEqual(first.locator(".busopt-at").text_content(), "16:30")
        self.assertEqual(first.locator(".busopt-leave").text_content(), "16:25 퇴근")
        self.assertEqual(self.page.locator("#busToday .busopt.rec .busopt-at").text_content(), "17:00")
        self.page.locator("#busStopEdit").click()                     # 100번 끄면 200번(30분 배차)만
        self.page.locator("#busPrevRoutes input").first.uncheck()
        self.page.locator("#busPrevSave").click()
        self.assertEqual(self.page.locator("#busToday .busopt").first.locator(".busopt-at").text_content(), "16:35")
        self.page.locator("#busBuffer").fill("10")
        self.page.locator("#busBuffer").press("Enter")
        self.assertEqual(self.page.locator("#busToday .busopt").first.locator(".busopt-leave").text_content(), "16:25 퇴근")
        self.page.locator("#busToday .busopt.rec").click()          # 오늘의 버스에서 바로 고르기
        self.assertEqual(self.page.locator('#rowOut input[data-day="thu"]').get_attribute("placeholder"), "16:55")
        self.page.evaluate("doSave()")
        self.assertEqual(self.page.evaluate("savedState.settings.bus.take"), ["200"])
        self.assertEqual(self.page.evaluate("savedState.settings.bus.bufferMin"), 10)
        self.assertEqual(self.page.evaluate("savedState.weeks['2026-10-26'].thu.bus"), {"route": "200", "at": "17:05"})

    def test_bus_choice_plans_checkout_and_shifts_other_days(self):
        for day in ("mon", "tue", "wed"):
            self.edit(day, "out", "16:49")
        self.assertTrue(self.page.locator("#rowBus").is_hidden())
        self.install_bus_stop()
        self.nav("work").click()
        bus_cell = lambda day: self.page.locator(f'#rowBus .buscell[data-day="{day}"]')
        self.assertTrue(self.page.locator("#rowBus").is_visible())
        self.assertEqual(self.text('#rowEstOut td[data-day="thu"]'), "16:49")
        self.assertEqual(bus_cell("thu").text_content(), "10017:00")     # 예상 퇴근 이후 첫 버스(17:00, 16:55 퇴근) 추천
        self.assertIn("suggest", bus_cell("thu").get_attribute("class"))

        bus_cell("thu").click()
        self.assertTrue(self.page.locator("#busPop").is_visible())
        self.assertIn("rec", self.page.locator("#busPop .busopt", has_text="17:00").first.get_attribute("class"))
        self.page.locator("#busPop .busopt", has_text="17:30").first.click()
        self.assertTrue(self.page.locator("#busPop").is_hidden())
        thu_out = self.page.locator('#rowOut input[data-day="thu"]')
        self.assertEqual(thu_out.input_value(), "")
        self.assertEqual(thu_out.get_attribute("placeholder"), "17:25")
        self.assertEqual(self.text('#rowWork td[data-day="thu"]'), "8:36")
        self.assertEqual(self.text('#rowEstOut td[data-day="fri"]'), "16:13")   # 목요일 36분 더 → 금요일 36분 일찍
        self.assertEqual(bus_cell("fri").text_content(), "10016:20")
        self.assertEqual(self.text("#sCumPlan"), "32:36")
        self.page.evaluate("doSave()")
        self.assertEqual(self.page.evaluate("savedState.weeks['2026-10-26'].thu"), {"type": "", "in": "", "out": "", "bus": {"route": "100", "at": "17:30"}})

        self.edit("thu", "out", "18:49")                    # 실제 퇴근이 버스 예정보다 우선
        self.assertEqual(self.text('#rowWork td[data-day="thu"]'), "10:00")
        self.edit("thu", "out", "")
        self.assertEqual(self.text('#rowWork td[data-day="thu"]'), "8:36")

        self.page.locator('.typesel[data-day="fri"]').select_option("연차")
        self.assertTrue(bus_cell("fri").is_disabled())
        bus_cell("thu").click()
        self.page.locator("#busPop button", has_text="선택 해제").click()
        self.assertIn("suggest", bus_cell("thu").get_attribute("class"))
        self.assertEqual(thu_out.get_attribute("placeholder"), "퇴근")
        for theme in ("excel", "dark"):
            self.page.evaluate("theme => applyTheme(theme)", theme)
            for width in (900, 720):
                self.page.set_viewport_size({"width": width, "height": 530})
                for view in ("work", "bus"):
                    self.page.evaluate("view => setView(view)", view)
                    self.assertTrue(self.page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (theme, width, view))

    def test_live_arrivals_calibrate_schedule_and_snap_picked_buses(self):
        for day in ("mon", "tue", "wed"):
            self.edit(day, "out", "16:49")
        self.page.evaluate("""async () => {
          window.pywebview = {api: {
            save: async s => { window.savedState = JSON.parse(JSON.stringify(s)); return true; },
            bus_tile: async () => null,
            bus_stop_routes: async () => ({status: 'ok', routes: [
              {no: '100', id: 'R100', first: '06:00', last: '23:00', iv: {wd: 10, sat: 20, sun: 30}, offset: 0, source: 'tago'},
            ]}),
            bus_arrivals: async () => ({status: 'ok', arrivals: [
              {no: '100', id: 'R100', sec: 420, prev: 3}, {no: '100', id: 'R100', sec: 1500, prev: 9},
            ]}),
          }};
          busDefaultKey = true;          // config.json 키가 있는 상태
          state.weeks['2026-10-26'].fri.bus = {route: '100', at: '17:00'};
          document.querySelector('#sideNav .navitem[data-view="bus"]').click();
          await previewBusStop({id: 'tago:31020:N1', nodeId: 'N1', cityCode: '31020', name: '판교역', no: '7073',
                               lat: 37.39, lng: 127.11, routes: [], source: 'tago'});
          saveBusPreview();
        }""")
        # 12:00 기준 7분 후 도착 → 시간표를 06:00 + 10분 배차에서 :07 위상으로(기점→정류장 7분)
        self.page.wait_for_function("busCfg().routes[0].offset === 7")
        self.assertIn("실시간 보정 12:00", self.text("#busSrc"))
        self.assertIn("100 7분 (3정류장 전)", self.text("#busLive"))
        # 실시간으로 보이는 구간(12:07, 12:25)은 실제 예정으로 — 그 사이 시간표상 12:17 버스는 빼고, 이후는 시간표
        self.assertEqual(self.page.evaluate("busArrivalsOn(new Date()).slice(0, 3).map(x => [fmt24(x.at), !!x.live])"),
                         [["12:07", True], ["12:25", True], ["12:37", False]])
        self.assertEqual(self.page.locator("#busToday .busopt").first.locator(".busopt-at").text_content(), "16:27")
        self.assertEqual(self.page.locator("#busToday .busopt.rec .busopt-at").text_content(), "16:57")
        self.assertEqual(self.page.evaluate("state.weeks['2026-10-26'].fri.bus.at"), "16:57")   # 고른 버스도 새 시간표로
        self.page.evaluate("doSave()")
        self.assertEqual(self.page.evaluate("savedState.settings.bus.routes[0].offset"), 7)

    def test_live_tab_lists_only_saved_buses_soonest_first(self):
        self.page.evaluate("""async () => {
          window.pywebview = {api: {
            save: async s => { window.savedState = JSON.parse(JSON.stringify(s)); return true; },
            bus_tile: async () => null,
            bus_stop_routes: async () => ({status: 'ok', routes: [
              {no: '87', id: '241213007', dest: '사기막골', first: '06:00', last: '23:00', iv: {wd: 10}, offset: 0, source: 'gbis'},
              {no: '310', id: '204000163', dest: '판교역', first: '06:00', last: '23:00', iv: {wd: 10}, offset: 0, source: 'gbis'},
              {no: '311', id: '204000192', dest: '판교역', first: '06:00', last: '23:00', iv: {wd: 10}, offset: 0, source: 'gbis'},
            ]}),
            bus_arrivals: async () => ({status: 'ok', arrivals: [
              {no: '310', id: '204000163', sec: 60, prev: 1},
              {no: '311', id: '204000192', sec: 180, prev: 3},
              {no: '311', id: '204000192', sec: 1140, prev: 13},
            ]}),
          }};
          busDefaultKey = true;
          document.querySelector('#sideNav .navitem[data-view="bus"]').click();
          await previewBusStop({id: 'gbis:204000158', stationId: '204000158', name: '텔레칩스', no: '05341',
                                lat: 37.40645, lng: 127.0873667, source: 'gbis'});
          busPreview.take.delete('310');          // 310번은 탈 버스에서 뺀다
          saveBusPreview();
        }""")
        self.page.locator("#busTabLive").click()
        self.assertTrue(self.page.locator("#busLivePane").is_visible())
        self.assertTrue(self.page.locator("#busTodayPane").is_hidden())
        self.assertEqual(self.text("#busLiveTitle"), "텔레칩스 · 05341")
        self.assertIn("기준 · 1분마다 갱신", self.text("#busLiveMeta"))
        rows = self.page.locator("#busLiveList .busliverow")
        # 저장한 탈 버스만(310번 제외) · 곧 오는 순 · 오는 버스가 없는 노선도 남긴다
        self.assertEqual(rows.locator(".busno").all_text_contents(), ["311", "87"])
        self.assertEqual(rows.nth(0).locator(".busliveinfo > span").all_text_contents(),
                         ["3분12:03 · 3정류장 전", "19분12:19 · 13정류장 전"])
        self.assertEqual(self.text("#busLiveList .busliverow.none .busliveinfo"), "도착 정보 없음")
        self.page.locator("#busTabToday").click()
        self.assertTrue(self.page.locator("#busLivePane").is_hidden())

    def test_live_tab_explains_when_stop_has_no_live_arrivals(self):
        self.nav("bus").click()
        self.page.locator("#busTabLive").click()
        self.assertIn("저장된 퇴근 정류장이 없어요", self.text("#busLiveList"))
        self.install_bus_stop()                                       # OSM 정류장: 실시간 미지원
        self.page.locator("#busTabLive").click()
        self.assertIn("실시간 도착을 볼 수 없어요", self.text("#busLiveList"))

    def test_bus_setup_survives_restart_and_uses_deploy_key(self):
        self.page.evaluate("""async () => {
          window.pywebview = {api: {
            save: async s => { localStorage.setItem('worktime', JSON.stringify(s)); return true; },
            bus_tile: async () => null,
            bus_info: async () => ({defaultKey: true}),
            bus_nearby: async (lat, lng, radius, key) => { window.nearbyKey = key; return {status: 'ok', source: 'tago', stops: [
              {id: 'tago:31020:A', nodeId: 'A', cityCode: '31020', name: '판교역북편', no: '7073', lat: 37.396, lng: 127.1114, routes: [], source: 'tago', dist: 50},
              {id: 'tago:31020:B', nodeId: 'B', cityCode: '31020', name: '판교역남편', no: '7478', lat: 37.3939, lng: 127.1108, routes: [], source: 'tago', dist: 90},
            ]}; },
            bus_stop_routes: async () => ({status: 'ok', routes: [
              {no: '100', id: 'R100', first: '06:00', last: '23:00', iv: {wd: 10}, offset: 0, source: 'tago'},
            ]}),
          }};
          await loadBusInfo();
          document.querySelector('#sideNav .navitem[data-view="bus"]').click();
          busMap.setView([37.395, 127.111], 16);
          await scanBusStops();
          await previewBusStop(busStops[0]);
          saveBusPreview();
          await doSave();
        }""")
        self.assertEqual(self.page.locator("#busKeyBtn, #busKey").count(), 0)   # 화면에 키 입력 없음 — config.json 키만 쓴다
        self.assertIsNone(self.page.evaluate("nearbyKey"))                  # 키 값은 화면에 없고 Python 이 채운다

        # 앱을 다시 켠 것처럼 저장본만으로 새 창을 연다(setUp 의 픽스처 주입 없음)
        again = self.context.new_page()
        again.on("pageerror", lambda exc: self.errors.append(str(exc)))
        again.goto((ROOT / "ui/index.html").as_uri())
        again.locator('#rowBus .buscell[data-day="fri"]').wait_for()
        self.assertTrue(again.locator("#rowBus").is_visible())
        again.locator('#sideNav .navitem[data-view="bus"]').click()
        self.assertIn("판교역북편", again.locator("#busStopEdit").text_content())
        again.locator("#busStopEdit").click()
        self.assertEqual(again.locator("#busPrevRoutes .busprevroute").count(), 1)
        self.assertEqual(again.locator("#busMap path.leaflet-interactive").count(), 2)   # 지난번 찾은 주변 정류장
        self.assertEqual(again.evaluate("[busMap.getZoom(), +busMap.getCenter().lat.toFixed(3)]"), [16, 37.395])
        again.close()

    def test_saved_gyeonggi_stop_keeps_station_id_for_live_arrivals(self):
        self.page.evaluate("""async () => {
          window.pywebview = {api: {
            save: async s => { window.savedState = JSON.parse(JSON.stringify(s)); return true; },
            bus_tile: async () => null,
            bus_stop_routes: async () => ({status: 'ok', routes: [
              {no: '310', id: '233000031', first: '06:00', last: '23:00', iv: {wd: 10}, offset: 0, source: 'gbis'},
            ]}),
          }};
          document.querySelector('#sideNav .navitem[data-view="bus"]').click();
          await previewBusStop({id: 'gbis:204000158', stationId: '204000158', name: '텔레칩스', no: '05341',
                                lat: 37.40645, lng: 127.0873667, source: 'gbis'});
          saveBusPreview();
          await doSave();
        }""")
        # 경기도 API 정류장은 stationId 만 있다 — 저장에서 빠지면 실시간 도착이 '미지원'이 된다
        self.assertEqual(self.page.evaluate("savedState.settings.bus.stop.stationId"), "204000158")

    def test_gyeonggi_peak_offpeak_weekend_and_saved_tago_stop_migration(self):
        result = self.page.evaluate("""() => {
          const r = {no: '87', id: '241213007', first: '05:00', last: '22:00', offset: 2, source: 'gbis',
                     iv: {wd: 10, sat: 25, sun: 0}, ivOff: {wd: 25, sat: 35, sun: 0},
                     span: {sat: {first: '05:30', last: '21:00'}, sun: {first: '05:00', last: '22:00'}}};
          const gap = (d, h) => { const ts = busRouteTimes(r, d); const i = ts.findIndex(t => t >= h * 3600); return (ts[i + 1] - ts[i]) / 60; };
          const thu = new Date('2026-10-29T00:00:00'), sat = new Date('2026-10-31T00:00:00'), sun = new Date('2026-11-01T00:00:00');
          return [gap(thu, 18), gap(thu, 14), gap(sat, 18), gap(sat, 14), fmt24(busRouteTimes(r, sat)[0]),
                  fmt24(busRouteTimes(r, thu).at(-1)),
                  busRouteTimes(r, sun).length, busIvText(r, 'wd'), busIvText(r, 'sun'),
                  busLiveMatch({id: 'GGB204000170', no: '3100'}, {id: '204000170', no: '3100'})];
        }""")
        # 퇴근 시간대 10분(출퇴근 배차) · 낮 25분(평시) · 토요일 25/35분, 토요일 첫차 05:30(+2분) · 평일 막차 22:00(+2분) · 일요일 운행 안 함
        self.assertEqual(result, [10, 25, 25, 35, "05:32", "22:02", 0, "배차 10~25분", "", True])

        # TAGO 로 저장해 둔 경기도 정류장은 다시 켤 때 경기도 API 정류장으로 바뀐다(TAGO 필드는 남김)
        self.page.evaluate("""() => localStorage.setItem('worktime', JSON.stringify({settings: {bus: {
          stop: {id: 'tago:31020:GGB204000158', nodeId: 'GGB204000158', cityCode: '31020', name: '텔레칩스', no: '5341',
                 lat: 37.40645, lng: 127.0873667, source: 'tago'}, routes: [], take: []}}, weeks: {}}))""")
        again = self.context.new_page()
        again.on("pageerror", lambda exc: self.errors.append(str(exc)))
        again.goto((ROOT / "ui/index.html").as_uri())
        again.locator('#rowBus .buscell[data-day="fri"]').wait_for(state="attached")
        self.assertEqual(again.evaluate("(({id, source, stationId, nodeId, cityCode}) => [id, source, stationId, nodeId, cityCode])(busCfg().stop)"),
                         ["gbis:204000158", "gbis", "204000158", "GGB204000158", "31020"])
        again.close()

    def test_layout_fits_minimum_window_and_both_themes(self):
        for theme in ("excel", "dark"):
            self.page.evaluate("theme => applyTheme(theme)", theme)
            for width in (900, 720):
                self.page.set_viewport_size({"width": width, "height": 530})
                for view in ("work", "bus", "cal", "meal", "ttree", "approval"):
                    self.page.evaluate("view => setView(view)", view)
                    self.assertTrue(self.nav("work").is_visible())
                    self.assertTrue(self.page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (theme, width, view))

    def test_overtime_form_preview_confirmation_and_history(self):
        self.page.evaluate("""() => {
          window.ttreeCalls = [];
          const line = {id: 'self', name: '자가', details: [{ordNo: 1, userName: '테스트 사용자'}]};
          window.pywebview = {api: {
            ttree_lookups: async () => { ttreeCalls.push('lookups'); return {
              status: 'ok', approvals: [line], leaveClasses: [], overtime: {
                enabled: true, startDate: '2026-10-26', endDate: '2026-11-01', hours: 12,
                canRestart: false, fixedApprovalId: 'self', approvals: [line]
              }
            }; },
            ttree_status: async () => { ttreeCalls.push('status'); return {
              status: 'ok', overtime: [{kind: 'overtime', title: '연장근무 12시간',
                registeredDate: '2026-10-23', statusCode: '900', statusName: '승인', reason: '업무 마무리'}]
            }; },
            ttree_preview_overtime: async draft => { ttreeCalls.push('preview'); return {
              status: 'ok', summary: '이번 주 연장근무 12시간\\n' + draft.startDate + ' ~ ' + draft.endDate + '\\n' + draft.reason
            }; },
            ttree_submit_overtime: async draft => { ttreeCalls.push('submit'); window.sentDraft = draft;
              return {status: 'ok', summary: '이번 주 연장근무 12시간 신청 완료'}; }
          }};
        }""")
        self.nav('ttree').click()
        self.page.wait_for_function("ttreeCalls.length >= 2")
        self.assertEqual(self.page.evaluate('ttreeCalls'), ['lookups', 'status'])
        self.page.locator('#ttreeKind').select_option('overtime')
        self.assertTrue(self.page.locator('#ttreeApproval').is_disabled())
        self.assertEqual(self.page.locator('#ttreeApproval').input_value(), 'self')
        self.assertTrue(self.page.locator('#ttreeOvertimeRestartRow').is_hidden())
        self.assertEqual(self.page.locator('#ttreeOvertimeStart').input_value(), '2026-10-26')
        self.assertIn('신청일 2026-10-23', self.text('#ttreeOvertimeList'))
        self.assertIn('승인', self.text('#ttreeOvertimeList'))
        self.page.locator('#ttreeOvertimeReason').fill('주간 업무 마무리')
        self.page.locator('#ttreePreview').click()
        self.assertIn('결재선: 자가', self.text('#ttreePreviewBox'))
        self.assertNotIn('submit', self.page.evaluate('ttreeCalls'))
        self.page.locator('#ttreeSubmit').click()
        self.assertNotIn('submit', self.page.evaluate('ttreeCalls'))
        self.page.locator('#ttreeConfirm').check()
        self.page.once('dialog', lambda dialog: dialog.dismiss())
        self.page.locator('#ttreeSubmit').click()
        self.assertNotIn('submit', self.page.evaluate('ttreeCalls'))
        for theme in ('excel', 'dark'):
            self.page.evaluate('theme => applyTheme(theme)', theme)
            for width in (900, 720):
                self.page.set_viewport_size({'width': width, 'height': 530})
                self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
                if theme == 'excel' and width == 900:
                    self.page.locator('.ttree-modal-body').evaluate('(el) => el.scrollTop = 0')
                    (ROOT / 'build').mkdir(exist_ok=True)
                    self.page.screenshot(path=str(ROOT / 'build/ui-overtime.png'), full_page=True)
        self.page.once('dialog', lambda dialog: dialog.accept())
        self.page.locator('#ttreeSubmit').click()
        self.assertEqual(self.page.evaluate("ttreeCalls.filter(x => x === 'submit').length"), 1)
        self.assertEqual(self.page.evaluate('sentDraft.reason'), '주간 업무 마무리')
        self.assertFalse(self.page.locator('#ttreeConfirm').is_checked())
        self.page.locator('#ttreeKind').select_option('leave')
        self.assertFalse(self.page.locator('#ttreeApproval').is_disabled())
        self.assertTrue(self.page.locator('#ttreeOvertimeForm').is_hidden())

    def test_approval_base_project_is_resolved_saved_and_sent_with_prefill(self):
        self.page.evaluate("""() => {
          window.apprCalls = [];
          const a = {code: '서-2606-013', name: '[그룹사] 디지털트윈 과제'};
          const b = {code: '로-2601-01', name: '디지털트윈 시뮬레이션 구축'};
          window.pywebview = {api: {
            save: async s => { window.savedSettings = s.settings; },
            approval_project: async kw => { apprCalls.push(['project', kw]); return {status: 'ok', projects: kw === '서-2606-013' ? [a] : [a, b]}; },
            approval_payday: async m => { apprCalls.push(['payday', m]); return {status: 'ok', payday: '2026-11-23', sourceTitle: '11월 지급일정'}; },
            approval_prefill: async p => { apprCalls.push(['prefill', p]); return {status: 'started'}; }
          }};
        }""")
        self.nav('approval').click()
        self.assertEqual(self.text('#apprProjectText'), '—')
        # 키워드가 여러 건에 걸리면 목록에서 고른다.
        self.page.locator('#apprProject').fill('디지털트윈')
        self.page.locator('#apprProjectLookup').click()
        self.page.wait_for_function("apprCalls.length >= 1")
        self.assertTrue(self.page.locator('#apprProjectPickWrap').is_visible())
        self.assertEqual(self.text('#apprProjectText'), '디지털트윈')
        self.page.locator('#apprProjectPick').select_option('로-2601-01')
        self.assertEqual(self.text('#apprProjectText'), '디지털트윈 시뮬레이션 구축')
        self.page.wait_for_function("window.savedSettings && window.savedSettings.approvalProjectCode === '로-2601-01'")
        # 코드 완전일치는 바로 확정되고 목록은 숨긴다.
        self.page.locator('#apprProject').fill('서-2606-013')
        self.assertEqual(self.text('#apprProjectText'), '서-2606-013')
        self.page.locator('#apprProjectLookup').click()
        self.page.wait_for_function("apprCalls.length >= 2")
        self.assertTrue(self.page.locator('#apprProjectPickWrap').is_hidden())
        self.assertEqual(self.text('#apprProjectText'), '[그룹사] 디지털트윈 과제')
        self.assertEqual(self.text('#apprProjectSrc'), '(서-2606-013)')
        # 폼 열기 payload 에 확정한 프로젝트가 실린다.
        self.page.locator('#apprName').fill('김다영')
        self.page.locator('#apprOpen').click()
        self.page.wait_for_function("apprCalls.some(c => c[0] === 'prefill')")
        sent = self.page.evaluate("apprCalls.find(c => c[0] === 'prefill')[1]")
        self.assertEqual(sent['payee'], '김다영')
        self.assertEqual(sent['payday'], '2026-11-23')
        self.assertEqual(sent['project'], {'code': '서-2606-013', 'name': '[그룹사] 디지털트윈 과제', 'keyword': '서-2606-013'})


if __name__ == "__main__":
    unittest.main()
