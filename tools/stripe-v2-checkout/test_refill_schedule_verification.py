"""Safety checks for the explicitly invoked external Dry Run verifier."""
import json
from pathlib import Path
import tempfile
import unittest
from qa.verify_sticky_refill_schedule import Verification, offer_body


class API:
    def __init__(self, response=None, uncertain=False):
        self.calls = []
        self.response = response
        self.uncertain = uncertain

    def call(self, *args):
        self.calls.append(args)
        if self.uncertain:
            raise TimeoutError('Uncertain provider result')
        return self.response


class RefillScheduleVerificationTests(unittest.TestCase):
    def test_uncertain_write_is_journaled_before_request_and_never_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'journal.json'
            api = API(uncertain=True)
            run = Verification(api, path)
            with self.assertRaises(TimeoutError):
                run.write('initial', '/api/v1/new_order', {'private_example': 'do not persist'})
            saved = path.read_text()
            self.assertNotIn('do not persist', saved)
            self.assertEqual(json.loads(saved)['operations']['initial']['status'], 'pending')
            with self.assertRaisesRegex(ValueError, 'Reconcile'):
                Verification(api, path).write('initial', '/api/v1/new_order', {'private_example': 'do not persist'})
            self.assertEqual(len(api.calls), 1)

    def test_confirmed_configuration_reused_and_changed_payload_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'journal.json'
            api = API({'status': 'SUCCESS', 'data': {'id': 123, 'irrelevant_secret': 'never persist'}})
            for _ in range(2):
                self.assertEqual(Verification(api, path).create('product', '/api/v2/products', {'sku': 'SYNTHETIC'}), 123)
            self.assertEqual(len(api.calls), 1)
            self.assertNotIn('never persist', path.read_text())
            with self.assertRaisesRegex(ValueError, 'Reconcile'):
                Verification(api, path).create('product', '/api/v2/products', {'sku': 'CHANGED'})

    def test_custom_refill_product_does_not_replace_initial_or_change_term(self):
        for count in (2, 4):
            body = offer_body(100, 200, count)
            self.assertEqual(body['products'], [{'id': 100}])
            self.assertEqual(body['recurring']['products'], [{'id': 200, 'cycle_depth': 1}])
            self.assertEqual(body['prepaid']['terms'][0]['cycles'], count)
            self.assertEqual(body['prepaid']['is_subscription'], 1)
            self.assertEqual(body['prepaid']['is_prepaid_notification_enabled'], 0)
        with self.assertRaises(ValueError):
            offer_body(100, 100, 4)
