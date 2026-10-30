# -*- coding: utf-8 -*-
r"""approval.py 검사(네트워크 없음): .venv\Scripts\python -m unittest tests.test_approval -v"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import approval  # noqa: E402


class TripHelpers(unittest.TestCase):
    def test_trip_title_is_yy_mm_dd_and_destination(self):
        self.assertEqual(approval.compose_trip_title("2026-10-28", "2026-10-28", "대전 한수원"), "26/10/28 대전 한수원")
        self.assertEqual(approval.compose_trip_title("2026-10-15", "2026-10-16", "경주 한수원 본사"), "26/10/15~16 경주 한수원 본사")
        self.assertEqual(approval.compose_trip_title("2026-10-31", "2026-11-02", "부산"), "26/10/31~11/02 부산")
        self.assertEqual(approval.compose_trip_title("2026-10-28", "", " 대전 "), "26/10/28 대전")
        self.assertEqual(approval.compose_trip_title("", "", "대전"), "대전")

    def test_trip_rows_follow_previous_documents(self):
        rows = approval.trip_rows({"start": "2026-10-28", "km": "278", "toll": "7,500", "lodging": ""})
        self.assertEqual([(r["kind"], r["acct"], r["amount"], r["date"], r["detail"]) for r in rows], [
            ("fuel", "6377", 69500, "2026-10-28", "왕복 278km(자차 이용)"),
            ("toll", "6379", 7500, "2026-10-28", "왕복 하이패스 비용"),
        ])
        rows = approval.trip_rows({"start": "2026-11-03", "km": 100, "rate": 300, "lodging": 80000})
        self.assertEqual([(r["kind"], r["amount"]) for r in rows], [("fuel", 30000), ("lodging", 80000)])
        self.assertEqual(approval.trip_rows({"start": "2026-11-03"}), [])
        self.assertEqual(approval.trip_rows({"start": "2026-11-03", "km": "abc", "toll": -5}), [])

    def test_trip_url_swaps_form_id_only(self):
        orig = approval._config
        try:
            approval._config = lambda key, default=None: {"approvalUrl": "https://gw.example.com/app/approval/document/new/381/3101"}.get(key, default)
            self.assertEqual(approval._trip_url(), "https://gw.example.com/app/approval/document/new/381/3279")
            approval._config = lambda key, default=None: {"approvalUrl": "https://gw.example.com/app/approval/document/new/381/3101",
                                                          "tripApprovalUrl": "https://gw.example.com/app/approval/document/new/381/9999"}.get(key, default)
            self.assertEqual(approval._trip_url(), "https://gw.example.com/app/approval/document/new/381/9999")
        finally:
            approval._config = orig

    def test_prefill_dispatches_trip_form(self):
        seen = []
        orig = approval.prefill_trip
        try:
            approval.prefill_trip = lambda p: seen.append(p) or {"status": "ok"}
            self.assertEqual(approval.prefill({"form": "trip", "start": "2026-10-28"}), {"status": "ok"})
            self.assertEqual(seen, [{"form": "trip", "start": "2026-10-28"}])
        finally:
            approval.prefill_trip = orig


class MealRowsJs(unittest.TestCase):
    """_MEAL_ROWS_JS 를 전표와 같은 구조의 작은 HTML 에서 실행: 적요 data-*, 승인시간별 상세, 상한, 재처리 방지."""
    ROW = ("<tr class='debitTr corp_card_row'><td class='debitRmk'><input value='{rmk}'></td>"
           "<td class='taxInvestigationDivision'><select><option>법인카드(과세)</option><option>법인카드(비과세)</option></select></td>"
           "<td class='apprTime'><input value='{time}'></td></tr>"
           "<tr class='debitTr2'><td class='valueOfSupply'><input value='{sup}'></td><td class='valueOfVAT'><input value='{vat}'></td>"
           "<td class='valueOfTot'>{tot}</td></tr>"
           "<tr class='debitTr3'><td class='summary'><input value='{detail}'></td></tr>")

    def run_js(self, rows, cap):
        from playwright.sync_api import sync_playwright
        html = "<table id='slipBplTable'><tbody>" + "".join(self.ROW.format(**r) for r in rows) + "</tbody></table>"
        acct = {"id": 10, "rmkNo": "6075", "rmk": "(용역) 법카 - 출장외근비(식대)", "crAcctCode": "6120003", "crAcctName": "여비-출장외근비",
                "drAcctCode": "2530002", "drAcctName": "미지급금-직원경비", "vatAcctCode": "1350000", "vatAcctName": "부가세대급금", "vatAcctCrdr": "1"}
        with sync_playwright() as p:
            b = p.chromium.launch(channel="msedge", headless=True)
            page = b.new_page()
            page.set_content(html)
            page.evaluate("""() => { window.supChanges = []; document.querySelectorAll('.valueOfSupply input').forEach((el, i) =>
                el.addEventListener('change', () => supChanges.push([i, el.value]))); }""")
            first = page.evaluate(approval._MEAL_ROWS_JS, {"acct": acct, "cap": cap})
            second = page.evaluate(approval._MEAL_ROWS_JS, {"acct": acct, "cap": cap})
            dump = page.evaluate("""() => Array.from(document.querySelectorAll('tr.debitTr')).map(tr => ({
                rmk: tr.querySelector('.debitRmk input').value, code: tr.querySelector('.debitRmk').getAttribute('data-code'),
                cr: tr.querySelector('.debitRmk').getAttribute('data-cr_acct'), meal: tr.getAttribute('data-wt-meal'),
                detail: tr.nextElementSibling.nextElementSibling.querySelector('.summary input').value }))""")
            changes = page.evaluate("supChanges")
            b.close()
        return first, second, dump, changes

    def test_labels_by_approval_time_caps_and_skips_done_rows(self):
        base = dict(rmk="", sup="9,463", vat="537", tot="10,000", detail="")
        rows = [dict(base, time="09:21:33"), dict(base, time="10:29:59"), dict(base, time="10:30:00"), dict(base, time="15:29:00"),
                dict(base, time="15:30:00"), dict(base, time="17:31:49"), dict(base, time=""),
                dict(base, time="12:00:00", sup="11,272", vat="1,128", tot="12,400"),
                dict(base, time="12:00:00", rmk="6071 / 직접 고른 적요", detail="직접 쓴 상세")]
        first, second, dump, changes = self.run_js(rows, 12000)
        self.assertEqual(first, {"rows": 9, "capped": 1})
        self.assertEqual(second, {"rows": 0, "capped": 0})
        self.assertEqual([d["detail"] for d in dump], [
            "출장외근비 - 아침식대", "출장외근비 - 아침식대", "출장외근비 - 점심식대", "출장외근비 - 점심식대",
            "출장외근비 - 저녁식대", "출장외근비 - 저녁식대", "출장외근비 - 식대", "출장외근비 - 점심식대", "직접 쓴 상세"])
        self.assertEqual(dump[0]["rmk"], "6075 / (용역) 법카 - 출장외근비(식대)")
        self.assertEqual((dump[0]["code"], dump[0]["cr"]), ("6075", "6120003"))
        self.assertEqual(dump[8]["rmk"], "6071 / 직접 고른 적요")   # 이미 고른 적요는 그대로
        self.assertTrue(all(d["meal"] == "1" for d in dump))
        self.assertEqual(changes, [[7, "12,000"]])   # 12,400 행만 공급가액을 상한으로 바꾸고 change

    def test_zero_cap_means_no_limit(self):
        rows = [dict(rmk="", sup="20,000", vat="2,000", tot="22,000", detail="", time="12:00:00")]
        first, _, _, changes = self.run_js(rows, 0)
        self.assertEqual(first, {"rows": 1, "capped": 0})
        self.assertEqual(changes, [])


if __name__ == "__main__":
    unittest.main()
