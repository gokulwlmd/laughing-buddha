"""Production safety and billing boundaries for the read-only client planner."""
import copy
import unittest

from fortifyhp_provisioning import build_manifest
from therapy_skeletons import all_skeletons


class FortifyHPPlanTests(unittest.TestCase):
    def setUp(self):
        self.campaign = {
            'campaign': {'id': 195, 'is_active': 1, 'is_archived': 0, 'gateway_id': 269},
            'routes': [{'method': 'stripe_link', 'profile_id': 269, 'provider_id': 250}],
            'gateways': [{'id': 269, 'account_id': 250, 'currency': 'USD', 'publishable_key_mode': 'live',
                          'capture_on_shipment': False, 'enable_delayed_capture': False}],
            'offers': [{'id': 423}, {'id': 481}],
        }
        self.catalog = {'catalog': {'campaign_id': 195, 'exact_master_sku_matches': []}}
        self.admin = {'masters': [
            {'sku': p['sku'], 'therapy_id': s['therapy']['id'], 'treatment_id': p['treatment_id'],
             'duration_months': p['duration_months'], 'test_activation_present': True,
             'test_activation_shippable': 0}
            for s in all_skeletons() for p in s['products']]}

    def build(self, **kwargs):
        return build_manifest(self.campaign, self.catalog, self.admin, **kwargs)

    def test_four_therapies_have_explicit_once_and_recurring_terms(self):
        result = self.build()
        self.assertEqual(result['counts'], {'therapies': 4, 'purchase_options': 16,
                         'independent_products': 40, 'independent_offers': 40,
                         'standard_choices': 20, 'prepaid_choices_pending_readback': 20, 'payable_choices': 0})
        products = {p['sku']: p for p in result['products']}
        for months in (1, 3, 6, 12):
            once, sub = (products[f'SEMA-{months}M' + suffix] for suffix in ('', '-SUB'))
            self.assertIsNone(once['renewal_days'])
            self.assertEqual(sub['renewal_days'], months * 30)
            self.assertEqual(once['full_term_price'], sub['full_term_price'])
        twelve = products['SEMA-12M-SUB']
        self.assertEqual(twelve['full_term_price'], '1428.00')
        self.assertEqual(twelve['offer']['product_unit_price'], '357.00')
        self.assertEqual(twelve['offer']['billing_model_days'], 90)
        self.assertEqual(twelve['shipment_days'], [0, 90, 180, 270])
        self.assertEqual(twelve['included_refill_claim_days'], [80, 170, 260])
        self.assertEqual(twelve['checkin_count'], 3)
        self.assertEqual(products['SEMA-6M']['shipment_days'], [0, 90])

    def test_existing_catalog_and_subscriptions_stay_unchanged(self):
        before = copy.deepcopy([self.campaign, self.catalog, self.admin])
        plan = self.build()
        self.assertEqual([self.campaign, self.catalog, self.admin], before)
        self.assertEqual(plan['existing_offer_ids_to_preserve'], [423, 481])
        self.assertEqual(plan['existing_product_price_policy'], 'never_modify')
        self.assertEqual(plan['existing_subscription_policy'], 'never_modify')
        self.assertEqual(plan['remote_writes'], 0)
        self.assertEqual(plan['review_id'], self.build()['review_id'])

    def test_test_activations_never_make_physical_plans_publishable(self):
        for product in self.build()['products']:
            self.assertFalse(product['publishable'])
            self.assertFalse(product['test_activation_reused'])
            self.assertTrue(product['is_shippable'])
            self.assertIn('preserve_external_sticky_order_consumer_fulfillment_responsibility', product['requirements'])
            if product['duration_months'] >= 6:
                self.assertIn('fortifyhp_scoped_shippable_prepaid_contract_and_quote_readback', product['requirements'])

    def test_duplicate_skus_are_explicit_candidates_not_auto_selected(self):
        self.catalog['catalog']['exact_master_sku_matches'] = [
            {'id': p, 'offer_id': 423, 'sku': 'SEMA-1M', 'archived_flag': 0,
             'is_shippable': 1, 'taxable': 0} for p in (17419, 45560)]
        rows = [p for p in self.build()['products'] if p['sku'] in ('SEMA-1M', 'SEMA-1M-SUB')]
        for row in rows:
            self.assertEqual([p['id'] for p in row['source_product_candidates']], [17419, 45560])
            self.assertIsNone(row['source_product_selected'])
            self.assertIn('explicit_source_product_selection', row['requirements'])

    def test_saved_site_prices_are_preserved_and_invalid_amounts_rejected(self):
        plan = self.build(brand_price_overrides={'SEMA-1M': '180.00'})
        product = next(p for p in plan['products'] if p['sku'] == 'SEMA-1M')
        self.assertEqual(product['full_term_price'], '180.00')
        self.assertEqual(product['price_source'], 'preserved_site_price')
        self.assertNotEqual(plan['review_id'], self.build()['review_id'])
        for amount in ('0', '-1', 'NaN', 'Infinity', '1.001'):
            with self.subTest(amount=amount), self.assertRaises(ValueError):
                self.build(brand_price_overrides={'SEMA-1M': amount})
        with self.assertRaisesRegex(ValueError, 'shipment units'):
            self.build(brand_price_overrides={'SEMA-12M': '100.01'})

    def test_wrong_gateway_or_site_collision_stops_planning(self):
        self.campaign['campaign']['gateway_id'] = 254
        with self.assertRaises(ValueError):
            self.build()
        self.campaign['campaign']['gateway_id'] = 269
        self.admin['site_summaries'] = [{'id': 'other-site', 'campaign_id': 195}]
        with self.assertRaisesRegex(ValueError, 'reconciliation'):
            self.build()

    def test_metadata_drift_or_missing_master_stops_planning(self):
        self.admin['masters'][0]['duration_months'] = 12
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.build()
        self.admin['masters'].pop(0)
        with self.assertRaisesRegex(ValueError, 'missing'):
            self.build()


if __name__ == '__main__':
    unittest.main()
