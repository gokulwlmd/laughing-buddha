"""FortifyHP provisioning integration with fake Sticky and a disposable DB."""
import copy
import tempfile
import unittest
from pathlib import Path

from app import Settings, create_app
from fortifyhp_setup import FortifySetup, ORIGIN, SOURCES
from qa.fake_master import MasterSticky
from import_master_therapies import promote_live
from master import fingerprint as master_fingerprint
from therapy_skeletons import all_skeletons


class FortifySticky(MasterSticky):
    def __init__(self):
        super().__init__()
        self.campaign_offers[195] = [423, 481]
        for prefix, terms in SOURCES.items():
            for term, pid in terms.items():
                sku = {('SERM', 1): 'SERM-30-1B', ('SERM', 3): 'SERM-30-3B'}.get((prefix, term), f'{prefix}-{term}M')
                self.products[pid] = {'id': pid, 'sku': sku, 'name': sku, 'category_id': 113,
                                     'price': '100.00', 'cost_of_goods': '0', 'restocking_fee': '0',
                                     'max_quantity': 1, 'is_shippable': 1, 'taxable': 0, 'archived_flag': 0}

    def detail(self, path):
        if path == '/api/v2/campaigns/195':
            return {'id': 195, 'name': 'Fortifyhp', 'is_active': 1, 'is_archived': 0, 'gateway_id': 269,
                    'payment_methods': [{'value': 'stripe_link'}, {'value': 'visa'}],
                    'alternative_payments': [{'payment_method': 'stripe_link', 'provider': {'id': 269, 'account_id': 250}}],
                    'countries': [{'id': 223, 'iso_2': 'US', 'name': 'United States'}],
                    'shipping_profiles': [{'id': 2, 'name': 'Free Shipping'}],
                    'offers': [self.detail('/api/v2/offers/' + str(oid)) for oid in self.campaign_offers[195]]}
        if path in ('/api/v2/offers/423', '/api/v2/offers/481'):
            oid = int(path.rsplit('/', 1)[1])
            return {'id': oid, 'name': 'Existing catalog', 'type_id': 1,
                    'products': [{'id': pid} for terms in SOURCES.values() for pid in terms.values()] if oid == 423 else [],
                    'billing_models': self.models()}
        if path == '/api/v2/providers/payment/profiles/269':
            return {'id': 269, 'account_id': 250, 'currency': {'code': 'USD'}, 'fields': {'account_fields': {
                    'publishable_key': 'pk_live_fake', 'capture_on_shipment': False, 'enable_delayed_capture': False}}}
        return super().detail(path)


class FortifySetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.fake = FortifySticky()
        self.app = create_app(Settings(public_url=ORIGIN, state_dir=Path(self.temp.name), authorization_verified=True), self.fake)
        promote_live(self.app)
        admin = self.app.state.admin
        for master in admin.records('master'):
            active = dict(master, payment_test_only=True, product_template={
                'sku': master['sku'], 'name': master['name'], 'category_id': 113,
                'is_shippable': 0, 'taxable': 0, 'price': '100.00'},
                offers=[{'id': 'test-upfront', 'name': 'Existing test plan', 'price': '100.00', 'billing_models': [2]}])
            active.pop('planning_contract', None)
            admin.put('test_catalog_activation', master['sku'], {'sku': master['sku'], 'master_hash': master_fingerprint(master),
                      'master': active, 'payment_test_only': True})
        for skeleton in all_skeletons():
            template = {'id': skeleton['id'].removesuffix('-v1'), 'name': skeleton['name'], 'title': skeleton['name'],
                        'therapy_id': skeleton['therapy']['id'], 'purchase_option_ids': [skeleton['therapy']['id'] + f'-{term}m' for term in (1, 3, 6, 12)],
                        'enabled': True, 'revision': 1}
            admin.put('checkout_template', template['id'], template)
        admin.put('brand', 'markrx', {'id': 'markrx', 'name': 'Markrx', 'campaign_id': 423})
        admin.put('site', 'markrx', {'id': 'markrx', 'name': 'Markrx', 'brand_id': 'markrx', 'campaign_id': 423})
        self.original_records = {(k, i): json for k, i, json in admin.store.db().execute('SELECT kind,id,data FROM admin_config')}
        # Exercise actual setup methods against disposable local state. The
        # production constructor's fixed /data restriction is tested separately.
        self.setup = FortifySetup.__new__(FortifySetup)
        self.setup.admin = self.app.state.admin
        self.setup.api = self.fake
        self.setup.path = Path(self.temp.name) / 'journal.json'
        self.setup.state = {'run_id': 'test', 'operations': {}}

    def tearDown(self):
        self.temp.cleanup()

    def test_production_constructor_rejects_other_data_directory(self):
        with self.assertRaisesRegex(ValueError, 'existing shared'):
            FortifySetup(self.app)

    def test_prepare_is_read_only_and_all_products_remain_shippable(self):
        before = copy.deepcopy(self.fake.products)
        result = self.setup.prepare()
        self.assertEqual(result['products'], 40)
        self.assertEqual(result['original_offers_preserved'], [423, 481])
        self.assertEqual(self.fake.products, before)
        self.assertFalse(self.fake.calls)
        self.assertTrue(all(r['product_body']['is_shippable'] == 1 for r in self.setup.state['review']['rows']))
        self.assertEqual(self.setup.prepare(), result)

    def test_full_setup_adds_only_new_catalog_and_replay_reuses_all_ids(self):
        before = copy.deepcopy(self.fake.products)
        result = self.setup.apply()
        self.assertEqual(result['quote_checks'], 40)
        self.assertEqual(result['orders_created'], 0)
        self.assertEqual(self.fake.count('/products'), 40)
        self.assertEqual(self.fake.count('/offers'), 40)
        self.assertEqual(self.fake.campaign_offers[195][:2], [423, 481])
        self.assertEqual(len(self.fake.campaign_offers[195]), 42)
        self.assertTrue(all(self.fake.products[pid] == value for pid, value in before.items()))
        admin = self.app.state.admin
        self.assertEqual(len(admin.records('master')), 40)
        self.assertEqual(len(admin.records('plan_checkout')), 4)
        self.assertEqual(len(admin.records('purchase_option')), 32)
        self.assertEqual(len(admin.records('test_catalog_activation')), 40)
        self.assertEqual(len(admin.records('campaign_master')), 40)
        self.assertEqual(len(admin.templates_for_site('fortifyhp')), 4)
        self.assertEqual([t['id'] for t in admin.templates_for_site('another-new-site')],
                         [s['id'].removesuffix('-v1') for s in all_skeletons()])
        with admin.store.db() as db:
            current = {(k, i): raw for k, i, raw in db.execute('SELECT kind,id,data FROM admin_config')}
        self.assertTrue(all(current[key] == value for key, value in self.original_records.items()))
        self.assertEqual(admin.activated_master(admin.get('master', 'SEMA-12M'))['product_template']['is_shippable'], 0)
        self.assertEqual(admin.activated_master(admin.get('master', 'SEMA-12M'), 'fortifyhp', 195)['product_template']['is_shippable'], 1)
        for plan in admin.records('plan_checkout'):
            catalog = admin.plan_options(*admin.plan_record(plan['id']))
            self.assertFalse(catalog['paymentTestOnly'])
            self.assertTrue(all(entry['available'] for entry in catalog['entries']))
        count = len(self.fake.calls)
        self.assertEqual(self.setup.apply(), result)
        self.assertEqual(self.fake.count('/products'), 40)
        self.assertEqual(self.fake.count('/offers'), 40)
        self.assertTrue(all(path == '/api/v2/order_total/calculate' for _, path, _ in self.fake.calls[count:]))
        # Ordinary reviewed provisioning can reuse these physical mappings too.
        _, _, preview, operations, _ = admin.prepare_master('provision', {'brand_id': 'fortifyhp', 'campaign_id': 195})
        self.assertEqual(operations, [])
        self.assertFalse(preview['stickyWrites'])
        # Normal site updates select only this tenant's four production templates.
        _, _, site_preview, site_operations, _ = admin.prepare_site('site', {
            'id': 'fortifyhp', 'name': 'FortifyHP', 'brand_id': 'fortifyhp', 'campaign_id': 195})
        self.assertEqual(len(site_preview['templates']), 4)
        self.assertEqual(site_operations, [])

    def test_uncertain_write_cannot_be_replayed_or_turned_into_a_payment(self):
        self.setup.prepare()
        self.setup.state['operations']['product:SEMA-1M'] = {'status': 'pending', 'body_hash': 'unknown'}
        with self.assertRaisesRegex(ValueError, 'Reconcile'):
            self.setup.apply()
        self.assertEqual(self.fake.count('/products'), 0)
        for path in ('/api/v1/new_order', '/api/v1/authorize_payment', '/api/v2/campaigns/422'):
            with self.assertRaisesRegex(ValueError, 'cannot submit'):
                self.setup.write('forbidden', 'POST', path, {})

    def test_source_or_routing_drift_stops_before_any_catalog_creation(self):
        self.setup.prepare()
        self.fake.products[45560]['is_shippable'] = 0
        with self.assertRaisesRegex(ValueError, 'source'):
            self.setup.apply()
        self.assertEqual(self.fake.count('/products'), 0)

    def test_only_this_campaigns_unfinished_payment_blocks_catalog_writes(self):
        attempt = self.app.state.store.create(195, 'SEMA-1M')
        self.app.state.store.claim('new', 'awaiting_card', attempt)
        with self.assertRaisesRegex(ValueError, 'unfinished payment'):
            self.setup.apply()
        self.assertEqual(self.fake.count('/products'), 0)

    def test_scoped_master_cannot_be_used_by_another_brand_or_campaign(self):
        self.setup.apply()
        admin = self.app.state.admin
        self.assertEqual(admin.master_for('SEMA-12M', 'markrx', 423), admin.get('master', 'SEMA-12M'))
        key = 'fortifyhp:195:SEMA-12M'
        overlay = admin.get('campaign_master', key)
        overlay['campaign_id'] = 423
        admin.put('campaign_master', key, overlay)
        with self.assertRaisesRegex(Exception, 'mapping needs reconciliation'):
            admin.master_for('SEMA-12M', 'fortifyhp', 195)


if __name__ == '__main__':
    unittest.main()
