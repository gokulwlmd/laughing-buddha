"""Site care bootstrap never changes another brand or shared master policy."""
from copy import deepcopy
import tempfile
import unittest

from fastapi.testclient import TestClient
from member_portal.site_setup import PRODUCTS, bootstrap_site_care, product_setup_for
from refill_rules import site_rule_key
from test_member_portal import build_member_fixture, ORIGIN, OWNER_EMAIL, OWNER_PASSWORD
import test_member_native_claims as native_tests
import test_member_care as care_tests
import test_member_portal as portal_tests


class MemberSiteSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app, self.fake, _ = build_member_fixture(self.temp.name)
        self.admin = self.app.state.admin
        self.admin.put('brand', 'fortifyhp', {'id': 'fortifyhp', 'name': 'FortifyHP', 'color': '#A2563F', 'campaign_id': 195})
        self.admin.put('site', 'fortifyhp', {'id': 'fortifyhp', 'name': 'FortifyHP', 'brand_id': 'fortifyhp', 'campaign_id': 195})
        for therapy in ('weight-loss', 'sermorelin', 'metformin', 'pt-141'):
            masters = [{'sku': sku, 'therapy_id': therapy} for sku, product in PRODUCTS.items() if product['therapy_id'] == therapy]
            self.admin.put('therapy', therapy, {'id': therapy, 'name': therapy})
            self.admin.put('plan_checkout', 'fortify-' + therapy, {'id': 'fortify-' + therapy, 'site_id': 'fortifyhp',
                'brand_id': 'fortifyhp', 'campaign_id': 195, 'therapy_id': therapy, 'template_snapshot': {'masters': masters}})
        self.admin.put('refill_policy', 'SEMA-12M-SUB', {'sku': 'SEMA-12M-SUB', 'enabled': False, 'revision': 9})

    def tearDown(self):
        self.temp.cleanup()

    def test_idempotent_bootstrap_enables_real_portal_metadata_without_shared_or_patient_changes(self):
        before = {kind: deepcopy(self.admin.records(kind)) for kind in ('master', 'refill_policy', 'test_catalog_activation')}
        result = bootstrap_site_care(self.admin)
        self.assertEqual((result['created_policies'], result['updated_plans']), (40, 4))
        repeated = bootstrap_site_care(self.admin)
        self.assertEqual((repeated['created_policies'], repeated['updated_plans']), (0, 0))
        for kind, records in before.items():
            self.assertEqual(self.admin.records(kind), records)
        with self.app.state.store.db() as db:
            for table in ('member_patients', 'member_orders', 'member_invites', 'member_grants'):
                self.assertEqual(db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0], 0)
        self.assertEqual(self.fake.calls, [])
        with TestClient(self.app) as client:
            self.assertEqual(client.get('/portal/fortifyhp').status_code, 200)
            data = client.get('/api/v1/sites/fortifyhp/portal/configuration').json()
            self.assertEqual(data['site']['theme'], 'fortifyhp')
            self.assertEqual(len(data['therapies']), 4)
        service = self.app.state.member_portal
        for term, days in [(1, []), (3, []), (6, [90]), (12, [90, 180, 270])]:
            rule = service.rule('SEMA-' + str(term) + 'M-SUB', 'fortifyhp')
            self.assertEqual(rule['check_in_days'], days)
            self.assertEqual(rule['included_refills_enabled'], bool(days))
        self.assertFalse(service.rule('SEMA-12M-SUB', 'site-a')['enabled'])

    def test_later_site_policy_edits_are_preserved_and_never_affect_another_site(self):
        bootstrap_site_care(self.admin)
        key = site_rule_key('fortifyhp', 'SEMA-12M-SUB')
        edited = self.admin.get('site_refill_policy', key)
        edited.update(enabled=False, revision=2)
        self.admin.put('site_refill_policy', key, edited)
        self.assertEqual(bootstrap_site_care(self.admin)['created_policies'], 0)
        self.assertEqual(self.admin.get('site_refill_policy', key), edited)
        self.assertEqual(self.app.state.member_portal.rule('SEMA-12M-SUB', 'site-a')['revision'], 9)

    def test_conflicting_schedule_leaves_all_site_metadata_untouched(self):
        plan = self.admin.get('plan_checkout', 'fortify-weight-loss')
        plan['template_snapshot']['masters'][0]['product_setup'] = {'shipment_count': 99}
        self.admin.put('plan_checkout', plan['id'], plan)
        before = deepcopy(self.admin.records('plan_checkout'))
        with self.assertRaisesRegex(ValueError, 'schedule differs'):
            bootstrap_site_care(self.admin)
        self.assertEqual(self.admin.records('plan_checkout'), before)
        self.assertEqual(self.admin.records('site_refill_policy'), [])
        with self.assertRaisesRegex(ValueError, 'verified FortifyHP'):
            bootstrap_site_care(self.admin, 'site-a')

    def test_owner_edits_same_sku_per_site_with_csrf_revision_and_membership_checks(self):
        bootstrap_site_care(self.admin)
        sku = 'SEMA-12M-SUB'
        self.admin.put('plan_checkout', 'other-site-plan', {'id': 'other-site-plan', 'site_id': 'site-b',
            'brand_id': 'brand-b', 'campaign_id': 423, 'template_snapshot': {'masters': [{'sku': sku}]}})
        path = '/api/admin/sites/fortifyhp/portal/refill-rules'
        with TestClient(self.app, base_url=ORIGIN) as client:
            self.assertEqual(client.get(path).status_code, 401)
            login = client.post('/api/admin/login', json={'email': OWNER_EMAIL, 'password': OWNER_PASSWORD}, headers={'Origin': ORIGIN})
            headers = {'Origin': ORIGIN, 'X-CSRF-Token': login.json()['csrfToken']}
            rule = next(rule for rule in client.get(path).json()['rules'] if rule['sku'] == sku)
            body = {key: value for key, value in rule.items() if key not in ('site_id', 'sku', 'name', 'source', 'revision')}
            body.update(expected_revision=rule['revision'], enabled=False, minimum_days=7)
            self.assertEqual(client.put(path + '/' + sku, json=body, headers={'Origin': ORIGIN}).status_code, 403)
            result = client.put(path + '/' + sku, json=body, headers=headers)
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(result.json()['minimum_days'], 7)
            self.assertEqual(client.put(path + '/' + sku, json=body, headers=headers).status_code, 409)
            self.assertEqual(client.put(path + '/UNKNOWN-SKU', json=body, headers=headers).status_code, 404)
            other = client.get('/api/admin/sites/site-b/portal/refill-rules').json()['rules'][0]
            self.assertEqual((other['sku'], other['minimum_days'], other['source'], other['revision']), (sku, 0, 'master', 0))
            self.assertEqual(self.admin.get('refill_policy', sku)['revision'], 9)
            self.assertEqual(self.app.state.member_portal.rule(sku, 'fortifyhp')['minimum_days'], 7)
            self.assertNotIn('minimum_days', self.app.state.member_portal.rule(sku, 'site-b'))


class SitePolicyNativeClaimTests(unittest.TestCase):
    setUp = native_tests.NativeClaimTests.setUp
    tearDown = portal_tests.MemberPortalTests.tearDown
    post_owner = portal_tests.MemberPortalTests.post_owner
    enroll = portal_tests.MemberPortalTests.enroll
    claim = native_tests.NativeClaimTests.claim
    forces = native_tests.NativeClaimTests.forces
    complete = care_tests.MemberCareTests.complete
    simulate = care_tests.MemberCareTests.simulate

    def test_native_claim_reads_site_override_and_respects_its_current_disable_switch(self):
        rule = self.app.state.admin.get('refill_policy', self.sku)
        self.app.state.admin.put('site_refill_policy', site_rule_key('site-a', self.sku), dict(rule, site_id='site-a', sku=self.sku))
        self.app.state.admin.put('refill_policy', self.sku, dict(rule, enabled=False))
        self.complete('initial'); self.simulate(80)
        self.assertEqual(self.claim().status_code, 200)
        self.assertEqual(len(self.forces()), 1)
        self.complete('checkin-90'); self.simulate(170)
        self.app.state.admin.put('site_refill_policy', site_rule_key('site-a', self.sku), dict(rule, site_id='site-a', sku=self.sku, enabled=False))
        self.assertEqual(self.claim(180).status_code, 409)
        self.assertEqual(len(self.forces()), 1)


if __name__ == '__main__':
    unittest.main()
