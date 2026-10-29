import datetime
import unittest
from unittest.mock import patch, Mock

import ttree


class OvertimeTests(unittest.TestCase):
    def setUp(self):
        today = patch.object(ttree, '_today', return_value=datetime.date(2026, 10, 29))
        today.start()
        self.addCleanup(today.stop)
        self.draft = dict(startDate='2026-10-26', endDate='2026-11-01', reason='주간 업무', sanctnId='self')
        self.policy = dict(startDate='2026-10-26', endDate='2026-11-01', enabled=True,
                           workTimeId='fresh-work', approvals=[{'id': 'self', 'name': '자가'}],
                           fixedApprovalId='self', canRestart=False)

    def response(self, data, status=201):
        return Mock(ok=status < 400, status=status, json=Mock(return_value=data))

    def test_week_boundaries_and_fixed_hours(self):
        self.assertEqual(ttree._overtime_week(datetime.date(2026, 11, 1)), ('2026-10-26', '2026-11-01'))
        self.assertEqual(ttree._overtime_week(datetime.date(2027, 1, 1)), ('2026-12-28', '2027-01-03'))
        payload = ttree.build_overtime_payload(dict(self.draft, hours=99, workTimeId='untrusted'), self.policy)
        self.assertEqual(payload['workExtnTime'], '12.000')
        self.assertEqual(payload['workTimeId'], 'fresh-work')
        self.assertNotIn('workRestartYn', payload)

    def test_validation_and_preview_have_no_network(self):
        with patch.object(ttree, '_session_context') as session, patch.object(ttree, '_post_json') as post:
            self.assertEqual(ttree.preview_overtime(self.draft)['status'], 'ok')
            for changes in ({'reason': ' '}, {'sanctnId': ''}, {'endDate': '2026-11-08'}, {'startDate': ''}):
                self.assertEqual(ttree.submit_overtime(dict(self.draft, **changes))['status'], 'error')
            session.assert_not_called()
            post.assert_not_called()
        for changes in ({'sanctnId': 'someone-else'}, {'restartWork': True}):
            with self.assertRaises(ValueError):
                ttree.build_overtime_payload(dict(self.draft, **changes), self.policy)

    def test_response_empty_and_malformed_are_different(self):
        with patch.object(ttree, '_get', return_value=self.response({}, 204)):
            self.assertEqual(ttree._overtime_rows(None, 'a', 'b'), [])
        with patch.object(ttree, '_get', return_value=self.response({'text': '<html>login</html>'})):
            with self.assertRaises(ValueError):
                ttree._overtime_rows(None, 'a', 'b')

    def submit(self, rows=None, usage=None, response=None, failure=None):
        usage = usage or {'weeklyWorkPrdtmMnt': 2400, 'totalRealWorkMnt': 2500, 'weeklyExtnWorkPrdtmMnt': 720}
        with patch.object(ttree, '_session_context', return_value=(None, None, None, {'userId': 'me'}, None)), \
             patch.object(ttree, '_overtime_context', return_value=self.policy), \
             patch.object(ttree, '_overtime_rows', return_value=rows or []), \
             patch.object(ttree, '_get', return_value=self.response(usage)), \
             patch.object(ttree, '_post_json', return_value=response or self.response({'resultMsg': '성공'}), side_effect=failure) as post, \
             patch.object(ttree, '_close') as close:
            result = ttree.submit_overtime(self.draft)
            close.assert_called_once()
            return result, post

    def test_submit_posts_once_with_current_context(self):
        result, post = self.submit()
        self.assertEqual(result['status'], 'ok')
        post.assert_called_once()
        self.assertEqual(post.call_args.args[1], '/work/workextn')
        self.assertEqual(post.call_args.args[2]['workTimeId'], 'fresh-work')
        self.assertEqual(post.call_args.args[2]['workExtnTime'], '12.000')

    def test_duplicate_blocks_waiting_approved_and_unknown(self):
        for code in ('000', '900', 'unexpected'):
            result, post = self.submit(rows=[{'workExtnConfmCd': code}])
            self.assertEqual(result['status'], 'duplicate')
            post.assert_not_called()
        for code in ('800', '999'):
            result, post = self.submit(rows=[{'workExtnConfmCd': code}])
            self.assertEqual(result['status'], 'ok')
            post.assert_called_once()

    def test_usage_limit_and_invalid_usage_block_submission(self):
        for usage in ({'bad': 1}, {'weeklyWorkPrdtmMnt': 2400, 'totalRealWorkMnt': 3121, 'weeklyExtnWorkPrdtmMnt': 720}):
            result, post = self.submit(usage=usage)
            self.assertEqual(result['status'], 'error')
            post.assert_not_called()

    def test_rejection_and_uncertain_result_are_not_success_or_retried(self):
        for response in (self.response({'resultMsg': '신청 불가'}, 400), self.response({'text': 'login'})):
            result, post = self.submit(response=response)
            self.assertEqual(result['status'], 'error')
            post.assert_called_once()
        result, post = self.submit(failure=TimeoutError('timeout'))
        self.assertIn('현황', result['message'])
        post.assert_called_once()

    def test_history_uses_registration_date_not_invented_work_period(self):
        row = ttree._normalize_overtime({'workExtnTime': '12.000', 'regDt': '20261023122932', 'workExtnConfmCd': '900'})
        self.assertEqual(row['title'], '연장근무 12시간')
        self.assertEqual(row['registeredDate'], '2026-10-23')
        self.assertEqual(row['statusName'], '승인')
        self.assertNotIn('startDate', row)

    def test_policy_parses_official_fixed_approval_and_blocks_changed_form(self):
        source = '''var _sessUserId = "me"; var _workExtnBtnYn = "Y";
        var _workStCd = "000"; var _workTimeId = "work";
        <form id="frmWorkExtn"><option value="12.000">12시간</option></form>
        window.approvalLine['approvalLine_extnMySanctnInfoList'].fixApprovalLine = function() {
        const fixApprovalLineName = ('자가' === 'null') ? outerFixApprovalLineName : '자가'; }
        '''
        with patch.object(ttree, '_get', return_value=Mock(ok=True, text=lambda: source)), \
             patch.object(ttree, '_approval_lines', return_value=self.policy['approvals']):
            policy = ttree._overtime_context(None, {'userId': 'me'})
            self.assertEqual(policy['fixedApprovalId'], 'self')
            self.assertFalse(policy['canRestart'])
            source = source.replace('12.000', '6.000')
            with self.assertRaises(ValueError):
                ttree._overtime_context(None, {'userId': 'me'})


if __name__ == '__main__':
    unittest.main()
