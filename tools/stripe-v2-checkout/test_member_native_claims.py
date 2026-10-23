"""HTTP claims through the actual manager/provider with offline Sticky only."""
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import test_member_care as care
import test_member_portal as portal


class NativeClaimTests(care.MemberCareTests):
    def setUp(self):
        portal.MemberPortalTests.setUp(self)
        self.fake = care.configure_native_care_fixture(self.app)
        self.sku = 'SEMA-12M-SUB'
        self.enroll()
        self.care_path = self.base + '/orders/9001/care-plan'

    def claim(self, day=90, key=None, order='9001', headers=None):
        return self.client.post(self.base + '/orders/' + order + '/care-tasks/checkin-' + str(day) + '/claim',
            headers=headers or self.patient_headers, json={'client_request_id': key or 'claim-cycle-' + str(day)})

    def forces(self):
        return [b for _, p, b in self.fake.calls if p.endswith('/order_force_bill')]

    def test_claim_first_journey_creates_three_zero_native_orders_and_stops_before_renewal(self):
        self.simulate(80)
        self.assertEqual(self.claim().status_code, 409)
        self.complete('initial')
        self.simulate(79)
        self.assertEqual(self.claim().status_code, 409)
        self.assertEqual(self.forces(), [])
        for index, day, following in [(2, 90, '2027-04-20'), (3, 180, '2027-07-19'), (4, 270, '2027-10-17')]:
            self.simulate(day - 10)
            path = self.base + '/orders/9001/care-tasks/checkin-' + str(day) + '/intake'
            self.assertEqual(self.client.get(path, headers=self.patient_headers).status_code, 409)
            result = self.claim(day)
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(result.json()['claim']['status'], 'claimed')
            child = str(9000 + index)
            self.assertEqual(result.json()['claim']['order_id'], child)
            self.assertEqual(self.fake.orders[child]['order_total'], '0.00')
            self.assertEqual(self.fake.orders[child]['products'][0]['recurring_date'], following)
            again = self.claim(day, key='another-key-' + str(day), order=child)
            self.assertEqual(again.status_code, 200, again.text)
            self.assertEqual(len(self.forces()), index - 1)
            intake = self.client.get(path, headers=self.patient_headers).json()
            self.assertEqual(intake['answers'], {})
            self.assertEqual(intake['claim_order_id'], child)
            if index < 4:
                self.simulate(day + 80)
                self.assertEqual(self.claim(day + 90).status_code, 409)
                self.simulate(day - 10)
            self.complete('checkin-' + str(day))
        self.simulate(360)
        self.assertEqual(self.claim(360).status_code, 404)
        self.assertEqual(len(self.forces()), 3)
        orders = self.client.get(self.base + '/orders', headers=self.patient_headers).json()['orders']
        self.assertEqual({r['id'] for r in orders}, {'9001', '9002', '9003', '9004'})
        self.assertEqual({r['care_plan']['term_order_id'] for r in orders}, {'9001'})
        self.assertFalse(any(p.endswith('/new_order') or p.endswith('/authorize_payment') for _, p, _ in self.fake.calls))

    def test_uncertain_write_is_never_retried_and_read_reconciliation_can_adopt_verified_child(self):
        self.complete('initial'); self.simulate(80)
        self.fake.failure = 'force_timeout'
        self.assertEqual(self.claim().status_code, 409)
        self.fake.failure = None
        self.assertEqual(self.claim(key='new-request-after-timeout').status_code, 409)
        self.assertEqual(len(self.forces()), 1)
        self.assertEqual(self.journey()['tasks'][1]['claim']['status'], 'uncertain')
        # Provider reconciliation is read-only: it cannot correct an unverified
        # schedule write. An independently reconciled native date can be read.
        self.fake.orders['9002']['products'][0]['recurring_date'] = '2027-04-20'
        result = self.claim()
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()['claim']['order_id'], '9002')
        self.assertEqual(len(self.forces()), 1)

    def test_scope_request_identity_and_current_policy_are_enforced(self):
        self.complete('initial'); self.simulate(80)
        url = '/api/v1/sites/site-b/portal/orders/9001/care-tasks/checkin-90/claim'
        self.assertEqual(self.client.post(url, headers=self.patient_headers, json={'client_request_id': 'cross-site-claim'}).status_code, 401)
        self.assertEqual(self.claim(order='9999').status_code, 404)
        rule = self.app.state.admin.get('refill_policy', self.sku)
        rule['enabled'] = False; self.app.state.admin.put('refill_policy', self.sku, rule)
        self.assertEqual(self.claim().status_code, 409)
        self.assertEqual(self.forces(), [])
        rule['enabled'] = True; self.app.state.admin.put('refill_policy', self.sku, rule)
        self.assertEqual(self.claim().status_code, 200)
        self.complete('checkin-90'); self.simulate(170)
        self.assertEqual(self.claim(180, key='claim-cycle-90').status_code, 409)
        self.assertEqual(len(self.forces()), 1)

    def test_two_concurrent_requests_reserve_only_one_native_cycle(self):
        self.complete('initial'); self.simulate(80)
        barrier = Barrier(2)
        original = self.service.provider.included_cycle_capability
        def simultaneous(*args, **kwargs):
            result = original(*args, **kwargs)
            barrier.wait(timeout=10)
            return result
        self.service.provider.included_cycle_capability = simultaneous
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda n: self.claim(key='concurrent-' + str(n)), [1, 2]))
        self.assertEqual(sorted(r.status_code for r in results), [200, 409], [r.text for r in results])
        self.assertEqual(len(self.forces()), 1)

    def test_stripe_payment_test_snapshot_obeys_test_request_switch(self):
        self.complete('initial')
        # A payment-test checkout may use a real Stripe card, so Sticky's test
        # flag alone is insufficient to decide whether test requests are on.
        self.fake.order.update(is_test_cc='0', gateway_id='254')
        self.fake.gateway.update(id=254, account_id=250, account_name='Stripe Connect v2')
        self.service.clock = lambda: portal.NOW + 80 * 86400
        auth = self.client.post(self.base + '/auth/login', json={
            'email': 'sample@example.invalid', 'password': portal.PATIENT_PASSWORD})
        self.assertEqual(auth.status_code, 200, auth.text)
        self.patient_headers = {'Authorization': 'Bearer ' + auth.json()['access_token'], 'Origin': portal.ORIGIN}
        self.service.sync('site-a', '9001')
        self.assertTrue(self.journey()['tasks'][1]['claim']['available'])
        rule = self.app.state.admin.get('refill_policy', self.sku)
        self.app.state.admin.put('refill_policy', self.sku, rule | {'test_requests_enabled': False})
        result = self.claim()
        self.assertEqual(result.status_code, 409, result.text)
        self.assertIn('not enabled for this test order', result.text)
        self.assertEqual(self.forces(), [])

    def test_policy_disabled_during_provider_preflight_does_not_reserve_or_force(self):
        self.complete('initial'); self.simulate(80)
        original = self.service.provider.included_cycle_capability
        rule = self.app.state.admin.get('refill_policy', self.sku)
        def disable_after_preflight(*args, **kwargs):
            proof = original(*args, **kwargs)
            self.app.state.admin.put('refill_policy', self.sku, rule | {'enabled': False})
            return proof
        self.service.provider.included_cycle_capability = disable_after_preflight
        result = self.claim()
        self.assertEqual(result.status_code, 409, result.text)
        self.assertIn('currently unavailable', result.text)
        self.assertEqual(self.forces(), [])
        with self.service.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM member_refill_claims').fetchone()[0], 0)
        self.app.state.admin.put('refill_policy', self.sku, rule)
        self.service.provider.included_cycle_capability = original
        retry = self.claim()
        self.assertEqual(retry.status_code, 200, retry.text)
        self.assertEqual(len(self.forces()), 1)

    def test_existing_native_child_requires_exact_schedule_then_adopts_without_force(self):
        self.complete('initial'); self.simulate(80)
        # Model a child created independently by Sticky's native scheduler.
        self.fake.call('POST', '/api/v1/order_force_bill', {'order_id': '9001', 'product_id': '7001'})
        self.service.sync('site-a', '9001')
        task = self.journey()['tasks'][1]
        self.assertEqual(task['claim']['status'], 'uncertain')
        self.assertFalse(task['can_open'])
        refused = self.claim()
        self.assertEqual(refused.status_code, 409, refused.text)
        self.assertEqual(len(self.forces()), 1)
        with self.service.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM member_refill_claims').fetchone()[0], 0)
        self.fake.orders['9002']['products'][0]['recurring_date'] = '2027-04-20'
        before = len(self.fake.calls)
        adopted = self.claim()
        self.assertEqual(adopted.status_code, 200, adopted.text)
        self.assertEqual(adopted.json()['claim']['order_id'], '9002')
        self.assertTrue(adopted.json()['claim']['claim_id'].startswith('claim_'))
        self.assertTrue(all(method == 'GET' or path == '/api/v1/order_view' for method, path, _ in self.fake.calls[before:]))
        self.assertEqual(len(self.forces()), 1)
        self.assertTrue(self.journey()['tasks'][1]['can_open'])

    def test_claim_window_respects_configured_minimum_days(self):
        self.complete('initial')
        rule = self.app.state.admin.get('refill_policy', self.sku)
        self.app.state.admin.put('refill_policy', self.sku, rule | {'minimum_days': 85})
        task = self.simulate(80)['tasks'][1]
        self.assertFalse(task['claim']['available'])
        self.assertEqual(task['claim']['opens_at'], '2027-01-15')
        self.assertEqual(self.claim().status_code, 409)
        self.assertEqual(self.forces(), [])
        self.simulate(85)
        result = self.claim()
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(len(self.forces()), 1)


for _base in NativeClaimTests.__mro__[1:]:
    for _name in vars(_base):
        if _name.startswith('test_') and _name not in vars(NativeClaimTests):
            setattr(NativeClaimTests, _name, None)
