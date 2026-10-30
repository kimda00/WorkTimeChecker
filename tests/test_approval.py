# -*- coding: utf-8 -*-
"""approval.py 의 네트워크 없는 순수 함수 검사: .venv\Scripts\python -m unittest tests.test_approval -v"""
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


if __name__ == "__main__":
    unittest.main()
