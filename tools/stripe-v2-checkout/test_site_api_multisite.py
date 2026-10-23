"""Multi-site Site API: registry, per-site catalogs and sessions. No network, no processor."""
import copy
import json
from pathlib import Path
import tempfile
import time
import unittest

from fastapi.testclient import TestClient
from demo.public import create_public_app, SiteRegistry, validate_sites, map_catalog
from demo.session_api import SessionStore
from test_site_api_public import fixture

ORIGIN = 'https://api.example'
SITES = {
    'payment-test': {'name': 'Master Therapy Payment Test', 'catalog': 'site-api-public-weight-loss', 'payment_test_only': True,
                     'domains': ['checkout.mastertherapy.example']},
    'glow-health': {'name': 'Glow Health', 'catalog': 'glow-weight-loss-public', 'domains': ['checkout.glowhealth.example'], 'portal_site': 'glow-site'},
    'paused-brand': {'name': 'Paused', 'catalog': 'paused-public', 'enabled': False},
}


def glow_catalog():
    data = fixture()
    data.update(id='glow-weight-loss-public', paymentTestOnly=False, title='Find your plan', therapy='GLP-1 program',
                branding={'name': 'Glow Health', 'color': '#7a2e5c', 'logo_url': 'https://cdn.example/glow.png',
                          'background_color': '#fbf6f8', 'text_color': '#3a1730', 'button_text_color': '#ffffff',
                          'font': 'rounded', 'layout': 'stacked', 'support_email': 'hello@glow.example', 'support_phone': ''})
    # Glow sells only semaglutide, at its own prices.
    data['entries'] = [e for e in data['entries'] if e['sku'].startswith('SEMA')]
    for e in data['entries']:
        for o in e['options']:
            o['upfrontPrice'] = str(int(float(o['upfrontPrice']) * 1.2))
    return data


class FakeTransport:
    """Stands in for the hosted checkout: enough to create a session."""
    def __init__(self):
        self.calls = []

    def call(self, row, method, path, body=None, client_ip=None):
        self.calls.append((row['site_id'], method, path))
        if path.startswith('/c/'):
            return '<meta name="checkout-csrf" content="' + 'a' * 64 + '">', {}
        if path == '/api/start-checkout':
            return {'status': 'new', 'attemptId': 'attempt-' + 'x' * 24}, {}
        if path == '/api/status':
            return {'status': 'new'}, {}
        raise AssertionError('unexpected call ' + path)


class MultiSiteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.reads = []
        catalogs = {'site-api-public-weight-loss': fixture(), 'glow-weight-loss-public': glow_catalog()}

        def read(catalog):
            self.reads.append(catalog)
            return copy.deepcopy(catalogs[catalog])
        self.catalogs = catalogs
        self.transport = FakeTransport()
        self.store = SessionStore(Path(self.temp.name) / 's')
        self.app = create_public_app(ORIGIN, read_catalog=read, sites=SITES, session_store=self.store, transport=self.transport)
        self.client = TestClient(self.app, base_url=ORIGIN)

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def test_each_site_returns_its_own_catalog_name_and_branding(self):
        a = self.client.get('/api/v1/sites/payment-test/plans').json()
        g = self.client.get('/api/v1/sites/glow-health/plans').json()
        self.assertEqual((a['site_id'], a['site_name'], len(a['plans']), a['demo']), ('payment-test', 'Master Therapy Payment Test', 16, True))
        self.assertEqual((g['site_id'], g['site_name'], len(g['plans']), g['demo']), ('glow-health', 'Glow Health', 8, False))
        self.assertTrue(all(p['medication'] == 'Semaglutide' for p in g['plans']))
        price = lambda c, pid: next(p['price'] for p in c['plans'] if p['plan_id'] == pid)
        self.assertEqual((price(a, 'sema-1m'), price(g, 'sema-1m')), ('249.00', '298.00'))
        self.assertEqual((g['color'], g['branding']['logo_url'], g['branding']['layout'], g['title']), ('#7a2e5c', 'https://cdn.example/glow.png', 'stacked', 'Find your plan'))
        self.assertEqual(sorted(set(self.reads)), ['glow-weight-loss-public', 'site-api-public-weight-loss'])

    def test_site_info_and_domain_lookup(self):
        info = self.client.get('/api/v1/sites/glow-health').json()
        self.assertEqual((info['site_name'], info['plan_count'], info['branding']['font'], info['domains']), ('Glow Health', 8, 'rounded', ['checkout.glowhealth.example']))
        for domain, site_id in (('checkout.glowhealth.example', 'glow-health'), ('WWW.checkout.mastertherapy.example', 'payment-test')):
            r = self.client.get('/api/v1/domains/' + domain)
            self.assertEqual((r.status_code, r.json()['site_id']), (200, site_id))
        self.assertEqual(self.client.get('/api/v1/domains/unknown.example').status_code, 404)
        self.assertTrue(info['portal_url'].endswith('/portal/glow-site'))
        self.assertIsNone(self.client.get('/api/v1/sites/payment-test').json()['portal_url'])

    def test_unknown_disabled_and_invalid_sites_are_404_everywhere(self):
        for site_id in ('other', 'paused-brand', 'Bad_ID', 'a'):
            for method, path in (('get', ''), ('get', '/plans'), ('post', '/sessions'), ('post', '/checkout')):
                r = getattr(self.client, method)(f'/api/v1/sites/{site_id}{path}', **({'json': {'plan_id': 'sema-1m'}} if method == 'post' else {}))
                self.assertEqual(r.status_code, 404, (site_id, path))
            self.assertEqual(self.client.get(f'/sites/{site_id}/docs').status_code, 404)
        self.assertNotIn('paused-public', self.reads)

    def test_sessions_are_bound_to_their_site(self):
        r = self.client.post('/api/v1/sites/glow-health/sessions', json={'plan_id': 'sema-3m'})
        self.assertEqual(r.status_code, 201, r.text)
        s = r.json()
        auth = {'Authorization': 'Bearer ' + s['session_token']}
        self.assertEqual(self.store.read(s['session_id'])['site_id'], 'glow-health')
        self.assertEqual(self.client.get(f"/api/v1/sites/glow-health/sessions/{s['session_id']}", headers=auth).status_code, 200)
        # The same token/session on another site is rejected.
        self.assertEqual(self.client.get(f"/api/v1/sites/payment-test/sessions/{s['session_id']}", headers=auth).status_code, 401)
        # A plan that only exists on another site is not found here.
        self.assertEqual(self.client.post('/api/v1/sites/glow-health/sessions', json={'plan_id': 'tirz-1m'}).status_code, 404)
        self.assertEqual(self.client.post('/api/v1/sites/payment-test/sessions', json={'plan_id': 'tirz-1m'}).status_code, 201)

    def test_one_failing_catalog_does_not_affect_other_sites(self):
        self.catalogs['glow-weight-loss-public']['entries'][0]['currency'] = 'bad!'
        self.assertEqual(self.client.get('/api/v1/sites/glow-health/plans').status_code, 503)
        self.assertEqual(self.client.get('/api/v1/sites/payment-test/plans').status_code, 200)

    def test_per_site_docs(self):
        self.client.get('/api/v1/sites/glow-health/plans')
        spec = self.client.get('/sites/glow-health/openapi.json').json()
        self.assertEqual(spec['info']['title'], 'Glow Health · Site API')
        self.assertIn('/api/v1/sites/glow-health/plans', spec['paths'])
        self.assertIn('/api/v1/sites/glow-health', spec['paths'])
        self.assertFalse(any('payment-test' in p for p in spec['paths']))
        self.assertNotIn('Real-charge payment tests only', spec['info']['description'])
        self.assertIn('Real-charge payment tests only', self.client.get('/sites/payment-test/openapi.json').json()['info']['description'])
        self.assertEqual(spec['components']['schemas']['CreateSession']['example'], {'plan_id': 'sema-1m'})
        self.assertIn('Glow Health', self.client.get('/sites/glow-health/docs').text)
        page = self.client.get('/').text
        self.assertIn('value="glow-health"', page)
        self.assertNotIn('value="paused-brand"', page)


class WarmupMultiSiteTests(unittest.TestCase):
    def test_background_warmup_covers_every_enabled_site_only(self):
        import threading
        seen = set(); both = threading.Event()
        catalogs = {'site-api-public-weight-loss': fixture(), 'glow-weight-loss-public': glow_catalog()}
        def read(catalog):
            seen.add(catalog)
            if {'site-api-public-weight-loss', 'glow-weight-loss-public'} <= seen:
                both.set()
            return copy.deepcopy(catalogs[catalog])
        app = create_public_app(ORIGIN, read_catalog=read, sites=SITES, warm_catalog=True)
        with TestClient(app, base_url=ORIGIN) as client:
            self.assertTrue(both.wait(3))
            reads_before = len(seen)
            self.assertEqual(client.get('/api/v1/sites/glow-health/plans').status_code, 200)
            self.assertEqual(client.get('/api/v1/sites/payment-test/plans').status_code, 200)
        self.assertNotIn('paused-public', seen)
        self.assertEqual(reads_before, 2)


class RegistryTests(unittest.TestCase):
    def test_validation_fails_closed(self):
        for bad in ({}, {'Bad': {'name': 'x', 'catalog': 'c-1'}}, {'ok-id': {'name': '', 'catalog': 'c-1'}},
                    {'ok-id': {'name': 'x', 'catalog': '../etc'}}, {'ok-id': {'name': 'x', 'catalog': 'c-1', 'domains': ['not a domain']}},
                    {'ok-id': {'name': 'x', 'catalog': 'c-1', 'portal_site': '../admin'}},
                    {'a1': {'name': 'x', 'catalog': 'c-1', 'domains': ['d.example']}, 'b1': {'name': 'y', 'catalog': 'c-2', 'domains': ['d.example']}}):
            with self.assertRaises(ValueError):
                validate_sites(bad)
        self.assertEqual(list(validate_sites({'_readme': 'x', 'ok-id': {'name': 'x', 'catalog': 'c-1'}})), ['ok-id'])

    def test_file_registry_reloads_and_keeps_last_valid_on_bad_edit(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'sites.json'
            path.write_text(json.dumps({'one': {'name': 'One', 'catalog': 'one-public'}}))
            registry = SiteRegistry(path=path)
            self.assertEqual(list(registry.all()), ['one'])
            time.sleep(0.01)
            path.write_text(json.dumps({'one': {'name': 'One', 'catalog': 'one-public'}, 'two': {'name': 'Two', 'catalog': 'two-public', 'domains': ['two.example']}}))
            self.assertEqual(sorted(registry.all()), ['one', 'two'])
            self.assertEqual(registry.by_domain('two.example'), 'two')
            time.sleep(0.01)
            path.write_text('{ broken json')
            self.assertEqual(sorted(registry.all()), ['one', 'two'])
            self.assertIsNotNone(registry.error)

    def test_repo_registry_is_valid(self):
        repo = Path(__file__).parent / 'demo' / 'sites.json'
        sites = validate_sites(json.loads(repo.read_text()))
        self.assertEqual(sites['payment-test']['catalog'], 'site-api-public-weight-loss')

    def test_catalog_must_match_its_site(self):
        with self.assertRaises(ValueError):
            map_catalog(glow_catalog(), 'payment-test', SITES['payment-test'])
        catalog, _ = map_catalog(glow_catalog(), 'glow-health', SITES['glow-health'])
        self.assertEqual(catalog.site_id, 'glow-health')


if __name__ == '__main__':
    unittest.main()
