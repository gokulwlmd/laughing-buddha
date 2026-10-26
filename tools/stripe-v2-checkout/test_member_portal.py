"""Real member-portal behavior against an offline Sticky contract fixture only."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import threading
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import secrets
import tempfile
import unittest
from urllib.parse import urlsplit

from fastapi.testclient import TestClient
from app import create_app, Settings
from admin import password_hash
from test_member_provider import FakeSticky
from patient_demo.provider import get_sample_answers

ORIGIN = 'https://portal.example.invalid'
OWNER_EMAIL = 'owner@example.invalid'
OWNER_PASSWORD = 'owner-only-test-password'
PATIENT_PASSWORD = 'patient-only-test-password'
NOW = datetime(2026, 10, 23, 12, tzinfo=timezone.utc).timestamp()


def build_member_fixture(directory, origin=ORIGIN):
    fake = FakeSticky()
    cfg = Settings(public_url=origin, state_dir=Path(directory), authorization_verified=True)
    app = create_app(cfg, sticky=fake)
    service = app.state.member_portal
    service.clock = lambda: NOW
    admin, store = app.state.admin, app.state.store
    for site_id, brand_id, campaign in [('site-a', 'brand-a', 422), ('site-b', 'brand-b', 423)]:
        admin.put('brand', brand_id, {'id': brand_id, 'name': 'Sample brand', 'color': '#245844', 'campaign_id': campaign})
        admin.put('site', site_id, {'id': site_id, 'name': 'Sample Site ' + site_id[-1].upper(), 'brand_id': brand_id, 'campaign_id': campaign})
    admin.put('therapy', 'weight-loss', {'id': 'weight-loss', 'name': 'Weight Loss'})
    master = {'sku': 'SEMA-1M-SUB', 'name': 'Semaglutide', 'therapy_id': 'weight-loss', 'product_setup': {}, 'planning_contract': {}}
    admin.put('master', master['sku'], master)
    admin.put('plan_checkout', 'plan-a', {'id': 'plan-a', 'site_id': 'site-a', 'brand_id': 'brand-a', 'campaign_id': 422,
        'therapy_id': 'weight-loss', 'payment_test_only': True, 'template_snapshot': {'masters': [deepcopy(master)]}})
    admin.put('link', 'member-link-a', {'id': 'member-link-a', 'brand_id': 'brand-a', 'sku': 'SEMA-1M-SUB', 'plan_checkout_id': 'plan-a', 'campaign_id': 422})
    attempt = store.create(422, 'SEMA-1M-SUB', 'member-link-a')
    quote = {'currency': 'USD', 'total': '1.00', 'option': {'productId': 7001, 'recurring': True, 'label': '1-month subscription'}}
    store.claim('new', 'captured', attempt, order_id='9001', quote=json.dumps(quote))
    salt = secrets.token_hex(16)
    with store.db() as db:
        db.execute('INSERT INTO admin_owner VALUES(1,?,?,?)', (OWNER_EMAIL, salt, password_hash(OWNER_PASSWORD, salt)))
    return app, fake, attempt


class MemberPortalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app, self.fake, self.attempt = build_member_fixture(self.tmp.name)
        self.client = TestClient(self.app, base_url=ORIGIN)
        result = self.client.post('/api/admin/login', json={'email': OWNER_EMAIL, 'password': OWNER_PASSWORD}, headers={'Origin': ORIGIN})
        self.owner_headers = {'Origin': ORIGIN, 'X-CSRF-Token': result.json()['csrfToken']}
        self.base = '/api/v1/sites/site-a/portal'
        self.owner = '/api/admin/sites/site-a/portal'
        self.service = self.app.state.member_portal

    def tearDown(self):
        self.client.close(); self.tmp.cleanup()

    def post_owner(self, path, payload):
        return self.client.post(self.owner + path, json=payload, headers=self.owner_headers)

    def enroll(self):
        response = self.post_owner('/invites', {'order_id': '9001'})
        self.assertEqual(response.status_code, 200, response.text)
        token = urlsplit(response.json()['enrollment_url']).fragment.split('=', 1)[1]
        response = self.client.post(self.base + '/auth/enroll', json={'invite_token': token, 'password': PATIENT_PASSWORD}, headers={'Origin': ORIGIN})
        self.assertEqual(response.status_code, 200, response.text)
        self.patient_headers = {'Authorization': 'Bearer ' + response.json()['access_token'], 'Origin': ORIGIN}
        return token, response.json()

    def test_no_seeded_orders_and_owner_sync_reads_only_bound_captured_orders(self):
        self.assertEqual(self.client.get(self.owner + '/overview').json()['orders'], [])
        result = self.post_owner('/sync', {})
        self.assertEqual(result.status_code, 200, result.text)
        row = result.json()['orders'][0]
        self.assertEqual((row['id'], row['payment_status'], row['total']), ('9001', 'paid', '1.00'))
        self.assertFalse(row['refill']['eligible'])
        self.assertNotIn('DO-NOT-RETURN', result.text)
        self.assertEqual(self.client.post('/api/admin/sites/site-b/portal/sync', json={'order_ids': ['9001']}, headers=self.owner_headers).status_code, 409)
        self.assertFalse(any(path in ('/api/v1/new_order', '/api/v1/authorize_payment') for _, path, _ in self.fake.calls))

    def test_one_time_order_internal_id_is_not_a_subscription(self):
        self.service.sync('site-a', '9001')
        row = self.service.order_record('site-a', '9001')
        raw, snapshot = json.loads(row['payload']), json.loads(row['snapshot'])
        line = raw['products'][0]
        line.update(is_recurring=False, billing_status='inactive', billing_model_id='2', next_billing_date=None)
        snapshot['quote_option']['recurring'] = False
        self.service.save_order('site-a', '9001', row['customer_id'], row['attempt_id'], row['therapy_id'], row['sku'], snapshot, raw)
        public = self.service.order_public(self.service.order_record('site-a', '9001'))
        self.assertEqual(public['subscriptions'], [])
        # A stopped recurring plan remains visible; it must not become a sale.
        snapshot['quote_option']['recurring'] = True
        line['billing_model_id'] = '3'
        self.service.save_order('site-a', '9001', row['customer_id'], row['attempt_id'], row['therapy_id'], row['sku'], snapshot, raw)
        public = self.service.order_public(self.service.order_record('site-a', '9001'))
        self.assertEqual(public['subscriptions'][0]['status'], 'inactive')

    def test_enrollment_is_single_use_and_site_scoped_without_email_order_search(self):
        token, auth = self.enroll()
        self.assertEqual(auth['patient']['email'], 'sample@example.invalid')
        repeat = self.client.post(self.base + '/auth/enroll', json={'invite_token': token, 'password': PATIENT_PASSWORD}, headers={'Origin': ORIGIN})
        self.assertEqual(repeat.status_code, 410)
        self.assertEqual(self.client.get('/api/v1/sites/site-b/portal/me', headers=self.patient_headers).status_code, 401)
        self.assertEqual(len(self.client.get(self.base + '/orders', headers=self.patient_headers).json()['orders']), 1)
        self.assertFalse(any('find' in path for _, path, _ in self.fake.calls))
        with self.service.db() as db:
            rows = db.execute('SELECT token_hash FROM member_sessions').fetchall()
        self.assertNotIn(auth['access_token'], str(rows))

    def test_unattributed_or_unverified_orders_cannot_be_imported_automatically(self):
        self.fake.order['campaign_id'] = '423'
        self.assertEqual(self.post_owner('/sync', {'order_ids': ['9001']}).status_code, 502)
        self.fake.order['campaign_id'] = '422'; self.fake.order['products'][0]['product_id'] = '7002'
        self.assertEqual(self.post_owner('/sync', {'order_ids': ['9001']}).status_code, 409)
        self.assertEqual(self.client.get(self.owner + '/overview').json()['orders'], [])

    def test_current_refunded_status_is_not_reported_as_paid_or_refill_eligible(self):
        self.fake.order['order_status'] = '6'
        row = self.post_owner('/sync', {}).json()['orders'][0]
        self.assertEqual(row['payment_status'], 'void_or_refunded')
        self.assertFalse(row['refill']['eligible'])

    def test_password_login_logout_and_expiration(self):
        self.enroll()
        self.assertEqual(self.client.post(self.base + '/auth/login', json={'email': 'sample@example.invalid', 'password': 'wrong'}).status_code, 401)
        result = self.client.post(self.base + '/auth/login', json={'email': 'sample@example.invalid', 'password': PATIENT_PASSWORD})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(self.client.post(self.base + '/auth/logout', headers=self.patient_headers).status_code, 200)
        self.assertEqual(self.client.get(self.base + '/me', headers=self.patient_headers).status_code, 401)
        self.service.clock = lambda: NOW + 86401
        self.assertEqual(self.client.get(self.base + '/me', headers={'Authorization': 'Bearer ' + result.json()['access_token']}).status_code, 401)

    def test_mock_intake_is_saved_with_real_order_grant_and_no_clinical_submission(self):
        self.enroll()
        path = self.base + '/intakes/9001'
        row = self.client.get(path, headers=self.patient_headers)
        self.assertEqual(row.status_code, 200, row.text)
        self.assertFalse(row.json()['provider_connected'])
        self.assertNotIn('demo_confirmation', [q['id'] for q in row.json()['template']['questions']])
        answers = get_sample_answers('weight-loss'); answers.pop('demo_confirmation')
        saved = self.client.patch(path, headers=self.patient_headers, json={'revision': 0, 'answers': answers, 'current_step': 2})
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(self.client.patch(path, headers=self.patient_headers, json={'revision': 0, 'answers': {}}).status_code, 409)
        submitted = self.client.post(path + '/submit', headers=self.patient_headers, json={'revision': 1})
        self.assertEqual(submitted.status_code, 200, submitted.text)
        self.assertEqual(self.client.patch(path, headers=self.patient_headers, json={'revision': 2, 'answers': {}}).status_code, 409)
        order = self.client.get(self.base + '/orders', headers=self.patient_headers).json()['orders'][0]
        self.assertEqual(order['medical_status'], 'not_connected')
        overview = self.client.get(self.owner + '/overview').json()
        self.assertNotIn('answers', json.dumps(overview['intakes']))

    def policy(self, **changes):
        rule = {'enabled': True, 'minimum_days': 0, 'request_window_days': 14, 'check_in_required': True,
                'review_required': True, 'test_requests_enabled': True, 'revision': 1,
                'allow_early_requests': True, 'early_request_minimum_days': 0, 'early_request_cooldown_days': 7, 'early_reason_required': True}
        self.app.state.admin.put('refill_policy', 'SEMA-1M-SUB', rule | changes)

    def test_refill_is_local_review_request_not_payment_or_shipment(self):
        self.enroll(); self.policy()
        body = {'order_id': '9001', 'sku': 'SEMA-1M-SUB', 'client_request_id': 'refill-request-1'}
        result = self.client.post(self.base + '/refills', headers=self.patient_headers, json=body)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()['request']['status'], 'check_in_required')
        self.assertTrue(result.json()['request']['test_only'])
        self.assertFalse(result.json()['request']['clinical_approval'])
        again = self.client.post(self.base + '/refills', headers=self.patient_headers, json=body)
        self.assertEqual(again.json()['request']['id'], result.json()['request']['id'])
        writes = [path for method, path, _ in self.fake.calls if path not in ('/api/v1/order_view', '/api/v2/providers/payment/profiles/254')]
        self.assertEqual(writes, [])

    def test_minimum_days_is_hard_floor_and_held_billing_disables_refills(self):
        self.enroll(); self.policy(minimum_days=30, request_window_days=90)
        body = {'order_id': '9001', 'sku': 'SEMA-1M-SUB', 'client_request_id': 'refill-request-1'}
        self.assertEqual(self.client.post(self.base + '/refills', headers=self.patient_headers, json=body).status_code, 409)
        self.policy()
        self.fake.order['products'][0].update(is_recurring='0', on_hold='1')
        self.assertEqual(self.client.post(self.base + '/refills', headers=self.patient_headers, json=body).status_code, 409)

    def test_subscription_pause_resume_are_explicit_idempotent_and_uncertainty_holds(self):
        self.enroll()
        path = self.base + '/orders/9001/subscriptions/synthetic-subscription-1/pause'
        body = {'client_request_id': 'pause-request-1'}
        first = self.client.post(path, headers=self.patient_headers, json=body)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()['subscriptions'][0]['status'], 'held')
        again = self.client.post(path, headers=self.patient_headers, json=body)
        self.assertEqual(again.status_code, 200)
        self.assertEqual(sum(p == '/api/v1/subscription_order_update' for _, p, _ in self.fake.calls), 1)
        self.fake.write_error = True
        path = self.base + '/orders/9001/subscriptions/synthetic-subscription-1/resume'
        result = self.client.post(path, headers=self.patient_headers, json={'client_request_id': 'resume-request-1'})
        self.assertEqual(result.status_code, 409)
        before = len(self.fake.calls)
        self.client.post(path, headers=self.patient_headers, json={'client_request_id': 'resume-request-2'})
        self.assertEqual(sum(p == '/api/v1/subscription_order_update' for _, p, _ in self.fake.calls), 2)
        self.assertGreaterEqual(len(self.fake.calls), before)

    def test_mock_messages_and_payment_method_capability_are_honest(self):
        self.enroll()
        body = {'body': 'Please contact me', 'client_message_id': 'message-request-1'}
        first = self.client.post(self.base + '/messages', headers=self.patient_headers, json=body)
        again = self.client.post(self.base + '/messages', headers=self.patient_headers, json=body)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json(), again.json())
        self.assertFalse(first.json()['provider_connected'])
        self.assertIn('no clinician has received it', first.json()['messages'][1]['body'])
        self.assertFalse(self.client.get(self.base + '/orders/9001/payment-method', headers=self.patient_headers).json()['available'])

    def test_explicit_owner_import_requires_managed_site_product_and_never_seeds(self):
        with self.service.db() as db:
            db.execute('DELETE FROM checkouts WHERE id=?', (self.attempt,))
        self.assertEqual(self.post_owner('/sync', {}).json()['orders'], [])
        body = {'order_ids': ['9001'], 'allow_import': True}
        self.assertEqual(self.post_owner('/sync', body).status_code, 409)
        self.app.state.admin.put('offering', 'assigned', {'id': 'assigned', 'brand_id': 'brand-a', 'campaign_id': 422,
                                                      'sku': 'SEMA-1M-SUB', 'product_id': 7001})
        result = self.post_owner('/sync', body)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()['orders'][0]['id'], '9001')
        self.assertEqual(self.client.post('/api/admin/sites/site-b/portal/sync', json=body, headers=self.owner_headers).status_code, 409)
        self.enroll()
        self.assertEqual(len(self.client.get(self.base + '/orders', headers=self.patient_headers).json()['orders']), 1)

    def test_verified_subscription_children_inherit_only_parent_grant(self):
        original_call = self.fake.call
        child = deepcopy(self.fake.order)
        child.update(order_id='9002', parent_id='9001', ancestor_id='9001', child_id='', order_total='0.00')
        self.fake.order['child_id'] = '9002'
        def call(method, path, body=None):
            if path == '/api/v1/order_view' and body['order_id'] == ['9002']:
                self.fake.calls.append((method, path, deepcopy(body)))
                return deepcopy(child)
            return original_call(method, path, body)
        self.fake.call = call
        self.enroll()
        orders = self.client.get(self.base + '/orders', headers=self.patient_headers).json()['orders']
        self.assertEqual({o['id'] for o in orders}, {'9001', '9002'})
        self.assertEqual(next(o for o in orders if o['id'] == '9002')['total'], '0.00')
        # A different customer or subscription cannot gain the parent's grant.
        child.update(order_id='9003', customer_id='8002')
        self.fake.order['child_id'] = '9003'
        before = len(orders)
        self.client.post(self.base + '/orders/9001/refresh', headers=self.patient_headers)
        self.assertEqual(len(self.client.get(self.base + '/orders', headers=self.patient_headers).json()['orders']), before)

    def test_receipt_invite_requires_exact_captured_site_attribution(self):
        row = self.app.state.store.read(self.attempt)
        result = self.service.receipt_invite(row)
        self.assertEqual(result['site_id'], 'site-a')
        self.assertIn('/portal/site-a#invite=', result['enrollment_url'])
        from fastapi import HTTPException
        with self.assertRaises(HTTPException):
            self.service.receipt_invite(row | {'status': 'awaiting_card'})
        with self.assertRaises(HTTPException):
            self.service.receipt_invite(row | {'link_id': None})

    def test_early_refill_requires_reason_and_replay_ignores_new_cooldown(self):
        self.enroll(); self.policy(minimum_days=30)
        body = {'order_id': '9001', 'sku': 'SEMA-1M-SUB', 'kind': 'early', 'client_request_id': 'early-request-1'}
        self.assertEqual(self.client.post(self.base + '/refills', headers=self.patient_headers, json=body).status_code, 422)
        body['reason'] = 'I would like the team to review an earlier delivery.'
        first = self.client.post(self.base + '/refills', headers=self.patient_headers, json=body)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()['request']['status'], 'awaiting_review')
        repeat = self.client.post(self.base + '/refills', headers=self.patient_headers, json=body)
        self.assertEqual(repeat.json(), first.json())
        second = self.client.post(self.base + '/refills', headers=self.patient_headers, json=body | {'client_request_id': 'early-request-2'})
        self.assertEqual(second.status_code, 409)
        with self.service.db() as db:
            row = db.execute('SELECT rule FROM member_refills').fetchone()
        self.assertEqual(json.loads(row['rule'])['minimum_days'], 30)

    def shipping(self):
        self.fake.order.update(shippable='1', has_been_posted='0', contact_id='8101',
            shipping_first_name='Sample', shipping_last_name='Member', shipping_street_address='1 Sample St',
            shipping_street_address2='', shipping_city='Tampa', shipping_state='FL', shipping_postcode='33601', shipping_country='US')
        self.fake.order['products'][0]['is_shippable'] = '1'
        return {'first_name': 'Sample', 'last_name': 'Member', 'address': '2 New St', 'address2': '',
                'city': 'Orlando', 'region': 'FL', 'postal_code': '32801', 'country': 'US'}

    def test_current_order_address_change_verifies_unposted_scope_and_is_idempotent(self):
        address = self.shipping(); self.enroll()
        order = self.client.get(self.base + '/orders', headers=self.patient_headers).json()['orders'][0]
        self.assertTrue(order['address_update_available'])
        body = {'client_request_id': 'address-request-1', 'address': address}
        path = self.base + '/orders/9001/address'
        first = self.client.post(path, headers=self.patient_headers, json=body)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()['shipping_address'], address)
        self.assertEqual(self.client.post(path, headers=self.patient_headers, json=body).status_code, 200)
        self.assertEqual(sum(p == '/api/v1/order_update' for _, p, _ in self.fake.calls), 1)
        self.fake.order['has_been_posted'] = '1'
        self.assertEqual(self.client.post(path, headers=self.patient_headers, json=body | {'client_request_id': 'address-request-2'}).status_code, 409)
        self.assertEqual(self.client.post(path, headers=self.patient_headers, json=body | {'card_number': 'not-accepted'}).status_code, 422)

    def test_subscription_address_override_does_not_change_current_order(self):
        address = self.shipping(); self.enroll()
        path = self.base + '/orders/9001/subscriptions/synthetic-subscription-1/address'
        body = {'client_request_id': 'future-address-1', 'address': address}
        result = self.client.post(path, headers=self.patient_headers, json=body)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()['shipping_address']['address'], '1 Sample St')
        self.assertEqual(result.json()['subscriptions'][0]['shipping_address']['address'], '2 New St')
        self.assertEqual(self.client.post(path, headers=self.patient_headers, json=body).status_code, 200)
        self.assertEqual(sum(p.endswith('/override/address') for _, p, _ in self.fake.calls), 1)
        self.assertFalse(any(p == '/api/v1/order_update' for _, p, _ in self.fake.calls))

    def test_prepaid_renewal_moves_term_anchor_and_blocks_older_order_refills(self):
        admin = self.app.state.admin
        plan = admin.get('plan_checkout', 'plan-a')
        plan['template_snapshot']['masters'][0]['product_setup'] = {'shipment_count': 2, 'shipment_interval_days': 90}
        admin.put('plan_checkout', 'plan-a', plan)
        self.fake.order['products'][0]['prepaid'] = [{'current_cycle': '1', 'total_cycles': '2', 'is_renew': '1'}]
        self.fake.order['child_id'] = '9002'
        children = {}
        for order_id, previous, cycle, offset, total, child_id in [
                ('9002', '9001', '2', 90, '0.00', '9003'), ('9003', '9002', '1', 180, '1.00', '')]:
            child = deepcopy(self.fake.order)
            child.update(order_id=order_id, parent_id=previous, ancestor_id='9001', child_id=child_id,
                         order_total=total, time_stamp=(datetime(2026, 10, 23, 10) + timedelta(days=offset)).strftime('%Y-%m-%d %H:%M:%S'))
            child['products'][0]['prepaid'][0]['current_cycle'] = cycle
            children[order_id] = child
        original_call = self.fake.call
        def call(method, path, body=None):
            if path == '/api/v1/order_view' and body['order_id'][0] in children:
                self.fake.calls.append((method, path, deepcopy(body)))
                return deepcopy(children[body['order_id'][0]])
            return original_call(method, path, body)
        self.fake.call = call
        self.enroll(); self.policy()
        root = self.service.order_record('site-a', '9001')
        latest = self.service.order_record('site-a', '9003')
        snapshot = json.loads(latest['snapshot'])
        self.assertEqual(snapshot['term_order_id'], '9003')
        self.assertEqual(snapshot['term_started_at'], children['9003']['time_stamp'])
        self.assertFalse(self.service.refill_availability(root)['eligible'])
        self.assertIn('latest verified order', self.service.refill_availability(root)['reason'])
        expected = (datetime(2026, 10, 23) + timedelta(days=270)).date().isoformat()
        self.assertEqual(self.service.refill_availability(latest)['next_date'], expected)
        self.assertIn(':9003:', self.service.refill_availability(latest)['_cycle_key'])

    def test_subscription_address_read_uses_verified_override_not_old_order_address(self):
        address = self.shipping(); self.enroll()
        self.fake.subscription['shipping']['address'] = '7 Future Way'
        path = self.base + '/orders/9001/subscriptions/synthetic-subscription-1/address'
        result = self.client.get(path, headers=self.patient_headers)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()['address']['address'], '7 Future Way')
        self.assertEqual(result.json()['scope'], 'future_subscription')
        self.assertFalse(any(p.endswith('/override/address') for _, p, _ in self.fake.calls))

    def test_parallel_early_requests_on_different_orders_share_one_sku_cooldown(self):
        self.enroll(); self.policy()
        self.app.state.admin.put('offering', 'assigned', {'id': 'assigned', 'brand_id': 'brand-a', 'campaign_id': 422,
                                                      'sku': 'SEMA-1M-SUB', 'product_id': 7001})
        second = deepcopy(self.fake.order)
        second.update(order_id='9004', ancestor_id='9004', is_test_cc='1')
        second['products'][0]['subscription_id'] = 'synthetic-subscription-2'
        original_call = self.fake.call
        def call(method, path, body=None):
            if path == '/api/v1/order_view' and body['order_id'] == ['9004']:
                self.fake.calls.append((method, path, deepcopy(body)))
                return deepcopy(second)
            return original_call(method, path, body)
        self.fake.call = call
        self.service.sync('site-a', '9004', allow_import=True)
        with self.service.db() as db:
            patient_id = db.execute("SELECT patient_id FROM member_grants WHERE order_id='9001'").fetchone()[0]
            db.execute('INSERT INTO member_grants VALUES(?,?,?,?,?)', ('site-a', '9004', patient_id, NOW, 'explicit_test_grant'))
        barrier = threading.Barrier(2)
        original_availability = self.service.refill_availability
        def availability(order):
            result = original_availability(order)
            barrier.wait(timeout=5)
            return result
        self.service.refill_availability = availability
        def send(order_id):
            return self.client.post(self.base + '/refills', headers=self.patient_headers,
                json={'order_id': order_id, 'sku': 'SEMA-1M-SUB', 'kind': 'early',
                      'reason': 'Fictional early delivery review', 'client_request_id': 'parallel-' + order_id})
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(send, ['9001', '9004']))
        finally:
            self.service.refill_availability = original_availability
        self.assertEqual(sorted(r.status_code for r in results), [200, 409], [r.text for r in results])
        with self.service.db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM member_refills WHERE kind='early'").fetchone()[0], 1)

    def test_swagger_has_site_scoped_auth_and_typed_order_response(self):
        schema = self.client.get('/portal/site-a/openapi.json').json()
        self.assertTrue(all('/site-a/portal/' in path for path in schema['paths']))
        orders = schema['paths']['/api/v1/sites/site-a/portal/orders']['get']
        self.assertIn('security', orders)
        self.assertEqual(orders['responses']['200']['content']['application/json']['schema']['$ref'], '#/components/schemas/OrdersResult')
        self.assertEqual(self.client.get('/api/admin/portal/sites').status_code, 200)
        anonymous = TestClient(self.app, base_url=ORIGIN)
        self.assertEqual(anonymous.get('/api/admin/portal/sites').status_code, 401)


if __name__ == '__main__':
    unittest.main()
