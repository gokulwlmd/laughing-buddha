"""Patient delivery updates and private message drafts; all providers are offline."""
from copy import deepcopy
import json
import unittest

import test_member_portal as fixtures
from member_portal.notifications import order_notifications


class MemberUpdatesTests(unittest.TestCase):
    setUp = fixtures.MemberPortalTests.setUp
    tearDown = fixtures.MemberPortalTests.tearDown
    post_owner = fixtures.MemberPortalTests.post_owner
    enroll = fixtures.MemberPortalTests.enroll

    def other_patient_headers(self):
        with self.service.db() as db:
            patient = dict(db.execute('SELECT * FROM member_patients LIMIT 1').fetchone())
            patient.update(id='other-patient', customer_id='other-customer', email='other@example.invalid')
            db.execute('INSERT INTO member_patients VALUES(?,?,?,?,?,?,?,?,?)', tuple(patient[key] for key in
                ('id', 'site_id', 'customer_id', 'name', 'email', 'salt', 'password_hash', 'identity_source', 'created')))
        return {'Authorization': 'Bearer ' + self.service.session(patient)['access_token'], 'Origin': fixtures.ORIGIN}

    def test_draft_is_private_persistent_revision_checked_and_never_sent(self):
        self.enroll()
        path = self.base + '/messages/draft'
        before = len(self.fake.calls)
        empty = self.client.get(path, headers=self.patient_headers).json()
        self.assertEqual((empty['body'], empty['revision']), ('', 0))
        self.assertEqual(self.client.put(path, headers=self.patient_headers,
            json={'body': 'Question about my treatment', 'revision': 0}).status_code, 200)
        saved = self.client.get(path, headers=self.patient_headers).json()
        self.assertEqual((saved['body'], saved['revision']), ('Question about my treatment', 1))
        self.assertFalse(saved['provider_connected'])
        conflict = self.client.put(path, headers=self.patient_headers, json={'body': 'Stale overwrite', 'revision': 0})
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(self.client.get(path, headers=self.patient_headers).json(), saved)
        self.assertEqual(self.client.get(path, headers=self.other_patient_headers()).json()['body'], '')
        self.assertEqual(self.client.get('/api/v1/sites/site-b/portal/messages/draft', headers=self.patient_headers).status_code, 401)
        self.assertEqual(self.client.get(path).status_code, 401)
        self.assertEqual(self.client.get(self.base + '/messages', headers=self.patient_headers).json()['messages'], [])
        self.assertEqual(len(self.fake.calls), before)

    def test_draft_validation_and_explicit_clear(self):
        self.enroll()
        path = self.base + '/messages/draft'
        for payload in ({'body': 'x' * 2001, 'revision': 0}, {'body': 'x', 'revision': True},
                        {'body': 'x', 'revision': -1}, {'body': 'x', 'revision': 0, 'patient_id': 'other'}):
            self.assertEqual(self.client.put(path, headers=self.patient_headers, json=payload).status_code, 422)
        self.client.put(path, headers=self.patient_headers, json={'body': 'Draft', 'revision': 0})
        cleared = self.client.put(path, headers=self.patient_headers, json={'body': '', 'revision': 1})
        self.assertEqual(cleared.status_code, 200)
        self.assertEqual((cleared.json()['body'], cleared.json()['revision']), ('', 2))

    def test_notifications_are_scoped_and_reads_are_durable_idempotent_and_local(self):
        self.enroll()
        path = self.base + '/notifications'
        before = len(self.fake.calls)
        response = self.client.get(path, headers=self.patient_headers)
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data['unread_count'], 1)
        item = data['notifications'][0]
        self.assertEqual((item['kind'], item['order_id']), ('intake_needed', '9001'))
        read_path = path + '/' + item['id'] + '/read'
        first = self.client.post(read_path, headers=self.patient_headers, json={})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()['unread_count'], 0)
        self.assertTrue(first.json()['notifications'][0]['read_at'])
        self.assertEqual(self.client.post(read_path, headers=self.patient_headers, json={}).json(), first.json())
        self.assertEqual(self.client.get(path, headers=self.patient_headers).json(), first.json())
        other = self.other_patient_headers()
        self.assertEqual(self.client.get(path, headers=other).json()['notifications'], [])
        self.assertEqual(self.client.post(read_path, headers=other, json={}).status_code, 404)
        self.assertEqual(self.client.post(path + '/unrelated/read', headers=self.patient_headers, json={}).status_code, 404)
        self.assertEqual(self.client.get('/api/v1/sites/site-b/portal/notifications', headers=self.patient_headers).status_code, 401)
        self.assertEqual(self.client.get(path).status_code, 401)
        self.assertEqual(len(self.fake.calls), before)

    def test_shipment_fields_and_alert_require_recorded_shipment_status(self):
        self.enroll()
        def update(**fields):
            with self.service.db() as db:
                row = db.execute('SELECT payload FROM member_orders WHERE order_id=?', ('9001',)).fetchone()
                payload = json.loads(row['payload']); payload.update(fields)
                db.execute('UPDATE member_orders SET payload=? WHERE order_id=?', (json.dumps(payload), '9001'))
        update(tracking_number='QA-TRACK-123', shipping_date='2026-10-23', fulfillment_status='pending')
        path = self.base + '/notifications'
        self.assertFalse(any(item['kind'] == 'shipped' for item in self.client.get(path, headers=self.patient_headers).json()['notifications']))
        update(fulfillment_status='shipped')
        order = self.client.get(self.base + '/orders', headers=self.patient_headers).json()['orders'][0]
        self.assertEqual((order['tracking_number'], order['shipping_date']), ('QA-TRACK-123', '2026-10-23'))
        items = self.client.get(path, headers=self.patient_headers).json()['notifications']
        shipment = next(item for item in items if item['kind'] == 'shipped')
        self.assertIn('QA-TRACK-123', shipment['body'])
        self.assertEqual(shipment['created_at'], '2026-10-23')
        self.client.post(path + '/' + shipment['id'] + '/read', headers=self.patient_headers, json={})
        update(tracking_number='QA-TRACK-456')
        new = next(item for item in self.client.get(path, headers=self.patient_headers).json()['notifications'] if item['kind'] == 'shipped')
        self.assertNotEqual(new['id'], shipment['id'])
        self.assertIsNone(new['read_at'])


class NotificationProjectionTests(unittest.TestCase):
    def order(self, order_id='100', term_id='100'):
        return {'id': order_id, 'product_name': 'Semaglutide', 'payment_status': 'paid',
            'care_plan': {'term_order_id': term_id, 'tasks': [
                {'id': 'initial', 'kind': 'initial', 'status': 'submitted', 'can_open': True},
                {'id': 'check-in-90', 'kind': 'check_in', 'status': 'not_started', 'can_open': False,
                 'claim': {'available': True, 'status': 'available', 'opens_at': '2027-01-10'}}]}}

    def test_one_refill_notification_per_term_with_independent_treatments(self):
        parent = self.order(); child = self.order('101')
        second = self.order('200', '200'); second['product_name'] = 'Metformin'
        items = order_notifications([child, parent, second], 'site-a', 'patient-a')
        self.assertEqual({item['order_id'] for item in items}, {'100', '200'})
        self.assertEqual(len(items), 2)
        self.assertEqual({item['action'] for item in items}, {'claim-refill'})
        self.assertIn('Metformin', next(item['title'] for item in items if item['order_id'] == '200'))

    def test_claim_becomes_checkin_and_completed_or_uncertain_claim_does_not_invite_reclaim(self):
        order = self.order(); task = order['care_plan']['tasks'][1]
        task.update(can_open=True, claim={'status': 'claimed', 'available': False, 'order_id': '101'})
        items = order_notifications([order], 'site-a', 'patient-a')
        self.assertEqual((items[0]['kind'], items[0]['action']), ('check_in_needed', 'open-care-task'))
        task['status'] = 'submitted'
        self.assertEqual(order_notifications([order], 'site-a', 'patient-a'), [])
        task['claim'] = {'status': 'uncertain', 'available': True}
        self.assertEqual(order_notifications([order], 'site-a', 'patient-a'), [])

    def test_other_sites_patients_and_unpaid_orders_do_not_share_alert_identity(self):
        order = self.order()
        identifiers = [order_notifications([order], site, patient)[0]['id'] for site, patient in
            [('site-a', 'patient-a'), ('site-b', 'patient-a'), ('site-a', 'patient-b')]]
        self.assertEqual(len(set(identifiers)), 3)
        order['payment_status'] = 'unknown'
        self.assertEqual(order_notifications([order], 'site-a', 'patient-a'), [])


if __name__ == '__main__':
    unittest.main()
