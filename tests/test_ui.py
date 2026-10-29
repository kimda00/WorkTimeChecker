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

    def test_navigation_has_stable_labels_and_a_dedicated_work_button(self):
        for button, panel, label in (("calBtn", "calPanel", "캘린더"), ("mealBtn", "mealPanel", "식단"), ("ttreeBtn", "ttreePanel", "TTree"), ("approvalBtn", "approvalPanel", "결재")):
            for _ in range(2):
                self.page.locator("#" + button).click()
                self.assertTrue(self.page.locator("#" + panel).is_visible())
                self.assertEqual(self.text("#" + button), label)
                self.assertEqual(self.page.locator("#" + button).get_attribute("aria-current"), "page")
                self.assertEqual(self.page.locator('.viewbtn[aria-current="page"]').count(), 1)
            self.page.locator("#workBtn").click()
            self.assertTrue(self.page.locator("#grid").is_visible())
            self.assertFalse(self.page.locator("#" + panel).is_visible())

    def test_layout_fits_minimum_window_and_both_themes(self):
        for theme in ("excel", "dark"):
            self.page.evaluate("theme => applyTheme(theme)", theme)
            for width in (900, 720):
                self.page.set_viewport_size({"width": width, "height": 530})
                for view in ("work", "cal", "meal", "ttree", "approval"):
                    self.page.evaluate("view => setView(view)", view)
                    self.assertTrue(self.page.locator("#workBtn").is_visible())
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
        self.page.locator('#ttreeBtn').click()
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


if __name__ == "__main__":
    unittest.main()
