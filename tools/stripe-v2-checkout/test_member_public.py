"""Offline verification of the isolated public portal wrapper and theme."""
from copy import deepcopy
import tempfile
import unittest

from fastapi.testclient import TestClient
from member_portal.public import public_portal
from test_member_portal import build_member_fixture, ORIGIN

PUBLIC_ORIGIN = 'https://patients.example.invalid'


class PublicMemberPortalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app, self.provider, _ = build_member_fixture(self.tmp.name)
        admin = self.app.state.admin
        site = deepcopy(admin.get('site', 'site-a'))
        site.update(id='fortifyhp', name='FortifyHP')
        admin.put('site', 'fortifyhp', site)

    def tearDown(self):
        self.tmp.cleanup()

    def test_theme_is_site_configuration_not_a_name_guess(self):
        with TestClient(self.app) as client:
            branded = client.get('/api/v1/sites/fortifyhp/portal/configuration').json()
            self.assertEqual(branded['site']['theme'], 'fortifyhp')
            self.assertEqual(client.get('/api/v1/sites/site-a/portal/configuration').json()['site']['theme'], 'default')
            site = self.app.state.admin.get('site', 'site-b')
            site.update(name='FortifyHP', portal_theme='<script>')
            self.app.state.admin.put('site', 'site-b', site)
            self.assertEqual(client.get('/api/v1/sites/site-b/portal/configuration').json()['site']['theme'], 'default')

    def test_only_selected_site_patient_routes_are_public(self):
        public_portal(self.app, site_id='fortifyhp', origin=PUBLIC_ORIGIN)
        with TestClient(self.app, base_url=PUBLIC_ORIGIN) as client:
            for path in ('/portal/fortifyhp', '/portal/fortifyhp/docs', '/portal-assets/portal.js', '/api/v1/sites/fortifyhp/portal/configuration'):
                self.assertEqual(client.get(path).status_code, 200, path)
            for path in ('/portal/site-a', '/portal-admin/fortifyhp', '/api/admin/auth', '/api/admin/sites/fortifyhp/portal/overview',
                         '/api/v1/sites/site-a/portal/configuration', '/portal/fortifyhp-other', '/portal-assets/../app.py', '/checkout/195/SEMA-1M', '/api/portal-enrollment'):
                self.assertEqual(client.get(path).status_code, 404, path)
            self.assertEqual(client.get('/api/v1/sites/fortifyhp/portal/orders').status_code, 401)
            self.assertEqual(client.get('/api/v1/sites/fortifyhp/portal/orders', headers={'Origin': ORIGIN}).status_code, 403)
            schema = client.get('/portal/fortifyhp/openapi.json').json()
            self.assertEqual(schema['servers'], [{'url': PUBLIC_ORIGIN}])
            self.assertTrue(all(p.startswith('/api/v1/sites/fortifyhp/portal/') for p in schema['paths']))
            self.assertEqual(self.app.state.settings.checkout_public_url, ORIGIN)
            self.assertEqual(self.provider.calls, [])

    def test_public_origin_and_site_are_required(self):
        for origin in ('', 'http://127.0.0.1:8873', 'https://portal.example.invalid/path', 'https://user@portal.example.invalid', 'https://portal.example.invalid#fragment'):
            with self.assertRaises(ValueError):
                public_portal(self.app, site_id='fortifyhp', origin=origin)
        for site in ('', None, '../site-a', 'site-a/portal'):
            with self.assertRaises(ValueError):
                public_portal(self.app, site_id=site, origin=PUBLIC_ORIGIN)


if __name__ == '__main__':
    unittest.main()
