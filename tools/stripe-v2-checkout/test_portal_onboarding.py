"""External storefront onboarding uses real site-scoped accounts and stored intakes."""
import json
import unittest
from urllib.parse import urlsplit
import test_member_portal as member

SHOP = 'https://shop.example.invalid'


class OnboardingTests(unittest.TestCase):
    setUp = member.MemberPortalTests.setUp
    tearDown = member.MemberPortalTests.tearDown
    post_owner = member.MemberPortalTests.post_owner
    enroll = member.MemberPortalTests.enroll

    def register(self):
        site = self.app.state.admin.get('site', 'site-a')
        self.app.state.admin.put('site', 'site-a', site | {'portal_origins': [SHOP]})

    def test_registered_origin_enroll_login_and_intake_with_site_isolation(self):
        self.register()
        contract = self.client.get(self.base + '/onboarding', headers={'Origin': SHOP})
        self.assertEqual(contract.headers['access-control-allow-origin'], SHOP)
        self.assertFalse(contract.json()['intake_provider_connected'])
        preflight = self.client.options(self.base + '/intakes/9001', headers={
            'Origin': SHOP, 'Access-Control-Request-Method': 'PATCH',
            'Access-Control-Request-Headers': 'authorization,content-type'})
        self.assertEqual(preflight.status_code, 200)
        self.assertNotIn('access-control-allow-credentials', preflight.headers)
        invitation = self.post_owner('/invites', {'order_id': '9001'}).json()
        token = urlsplit(invitation['enrollment_url']).fragment.split('=', 1)[1]
        auth = self.client.post(contract.json()['enroll_path'], headers={'Origin': SHOP},
            json={'invite_token': token, 'password': member.PATIENT_PASSWORD})
        self.assertEqual(auth.status_code, 200, auth.text)
        headers = {'Origin': SHOP, 'Authorization': 'Bearer ' + auth.json()['access_token']}
        intake = self.client.get(self.base + '/intakes/9001', headers=headers).json()
        saved = self.client.patch(self.base + '/intakes/9001', headers=headers,
            json={'revision': intake['revision'], 'answers': {'allergies': 'Fictional QA answer'}, 'current_step': 1})
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(self.client.get(self.base + '/intakes/9001', headers=headers).json()['answers']['allergies'], 'Fictional QA answer')
        self.assertEqual(self.client.get('/api/v1/sites/site-b/portal/me', headers=headers).status_code, 403)
        self.assertEqual(self.client.get(self.base + '/me', headers=headers | {'Origin': 'https://evil.invalid'}).status_code, 403)
        self.assertEqual(self.client.post(contract.json()['enroll_path'], headers={'Origin': SHOP},
            json={'invite_token': token, 'password': 'replacement-password'}).status_code, 410)
        login = self.client.post(contract.json()['login_path'], headers={'Origin': SHOP},
            json={'email': auth.json()['patient']['email'], 'password': member.PATIENT_PASSWORD})
        self.assertEqual(login.status_code, 200)
        self.assertEqual(self.client.get(self.base + '/intakes/9001').status_code, 401)

    def test_cart_order_claim_needs_receipt_and_matching_authenticated_email(self):
        _, auth = self.enroll()
        order = self.service.order_record('site-a', '9001')
        payload = json.loads(order['payload'])
        payload['customer']['id'] = 'different-sticky-customer'
        with self.service.db() as db:
            columns = list(order)
            values = dict(order, snapshot=json.dumps(dict(json.loads(order['snapshot']), root_order_id='9002', term_order_id='9002')), order_id='9002', customer_id='different-sticky-customer', payload=json.dumps(payload))
            db.execute('INSERT INTO member_orders (' + ','.join(columns) + ') VALUES (' + ','.join('?' for _ in columns) + ')', tuple(values[k] for k in columns))
        order = self.service.order_record('site-a', '9002')
        invitation = self.service.issue_invite('site-a', order)
        token = urlsplit(invitation['enrollment_url']).fragment.split('=', 1)[1]
        for _ in range(2):
            result = self.client.post(self.base + '/auth/claim', headers=self.patient_headers, json={'invite_token': token})
            self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(self.client.get(self.base + '/intakes/9002', headers=self.patient_headers).status_code, 200)
        with self.service.db() as db:
            values.update(order_id='9003')
            payload['customer']['email'] = 'another@example.invalid'
            values['payload'] = json.dumps(payload)
            db.execute('INSERT INTO member_orders (' + ','.join(columns) + ') VALUES (' + ','.join('?' for _ in columns) + ')', tuple(values[k] for k in columns))
        wrong = self.service.issue_invite('site-a', self.service.order_record('site-a', '9003'))
        bad_token = urlsplit(wrong['enrollment_url']).fragment.split('=', 1)[1]
        self.assertEqual(self.client.post(self.base + '/auth/claim', headers=self.patient_headers, json={'invite_token': bad_token}).status_code, 403)
        self.assertEqual(self.client.get(self.base + '/intakes/9003', headers=self.patient_headers).status_code, 404)
