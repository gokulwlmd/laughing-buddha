"""Offline care timelines with real-order-shaped fixtures, never external writes."""
from copy import deepcopy
import json
from datetime import datetime, timezone, timedelta
import test_member_portal as fixtures
NOW = fixtures.NOW
from patient_demo.app import visible


def configure_care_fixture(app, fake, months=12):
    """Called before the first import/enrollment, using only the offline fixture."""
    admin, store = app.state.admin, app.state.store
    sku = f'SEMA-{months}M-SUB'
    count, interval = (months // 3, 90) if months >= 6 else (1, months * 30)
    master = {'sku': sku, 'name': 'Semaglutide', 'therapy_id': 'weight-loss',
              'product_setup': {'shipment_count': count, 'shipment_interval_days': interval}, 'planning_contract': {}}
    admin.put('master', sku, master)
    plan = admin.get('plan_checkout', 'plan-a')
    plan['template_snapshot'] = {'masters': [master]}
    admin.put('plan_checkout', 'plan-a', plan)
    link = admin.get('link', 'member-link-a'); link['sku'] = sku
    admin.put('link', 'member-link-a', link)
    with store.db() as db:
        db.execute("UPDATE checkouts SET sku=? WHERE order_id='9001'", (sku,))
        for row in db.execute("SELECT id,quote FROM checkouts WHERE order_id='9001' AND quote IS NOT NULL").fetchall():
            quote = json.loads(row[1]); quote['option']['label'] = f'{months}-month subscription'
            db.execute('UPDATE checkouts SET quote=? WHERE id=?', (json.dumps(quote), row[0]))
    fake.order.update(gateway_id='1', is_test_cc='1')
    line = fake.order['products'][0]
    line.update(sku=sku, is_shippable='0', billing_model={'id': '4', 'days': interval, 'type': {'id': 1}})
    if count > 1:
        line['prepaid'] = {'current_cycle': '1', 'total_cycles': str(count), 'is_renew': '1'}
    rule = {'enabled': True, 'minimum_days': 0, 'request_window_days': 14, 'check_in_required': True,
            'review_required': True, 'test_requests_enabled': True, 'revision': 1,
            'allow_early_requests': False, 'early_request_minimum_days': 0, 'early_request_cooldown_days': 7,
            'early_reason_required': True, 'intake_template_id': 'weight-loss', 'initial_intake_required': True,
            'check_in_days': list(range(interval, count * interval, interval))}
    admin.put('refill_policy', sku, rule)
    return sku


def configure_native_care_fixture(app, months=12):
    """Enable actual ClaimsManager with an offline native-cycle adapter fixture."""
    from test_member_provider import IncludedCycleSticky
    native = IncludedCycleSticky(cycles=months // 3, renews=True)
    app.state.admin.api = native
    app.state.member_portal.provider.api = native
    # Native fixtures use a fixed original order date and original model IDs.
    sku = configure_care_fixture(app, native, months)
    native.order['products'][0]['prepaid'] = [native.order['products'][0]['prepaid']]
    native.product['sku'] = sku
    app.state.member_portal.provider.wall_clock = lambda: NOW
    rule = app.state.admin.get('refill_policy', sku)
    rule.update(included_refills_enabled=True, claim_window_days=10)
    app.state.admin.put('refill_policy', sku, rule)
    return native


class MemberCareTests(fixtures.MemberPortalTests):
    # Reuse setup helpers, not the parent suite (which has unmapped-SKU expectations).
    def setUp(self):
        super().setUp()
        self.sku = configure_care_fixture(self.app, self.fake)
        self.enroll()
        self.care_path = self.base + '/orders/9001/care-plan'

    def journey(self):
        response = self.client.get(self.care_path, headers=self.patient_headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def simulate(self, day):
        response = self.post_owner('/orders/9001/care-clock', {'day_offset': day})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['care_plan']

    def complete(self, task_id):
        path = self.base + '/orders/9001/care-tasks/' + task_id + '/intake'
        response = self.client.get(path, headers=self.patient_headers)
        self.assertEqual(response.status_code, 200, response.text)
        intake = response.json()
        answers = {q['id']: q['sample'] for q in intake['template']['questions'] if 'sample' in q}
        answers = {q['id']: answers[q['id']] for q in intake['template']['questions'] if q['id'] in answers and visible(q, answers)}
        response = self.client.patch(path, headers=self.patient_headers, json={'revision': intake['revision'], 'answers': answers})
        self.assertEqual(response.status_code, 200, response.text)
        response = self.client.post(path + '/submit', headers=self.patient_headers, json={'revision': response.json()['revision']})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def refill(self, task_id, key=None):
        return self.client.post(self.base + '/refills', headers=self.patient_headers,
            json={'order_id': '9001', 'sku': self.sku, 'task_id': task_id, 'client_request_id': key or 'request-' + task_id})

    def test_care_checkpoint_windows_and_independent_immutable_answers(self):
        plan = self.journey()
        self.assertEqual([t['day_offset'] for t in plan['tasks']], [0, 90, 180, 270])
        self.assertTrue(plan['tasks'][0]['can_open'])
        self.assertFalse(plan['tasks'][1]['can_open'])
        path = self.base + '/orders/9001/care-tasks/checkin-90/intake'
        self.assertEqual(self.client.get(path, headers=self.patient_headers).status_code, 409)
        initial = self.complete('initial')
        self.simulate(75)
        self.assertEqual(self.client.get(path, headers=self.patient_headers).status_code, 409)
        self.simulate(76)
        self.assertEqual(self.client.get(path, headers=self.patient_headers).status_code, 200)
        self.simulate(90)
        self.assertEqual(self.refill('checkin-90').status_code, 409)
        first = self.complete('checkin-90')
        self.assertNotEqual(initial['id'], first['id'])
        request = self.refill('checkin-90')
        self.assertEqual(request.status_code, 200, request.text)
        self.assertEqual(request.json()['request']['status'], 'awaiting_review')
        self.assertTrue(request.json()['request']['simulated'])
        self.assertEqual(self.refill('checkin-90').json()['request']['id'], request.json()['request']['id'])
        self.assertEqual(self.client.patch(path, headers=self.patient_headers, json={'revision': first['revision'], 'answers': {}}).status_code, 409)
        for day in (180, 270):
            self.simulate(day)
            task = 'checkin-' + str(day)
            self.assertEqual(self.refill(task).status_code, 409)
            new_intake = self.client.get(self.base + '/orders/9001/care-tasks/' + task + '/intake', headers=self.patient_headers).json()
            self.assertEqual(new_intake['answers'], {})
            self.complete(task)
            self.assertEqual(self.refill(task).status_code, 200)
        self.simulate(360)
        self.assertFalse(self.journey()['tasks'][-1]['refill']['eligible'])
        prohibited = ('new_order', 'authorize_payment', 'force_bill', 'subscription_order_update', 'order_update')
        self.assertFalse(any(any(name in path for name in prohibited) for _, path, _ in self.fake.calls))

    def test_care_initial_route_compatibility_and_no_foreign_task(self):
        initial = self.complete('initial')
        legacy = self.client.get(self.base + '/intakes/9001', headers=self.patient_headers)
        self.assertEqual(legacy.status_code, 200, legacy.text)
        self.assertEqual(legacy.json()['id'], initial['id'])
        self.assertEqual(self.client.get(self.base + '/orders/9001/care-tasks/checkin-45/intake', headers=self.patient_headers).status_code, 404)
        self.assertEqual(self.client.post(self.base + '/refills', headers=self.patient_headers, json={'order_id': '9001', 'sku': self.sku, 'client_request_id': 'missing-task'}).status_code, 422)

    def test_care_policy_snapshot_and_template_binding(self):
        initial = self.complete('initial')
        self.assertIn('Semaglutide', initial['template']['title'])
        policy = self.app.state.admin.get('refill_policy', self.sku)
        policy.update(check_in_days=[100], revision=2)
        self.app.state.admin.put('refill_policy', self.sku, policy)
        self.assertEqual([t['day_offset'] for t in self.journey()['tasks']], [0, 90, 180, 270])
        self.assertEqual(self.journey()['rule_revision'], 1)


    def test_care_requires_earlier_checkpoints_and_exposes_staff_summaries(self):
        self.complete('initial')
        self.simulate(180)
        self.complete('checkin-180')
        response = self.refill('checkin-180')
        self.assertEqual(response.status_code, 409)
        self.assertIn('earlier', response.json()['detail'])
        late = self.complete('checkin-90')
        self.assertEqual(late['submitted_at'], datetime.fromtimestamp(NOW, timezone.utc).isoformat().replace('+00:00', 'Z'))
        self.assertEqual(self.refill('checkin-90', 'past-checkpoint').status_code, 409)
        self.assertEqual(self.refill('checkin-180').status_code, 200)
        overview = self.client.get(self.owner + '/overview').json()
        self.assertEqual(overview['summaries']['intakes_submitted'], 3)
        self.assertEqual({i['task_id'] for i in overview['intakes']}, {'initial', 'checkin-90', 'checkin-180'})
        self.assertNotIn('answers', json.dumps(overview['intakes']))

    def test_care_six_month_and_short_plans_use_their_purchased_schedule(self):
        import tempfile
        for months, offsets in [(1, [0]), (3, [0]), (6, [0, 90])]:
            with self.subTest(months=months), tempfile.TemporaryDirectory() as directory:
                app, fake, _ = fixtures.build_member_fixture(directory)
                configure_care_fixture(app, fake, months)
                service = app.state.member_portal
                row = service.sync('site-a', '9001')
                service.enroll('site-a', row, fixtures.PATIENT_PASSWORD, 'offline_fixture')
                plan = service.care.public(row)
                self.assertEqual([task['day_offset'] for task in plan['tasks']], offsets)
                self.assertEqual(plan['coverage_days'], months * 30)

    def test_care_import_requires_actual_offer_and_fixed_day_schedule_proof(self):
        row = self.service.order_record('site-a', '9001')
        snapshot = json.loads(row['snapshot']); snapshot.update(schedule_verified=False, source='owner_import')
        with self.service.db() as db:
            db.execute('UPDATE member_orders SET snapshot=? WHERE order_id=?', (json.dumps(snapshot), '9001'))
        self.assertEqual(self.journey()['tasks'], [])
        self.assertEqual(self.post_owner('/orders/9001/care-clock', {'day_offset': 90}).status_code, 409)
        line = self.fake.order['products'][0]
        line['offer'] = {'id': '7002'}
        line['recurring_date'] = (datetime(2026, 10, 23) + timedelta(days=90)).strftime('%Y-%m-%d')
        self.fake.billing_model.update(days=90)
        self.fake.offer['prepaid'].update(cycles=4)
        response = self.post_owner('/orders/9001/verify-care-schedule', {'shipment_interval_days': 90, 'shipment_count': 4, 'term_days': 360})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()['verified'])
        self.assertEqual(len(self.journey()['tasks']), 4)
        self.assertFalse(any('order_update' in path or 'new_order' in path for _, path, _ in self.fake.calls))

    def test_care_legacy_initial_is_adopted_without_becoming_a_later_checkin(self):
        row = self.service.order_record('site-a', '9001')
        patient = self.service.patient('site-a', type('R', (), {'headers': {}})(), type('C', (), {'credentials': self.patient_headers['Authorization'][7:]})())
        legacy = self.service.intake(row, patient)
        self.journey()
        initial = self.client.get(self.base + '/intakes/9001', headers=self.patient_headers).json()
        self.assertEqual(initial['id'], legacy['id'])
        self.simulate(90)
        later = self.client.get(self.base + '/orders/9001/care-tasks/checkin-90/intake', headers=self.patient_headers).json()
        self.assertNotEqual(later['id'], legacy['id'])
        self.assertEqual(later['answers'], {})

# unittest inheritance otherwise repeats all unrelated parent tests with this
# deliberately different fixture. Helpers are inherited; only this slice runs.
for _name in list(vars(fixtures.MemberPortalTests)):
    if _name.startswith('test_') and _name not in vars(MemberCareTests):
        setattr(MemberCareTests, _name, None)
