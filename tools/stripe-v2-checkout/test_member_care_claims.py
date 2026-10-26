"""Claim-first care read models and public checkout discovery, offline only."""
import json
import types
import test_member_care as care_fixtures


class MemberClaimCareTests(care_fixtures.MemberCareTests):
    def native_mode(self):
        rule = self.app.state.admin.get('refill_policy', self.sku)
        rule.update(included_refills_enabled=True, claim_window_days=10)
        self.app.state.admin.put('refill_policy', self.sku, rule)
        self.claim_states = {}
        def task_state(row, plan, task):
            context = self.service.care.claim_context(row, task['id'])
            return self.claim_states.get(task['id'], {'available': False, 'status': 'locked',
                'order_id': None, 'claim_id': None, 'opens_at': context['opens_at'], 'reason': 'Claim first', 'amount': '0.00'})
        self.service.claims = types.SimpleNamespace(task_state=task_state)

    def test_native_claim_replaces_legacy_checkin_with_fresh_immutable_submission(self):
        self.complete('initial'); self.simulate(90)
        legacy = self.complete('checkin-90')
        self.native_mode()
        task = self.journey()['tasks'][1]
        self.assertEqual(task['legacy_intake_status'], 'submitted')
        self.assertEqual(task['intake_status'], 'not_started')
        self.assertFalse(task['can_submit'])
        path = self.base + '/orders/9001/care-tasks/checkin-90/intake'
        self.assertEqual(self.client.get(path, headers=self.patient_headers).status_code, 409)
        self.claim_states['checkin-90'] = {'available': False, 'status': 'claimed', 'claim_id': 'claim-offline',
            'order_id': '9002', 'reason': 'Claimed', 'amount': '0.00', 'simulated': True}
        fresh = self.client.get(path, headers=self.patient_headers)
        self.assertEqual(fresh.status_code, 200, fresh.text)
        self.assertNotEqual(fresh.json()['id'], legacy['id'])
        self.assertEqual(fresh.json()['answers'], {})
        self.assertEqual(fresh.json()['claim_order_id'], '9002')
        self.assertEqual(self.client.post(path + '/submit', headers=self.patient_headers, json={'revision': legacy['revision']}).status_code, 409)
        completed = self.complete('checkin-90')
        self.assertTrue(completed['simulated'])
        self.assertEqual(self.client.patch(path, headers=self.patient_headers, json={'revision': completed['revision'], 'answers': {}}).status_code, 409)
        history = self.client.get(path + '-history', headers=self.patient_headers)
        self.assertEqual(history.status_code, 200, history.text)
        self.assertEqual({i['id'] for i in history.json()['intakes']}, {legacy['id'], completed['id']})
        self.assertEqual(self.refill('checkin-90').status_code, 409)
        overview = self.client.get(self.owner + '/overview').json()
        self.assertEqual(sum(bool(i.get('claim_id')) for i in overview['intakes']), 1)
        self.assertNotIn('answers', json.dumps(overview['intakes']))

    def test_native_context_opens_ten_days_before_each_actual_shipment(self):
        self.native_mode()
        row = self.service.order_record('site-a', '9001')
        for day, target in [(90, 2), (180, 3), (270, 4)]:
            context = self.service.care.claim_context(row, 'checkin-' + str(day))
            self.assertEqual((self.service.date(context['due_date']) - self.service.date(context['opens_at'])).days, 10)
            self.assertEqual(context['target_cycle'], target)
            self.assertFalse(context['initial_complete'])
        self.complete('initial')
        self.assertTrue(self.service.care.claim_context(row, 'checkin-90')['initial_complete'])
        self.assertEqual(self.journey()['tasks'][1]['claim']['opens_at'], '2027-01-11')

    def test_uncertain_claim_never_unlocks_the_new_checkin(self):
        self.native_mode(); self.complete('initial'); self.simulate(90)
        self.claim_states['checkin-90'] = {'available': False, 'status': 'uncertain', 'claim_id': 'claim-uncertain', 'order_id': None, 'reason': 'Confirming'}
        task = self.journey()['tasks'][1]
        self.assertFalse(task['can_open']); self.assertFalse(task['can_submit'])
        self.assertEqual(self.client.get(self.base + '/orders/9001/care-tasks/checkin-90/intake', headers=self.patient_headers).status_code, 409)
        self.assertFalse(any('new_order' in path or 'force_bill' in path for _, path, _ in self.fake.calls))

    def test_paid_store_only_exposes_same_site_public_enabled_real_options(self):
        admin = self.app.state.admin
        plan = admin.get('plan_checkout', 'plan-a')
        plan.update(enabled=True, visibility='public')
        admin.put('plan_checkout', 'plan-a', plan)
        admin.put('plan_checkout', 'private-choice', dict(plan, id='private-choice', visibility='private'))
        admin.put('plan_checkout', 'foreign-choice', dict(plan, id='foreign-choice', site_id='site-b', brand_id='brand-b', campaign_id=423))
        calls = []
        def read(key):
            value = admin.get('plan_checkout', key)
            return value, admin.get('brand', value['brand_id']), admin.get('therapy', value['therapy_id'])
        def options(p, brand, therapy):
            calls.append(p['id'])
            return {'therapy': 'Weight Loss', 'entries': [{'available': True, 'name': 'Semaglutide',
                'sku': self.sku, 'durationMonths': 12, 'currency': 'usd', 'purchaseOptionId': 'annual',
                'options': [{'key': '7002:7001:4', 'prepaidCycles': 4, 'upfrontPrice': '1494.00', 'renewal': True, 'basePrice': '373.50'},
                            {'key': 'bad', 'basePrice': '0.00'}, {'key': 'nan', 'basePrice': 'NaN'},
                            {'key': 'blocked', 'basePrice': '100', 'blockedReason': 'Unavailable'}]}]}
        admin.plan_record, admin.plan_options = read, options
        self.service.cfg.checkout_public_url = 'https://checkout.example.invalid'
        response = self.client.get(self.base + '/store', headers=self.patient_headers)
        self.assertEqual(response.status_code, 200, response.text)
        products = response.json()['plans']
        self.assertEqual(len(products), 1)
        self.assertEqual(products[0]['total'], '1494.00')
        self.assertEqual(products[0]['currency'], 'USD')
        self.assertEqual(products[0]['sku'], self.sku)
        self.assertIs(products[0]['recurring'], True)
        self.assertTrue(products[0]['checkout_url'].startswith('https://checkout.example.invalid/plans/plan-a/choose?'))
        self.assertNotIn('access=', products[0]['checkout_url'])
        self.assertEqual(calls, ['plan-a'])
        self.client.get(self.base + '/store', headers=self.patient_headers)
        self.assertEqual(calls, ['plan-a'])
        self.assertEqual(self.client.get('/api/v1/sites/site-b/portal/store', headers=self.patient_headers).status_code, 401)
        plan['enabled'] = False; admin.put('plan_checkout', 'plan-a', plan)
        self.assertEqual(self.client.get(self.base + '/store', headers=self.patient_headers).json()['plans'], [])

    def test_care_clock_is_shared_by_one_term_but_not_a_paid_renewal(self):
        self.simulate(80)
        row = self.service.order_record('site-a', '9001')
        raw, snap = json.loads(row['payload']), json.loads(row['snapshot'])
        raw.update(id='9002', total='0.00', parent_id='9001')
        raw['products'][0]['prepaid']['current_cycle'] = 2
        self.service.save_order('site-a', '9002', row['customer_id'], '', row['therapy_id'], row['sku'], snap, raw)
        child = self.service.order_record('site-a', '9002')
        self.assertEqual(self.service.care.simulation(child)['day_offset'], 80)
        snap.update(term_order_id='9003', term_started_at='2027-10-18 10:00:00')
        raw.update(id='9003', total='1.00')
        self.service.save_order('site-a', '9003', row['customer_id'], '', row['therapy_id'], row['sku'], snap, raw)
        self.assertFalse(self.service.care.simulation(self.service.order_record('site-a', '9003'))['enabled'])


for _base in MemberClaimCareTests.__mro__[1:]:
    for _name in vars(_base):
        if _name.startswith('test_') and _name not in vars(MemberClaimCareTests):
            setattr(MemberClaimCareTests, _name, None)
