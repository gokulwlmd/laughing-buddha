"""Form-entry reuse never substitutes for authoritative prices or payment checks."""
import unittest
from catalog import RoutingHints
import threading
import test_site_session_api as sessions
from test_checkout import CONTACT


class EntryCacheTests(unittest.TestCase):
    def test_hint_expiry_and_bounded_memory(self):
        now = [0]
        cache = RoutingHints(ttl=2, limit=2, clock=lambda: now[0])
        cache.remember(('site-a',), 10)
        self.assertEqual(cache.get(('site-a',)), 10)
        cache.remember(('site-b',), 20)
        now[0] = 3
        self.assertIsNone(cache.get(('site-a',)))
        cache.remember(('site-c',), 30)
        cache.remember(('site-d',), 40)
        self.assertEqual(len(cache.entries), 2)
        self.assertIsNone(cache.get(('site-b',)))


class EntryQuoteTests(unittest.TestCase):
    setUp = sessions.SessionApiTests.setUp
    tearDown = sessions.SessionApiTests.tearDown
    create = sessions.SessionApiTests.create
    configured = sessions.SessionApiTests.configured

    def test_entry_reads_configuration_concurrently_and_payment_checks_stay_fresh(self):
        path, headers, _ = self.configured()
        self.fake.reads.clear()
        original = self.fake.detail
        barrier = threading.Barrier(2)
        def concurrent(path):
            if any(part in path for part in ('/campaigns/', '/profiles/')):
                barrier.wait(timeout=3)
            return original(path)
        self.fake.detail = concurrent
        body = {'contact': CONTACT, 'shipping_id': 2}
        first = self.client.post(path + '/quote', headers=headers, json=body)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(len(self.fake.reads), 3)
        self.fake.total = '2.25'
        second = self.client.post(path + '/quote', headers=headers, json=body)
        self.assertEqual(second.json()['amount'], 225)
        self.assertEqual(self.fake.count('/calculate'), 2)
        self.fake.archived = True
        pay = self.client.post(path + '/payment', headers=headers,
            json={'quote_id': second.json()['quote_id'], 'accept_terms': True})
        self.assertGreaterEqual(pay.status_code, 400)
        self.assertTrue(any('/products/' in p for p in self.fake.reads))
        self.assertEqual(self.fake.count('/authorize_payment'), 0)

    def test_local_disabled_link_rejects_cached_catalog(self):
        path, headers, _ = self.configured()
        link = self.engine.state.admin.get('link', self.link_id)
        self.engine.state.admin.put('link', self.link_id, link | {'enabled': False})
        result = self.client.post(path + '/quote', headers=headers, json={'contact': CONTACT, 'shipping_id': 2})
        self.assertGreaterEqual(result.status_code, 400)
        self.assertEqual(self.fake.count('/calculate'), 0)
