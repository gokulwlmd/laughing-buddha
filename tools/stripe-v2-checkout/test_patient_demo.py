"""Patient demo isolation, resumable intake, and mock-only API boundaries."""
from datetime import datetime
import hashlib
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from patient_demo.app import create_app
from patient_demo.provider import get_sample_answers


class PatientDemoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='patient-demo-test-')
        self.now = 1800000000
        self.app = create_app(state_dir=self.temp.name, clock=lambda: self.now)
        self.client = TestClient(self.app)
        self.workspace = self.new_workspace()
        self.site = 'willow-health'
        self.path = '/api/v1/sites/' + self.site
        self.patient = self.headers(self.workspace, self.site)
        self.admin = self.headers(self.workspace, self.site, 'admin')

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def new_workspace(self):
        response = self.client.post('/api/demo/workspaces', json={})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    @staticmethod
    def headers(workspace, site, role='patient'):
        item = next(item for item in workspace['sites'] if item['id'] == site)
        return {'Authorization': 'Bearer ' + item[role + '_token']}

    def order(self, therapy='weight-loss', headers=None, path=None):
        response = self.client.get((path or self.path) + '/orders', headers=headers or self.patient)
        self.assertEqual(response.status_code, 200, response.text)
        return next(item for item in response.json()['orders'] if item['therapy_id'] == therapy)

    def intake(self, therapy='weight-loss'):
        order = self.order(therapy)
        path = self.path + '/intakes/' + order['id']
        response = self.client.get(path, headers=self.patient)
        self.assertEqual(response.status_code, 200, response.text)
        return path, response.json()

    def save(self, path, draft, answers, **extra):
        response = self.client.patch(path, headers=self.patient,
                                     json={'revision': draft['revision'], 'answers': answers, **extra})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def submit(self, path, draft):
        response = self.client.post(path + '/submit', headers=self.patient,
                                    json={'revision': draft['revision']})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_workspace_tokens_are_unique_and_only_hashes_are_stored(self):
        other = self.new_workspace()
        self.assertNotEqual(other['workspace_id'], self.workspace['workspace_id'])
        self.assertEqual({s['id'] for s in self.workspace['sites']},
                         {'willow-health', 'harbor-wellness'})
        tokens = [site[role + '_token'] for workspace in (self.workspace, other)
                  for site in workspace['sites'] for role in ('patient', 'admin')]
        self.assertEqual(len(set(tokens)), 8)
        with sqlite3.connect(self.app.state.database) as db:
            digests = {row[0] for row in db.execute('SELECT digest FROM tokens')}
        self.assertEqual(digests, {hashlib.sha256(token.encode()).hexdigest() for token in tokens})
        for file in Path(self.temp.name).glob('patient-demo.sqlite3*'):
            data = file.read_bytes()
            for token in tokens:
                self.assertNotIn(token.encode(), data)

    def test_two_sites_have_four_therapy_orders_with_separate_patient_records(self):
        patient_ids, order_ids = set(), set()
        for site in self.workspace['sites']:
            prefix = '/api/v1/sites/' + site['id']
            headers = self.headers(self.workspace, site['id'])
            configuration = self.client.get(prefix + '/configuration').json()
            self.assertEqual(configuration['site']['id'], site['id'])
            self.assertEqual({t['id'] for t in configuration['therapies']},
                             {'weight-loss', 'sermorelin', 'metformin', 'pt-141'})
            me = self.client.get(prefix + '/me', headers=headers).json()
            patient_ids.add(me['patient']['id'])
            orders = self.client.get(prefix + '/orders', headers=headers).json()['orders']
            self.assertEqual(len(orders), 4)
            self.assertEqual({o['therapy_id'] for o in orders},
                             {'weight-loss', 'sermorelin', 'metformin', 'pt-141'})
            for order in orders:
                self.assertEqual(order['site_id'], site['id'])
                self.assertTrue(order['demo'])
                self.assertEqual(order['payment_status'], 'paid_demo')
                self.assertEqual(order['medical_status'], 'not_submitted')
                self.assertEqual(order['fulfillment_status'], 'not_started')
                order_ids.add(order['id'])
        self.assertEqual(len(patient_ids), 2)
        self.assertEqual(len(order_ids), 8)

    def test_private_routes_require_valid_unexpired_bearer_and_correct_role(self):
        path, _ = self.intake()
        routes = [self.path + suffix for suffix in ('/me', '/orders', '/messages', '/admin/overview')] + [path]
        for route in routes:
            for headers in ({}, {'Authorization': 'Bearer invalid'}, {'Authorization': 'Basic abc'}):
                with self.subTest(route=route, headers=headers):
                    self.assertEqual(self.client.get(route, headers=headers).status_code, 401)
        self.assertEqual(self.client.get(self.path + '/admin/overview', headers=self.patient).status_code, 403)
        for route in (self.path + '/me', self.path + '/messages', path):
            self.assertEqual(self.client.get(route, headers=self.admin).status_code, 403)
        self.assertEqual(self.client.patch(path, headers=self.admin,
                                          json={'revision': 0, 'answers': {}}).status_code, 403)
        self.assertEqual(self.client.post(path + '/submit', headers=self.admin,
                                         json={'revision': 0}).status_code, 403)
        self.now = datetime.fromisoformat(self.workspace['expires_at'].replace('Z', '+00:00')).timestamp()
        self.assertEqual(self.client.get(self.path + '/orders', headers=self.patient).status_code, 401)
        self.assertEqual(self.client.get(self.path + '/admin/overview', headers=self.admin).status_code, 401)

    def test_workspace_and_site_tokens_cannot_read_or_write_foreign_orders(self):
        path, draft = self.intake()
        other = self.new_workspace()
        other_patient = self.headers(other, self.site)
        other_orders = self.client.get(self.path + '/orders', headers=other_patient).json()['orders']
        self.assertNotIn(draft['order_id'], {o['id'] for o in other_orders})
        for method, suffix, body in (('get', '', None), ('patch', '', {'revision': 0, 'answers': {}}),
                                     ('post', '/submit', {'revision': 0})):
            kwargs = {'headers': other_patient}
            if body is not None:
                kwargs['json'] = body
            self.assertEqual(getattr(self.client, method)(path + suffix, **kwargs).status_code, 404)
        harbor_path = path.replace(self.site, 'harbor-wellness')
        harbor_headers = self.headers(self.workspace, 'harbor-wellness')
        self.assertEqual(self.client.get(harbor_path, headers=self.patient).status_code, 403)
        self.assertEqual(self.client.get(harbor_path, headers=harbor_headers).status_code, 404)
        self.assertEqual(self.client.get('/api/v1/sites/harbor-wellness/admin/overview',
                                         headers=self.admin).status_code, 403)

    def test_autosave_merges_answers_resumes_after_restart_and_rejects_lost_updates(self):
        path, draft = self.intake()
        first = self.save(path, draft, {'weight_goals': 'Sample goal'}, current_step=1)
        self.assertEqual(first['revision'], draft['revision'] + 1)
        self.now += 10
        second = self.save(path, first, {'height_inches': 68})
        self.assertEqual(second['answers'], {'weight_goals': 'Sample goal', 'height_inches': 68})
        self.assertEqual(second['current_step'], 1)
        self.assertNotEqual(second['updated_at'], first['updated_at'])
        stale = self.client.patch(path, headers=self.patient,
                                  json={'revision': first['revision'], 'answers': {'height_inches': 72}})
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.json()['detail']['code'], 'revision_conflict')
        self.client.close()
        self.app = create_app(state_dir=self.temp.name, clock=lambda: self.now)
        self.client = TestClient(self.app)
        restored = self.client.get(path, headers=self.patient).json()
        self.assertEqual(restored, second)
        cleared = self.save(path, restored, {'height_inches': None})
        self.assertEqual(cleared['answers'], {'weight_goals': 'Sample goal'})

    def test_each_therapy_has_usable_backend_questions_and_submits_without_medical_approval(self):
        template_ids = set()
        for therapy in ('weight-loss', 'sermorelin', 'metformin', 'pt-141'):
            with self.subTest(therapy=therapy):
                path, draft = self.intake(therapy)
                self.assertEqual(draft['therapy_id'], therapy)
                self.assertTrue(draft['template']['demo'])
                self.assertTrue(draft['template']['sections'])
                template_ids.add(draft['template']['id'])
                saved = self.save(path, draft, get_sample_answers(therapy), current_step=2)
                submitted = self.submit(path, saved)
                self.assertEqual(submitted['status'], 'submitted')
                self.assertIsNotNone(submitted['submitted_at'])
                self.assertEqual(submitted['answers'], get_sample_answers(therapy))
                order = self.order(therapy)
                self.assertEqual(order['intake_status'], 'submitted')
                self.assertEqual(order['medical_status'], 'awaiting_review')
                self.assertEqual(order['payment_status'], 'paid_demo')
                self.assertEqual(order['fulfillment_status'], 'not_started')
        self.assertEqual(len(template_ids), 4)

    def test_required_conditional_answers_are_validated_and_hidden_answers_are_not_submitted(self):
        path, draft = self.intake()
        missing = self.client.post(path + '/submit', headers=self.patient, json={'revision': draft['revision']})
        self.assertEqual(missing.status_code, 422)
        self.assertEqual(missing.json()['detail']['code'], 'required_answers_missing')
        answers = get_sample_answers('weight-loss') | {'previous_weight_treatment': 'yes'}
        saved = self.save(path, draft, answers)
        conditional = self.client.post(path + '/submit', headers=self.patient,
                                       json={'revision': saved['revision']})
        self.assertEqual(conditional.status_code, 422)
        self.assertIn('previous_weight_details', conditional.json()['detail']['question_ids'])
        saved = self.save(path, saved, {'previous_weight_details': 'Synthetic prior treatment'})
        saved = self.save(path, saved, {'previous_weight_treatment': 'no'})
        submitted = self.submit(path, saved)
        self.assertNotIn('previous_weight_details', submitted['answers'])

    def test_submitted_answers_are_frozen_and_cannot_be_replaced_or_resubmitted(self):
        path, draft = self.intake()
        saved = self.save(path, draft, get_sample_answers('weight-loss'))
        submitted = self.submit(path, saved)
        for revision in (saved['revision'], submitted['revision']):
            self.assertEqual(self.client.patch(path, headers=self.patient,
                json={'revision': revision, 'answers': {'weight_goals': 'Changed'}}).status_code, 409)
            self.assertEqual(self.client.post(path + '/submit', headers=self.patient,
                json={'revision': revision}).status_code, 409)
        self.client.close()
        self.client = TestClient(create_app(state_dir=self.temp.name, clock=lambda: self.now))
        self.assertEqual(self.client.get(path, headers=self.patient).json(), submitted)

    def test_whitespace_only_required_answers_cannot_be_submitted(self):
        path, draft = self.intake()
        saved = self.save(path, draft, get_sample_answers('weight-loss') | {'weight_goals': '  \n  '})
        response = self.client.post(path + '/submit', headers=self.patient,
                                    json={'revision': saved['revision']})
        self.assertEqual(response.status_code, 422)
        self.assertIn('weight_goals', response.json()['detail']['question_ids'])
        self.assertEqual(self.client.get(path, headers=self.patient).json()['status'], 'draft')

    def test_unknown_fields_wrong_types_and_invalid_steps_cannot_change_draft(self):
        path, draft = self.intake()
        invalid = [
            {'revision': 0, 'answers': {}, 'site_id': 'harbor-wellness'},
            {'revision': '0', 'answers': {}},
            {'revision': True, 'answers': {}},
            {'revision': 0, 'answers': []},
            {'revision': 0, 'answers': {'unrecognized': 'Private rejected text'}},
            {'revision': 0, 'answers': {'height_inches': '68'}},
            {'revision': 0, 'answers': {'height_inches': True}},
            {'revision': 0, 'answers': {'weight_goals': ['Private rejected text']}},
            {'revision': 0, 'answers': {'previous_weight_treatment': 'invalid'}},
            {'revision': 0, 'answers': {}, 'current_step': 999},
            {'revision': 0, 'answers': {}, 'current_step': -1},
            {'revision': 0, 'answers': {}, 'current_step': '1'},
        ]
        for payload in invalid:
            with self.subTest(payload=payload):
                response = self.client.patch(path, headers=self.patient, json=payload)
                self.assertEqual(response.status_code, 422, response.text)
                self.assertNotIn('Private rejected text', response.text)
        self.assertEqual(self.client.get(path, headers=self.patient).json(), draft)
        self.assertEqual(self.client.post(path + '/submit', headers=self.patient,
                         json={'revision': 0, 'approved': True}).status_code, 422)

    def test_messages_are_idempotent_explicitly_mock_and_isolated_by_site_and_workspace(self):
        path = self.path + '/messages'
        payload = {'body': 'A fictional question for the care team', 'client_message_id': 'qa-message-0001'}
        first = self.client.post(path, headers=self.patient, json=payload)
        self.assertEqual(first.status_code, 200)
        self.assertFalse(first.json()['provider_connected'])
        messages = first.json()['messages']
        self.assertEqual(len(messages), 2)
        self.assertEqual({m['sender'] for m in messages}, {'patient', 'demo_assistant'})
        self.assertTrue(next(m for m in messages if m['sender'] == 'demo_assistant')['automated'])
        self.assertEqual(self.client.post(path, headers=self.patient, json=payload).json(), first.json())
        self.assertEqual(self.client.post(path, headers=self.patient,
                         json=payload | {'body': 'Changed message'}).status_code, 409)
        other = self.new_workspace()
        for prefix, headers in ((self.path, self.headers(other, self.site)),
                ('/api/v1/sites/harbor-wellness', self.headers(self.workspace, 'harbor-wellness'))):
            self.assertEqual(self.client.get(prefix + '/messages', headers=headers).json()['messages'], [])
            response = self.client.post(prefix + '/messages', headers=headers, json=payload)
            self.assertEqual(response.status_code, 200)
            self.assertFalse({m['id'] for m in messages} & {m['id'] for m in response.json()['messages']})
        self.assertEqual(self.client.post(path, headers=self.admin, json=payload).status_code, 403)

    def test_message_validation_does_not_echo_rejected_content(self):
        path = self.path + '/messages'
        for payload in (
            {'body': '   ', 'client_message_id': 'qa-message-0001'},
            {'body': 'Private rejected text', 'client_message_id': 'short'},
            {'body': 'Private rejected text', 'client_message_id': 'qa-message-0001', 'site_id': 'wrong'},
            {'body': ['Private rejected text'], 'client_message_id': 'qa-message-0001'},
        ):
            response = self.client.post(path, headers=self.patient, json=payload)
            self.assertEqual(response.status_code, 422)
            self.assertNotIn('Private rejected text', response.text)
        self.assertEqual(self.client.get(path, headers=self.patient).json()['messages'], [])

    def test_admin_sees_filtered_order_and_intake_progress_without_medical_answers(self):
        path, draft = self.intake()
        secret_sample = 'Synthetic medical answer only the patient should receive'
        saved = self.save(path, draft, {'weight_goals': secret_sample})
        overview = self.client.get(self.path + '/admin/overview?therapy_id=weight-loss', headers=self.admin)
        self.assertEqual(overview.status_code, 200)
        data = overview.json()
        self.assertEqual(len(data['orders']), 1)
        self.assertEqual(data['summaries']['intake_drafts'], 1)
        self.assertEqual(data['intakes'][0]['answered'], 1)
        self.assertNotIn(secret_sample, overview.text)
        self.assertNotIn('answers', data['intakes'][0])
        self.assertNotIn('template', data['intakes'][0])
        for group in ('orders', 'intakes', 'leads'):
            self.assertTrue(all(row['therapy_id'] == 'weight-loss' for row in data[group]))
        saved = self.save(path, saved, get_sample_answers('weight-loss'))
        self.submit(path, saved)
        after = self.client.get(self.path + '/admin/overview?therapy_id=weight-loss', headers=self.admin).json()
        self.assertEqual(after['summaries']['intake_drafts'], 0)
        self.assertEqual(after['summaries']['intakes_submitted'], 1)
        self.assertEqual(after['orders'][0]['medical_status'], 'awaiting_review')
        self.assertEqual(self.client.get(self.path + '/orders?therapy_id=unknown', headers=self.patient).status_code, 422)
        self.assertEqual(self.client.get(self.path + '/admin/overview?therapy_id=unknown', headers=self.admin).status_code, 422)
        foreign = self.headers(self.new_workspace(), self.site, 'admin')
        foreign_data = self.client.get(self.path + '/admin/overview', headers=foreign).json()
        self.assertEqual(foreign_data['intakes'], [])
        self.assertNotIn(draft['order_id'], {o['id'] for o in foreign_data['orders']})

    def test_site_swagger_is_scoped_documents_auth_and_does_not_expose_integrations(self):
        for site in ('willow-health', 'harbor-wellness'):
            response = self.client.get('/sites/' + site + '/openapi.json')
            self.assertEqual(response.status_code, 200)
            spec = response.json()
            paths = set(spec['paths'])
            expected = {'/api/demo/workspaces'} | {'/api/v1/sites/' + site + suffix for suffix in (
                '/configuration', '/me', '/orders', '/intakes/{order_id}',
                '/intakes/{order_id}/submit', '/messages', '/admin/overview')}
            self.assertEqual(paths, expected)
            for path, operations in spec['paths'].items():
                for operation in operations.values():
                    self.assertNotIn('site_id', [p['name'] for p in operation.get('parameters', [])])
                    if not path.endswith(('/configuration', '/workspaces')):
                        self.assertTrue(operation.get('security'))
            for forbidden in ('STICKY_API_PASSWORD', 'STRIPE_SECRET_KEY', '/api/authorize', '/api/capture'):
                self.assertNotIn(forbidden, response.text)
            self.assertEqual(self.client.get('/sites/' + site + '/docs').status_code, 200)
        self.assertEqual(self.client.get('/sites/unknown/openapi.json').status_code, 404)
        self.assertEqual(self.client.get('/api/v1/sites/unknown/configuration').status_code, 404)

    def test_api_data_and_auth_errors_are_not_cacheable_and_workspace_origin_is_restricted(self):
        path, _ = self.intake()
        responses = [
            self.client.get(self.path + '/configuration'),
            self.client.get(self.path + '/me', headers=self.patient),
            self.client.get(path, headers=self.patient),
            self.client.get(self.path + '/messages', headers=self.patient),
            self.client.get(self.path + '/admin/overview', headers=self.admin),
            self.client.get(self.path + '/orders'),
            self.client.post('/api/demo/workspaces', json={}),
        ]
        for response in responses:
            self.assertEqual(response.headers.get('cache-control'), 'no-store')
            self.assertEqual(response.headers.get('referrer-policy'), 'no-referrer')
            self.assertEqual(response.headers.get('x-content-type-options'), 'nosniff')
        self.assertEqual(self.client.post('/api/demo/workspaces', json={},
                         headers={'Origin': 'https://unrelated.example'}).status_code, 403)
        self.assertEqual(self.client.post('/api/demo/workspaces', json={},
                         headers={'Origin': 'http://testserver'}).status_code, 201)
        self.assertEqual(self.client.post('/api/demo/workspaces', json={'role': 'owner'}).status_code, 422)

    def test_all_demo_operations_work_without_network_and_no_payment_routes_exist(self):
        with patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('No external HTTP')),\
             patch('socket.create_connection', side_effect=AssertionError('No external socket')):
            self.new_workspace()
            self.assertEqual(self.client.get('/health').json()['payments_enabled'], False)
            path, draft = self.intake('metformin')
            saved = self.save(path, draft, get_sample_answers('metformin'))
            self.submit(path, saved)
            response = self.client.post(self.path + '/messages', headers=self.patient,
                json={'body': 'Sample message', 'client_message_id': 'offline-message-0001'})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(self.client.get(self.path + '/admin/overview', headers=self.admin).status_code, 200)
        for route in ('/api/authorize', '/api/capture', '/api/stripe', '/api/sticky',
                      self.path + '/checkout', self.path + '/refills/approve'):
            self.assertEqual(self.client.post(route, headers=self.patient, json={}).status_code, 404)


if __name__ == '__main__':
    unittest.main()
