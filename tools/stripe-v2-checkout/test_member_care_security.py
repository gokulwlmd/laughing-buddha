"""Independent care isolation regressions using offline Sticky fixtures only."""
from copy import deepcopy
import json
import unittest

from fastapi.testclient import TestClient
import test_member_portal as fixtures
import test_member_care as care_fixtures


class MemberCareSecurityTests(unittest.TestCase):
    tearDown = fixtures.MemberPortalTests.tearDown
    post_owner = fixtures.MemberPortalTests.post_owner
    enroll = fixtures.MemberPortalTests.enroll
    journey = care_fixtures.MemberCareTests.journey
    simulate = care_fixtures.MemberCareTests.simulate
    complete = care_fixtures.MemberCareTests.complete
    refill = care_fixtures.MemberCareTests.refill

    def setUp(self):
        fixtures.MemberPortalTests.setUp(self)
        self.sku = care_fixtures.configure_care_fixture(self.app, self.fake)
        self.enroll()
        self.care_path = self.base + '/orders/9001/care-plan'

    def assert_read_only_provider(self):
        self.assertTrue(all(method == 'GET' or path == '/api/v1/order_view' for method, path, _ in self.fake.calls))

    def test_care_reads_and_clock_require_correct_patient_site_or_owner(self):
        with TestClient(self.app, base_url=fixtures.ORIGIN) as outsider:
            self.assertEqual(outsider.get(self.care_path).status_code, 401)
            self.assertEqual(outsider.get(self.care_path, headers={'Authorization': 'Bearer invalid'}).status_code, 401)
            self.assertEqual(outsider.get(self.care_path.replace('site-a', 'site-b'), headers=self.patient_headers).status_code, 401)
            self.assertEqual(outsider.get(self.care_path.replace('/9001/', '/9002/'), headers=self.patient_headers).status_code, 404)
            self.assertEqual(outsider.post(self.owner + '/orders/9001/care-clock', headers=self.patient_headers,
                json={'day_offset': 90}).status_code, 401)
        self.assertEqual(self.client.post(self.owner + '/orders/9001/care-clock',
            headers=self.owner_headers | {'Origin': 'https://foreign.invalid'}, json={'day_offset': 90}).status_code, 403)
        self.assertEqual(self.post_owner('/orders/9001/care-clock', {'day_offset': 90, 'force_bill': True}).status_code, 422)
        self.assert_read_only_provider()

    def test_clock_requires_all_dry_run_guards_and_cannot_change_real_time(self):
        original = deepcopy(self.fake.order)
        for changes, product in [({'is_test_cc': '0'}, {}), ({'gateway_id': '254'}, {}), ({}, {'is_shippable': '1'}),
                                  ({'is_test_cc': '0', 'gateway_id': '254'}, {'is_shippable': '1'})]:
            with self.subTest(changes=changes, product=product):
                self.fake.order = deepcopy(original)
                self.fake.order.update(changes)
                self.fake.order['products'][0].update(product)
                response = self.post_owner('/orders/9001/care-clock', {'day_offset': 90})
                self.assertEqual(response.status_code, 409, response.text)
                self.assertEqual(self.service.clock(), fixtures.NOW)
        self.fake.order = original
        plan = self.simulate(90)
        self.assertTrue(plan['simulation']['enabled'])
        self.assertEqual(self.service.clock(), fixtures.NOW)
        restored = self.simulate(None)
        self.assertFalse(restored['simulation']['enabled'])
        self.assertFalse(restored['tasks'][1]['can_submit'])
        self.assertEqual(self.post_owner('/orders/9001/care-clock', {'day_offset': 361}).status_code, 422)
        self.assert_read_only_provider()

    def test_simulated_order_does_not_unlock_a_separate_normal_paid_term(self):
        self.journey()
        with self.service.db() as db:
            row = dict(db.execute("SELECT * FROM member_orders WHERE order_id='9001'").fetchone())
            grant = dict(db.execute("SELECT * FROM member_grants WHERE order_id='9001'").fetchone())
            snapshot, payload = json.loads(row['snapshot']), json.loads(row['payload'])
            snapshot.update(root_order_id='9002', term_order_id='9002', payment_test_only=False)
            payload.update(id='9002', gateway_id='254', test_order=False)
            payload['products'][0].update(subscription_id='separate-live-subscription', is_shippable=True)
            db.execute('INSERT INTO member_orders VALUES(?,?,?,?,?,?,?,?,?)', (row['site_id'], '9002', row['customer_id'], '', row['therapy_id'], row['sku'], json.dumps(snapshot), json.dumps(payload), row['synced']))
            db.execute('INSERT INTO member_grants VALUES(?,?,?,?,?)', (grant['site_id'], '9002', grant['patient_id'], grant['created'], 'offline-fixture'))
        self.simulate(180)
        other = self.client.get(self.care_path.replace('/9001/', '/9002/'), headers=self.patient_headers)
        self.assertEqual(other.status_code, 200, other.text)
        self.assertFalse(other.json()['simulation']['available'])
        self.assertFalse(other.json()['simulation']['enabled'])
        self.assertEqual([t['can_submit'] for t in other.json()['tasks']], [True, False, False, False])
        self.assert_read_only_provider()

    def test_initial_submission_and_each_checkpoint_are_independent_and_request_ids_cannot_collide(self):
        self.simulate(90)
        self.complete('checkin-90')
        self.assertEqual(self.refill('checkin-90', 'care-security-request').status_code, 409)
        self.complete('initial')
        first = self.refill('checkin-90', 'care-security-request')
        self.assertEqual(first.status_code, 200, first.text)
        self.assertFalse(first.json()['request']['clinical_approval'])
        self.assertFalse(first.json()['request']['fulfillment_created'])
        self.simulate(180)
        self.assertEqual(self.refill('checkin-180', 'care-security-request').status_code, 409)
        self.assertEqual(self.refill('checkin-180', 'care-security-request-new').status_code, 409)
        self.complete('checkin-180')
        self.assertEqual(self.refill('checkin-90', 'old-task-replay-key').status_code, 409)
        second = self.refill('checkin-180', 'care-security-request-new')
        self.assertEqual(second.status_code, 200, second.text)
        self.assertNotEqual(first.json()['request']['id'], second.json()['request']['id'])
        self.assert_read_only_provider()

    def test_live_disable_switches_override_saved_policy_without_rewriting_answers(self):
        self.simulate(90)
        self.complete('initial')
        submitted = self.complete('checkin-90')
        saved_policy = self.app.state.admin.get('refill_policy', self.sku)
        for override in [{'enabled': False}, {'test_requests_enabled': False}]:
            with self.subTest(override=override):
                self.app.state.admin.put('refill_policy', self.sku, saved_policy | override)
                self.assertEqual(self.refill('checkin-90').status_code, 409)
                current = self.client.get(self.base + '/orders/9001/care-tasks/checkin-90/intake', headers=self.patient_headers)
                self.assertEqual(current.json()['answers'], submitted['answers'])
                self.assertEqual(current.json()['status'], 'submitted')
        self.assert_read_only_provider()

    def test_simulated_answers_cannot_satisfy_a_live_refill_after_gateway_changes(self):
        self.simulate(90)
        self.complete('initial')
        submitted = self.complete('checkin-90')
        self.assertTrue(submitted['simulated'])
        self.fake.order.update(gateway_id='254', is_test_cc='0')
        self.fake.order['products'][0]['is_shippable'] = '1'
        response = self.post_owner('/orders/9001/care-clock', {'day_offset': None})
        self.assertEqual(response.status_code, 200, response.text)
        request = self.refill('checkin-90')
        self.assertEqual(request.status_code, 409)
        self.assertIn('Simulated check-ins', request.text)
        self.assert_read_only_provider()

    def test_skipped_required_checkin_cannot_be_bypassed_and_term_end_blocks_new_requests(self):
        self.simulate(180)
        self.complete('initial')
        self.complete('checkin-180')
        skipped = self.refill('checkin-180')
        self.assertEqual(skipped.status_code, 409)
        self.assertIn('earlier required', skipped.text)
        self.complete('checkin-90')
        self.assertEqual(self.refill('checkin-180').status_code, 200)
        self.simulate(360)
        self.assertEqual(self.refill('checkin-270', 'after-term-request').status_code, 409)
        self.assertEqual(self.client.get(self.base + '/orders/9001/care-tasks/checkin-270/intake', headers=self.patient_headers).status_code, 409)
        self.assert_read_only_provider()

    def test_earlier_simulated_checkin_cannot_qualify_a_later_live_request(self):
        initial = self.complete('initial')
        self.assertFalse(initial['simulated'])
        self.simulate(90)
        self.assertTrue(self.complete('checkin-90')['simulated'])
        self.fake.order.update(gateway_id='254', is_test_cc='0')
        self.fake.order['products'][0]['is_shippable'] = '1'
        self.assertEqual(self.post_owner('/orders/9001/care-clock', {'day_offset': None}).status_code, 200)
        self.service.clock = lambda: fixtures.NOW + 180 * 86400
        auth = self.client.post(self.base + '/auth/login', json={
            'email': 'sample@example.invalid', 'password': fixtures.PATIENT_PASSWORD})
        self.assertEqual(auth.status_code, 200, auth.text)
        self.patient_headers = {'Authorization': 'Bearer ' + auth.json()['access_token'], 'Origin': fixtures.ORIGIN}
        current = self.complete('checkin-180')
        self.assertFalse(current['simulated'])
        response = self.refill('checkin-180', 'prior-simulated-checkpoint')
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn('Simulated check-ins', response.text)
        self.assert_read_only_provider()

    def test_early_request_opens_only_current_form_and_still_needs_reason_and_review(self):
        policy = self.app.state.admin.get('refill_policy', self.sku)
        policy.update(allow_early_requests=True, early_request_minimum_days=30)
        self.app.state.admin.put('refill_policy', self.sku, policy)
        self.complete('initial')
        self.assertFalse(self.simulate(29)['tasks'][1]['can_open'])
        tasks = self.simulate(30)['tasks']
        self.assertTrue(tasks[1]['can_open'])
        self.assertFalse(tasks[2]['can_open'])
        self.complete('checkin-90')
        self.assertEqual(self.refill('checkin-90', 'too-early-scheduled').status_code, 409)
        body = {'order_id': '9001', 'sku': self.sku, 'task_id': 'checkin-90', 'kind': 'early', 'client_request_id': 'early-security-request'}
        response = self.client.post(self.base + '/refills', headers=self.patient_headers, json=body)
        self.assertEqual(response.status_code, 422)
        response = self.client.post(self.base + '/refills', headers=self.patient_headers, json=body | {'reason': 'Offline example reason'})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['request']['status'], 'awaiting_review')
        self.assertFalse(response.json()['request']['clinical_approval'])
        self.assertFalse(response.json()['request']['fulfillment_created'])
        self.app.state.admin.put('refill_policy', self.sku, policy | {'allow_early_requests': False})
        response = self.client.post(self.base + '/refills', headers=self.patient_headers,
            json=body | {'client_request_id': 'early-disabled-request', 'reason': 'Offline example reason'})
        self.assertEqual(response.status_code, 409)
        self.assert_read_only_provider()

    def test_declined_simulated_request_cannot_bypass_early_cooldown_at_same_clock(self):
        policy = self.app.state.admin.get('refill_policy', self.sku)
        policy.update(allow_early_requests=True, early_request_minimum_days=30, early_request_cooldown_days=7)
        self.app.state.admin.put('refill_policy', self.sku, policy)
        self.simulate(30)
        self.complete('initial')
        self.complete('checkin-90')
        body = {'order_id': '9001', 'sku': self.sku, 'task_id': 'checkin-90', 'kind': 'early',
                'client_request_id': 'early-cooldown-first', 'reason': 'Offline example reason'}
        first = self.client.post(self.base + '/refills', headers=self.patient_headers, json=body)
        self.assertEqual(first.status_code, 200, first.text)
        record = first.json()['request']
        reviewed = self.client.patch(self.owner + '/refills/' + record['id'], headers=self.owner_headers,
            json={'revision': record['revision'], 'status': 'declined', 'note': 'Offline review'})
        self.assertEqual(reviewed.status_code, 200, reviewed.text)
        again = self.client.post(self.base + '/refills', headers=self.patient_headers,
            json=body | {'client_request_id': 'early-cooldown-second'})
        self.assertEqual(again.status_code, 409, again.text)
        self.assert_read_only_provider()


if __name__ == '__main__':
    unittest.main()
