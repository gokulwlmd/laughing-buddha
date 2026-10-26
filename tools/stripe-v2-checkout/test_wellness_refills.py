"""Source-derived refill defaults and genuine claim paths with offline provider."""
from copy import deepcopy
import json
import sqlite3
import unittest
from unittest.mock import patch
import test_member_portal as portal
import test_member_care as care
from import_wellness_masters import prepare as masters
from import_wellness_refill_policies import prepare, install
from catalog_refill_policies import source_products, proposed_policy
from member_portal.intake_templates import get_template, binding_for_sku
from test_wellness_masters import WellnessMasterTests


def configure_wellness_fixture(app, sku='NAD-INJ-12M-SUB'):
    records = masters({})
    p = next(p for p in source_products() if sku in (p['sku'], p['sku'] + '-SUB'))
    months = p['duration_months']
    native = care.configure_native_care_fixture(app, months=months)
    admin = app.state.admin
    master = records['master', sku]
    for key, value in records.items():
        admin.put(*key, value)
    plan = admin.get('plan_checkout', 'plan-a')
    plan.update(therapy_id=p['therapy_id'], template_snapshot={'masters': [master]})
    admin.put('plan_checkout', 'plan-a', plan)
    link = admin.get('link', 'member-link-a'); link['sku'] = sku
    admin.put('link', 'member-link-a', link)
    with app.state.store.db() as db:
        db.execute("UPDATE checkouts SET sku=? WHERE order_id='9001'", (sku,))
    native.order['products'][0]['sku'] = sku
    native.product['sku'] = sku
    policy = proposed_policy(p, sku)
    policy['test_requests_enabled'] = True
    admin.put('refill_policy', sku, policy)
    return native, sku


class WellnessRefillImportTests(WellnessMasterTests):
    def test_policies_follow_source_and_do_not_change_masters(self):
        from import_wellness_masters import install as install_masters
        install_masters(self.path, True)
        before = self.records()
        self.assertEqual(install(self.path)['policies'], 34)
        self.assertEqual(before, self.records())
        result = install(self.path, True)
        self.assertEqual(result['included_refill_policies'], 16)
        for k, v in before.items(): self.assertEqual(self.records()[k], v)
        for p in source_products():
            for suffix in ('', '-SUB'):
                rule = self.records()['refill_policy', p['sku'] + suffix]
                self.assertEqual(rule['included_refills_enabled'], p['included_refills'] > 0)
                self.assertEqual(rule['check_in_required'], p['check_in_required'])
                self.assertEqual(rule['check_in_days'], [])
                self.assertEqual(rule['claim_window_days'], 20)
                self.assertTrue(rule['initial_intake_required'])
                self.assertFalse(rule['test_requests_enabled'])
        self.assertTrue(install(self.path, True)['already_imported'])

    def test_existing_policy_and_changed_delivery_schedule_are_not_overwritten(self):
        records = masters({})
        records['refill_policy', 'NAD-INJ-1M'] = {'revision': 7}
        with self.assertRaisesRegex(ValueError, 'Existing refill policy'): prepare(records)
        del records['refill_policy', 'NAD-INJ-1M']
        records['master', 'NAD-INJ-1M']['product_setup']['shipment_days'] = [0, 15]
        with self.assertRaisesRegex(ValueError, 'Master differs'): prepare(records)

    def test_every_exact_pair_has_initial_intake_and_excluded_sku_has_none(self):
        for p in source_products():
            for suffix in ('', '-SUB'):
                sku = p['sku'] + suffix
                template = get_template(p['therapy_id'], sku=sku)
                self.assertEqual(template['sku'], sku)
                self.assertEqual(template['product_name'], p['name'])
                self.assertTrue(template['questions'])
        self.assertIsNone(binding_for_sku('MIN-1MG-FINA-1.25MG'))


class WellnessClaimTests(care.MemberCareTests):
    def setUp(self):
        portal.MemberPortalTests.setUp(self)
        self.fake, self.sku = configure_wellness_fixture(self.app)
        self.enroll()
        self.care_path = self.base + '/orders/9001/care-plan'

    def claim(self, day, key=None):
        return self.client.post(self.base + f'/orders/9001/care-tasks/shipment-{day}/claim',
            headers=self.patient_headers, json={'client_request_id': key or 'wellness-claim-' + str(day)})

    def complete_initial(self):
        path = self.base + '/orders/9001/care-tasks/initial/intake'
        form = self.client.get(path, headers=self.patient_headers).json()
        answers = {q['id']: q.get('sample') or 'Offline example answer' for q in form['template']['questions'] if not q.get('show_if')}
        patched = self.client.patch(path, headers=self.patient_headers, json={'revision': form['revision'], 'answers': answers})
        self.assertEqual(patched.status_code, 200, patched.text)
        result = self.client.post(path + '/submit', headers=self.patient_headers, json={'revision': patched.json()['revision']})
        self.assertEqual(result.status_code, 200, result.text)

    def test_three_zero_claims_without_checkins_at_exact_windows(self):
        tasks = self.journey()['tasks']
        self.assertEqual([t['kind'] for t in tasks], ['initial'] + ['included_shipment'] * 3)
        self.simulate(70)
        self.assertEqual(self.claim(90).status_code, 409)
        self.complete_initial()
        for day in (90, 180, 270):
            self.simulate(day - 21)
            self.assertEqual(self.claim(day).status_code, 409)
            self.simulate(day - 20)
            result = self.claim(day)
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(result.json()['claim']['amount'], '0.00')
            task = next(t for t in result.json()['care_plan']['tasks'] if t['day_offset'] == day)
            self.assertEqual(task['status'], 'complete')
            self.assertEqual(task['intake_status'], 'not_required')
            self.assertFalse(task['can_open']); self.assertFalse(task['can_submit'])
            self.assertNotIn('Complete its check-in', result.json()['claim']['reason'])
            self.assertEqual(self.claim(day, 'different-key-' + str(day)).status_code, 200)
            intake = self.client.get(self.base + f'/orders/9001/care-tasks/shipment-{day}/intake', headers=self.patient_headers)
            self.assertEqual(intake.status_code, 409)
        self.assertEqual(self.claim(360).status_code, 404)
        self.assertEqual(len([p for _, p, _ in self.fake.calls if p.endswith('/order_force_bill')]), 3)
        with self.service.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM member_claim_intakes').fetchone()[0], 0)

    def test_uncertain_claim_does_not_retry_and_site_isolation_holds(self):
        self.complete_initial(); self.simulate(70)
        self.fake.failure = 'force_timeout'
        self.assertEqual(self.claim(90).status_code, 409)
        self.fake.failure = None
        self.assertEqual(self.claim(90, 'different-retry-key').status_code, 409)
        self.assertEqual(len([p for _, p, _ in self.fake.calls if p.endswith('/order_force_bill')]), 1)
        response = self.client.post('/api/v1/sites/site-b/portal/orders/9001/care-tasks/shipment-90/claim',
            headers=self.patient_headers, json={'client_request_id': 'other-site-test'})
        self.assertEqual(response.status_code, 401)

    def test_master_and_site_editors_accept_confirmed_no_checkin_policies(self):
        rule = self.service.rule(self.sku, 'site-a')
        body = {k: v for k, v in rule.items() if k not in ('sku', 'revision')}
        body['expected_revision'] = 1
        result = self.client.put('/api/admin/master-refill-rules/' + self.sku, headers=self.owner_headers, json=body)
        self.assertEqual(result.status_code, 200, result.text)
        body['expected_revision'] = 0
        result = self.client.put(self.owner + '/refill-rules/' + self.sku, headers=self.owner_headers, json=body)
        self.assertEqual(result.status_code, 200, result.text)
        body['expected_revision'] = 1; body['check_in_days'] = [90]
        self.assertEqual(self.client.put(self.owner + '/refill-rules/' + self.sku, headers=self.owner_headers, json=body).status_code, 422)

    def test_included_order_api_never_reopens_initial_form(self):
        self.complete_initial(); self.simulate(70)
        claim = self.claim(90)
        self.assertEqual(claim.status_code, 200, claim.text)
        child = claim.json()['claim']['order_id']
        result = self.client.get(self.base + '/intakes/' + child, headers=self.patient_headers)
        self.assertEqual(result.status_code, 409, result.text)
        orders = self.client.get(self.base + '/orders', headers=self.patient_headers).json()['orders']
        public = next(o for o in orders if o['id'] == child)
        self.assertEqual(public['order_role'], 'included_refill')
        self.assertEqual(public['intake_status'], 'not_required')
        self.assertEqual(public['sku'], self.sku)

    def test_full_term_renewal_uses_same_sku_and_skips_unrequired_form(self):
        self.complete_initial()
        for day in (90, 180, 270):
            self.simulate(day - 20)
            self.assertEqual(self.claim(day).status_code, 200)
        parent = self.fake.orders['9004']
        child = deepcopy(parent)
        child.update(order_id='9005', parent_id='9004', child_id='', order_total='100.00', time_stamp='2027-10-17 12:00:00')
        child['products'][0]['prepaid'][0]['current_cycle'] = '1'
        child['products'][0]['recurring_date'] = '2028-01-15'
        for old in self.fake.orders.values():
            old['child_id'] = ','.join(filter(None, [old['child_id'], '9005']))
        self.fake.orders['9005'] = child
        self.service.sync('site-a', '9001')
        row = self.service.order_record('site-a', '9005')
        self.assertEqual(json.loads(row['snapshot'])['term_order_id'], '9005')
        public = self.service.order_public(row)
        self.assertEqual(public['order_role'], 'paid_renewal')
        self.assertEqual(public['sku'], self.sku)
        self.assertEqual(public['intake_status'], 'not_required')
        self.assertEqual(public['care_plan']['tasks'][0]['kind'], 'renewal_ready')
        self.assertEqual(self.client.get(self.base+'/intakes/9005', headers=self.patient_headers).status_code, 409)
        root = self.client.get(self.base+'/intakes/9001', headers=self.patient_headers)
        self.assertEqual(root.json()['status'], 'submitted')

class SixMonthWellnessTests(WellnessClaimTests):
    def setUp(self):
        portal.MemberPortalTests.setUp(self)
        self.fake, self.sku = configure_wellness_fixture(self.app, 'NAD-INJ-6M-SUB')
        self.enroll(); self.care_path = self.base + '/orders/9001/care-plan'

    def test_only_one_included_refill(self):
        self.complete_initial(); self.simulate(70)
        self.assertEqual(self.claim(90).status_code, 200)
        self.assertEqual(self.claim(180).status_code, 404)
        self.assertEqual(len(self.journey()['tasks']), 2)
        self.assertEqual(len([p for _, p, _ in self.fake.calls if p.endswith('/order_force_bill')]), 1)


for cls in (WellnessRefillImportTests, WellnessClaimTests, SixMonthWellnessTests):
    for parent in cls.__mro__[1:]:
        for name in vars(parent):
            if name.startswith('test_') and name not in vars(cls): setattr(cls, name, None)
